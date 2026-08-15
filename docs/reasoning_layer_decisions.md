# Reasoning Layer decisions log

Decisions made before/while building the Reasoning Layer. Same pattern as
docs/kg_modelling_decisions.md — captured here so nothing gets re-litigated.

## Routing realism: GTFS-based, direct connections only

**Decision:** compute actual public-transport travel time (not straight-line
distance) using Wiener Linien's GTFS feed ("Fahrplandaten GTFS Wien" on
data.gv.at — confirmed to exist via the Mobilitätsverbünde Österreich catalog),
but scope routing to trips that don't require changing lines. Full multi-transfer
journey planning (general shortest-path routing across the whole network) is
explicitly out of scope — that's a substantial engineering problem on its own
(it's what dedicated routers like OpenTripPlanner exist for) and not a good use
of the remaining timeline.
**Why:** straight-line ("as the crow flies") distance, which is all the KG
currently supports (see the nearest-playground demo in
`notebooks/03_kg_visualization.ipynb`), is a poor proxy for actual transit time.
GTFS `stop_times.txt` gives real scheduled travel times, so it's the right data
source — but a full router is disproportionate effort for a proof-of-concept
scoped at "~5 POI categories" (now 7) per the one-pager.
**How to apply:** a trip = walk to nearest stop (distance ÷ assumed walking
speed) → ride using `stop_times` scheduled duration to a stop near the
destination, only if reachable without a line change → walk the last leg. If no
direct connection exists between the nearest stops, that's a legitimate "not
computed" result for the POC rather than something to force an answer for.

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
