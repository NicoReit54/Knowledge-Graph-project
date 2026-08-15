# (Live) Mobility KG for Vienna

Knowledge Graphs VU, 2026S — Nico Reiterer (6 ECTS)

## Project

Integrates City of Vienna open data (points-of-interest) with (live) Wiener Linien
transit data into a unified knowledge graph. Uses reasoning to generate personalized
activity plans and route suggestions based on user interests, spatial proximity, and
(live) mobility constraints.

See `docs/One-Pager.pdf` for the full project description and learning outcome scope.

## Status (updated 2026-08-15)

Ahead of the original plan — Data Collection & EDA, KG Modelling, and KG Creation
are done, and the Reasoning Layer has a first working piece, all as of week 1 of
the original 8-week timeline (see `TIMELINE.md`). Roughly in order of what happened:

1. **Data Collection & EDA** — done. 17 City of Vienna POI CSVs profiled (per-file
   + cross-file overview notebooks), narrowed to 7 final sources. Wiener Linien
   static transit data (stops/platforms/lines) downloaded and joined.
2. **KG Modelling** — done. Ontology at `kg/schema/ontology.ttl`, reusing
   schema.org/W3C Geo/SKOS rather than inventing everything. Design + rationale
   in `docs/kg_schema_design.md`.
3. **KG Creation** — done. `kg/ingestion/build_kg.py` builds the full KG
   (80,485 triples: TBox + all 7 POI sources + full Wiener Linien transport data)
   into `kg/vienna_mobility_kg.ttl` in one command.
4. **Reasoning Layer** — started. `reasoning/gtfs_routing.py` computes actual
   public-transport travel time (not straight-line distance) using Wiener
   Linien's GTFS schedule, scoped to direct (no-transfer) connections. See
   `docs/reasoning_layer_decisions.md` for why, and
   `notebooks/04_reasoning_travel_time.ipynb` for the validation.

**Not started yet:** live data (RBL/`monitor` API) wired into reasoning, the
Service Layer (activity/route suggestion demo), and GNN exploration (stretch
goal, first thing to cut if time runs short).

## Stack

RDF/SPARQL-based: rdflib (in-memory graph, serialized to Turtle — no external
triple store needed at this scale, see `docs/kg_modelling_decisions.md`), pandas
for GTFS/tabular work, matplotlib for visualization. Dependency management via
`uv` (`pyproject.toml` / `uv.lock`), not pip/requirements.txt.

## Structure

- `data/raw/` — original downloaded datasets, untouched: 17 City of Vienna POI
  CSVs, 3 Wiener Linien static CSVs (`wienerlinien-ogd-*`), and `gtfs/` (the full
  Wiener Linien GTFS schedule feed — `stop_times.txt` alone is 7.1M rows/621MB)
- `data/processed/` — cleaned/derived data: deduped/parsed POI CSVs (see
  `notebooks/01_cleaning_data.ipynb`) and the GTFS feed pre-filtered to one
  representative service day (see `reasoning/gtfs_routing.py`)
- `notebooks/` — numbered, run in order for the full story:
  - `00_eda_overview_all_files.ipynb` — cross-file EDA/comparison across all 17 raw CSVs
  - `eda_*.ipynb` (+ one stray `eda_MUSEUMOGD.md`, superseded, safe to delete) — per-file deep-dive EDA
  - `01_cleaning_data.ipynb` — the 3 cleaning transformations, consolidated and reproducible
  - `02_kg_instantiation.ipynb` — exploratory, cell-by-cell version of the ingestion logic
  - `03_kg_visualization.ipynb` — fun sanity-check visuals (bar chart, coordinate "map", mini graph diagrams)
  - `04_reasoning_travel_time.ipynb` — validates the GTFS travel-time reasoning
- `kg/schema/ontology.ttl` — the TBox (classes, properties); see `docs/kg_schema_design.md`
- `kg/ingestion/build_kg.py` — rerunnable ingestion script:
  `python kg/ingestion/build_kg.py` rebuilds `kg/vienna_mobility_kg.ttl` (the
  canonical KG artifact) from `data/raw/` + `data/processed/`
- `kg/vienna_mobility_kg.ttl` — the current full KG (TBox + ABox). `kg/instances_demo.ttl`
  is an earlier, superseded 3-source demo from the notebook — safe to delete
- `reasoning/gtfs_routing.py` — `GtfsRouter`: nearest-stop lookup + direct-connection
  travel-time estimation using GTFS, independent of the RDF graph (see
  `docs/reasoning_layer_decisions.md` for why they're not formally linked)
- `service/` — not started yet: demo layer producing activity/route suggestions from the KG
- `docs/` — key files for orientation:
  - `One-Pager.pdf` — the original project proposal
  - `wiener_linien_api_notes.md` — live API + static data notes
  - `kg_modelling_decisions.md` — scope/cleaning/schema decisions log
  - `kg_schema_design.md` — full ontology design + per-file mapping table
  - `reasoning_layer_decisions.md` — routing scope decisions log

## Timeline

See `TIMELINE.md`. Hard deadline: 2026-09-30.

## Setup

```bash
uv sync
uv run jupyter lab
```
