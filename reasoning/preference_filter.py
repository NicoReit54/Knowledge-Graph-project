"""
Preference + travel-time filtering: "find me a <category>, with <amenities>,
in <district>, ranked by how fast I can actually get there from here."

Combines three things built separately so far:
- the KG's category (rdf:type) + schema:amenityFeature data (KG Modelling/Creation)
- the KG's schema:containedInPlace -> viennakg:District links (KG Modelling)
- reasoning.gtfs_routing.GtfsRouter's travel time, up to 2 transfers (Reasoning Layer)

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
- District filtering (`district=` on find_pois) matches on
  schema:containedInPlace, which every POI already has from KG Modelling --
  no new ingestion needed, just a new query parameter. Applied as an early
  candidate-set filter (before travel-time computation), not a post-filter,
  so it also narrows the routing workload. Accepts a district number (1-23),
  a "BezirkN" URI-local-name string, or a case-insensitive substring of the
  district's rdfs:label (e.g. 6, "Bezirk6", or "mariahilf" all resolve to the
  6th district). Unresolvable input raises ValueError rather than silently
  matching nothing, since a typo'd district name silently returning zero
  results is a confusing failure mode.
- There's no free-text description field anywhere in the KG (checked: no
  schema:description triples exist at all). describe_poi() composes a
  human-readable summary from whatever structured fields a given POI
  actually has (address, url, contact info, opening hours, area, amenities,
  tourist-attraction subcategory) -- fields vary by POI class and source, so
  the description is best-effort, not guaranteed complete. Only computed for
  final top_n results, not every candidate, to keep find_pois() cheap.
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
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""


def list_districts(g: Graph):
    """All 23 districts as [{"number": 1, "label": "1. Innere Stadt", "uri": "..."}],
    sorted by number. For populating a district dropdown/filter UI -- see
    notebooks/06_service_layer.ipynb section on district filtering."""
    q = f"""{PREFIXES}
    SELECT ?d ?label WHERE {{
        ?d a viennakg:District ; rdfs:label ?label .
    }}"""
    out = []
    for r in g.query(q):
        local = str(r.d).rsplit("#", 1)[-1]  # "Bezirk6"
        number = int(local.replace("Bezirk", ""))
        out.append({"number": number, "label": str(r.label), "uri": str(r.d)})
    return sorted(out, key=lambda d: d["number"])


def resolve_district(g: Graph, district) -> str:
    """District number (1-23), "BezirkN", or a case-insensitive substring of
    the district's rdfs:label -> district URI (str). Raises ValueError if no
    district matches, rather than silently filtering to nothing."""
    districts = list_districts(g)
    if isinstance(district, int) or (isinstance(district, str) and district.strip().isdigit()):
        number = int(district)
        for d in districts:
            if d["number"] == number:
                return d["uri"]
        raise ValueError(f"No district numbered {number} (valid: 1-23)")

    needle = str(district).strip().lower().replace("bezirk", "").strip()
    for d in districts:
        if needle in d["label"].lower() or needle in str(d["number"]):
            return d["uri"]
    raise ValueError(
        f"Could not resolve district {district!r}. Valid: a number 1-23, "
        f"'BezirkN', or a substring of a label like "
        f"{districts[0]['label']!r}."
    )


def _pois_of_class(g: Graph, class_qname: str):
    """POIs of one class -> {uri: (name, lon, lat, district_uri)}. Kept as a
    single simple triple pattern per class deliberately -- see the note
    below in _candidate_pois. containedInPlace is OPTIONAL since it's a
    simple non-string-filtered join and doesn't trigger the query-planner
    pathology that motivated splitting out the amenity lookup."""
    q = f"""{PREFIXES}
    SELECT ?poi ?name ?lon ?lat ?district WHERE {{
        ?poi a {class_qname} ; schema:name ?name ; geo:long ?lon ; geo:lat ?lat .
        OPTIONAL {{ ?poi schema:containedInPlace ?district . }}
    }}"""
    return {
        str(r.poi): (str(r.name), float(r.lon), float(r.lat), str(r.district) if r.district else None)
        for r in g.query(q)
    }


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


def _candidate_pois(g: Graph, poi_classes=None, required_amenities=None, district_uri=None):
    """POIs of the requested class(es) with all required amenities present,
    optionally restricted to one district.

    Deliberately NOT one SPARQL query joining class-match and amenity-match
    patterns together: that triggers a severe rdflib query-planning
    pathology on this graph (a query combining `?poi a ?type` with an
    amenityFeature join and a CONTAINS/LCASE filter took >35s and was killed;
    the same two patterns run as separate queries take ~0.15s and ~0.25s).
    Root cause not fully diagnosed -- rdflib's SPARQL optimizer likely
    mishandles the join ordering with the string filter present -- so the
    fix is to run each lookup as its own simple query and intersect the
    resulting URI sets in Python, which is both fast and easy to reason
    about. Returns (uri, name, class_label, lon, lat, district_uri) tuples.

    district_uri filtering happens here, in Python, alongside the amenity
    intersection -- before any travel-time computation -- so an over-narrow
    district also shrinks the routing workload downstream, not just the
    final display list."""
    classes = poi_classes or list(CLASS_MAP.keys())
    unknown = set(classes) - set(CLASS_MAP)
    if unknown:
        raise ValueError(f"Unknown POI class(es): {unknown}. Known: {list(CLASS_MAP)}")

    by_class = {}
    for c in classes:
        for uri, (name, lon, lat, poi_district) in _pois_of_class(g, CLASS_MAP[c]).items():
            by_class[uri] = (name, c, lon, lat, poi_district)

    matched_uris = set(by_class)
    for amenity in required_amenities or []:
        matched_uris &= _pois_with_amenity(g, amenity)

    if district_uri is not None:
        matched_uris = {u for u in matched_uris if by_class[u][4] == district_uri}

    return [(uri, *by_class[uri][:4]) for uri in matched_uris]


def describe_poi(g: Graph, poi_uri: str) -> str:
    """Best-effort human-readable description composed from whatever
    structured fields this POI actually has in the KG -- there is no
    free-text description field in the data (see module docstring), so this
    is assembled from address/url/contact/opening-hours/area/amenities/
    tourist-attraction-subcategory, whichever are present. Returns "" if
    nothing beyond name/location is known (common for e.g. BathingSite)."""
    q = f"""{PREFIXES}
    SELECT ?address ?url ?telephone ?email ?openingHours ?areaSqm ?catLabel ?districtLabel WHERE {{
        OPTIONAL {{ <{poi_uri}> schema:address ?address . }}
        OPTIONAL {{ <{poi_uri}> schema:url ?url . }}
        OPTIONAL {{ <{poi_uri}> schema:telephone ?telephone . }}
        OPTIONAL {{ <{poi_uri}> schema:email ?email . }}
        OPTIONAL {{ <{poi_uri}> schema:openingHours ?openingHours . }}
        OPTIONAL {{ <{poi_uri}> viennakg:areaSqm ?areaSqm . }}
        OPTIONAL {{ <{poi_uri}> viennakg:hasCategory ?cat . ?cat skos:prefLabel ?catLabel . }}
        OPTIONAL {{ <{poi_uri}> schema:containedInPlace ?d . ?d rdfs:label ?districtLabel . }}
    }}"""
    rows = list(g.query(q))
    parts = []
    if rows:
        r = rows[0]
        if r.catLabel:
            parts.append(str(r.catLabel))
        if r.districtLabel:
            parts.append(f"in {r.districtLabel}")
        if r.address:
            parts.append(f"at {r.address}")
        if r.areaSqm:
            parts.append(f"{float(r.areaSqm):,.0f} m²")
        if r.openingHours:
            parts.append(f"open {r.openingHours}")
        if r.telephone:
            parts.append(f"tel {r.telephone}")
        if r.email:
            parts.append(f"email {r.email}")
        if r.url:
            parts.append(str(r.url))

    q2 = f"""{PREFIXES}
    SELECT ?fname ?fvalue WHERE {{
        <{poi_uri}> schema:amenityFeature ?f .
        ?f schema:name ?fname ; schema:value ?fvalue .
    }}"""
    amenities = [str(r.fname) for r in g.query(q2) if bool(r.fvalue)]
    if amenities:
        parts.append("amenities: " + ", ".join(sorted(amenities)))

    return " -- ".join(parts)


def find_pois(g: Graph, router: GtfsRouter, origin_lon: float, origin_lat: float,
              poi_classes=None, required_amenities=None, district=None,
              max_travel_time_min=None, depart_after="14:00:00", max_transfers=2,
              max_walk_min=None, top_n=10, with_description=True):
    """Preference-matching POIs near (origin_lon, origin_lat), ranked by
    real transit travel time (not distance, and -- since GtfsRouter now
    supports it -- not limited to direct connections either; up to
    `max_transfers` transfers are considered). POIs with no connection at all
    within `max_transfers` are still included (sorted last) unless
    max_travel_time_min excludes them.

    district: optional filter restricting candidates to one Vienna district
    -- accepts a number (1-23), "BezirkN", or a substring of the district's
    label (see resolve_district()). None (default) searches all districts.

    max_walk_min: hard cap on walking time to/from a transit stop at both
    ends (e.g. 10 for a stroller/mobility constraint) -- see
    GtfsRouter.reachable_from()/travel_time_to() docstrings for the strict-
    vs-fallback behavior this triggers. None (default) leaves walking
    unrestricted (beyond the generous built-in default).

    with_description: if True (default), attaches a best-effort "description"
    string (see describe_poi()) to each of the final top_n results. Computed
    only for the results actually returned, not every candidate, so it's
    cheap even for large candidate pools; set False to skip entirely.

    Uses router.reachable_from() ONCE for this origin, then router
    .travel_time_to() per candidate -- not router.estimate_travel_time() in a
    loop, which would redo the full network search per candidate. For 1,000+
    candidates that's the difference between ~3s and several minutes."""
    district_uri = resolve_district(g, district) if district is not None else None
    candidates = _candidate_pois(g, poi_classes, required_amenities, district_uri)
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
            "uri": uri,
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
    results = results[:top_n]

    if with_description:
        for r in results:
            r["description"] = describe_poi(g, r["uri"])

    return results
