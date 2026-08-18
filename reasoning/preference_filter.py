"""
Preference + travel-time filtering: "find me a <category>, with <amenities>,
ranked by how fast I can actually get there from here."

Combines two things built separately so far:
- the KG's category (rdf:type) + schema:amenityFeature data (KG Modelling/Creation)
- reasoning.gtfs_routing.GtfsRouter's direct-connection travel time (Reasoning Layer)

Design notes (see docs/reasoning_layer_decisions.md for the broader context):
- POI class filtering uses an explicit list of the 7 known POI classes rather
  than querying the common viennakg:POI supertype generically. Tried RDFS
  materialization via owlrl to make the supertype queryable directly -- on
  this graph (80K+ triples) a full RDFS closure pass didn't finish in a
  reasonable time, so it's not worth it just to avoid listing 7 class names
  that are already fixed and known.
- POIs without a direct transit connection are NOT dropped from results --
  only excluded if the caller sets a hard max_travel_time_min. Otherwise
  they're returned, sorted after all reachable ones, clearly marked. Silently
  hiding them would make preference queries look broken given how rare direct
  connections are (see notebooks/04_reasoning_travel_time.ipynb).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rdflib import Graph

from reasoning.gtfs_routing import GtfsRouter

CLASS_MAP = {
    "Museum": "schema:Museum",
    "Library": "schema:Library",
    "BathingSite": "viennakg:BathingSite",
    "Park": "schema:Park",
    "SwimmingPool": "viennakg:SwimmingPool",
    "PlaygroundArea": "viennakg:PlaygroundArea",
    "TouristAttraction": "schema:TouristAttraction",
}

PREFIXES = """
PREFIX schema: <https://schema.org/>
PREFIX viennakg: <http://example.org/viennakg#>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
"""


def _pois_of_class(g: Graph, class_qname: str):
    """POIs of one class -> {uri: (name, lon, lat)}. Kept as a single simple
    triple pattern per class deliberately -- see the note below."""
    q = f"""{PREFIXES}
    SELECT ?poi ?name ?lon ?lat WHERE {{
        ?poi a {class_qname} ; schema:name ?name ; geo:long ?lon ; geo:lat ?lat .
    }}"""
    return {str(r.poi): (str(r.name), float(r.lon), float(r.lat)) for r in g.query(q)}


def _pois_with_amenity(g: Graph, amenity_substring: str):
    """POI URIs with a schema:amenityFeature whose name contains
    `amenity_substring` (case-insensitive) and value=true -> set of URIs."""
    q = f"""{PREFIXES}
    SELECT ?poi WHERE {{
        ?poi schema:amenityFeature ?f .
        ?f schema:name ?fname ; schema:value true .
        FILTER(CONTAINS(LCASE(STR(?fname)), LCASE("{amenity_substring}")))
    }}"""
    return {str(r.poi) for r in g.query(q)}


def _candidate_pois(g: Graph, poi_classes=None, required_amenities=None):
    """POIs of the requested class(es) with all required amenities present.

    Deliberately NOT one SPARQL query joining class-match and amenity-match
    patterns together: that triggers a severe rdflib query-planning
    pathology on this graph (a query combining `?poi a ?type` with an
    amenityFeature join and a CONTAINS/LCASE filter took >35s and was killed;
    the same two patterns run as separate queries take ~0.15s and ~0.25s).
    Root cause not fully diagnosed -- rdflib's SPARQL optimizer likely
    mishandles the join ordering with the string filter present -- so the
    fix is to run each lookup as its own simple query and intersect the
    resulting URI sets in Python, which is both fast and easy to reason
    about. Returns (uri, name, class_label, lon, lat) tuples."""
    classes = poi_classes or list(CLASS_MAP.keys())
    unknown = set(classes) - set(CLASS_MAP)
    if unknown:
        raise ValueError(f"Unknown POI class(es): {unknown}. Known: {list(CLASS_MAP)}")

    by_class = {}
    for c in classes:
        for uri, (name, lon, lat) in _pois_of_class(g, CLASS_MAP[c]).items():
            by_class[uri] = (name, c, lon, lat)

    matched_uris = set(by_class)
    for amenity in required_amenities or []:
        matched_uris &= _pois_with_amenity(g, amenity)

    return [(uri, *by_class[uri]) for uri in matched_uris]


def find_pois(g: Graph, router: GtfsRouter, origin_lon: float, origin_lat: float,
              poi_classes=None, required_amenities=None,
              max_travel_time_min=None, depart_after="14:00:00", max_transfers=2,
              max_walk_min=None, top_n=10):
    """Preference-matching POIs near (origin_lon, origin_lat), ranked by
    real transit travel time (not distance, and -- since GtfsRouter now
    supports it -- not limited to direct connections either; up to
    `max_transfers` transfers are considered). POIs with no connection at all
    within `max_transfers` are still included (sorted last) unless
    max_travel_time_min excludes them.

    max_walk_min: hard cap on walking time to/from a transit stop at both
    ends (e.g. 10 for a stroller/mobility constraint) -- see
    GtfsRouter.reachable_from()/travel_time_to() docstrings for the strict-
    vs-fallback behavior this triggers. None (default) leaves walking
    unrestricted (beyond the generous built-in default).

    Uses router.reachable_from() ONCE for this origin, then router
    .travel_time_to() per candidate -- not router.estimate_travel_time() in a
    loop, which would redo the full network search per candidate. For 1,000+
    candidates that's the difference between ~3s and several minutes."""
    candidates = _candidate_pois(g, poi_classes, required_amenities)
    reachability = router.reachable_from(origin_lon, origin_lat, depart_after, max_transfers,
                                          max_walk_min=max_walk_min)

    results = []
    for uri, name, type_label, lon, lat in candidates:
        trip = router.travel_time_to(reachability, lon, lat)
        reachable = trip["found_direct_connection"]
        if max_travel_time_min is not None:
            if not reachable or trip["total_travel_min"] > max_travel_time_min:
                continue
        results.append({
            "name": name,
            "type": type_label,
            "lon": lon,
            "lat": lat,
            "reachable": reachable,
            "num_transfers": trip.get("num_transfers"),
            "travel_time_min": round(trip["total_travel_min"], 1) if reachable else None,
            "line": trip.get("line"),
        })

    # reachable ones first (fastest first), unreachable ones after
    results.sort(key=lambda r: (not r["reachable"], r["travel_time_min"] or float("inf")))
    return results[:top_n]
