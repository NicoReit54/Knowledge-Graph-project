# (Live) Mobility KG for Vienna

Knowledge Graphs VU, 2026S — Nico Reiterer (6 ECTS)

## Project

Integrates City of Vienna open data (points-of-interest) with (live) Wiener Linien
transit data into a unified knowledge graph. Uses reasoning to generate personalized
activity plans and route suggestions based on user interests, spatial proximity, and
(live) mobility constraints.

See `docs/One-Pager.pdf` for the full project description and learning outcome scope.

## Stack

RDF/SPARQL-based (rdflib, optionally GraphDB for larger-scale querying).

## Structure

- `data/raw/` — original downloaded datasets (Wiener Linien, City of Vienna POI data), untouched
- `data/processed/` — cleaned/transformed data ready for KG ingestion
- `notebooks/` — EDA, cleaning, and KG-instantiation walkthroughs (01_cleaning_data,
  02_kg_instantiation — the exploratory, cell-by-cell version of the ingestion logic)
- `kg/schema/ontology.ttl` — the TBox (classes, properties); see `docs/kg_schema_design.md`
- `kg/ingestion/build_kg.py` — rerunnable ingestion script; rebuilds
  `kg/vienna_mobility_kg.ttl` (the canonical KG artifact) from `data/raw/` +
  `data/processed/` in one command: `python kg/ingestion/build_kg.py`
- `kg/vienna_mobility_kg.ttl` — the current full KG (TBox + ABox), rdflib/Turtle-backed
  (no external triple store — plenty fast at this scale, see
  `docs/kg_modelling_decisions.md`)
- `reasoning/` — reasoning rules and queries (proximity, routing, preference filtering)
- `service/` — demo layer producing activity/route suggestions from the KG
- `docs/` — one-pager, notes, write-up material

## Timeline

See `TIMELINE.md`. Hard deadline: 2026-09-30.

## Setup

\`\`\`bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
\`\`\`
