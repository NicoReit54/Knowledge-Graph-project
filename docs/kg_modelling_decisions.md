# Modelling decisions log

Decisions made during Data Collection & EDA that shape the KG schema.

## Category scope (final, for now)

7 POI sources feeding the KG:
1. Museen (`data/processed/MUSEUMOGD_clean.csv`)
2. Büchereien (`data/raw/BUECHEREIOGD.csv`)
3. Badestellen (`data/raw/BADESTELLENOGD.csv`)
4. Parkanlagen (`data/processed/PARKINFOOGD_clean.csv`)
5. Schwimmbäder (`data/raw/SCHWIMMBADOGD.csv`)
6. Spielplätze (`data/raw/SPIELPLATZPUNKTOGD.csv`)
7. Sights (subset of `WIENTOURISMUSOGD.csv`): `data/processed/WIENTOURISMUS_sights_clean.csv`

Plus Wiener Linien transit data (stops/platforms/lines, see
`docs/wiener_linien_api_notes.md`) but seperately from the KG.

## Multi-features

**Decision: separate nodes per feature, not list-valued properties.**
Applies to Spielplätze (`SPIELPLATZ_DETAIL` equipment, `TYP_DETAIL` category,
and the repeated `ANL_NAME` rows in general). Each CSV row becomes its own
POI node/feature in the KG rather than aggregating by playground name into
one node with a list property. Same as the input data in a way and hence a 
bit easier to handle.

**Contrast with WIENTOURISMUS "sights" duplicates:** the 3 repeated names
found there (Haus des Meeres, Judenplatz, Rathausplatz) are a *different*
situation: same landmark listed twice with a ~10-15m coordinate difference and a
different `UID_`, not distinct sub-features. Those were deduplicated (kept
first), unlike the Spielplätze repeats which are genuinely separate
features.

## Field-level decisions

- **`FLAECHE` (park area):** from formatted string (e.g.
  `"14.714 m²"`, German thousands-separator) to numeric `FLAECHE_M2`. Done
  in `data/processed/PARKINFOOGD_clean.csv`.
- **`BADEQUALITAET` (Badestellen water quality code):** dropped from the
  schema. Water quality is consistently good across Vienna's bathing sites
  (see `eda_BADESTELLENOGD.ipynb`), so this field is not useful for any
  reasoning logic for now (TODO: Revisit in the future if necessary).
- **`BEZIRK` for the new sights subset:** `WIENTOURISMUSOGD.csv` has no
  `BEZIRK` column, only `POSTALCODE`. Derived via following postal code
  convention (`BEZIRK = (POSTALCODE - 1000) / 10`). 

## Known open items (not yet decided, not blocking)

- Opening hours (Büchereien's `OEFFNUNGSZEITEN1..6`, Parks' `OEFF_ZEITEN`)
  are free text and not yet parsed into something useful. TODO
- Live/temporal signals of Wiener Linien not taken into account yet.

## KG Creation
**Decision: in-memory `rdflib.Graph()` serialized to a single Turtle file
(`kg/vienna_mobility_kg.ttl`), not an external triple store.** At this
project's scale (80,485 triples total: TBox + all 7 POI sources + full
Wiener Linien transport data), rdflib builds and serializes the whole graph
from scratch in a few seconds. No need for GraphDB/... setup
and maintenance overhead for a proof-of-concept this size and other personal
time constraints such as work and others...

**How to apply:** if query performance becomes a real bottleneck (e.g. once
live data or a bigger POI set is added), swapping in a real triple store
is more of a plug and play situation, not a redesign. The ontology and mapping
logic don't change either way. 

**Two ingestion scripts/notebooks exist; on purpose to show the thought process:**
- `notebooks/02_kg_instantiation.ipynb`: exploratory, cell-by-cell, with
  inline SPARQL validation queries, writes `kg/instances_demo.ttl`.
- `kg/ingestion/build_kg.py`: the same mapping logic, written into a
  reusable script, writes actual `kg/vienna_mobility_kg.ttl`.
