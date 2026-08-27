"""
Adds viennakg:inferredTag facts to POIs that no source CSV states directly, 
derived directly from triples already in the graph.

Five rules, chosen to cover/showcase that you can already infer from that
simple of a graph. Obviously this can be expanded very much.

1. FamilyFriendly: Park with both "Playground" and "Water feature" amenities true. 465 / 1051 parks.
2. ActivePlayground: PlaygroundArea with 4 or more distinct equipment types marked true. 491 / 771 playground areas.
3. QuietPocketPark (based on Uli Simas famous pocket park, iykyk): Park under 3000 sqm without a Playground amenity. 313 / 1051 parks.
4. OldTownLandmark: TouristAttraction located in Bezirk1 (Innere Stadt, Vienna's old town). 87 / 247 tourist attractions.
5. TransitAccessibleForFamilies: PlaygroundArea within 300m (haversine) of a Stop. 679 / 771 playground areas. 
   Funfact: High match rate reflects how dense Vienna's stop network actually is.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
from rdflib import Graph, Literal, Namespace, URIRef

from reasoning.gtfs_routing import haversine_m

VIENNAKG = Namespace("http://example.org/viennakg#")

PREFIXES = """
PREFIX schema: <https://schema.org/>
PREFIX viennakg: <http://example.org/viennakg#>
PREFIX geo: <http://www.w3.org/2003/01/geo/wgs84_pos#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""

# Randomly chosen thresholds for the rules
AREA_THRESHOLD_SQM = 3000
EQUIPMENT_THRESHOLD = 4
TRANSIT_DISTANCE_M = 300


def _pois_with_amenity_true(g: Graph, class_qname: str, amenity_name: str):
    q = f"""{PREFIXES}
    SELECT ?poi WHERE {{
        ?poi a {class_qname} ; schema:amenityFeature ?f .
        ?f schema:name "{amenity_name}" ; schema:value true .
    }}"""
    return {str(r.poi) for r in g.query(q)}


def rule_family_friendly(g: Graph):
    playground = _pois_with_amenity_true(g, "schema:Park", "Playground")
    water = _pois_with_amenity_true(g, "schema:Park", "Water feature")
    return playground & water


def rule_active_playground(g: Graph):
    q = f"""{PREFIXES}
    SELECT ?poi ?fname WHERE {{
        ?poi a viennakg:PlaygroundArea ; schema:amenityFeature ?f .
        ?f schema:name ?fname ; schema:value true .
    }}"""
    equipment = defaultdict(set)
    for r in g.query(q):
        equipment[str(r.poi)].add(str(r.fname))
    return {uri for uri, names in equipment.items() if len(names) >= EQUIPMENT_THRESHOLD}


def rule_quiet_pocket_park(g: Graph):
    q = f"""{PREFIXES}
    SELECT ?poi ?area WHERE {{
        ?poi a schema:Park ; viennakg:areaSqm ?area .
    }}"""
    small = {str(r.poi) for r in g.query(q) if float(r.area) < AREA_THRESHOLD_SQM}
    playground = _pois_with_amenity_true(g, "schema:Park", "Playground")
    return small - playground


def rule_old_town_landmark(g: Graph):
    q = f"""{PREFIXES}
    SELECT ?poi WHERE {{
        ?poi a schema:TouristAttraction ; schema:containedInPlace viennakg:Bezirk1 .
    }}"""
    return {str(r.poi) for r in g.query(q)}


def rule_transit_accessible_for_families(g: Graph):
    """Nearest-stop distance per playground, computed in Python rather
    than SPARQL. rdflib has no spatial index, so a cross join filtered by
    haversine would be O(playgrounds x stops) inside the query engine
    too; doing it with numpy is the same cost but much faster in
    practice. A cheap planar distance picks the nearest candidate stop
    first, then haversine gives the real distance just for that one."""
    q_stops = f"""{PREFIXES}
    SELECT ?lon ?lat WHERE {{ ?s a viennakg:Stop ; geo:long ?lon ; geo:lat ?lat . }}"""
    stops = np.array([(float(r.lon), float(r.lat)) for r in g.query(q_stops)])

    q_pg = f"""{PREFIXES}
    SELECT ?poi ?lon ?lat WHERE {{
        ?poi a viennakg:PlaygroundArea ; geo:long ?lon ; geo:lat ?lat .
    }}"""
    out = set()
    for r in g.query(q_pg):
        lon, lat = float(r.lon), float(r.lat)
        approx = np.hypot(stops[:, 0] - lon, stops[:, 1] - lat)
        nearest = stops[np.argmin(approx)]
        if haversine_m(lon, lat, nearest[0], nearest[1]) <= TRANSIT_DISTANCE_M:
            out.add(str(r.poi))
    return out


RULES = {
    "FamilyFriendly": rule_family_friendly,
    "ActivePlayground": rule_active_playground,
    "QuietPocketPark": rule_quiet_pocket_park,
    "OldTownLandmark": rule_old_town_landmark,
    "TransitAccessibleForFamilies": rule_transit_accessible_for_families,
}

def infer_tags(g: Graph, verbose: bool = True) -> dict:
    """Runs all 5 rules and adds a viennakg:inferredTag triple for every
    match. Returns {tag: match_count}."""
    counts = {}
    for tag, rule in RULES.items():
        uris = rule(g)
        for uri in uris:
            g.add((URIRef(uri), VIENNAKG.inferredTag, Literal(tag)))
        counts[tag] = len(uris)
        if verbose:
            print(f"  {tag:32} {len(uris):>4} POIs tagged")
    return counts


def main():
    root = Path(__file__).resolve().parents[2]
    kg_path = root / "kg" / "vienna_mobility_kg.ttl"

    g = Graph()
    g.parse(str(kg_path), format="turtle")
    before = len(g)
    print(f"Loaded {before} triples")

    print("Running KG completion rules:")
    counts = infer_tags(g)

    g.serialize(destination=str(kg_path), format="turtle")
    print(f"\nSaved {len(g)} triples to {kg_path.relative_to(root)} "
          f"({len(g) - before} new triples, {sum(counts.values())} inferredTag matches total)")
    return g


if __name__ == "__main__":
    main()
