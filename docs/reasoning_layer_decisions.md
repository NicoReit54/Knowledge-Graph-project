# Reasoning Layer decisions log

Decisions made before/while building the Reasoning Layer. Same pattern as
docs/kg_modelling_decisions.md — captured here so nothing gets re-litigated.

## Routing realism: GTFS-based, up to 2 transfers (superseded direct-only)

**Original decision (2026-08-15):** direct connections only, no transfers.
**Revised (2026-08-18):** extended to a bounded, RAPTOR-lite round-based
search allowing up to 2 transfers, once the direct-only limitation's real
cost became clear in practice: well under 1% of POI pairs had a direct
connection (see `notebooks/04_reasoning_travel_time.ipynb`'s original
findings), which is a bad look for a project literally about generating
activity suggestions — most real suggestions would've come back "no route."
Full unbounded multi-transfer journey planning (arbitrary transfer count,
proper Pareto-optimal itinerary sets) is still out of scope — that remains a
substantially bigger problem (what dedicated routers like OpenTripPlanner
solve) than a 2-round bounded search.
**Why:** GTFS `stop_times.txt` gives real scheduled travel times, so it's the
right data source (unchanged reasoning from the original decision) — but
"direct only" turned out to understate real transit accessibility so badly
that it wasn't a useful proof-of-concept limitation, it was closer to
"routing doesn't really work for most queries." A bounded 2-transfer search
is a meaningfully bigger implementation (see `reasoning/gtfs_routing.py`) but
still tractable: round-based (round 0 = direct, round 1 = one transfer,
round 2 = two), vectorized with pandas merges rather than per-stop Python
loops, ~0.2-0.4s per origin search even across the whole network.
**How to apply:** `GtfsRouter.reachable_from(origin, ...)` computes reachability
to the WHOLE network from one origin in one pass; `travel_time_to(...)` then
does a cheap per-destination lookup against that result. For checking many
candidate destinations from one origin (e.g. `preference_filter.find_pois()`
ranking a whole POI category), always use this split pattern, not
`estimate_travel_time()` in a loop — that recomputes the full network search
per candidate and is 100x+ slower for batch use. Direct (0-transfer)
connections are still always found first (round 0) and are never displaced by
a slower multi-transfer route to the same destination — a later round only
overwrites an entry if it's strictly faster.

**Two real bugs found while building the 2-transfer search** (both fixed,
worth remembering since they'd resurface in similar spatial/graph-search code):
1. Considering only the single geometrically-nearest stop as a search origin
   can silently pick a badly-connected platform (e.g. one near the END of
   most trip patterns — an alighting-heavy platform) even when a slightly
   farther platform at the same named stop boards well. Fixed by considering
   every stop within walking distance as a possible starting point
   (`_nearby_stops()`), not just the nearest one.
2. The total-time formula was double-counting the initial walk leg (present
   even in the original direct-only version, ~2 min systematic overcount on
   the earlier notebook's numbers — not dramatically wrong, but a real bug).
   Also needed a deliberate tie-break rule (prefer the option requiring the
   *shortest* walk when two boarding choices land on the exact same arrival
   time — common on frequent lines) since an arbitrary tie-break could
   surface a 17-minute walk over a 2-minute one for an identical total time.

## Architecture: GTFS stays tabular, not fully tripled into the KG

**Decision:** GTFS's trip-level data (`stop_times.txt` etc.) is not modelled as
RDF triples. It's kept as a supporting tabular resource (e.g. loaded with
pandas/a GTFS library) that the Reasoning Layer's routing function queries
alongside the KG at run time, rather than materializing every scheduled trip as
graph triples.
**Why:** a full year of Vienna's schedule is easily millions of rows — modelling
that at RDF triple granularity would dwarf the rest of the KG (currently 80,485
triples total) for no reasoning benefit; the KG's job is entities/structure/
spatial/category reasoning, not raw timetable storage.
**How to apply:** the ontology (`kg/schema/ontology.ttl`) doesn't need new GTFS
trip/stop_time classes. What it likely does need: `viennakg:Platform` currently
has no stop-sequence/direction properties (`REIHENFOLGE`/`RICHTUNG` from
`steige.csv` were never ingested) — add these if/when direct-connection lookups
need "which stop comes next on this line" logic that GTFS's own `stop_sequence`
doesn't already cover more reliably.

## Next step

Grab the GTFS feed directly (same pattern as other bulk downloads in this
project — sandbox network access to data.gv.at/data.wien.gv.at is unreliable,
Nico has unrestricted access) and drop the relevant files
(`stops.txt`, `routes.txt`, `trips.txt`, `stop_times.txt`, `calendar.txt`) into
`data/raw/gtfs/`.
