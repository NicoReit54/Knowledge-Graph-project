# (Live) Mobility KG for Vienna

Knowledge Graphs VU, 2026S, Nico Reiterer (6 ECTS)

## Project

Integrates City of Vienna open data (points-of-interest) with (live) Wiener Linien
transit data into a unified knowledge graph. Uses reasoning to generate personalized
activity plans and route suggestions based on user interests, spatial proximity, and
(live) mobility constraints.

See `docs/One-Pager.pdf` for the full project description and learning outcome scope.

## Status (updated 2026-08-25)

All five pipeline phases from the one-pager have at least a first working version.
Way ahead of the original 8-week plan (see `TIMELINE.md`).

1. **Data Collection & EDA**: done. 17 City of Vienna POI CSVs profiled, narrowed
   to 7 final sources. Wiener Linien static transit data (stops/platforms/lines)
   downloaded and joined.
2. **KG Modelling**: done. Ontology at `kg/schema/ontology.ttl`, reusing
   schema.org/W3C Geo/SKOS. Design + rationale in `docs/kg_schema_design.md`.
3. **KG Creation**: done. `kg/ingestion/build_kg.py` builds the full KG
   (80,485 triples) into `kg/vienna_mobility_kg.ttl` in one command.
4. **Reasoning Layer**: done (first pass). `reasoning/gtfs_routing.py` computes
   real public-transport travel time (not straight-line distance) using GTFS,
   with up to 2 transfers (extended from an initial direct-only version once
   that turned out to cover under 1% of POI pairs) and a configurable hard
   walking-distance limit (`max_walk_min`, for mobility constraints like a
   stroller). `reasoning/preference_filter.py`'s `find_pois()` combines
   category/amenity matching with travel-time ranking. See
   `docs/reasoning_layer_decisions.md`.
5. **Service Layer**: done (first pass). `service/activity_planner.py`'s
   `plan_activities()` generates real 1-to-5-stop itineraries (not just single
   POI suggestions or bare travel-time chains), visited in the given order and
   found via a bounded beam search (not exhaustive branching, which is
   intractable past ~2 stops, see `docs/service_layer_decisions.md`). Each
   stop can carry its own district filter (`schema:containedInPlace`-based)
   and gets a best-effort description composed from whatever structured KG
   fields it has. Per-category default visit durations (overridable) are
   folded into the time budget and correctly chained into each leg's
   departure time; the same POI is never suggested twice within one plan.
   `notebooks/06_service_layer.ipynb` has fixed examples plus an interactive
   ipywidgets form (up to 5 interest slots). See
   `docs/service_layer_decisions.md`.

**Not started:** live data (RBL/`monitor` API) wired into reasoning, a return
trip in itineraries, and GNN exploration (stretch goal, lowest priority). No
specific next-session request pending, see `docs/service_layer_decisions.md`
and `TIMELINE.md` for what's naturally next.

## Stack

RDF/SPARQL-based: rdflib (in-memory graph, serialized to Turtle, no external
triple store needed at this scale, see `docs/kg_modelling_decisions.md`), pandas
for GTFS/tabular work, matplotlib for visualization, ipywidgets for the Service
Layer's interactive demo. Dependency management via `uv` (`pyproject.toml` /
`uv.lock`), not pip/requirements.txt.

## Structure

- `data/raw/`: original downloaded datasets, untouched. 17 City of Vienna POI
  CSVs, 3 Wiener Linien static CSVs (`wienerlinien-ogd-*`), and `gtfs/` (the full
  Wiener Linien GTFS schedule feed, `stop_times.txt` alone is 7.1M rows/621MB)
- `data/processed/`: cleaned/derived data. Deduped/parsed POI CSVs (see
  `notebooks/01_cleaning_data.ipynb`) and the GTFS feed pre-filtered to one
  representative service day (`gtfs_wl_<date>_*.csv`, see `reasoning/gtfs_routing.py`)
- `notebooks/`: numbered, run in order for the full story:
  - `00_eda_overview_all_files.ipynb`: cross-file EDA/comparison across all 17 raw CSVs
  - `eda_*.ipynb` (+ one stray `eda_MUSEUMOGD.md`, superseded, safe to delete): per-file deep-dive EDA
  - `01_cleaning_data.ipynb`: the 3 cleaning transformations, consolidated and reproducible
  - `02_kg_instantiation.ipynb`: exploratory, cell-by-cell version of the ingestion logic
  - `03_kg_visualization.ipynb`: fun sanity-check visuals (bar chart, coordinate "map", mini graph diagrams)
  - `04_reasoning_travel_time.ipynb`: validates the GTFS travel-time reasoning (incl. multi-transfer)
  - `05_preference_filtering.ipynb`: validates category/amenity + travel-time ranking
  - `06_service_layer.ipynb`: multi-stop itineraries, visit times, walk-time limit, interactive demo
- `kg/schema/ontology.ttl`: the TBox (classes, properties); see `docs/kg_schema_design.md`
- `kg/ingestion/build_kg.py`: rerunnable ingestion script.
  `python kg/ingestion/build_kg.py` rebuilds `kg/vienna_mobility_kg.ttl` (the
  canonical KG artifact) from `data/raw/` + `data/processed/`
- `kg/vienna_mobility_kg.ttl`: the current full KG (TBox + ABox). `kg/instances_demo.ttl`
  is an earlier, superseded 3-source demo from the notebook, safe to delete
- `reasoning/gtfs_routing.py`: `GtfsRouter`, multi-platform, up-to-2-transfer
  travel-time estimation using GTFS, independent of the RDF graph (see
  `docs/reasoning_layer_decisions.md` for why they're not formally linked).
  Key methods: `estimate_travel_time()` (one-off), `reachable_from()` +
  `travel_time_to()` (batch-efficient, compute reachability once per origin)
- `reasoning/preference_filter.py`: `find_pois()`, category/amenity/district-matched
  POIs ranked by real travel time; `describe_poi()` composes a best-effort
  description from structured KG fields (no free-text description exists in
  the source data); `list_districts()`/`resolve_district()` for the district filter
- `service/activity_planner.py`: `plan_activities()`, 1-to-5-stop itineraries
  (bounded beam search, fixed stop order, POI dedup within a plan) with
  per-category visit durations (`DEFAULT_VISIT_MINUTES`), per-stop district
  filtering, and an optional hard `max_walk_min` constraint; `format_plan()`
  for human-readable output
- `docs/`: key files for orientation:
  - `One-Pager.pdf`: the original project proposal
  - `wiener_linien_api_notes.md`: live API + static data notes
  - `kg_modelling_decisions.md`: scope/cleaning/schema decisions log
  - `kg_schema_design.md`: full ontology design + per-file mapping table
  - `reasoning_layer_decisions.md`: routing scope decisions log (direct-only → 2-transfer)
  - `service_layer_decisions.md`: Service Layer design log

## Timeline

See `TIMELINE.md`. Hard deadline: 2026-09-30.

## Setup

```bash
uv sync
uv run jupyter lab
```
