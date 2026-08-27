# KG Evolution decisions log (LO8)

Decisions made while building the KG completion step. Same pattern as the
other decisions logs, captured here so nothing gets re-litigated.

## Distinct predicate for inferred facts, not reusing schema:amenityFeature

**Decision:** rule-derived facts get their own predicate,
`viennakg:inferredTag` (a plain string literal on the POI), rather than
being added as more `schema:amenityFeature` entries.

**Why:** the whole point of LO8 is to show the KG *evolving*, i.e. facts
appearing that weren't in any source file, derived purely from triples
already present. If inferred tags lived on the same predicate as sourced
amenities, there'd be no way to tell which triples came from a CSV and
which came from a rule just by looking at the graph. A separate predicate
keeps that provenance visible and queryable (`?poi viennakg:inferredTag
?tag` finds only rule output, nothing else).

**How to apply:** `kg/enrichment/infer_tags.py` is the only thing that
writes `viennakg:inferredTag`. It runs after `kg/ingestion/build_kg.py`
(needs the graph fully built first) and is idempotent: rerunning it adds
nothing new, since `rdflib.Graph` is a set and each rule always produces
the same triples for the same match. Safe to run again after every
`build_kg.py` rebuild, not just once.

## The 5 rules

Chosen to cover different inference techniques, not five variations on one
idea. Counts below are against the live KG (`kg/vienna_mobility_kg.ttl`,
80,485 triples before tagging, 82,520 after: 2,035 new triples).

1. **FamilyFriendly** (boolean conjunction): `schema:Park` with both
   "Playground" and "Water feature" amenities true.
   **465 / 1,051 parks.**
2. **ActivePlayground** (count/aggregation threshold): `viennakg:PlaygroundArea`
   with 4 or more distinct equipment types marked true (median playground
   has 5, so this is "above-average equipped", not a rare outlier).
   **491 / 771 playground areas.**
3. **QuietPocketPark** (numeric threshold + negation): `schema:Park` under
   3,000 sqm *without* a Playground amenity, small and not obviously a
   family destination.
   **313 / 1,051 parks.**
4. **OldTownLandmark** (categorical + spatial containment):
   `schema:TouristAttraction` located in Bezirk1 (Innere Stadt, Vienna's
   old town). Turns out every tourist attraction in Bezirk1 qualifies, no
   extra subcategory filter needed to narrow it down.
   **87 / 247 tourist attractions.**
5. **TransitAccessibleForFamilies** (cross-domain spatial-distance
   computation): `viennakg:PlaygroundArea` within 300m (haversine) of a
   `viennakg:Stop`. The only rule that crosses from the POI side of the
   graph to the transit side.
   **679 / 771 playground areas.**

Rule 5's match rate (88%) is much higher than the others. Flagging that
honestly rather than hiding it: Vienna's transit network is dense enough
that "near a stop" isn't a very discriminating filter for playgrounds
specifically. Kept anyway since dropping it would mean losing the one rule
that reasons across both halves of the KG (POIs and transit), which is
worth more here than a cleaner match rate.

## Implementation: split queries, not one combined SPARQL query

**Decision:** each rule runs as one or two simple SPARQL queries plus a
Python set intersection/union, never one query that joins class-match,
amenity-match, and a numeric filter together.

**Why:** same rdflib query-planner issue already documented in
`reasoning/preference_filter.py` (`_candidate_pois()`): combining a class
join with an amenityFeature join and a string filter in one query can take
35s+ or hang entirely, while the same patterns as separate queries run in
well under a second combined. Confirmed again live while building rule 3
(a combined Park + two amenityFeature joins query hit the 120s timeout;
split into separate queries it ran in 0.26s). Not worth re-diagnosing the
root cause every time, the fix is always the same: split and intersect in
Python.

## Wiring into find_pois(): inferred tags are real filters, not just labels

**Decision:** `reasoning/preference_filter.py`'s `required_amenities`
matches both `schema:amenityFeature` (sourced) and `viennakg:inferredTag`
(rule-derived), via a new `_pois_with_inferred_tag()` alongside the
existing `_pois_with_amenity()`. `describe_poi()` also lists any inferred
tags a POI has, alongside its other structured fields.

**Why:** a completion step that only writes triples nobody can query is a
weaker demonstration of "evolution" than one that's actually usable end to
end. Calling `find_pois(poi_classes=["Park"],
required_amenities=["FamilyFriendly"])` now works exactly like searching
for "Playground" does, even though "FamilyFriendly" appears nowhere in any
raw CSV.

**How to apply:** `_candidate_pois()` unions the amenity-match and
inferred-tag-match sets per required amenity, then intersects across all
requirements, same pattern as before. Verified: `Park` + `FamilyFriendly`
returns exactly 465 (matches the rule's own count), and `Park` +
`["Playground", "FamilyFriendly"]` together still returns exactly 465
(FamilyFriendly already implies Playground=true, so adding the sourced
amenity as an extra filter shouldn't narrow the set further, and it
doesn't).

## LO8 mapping

This whole feature exists to claim LO8 ("evolve a knowledge graph"):
`kg/enrichment/infer_tags.py` is a genuine post-hoc completion pass that
adds facts the graph didn't have, distinguishable by predicate from
everything ingestion produced, safely rerunnable, and immediately useful
through the existing Service Layer rather than sitting inert.
