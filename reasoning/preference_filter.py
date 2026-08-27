"""
Preference + travel-time filtering: "find me a <category>, with <amenities>,
in <district>, ranked by how fast I can actually get there."

Combines the KG's category/amenity/district data (KG Modelling) with
GtfsRouter's travel time, up to 2 transfers (Reasoning Layer).

Design notes (see docs/reasoning_layer_decisions.md):
- POI classes are an hardcoded list of the 7 known/chosen ones, not a 
  viennakg:POI supertype query. RDFS materialization via owlrl was tried to
  make the supertype queryable but didn't finish in reasonable time on this
  graph (80K+ triples) on my machine; not worth it just to avoid listing 7 fixed names
  (for now; #TODO). Unlike the District class, POI has subclasses, so this needs just
  takes too long to materialize.
- Unreachable POIs aren't dropped, only excluded if max_travel_time_min is
  set. Otherwise sorted last and clearly marked; hiding them would make
  queries look broken given how rare direct connections are.
- District filtering matches schema:containedInPlace, already on every POI.
  Applied before travel-time computation, so it also narrows the routing
  workload. Accepts a number (1-23), "BezirkN", or a label substring;
  unresolvable input raises rather than matching nothing.
- No free-text description exists anywhere in the KG (for now). 
  describe_poi() is made to assemble a "best-effort description" 
  from whatever structured fields we have available at this stage.
- required_amenities matches both schema:amenityFeature (directly sourced) and
  viennakg:inferredTag (derived in kg/enrichment/infer_tags.py, so tags like
  "FamilyFriendly" are usable as a filter as well.
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
    """All 23 districts as {"number", "label", "uri"} dicts, sorted by
    number. Used for district dropdown/filter UIs."""
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
    """District number (1-23), "BezirkN", or a label substring -> district
    URI. Raises ValueError if nothing matches, rather than silently
    filtering to nothing."""
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
    """POIs of one class -> {uri: (name, lon, lat, district_uri)}. One
    simple triple pattern per class, see _candidate_pois for why.
    containedInPlace is OPTIONAL since it's a plain join, not the
    string-filtered kind that causes the query-planner issue below."""
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


def _pois_with_inferred_tag(g: Graph, tag_substring: str):
    """POI URIs with a viennakg:inferredTag containing `tag_substring`
    -> set of URIs. These are derived facts added in kg/enrichment/infer_tags.py"""
    q = f"""{PREFIXES}
    SELECT ?poi WHERE {{
        ?poi viennakg:inferredTag ?tag .
        FILTER(CONTAINS(LCASE(STR(?tag)), LCASE("{tag_substring}")))
    }}"""
    return {str(r.poi) for r in g.query(q)}


def _candidate_pois(g: Graph, poi_classes=None, required_amenities=None, district_uri=None):
    """POIs of the requested class(es) with all required amenities,
    optionally restricted to one district.

    Not one SPARQL query joining class-match and amenity-match: that
    triggers a severe rdflib query-planning issue on this graph (a query
    combining `?poi a ?type` with an amenityFeature join and a CONTAINS/
    LCASE filter took >35s; the same two patterns as separate queries take
    ~0.15s and ~0.25s combined). Root cause not fully diagnosed, likely a
    join-ordering issue with the string filter present. Fix: run each
    lookup separately, intersect the URI sets in Python. Returns
    (uri, name, class_label, lon, lat, district_uri) tuples.

    district_uri filtering happens here, before travel-time computation, so
    it also shrinks the routing workload downstream.

    Each entry in required_amenities can match either a schema:amenityFeature
    (sourced) or a viennakg:inferredTag (rule-derived, see
    _pois_with_inferred_tag), so "FamilyFriendly" works as a filter exactly
    like "Playground" does, even though nothing in the raw data says so."""
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
        matched_uris &= (_pois_with_amenity(g, amenity) | _pois_with_inferred_tag(g, amenity))

    if district_uri is not None:
        matched_uris = {u for u in matched_uris if by_class[u][4] == district_uri}

    return [(uri, *by_class[uri][:4]) for uri in matched_uris]


def describe_poi(g: Graph, poi_uri: str) -> str:
    """Best-effort description composed from whatever structured fields a
    POI has. No free-text description exists in the KG (see module
    docstring), so this assembles one from address/url/contact/opening-
    hours/area/amenities/subcategory, whichever are present. Returns "" if
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

    q3 = f"""{PREFIXES}
    SELECT ?tag WHERE {{ <{poi_uri}> viennakg:inferredTag ?tag . }}"""
    tags = sorted(str(r.tag) for r in g.query(q3))
    if tags:
        parts.append("tags: " + ", ".join(tags))

    return " -- ".join(parts)


def find_pois(g: Graph, router: GtfsRouter, origin_lon: float, origin_lat: float,
              poi_classes=None, required_amenities=None, district=None,
              max_travel_time_min=None, depart_after="14:00:00", max_transfers=2,
              max_walk_min=None, top_n=10, with_description=True):
    """Preference-matching POIs near (origin_lon, origin_lat), ranked by
    real transit travel time (not distance), up to max_transfers transfers.
    POIs with no connection at all are still included (sorted last) unless
    max_travel_time_min excludes them.

    district: optional filter to one Vienna district, accepts a number
    (1-23), "BezirkN", or a label substring (see resolve_district()). None
    searches all districts.

    max_walk_min: hard cap on walking time at both ends (e.g. 10 for a
    stroller/mobility constraint). None leaves walking unrestricted.

    with_description: attaches a best-effort description (see
    describe_poi()) to each of the final top_n results, only for what's
    returned, so it stays cheap. Set False to skip.

    Uses router.reachable_from() once for this origin, then travel_time_to()
    per candidate, not estimate_travel_time() in a loop, which would redo
    the full network search per candidate. For 1,000+ candidates that's the
    difference between ~3s and several minutes."""
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
