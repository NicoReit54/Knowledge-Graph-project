# Modelling decisions log

Decisions made during Data Collection & EDA that shape the upcoming KG schema.
Keeping this here so nothing gets re-litigated during KG Modelling week.

## Category scope (final, for now)

7 POI sources feeding the KG:
1. Museen (`data/processed/MUSEUMOGD_clean.csv`)
2. Büchereien (`data/raw/BUECHEREIOGD.csv`)
3. Badestellen (`data/raw/BADESTELLENOGD.csv`)
4. Parkanlagen (`data/processed/PARKINFOOGD_clean.csv`)
5. Schwimmbäder (`data/raw/SCHWIMMBADOGD.csv`)
6. Spielplätze (`data/raw/SPIELPLATZPUNKTOGD.csv`)
7. Sights (subset of `WIENTOURISMUSOGD.csv`) — `data/processed/WIENTOURISMUS_sights_clean.csv`

Plus Wiener Linien transit data (stops/platforms/lines, see
`docs/wiener_linien_api_notes.md`).

## Multi-feature / multi-value handling

**Decision: separate nodes per feature, not list-valued properties.**
Applies to Spielplätze (`SPIELPLATZ_DETAIL` equipment, `TYP_DETAIL` category, and
the repeated `ANL_NAME` rows in general) — each CSV row becomes its own POI
node/feature in the KG rather than aggregating by playground name into one node
with a list property. This is the more granular option and matches how the
source data is already structured (one row = one point-feature).

**Contrast with WIENTOURISMUS "sights" duplicates:** the 3 repeated names found
there (Haus des Meeres, Judenplatz, Rathausplatz) are a *different* situation —
same landmark listed twice with a ~10-15m coordinate drift and a different
`UID_`, not distinct sub-features. Those were deduplicated (kept first), unlike
the Spielplätze repeats which are genuinely separate features.

## Field-level decisions

- **`FLAECHE` (park area):** parsed from formatted string (e.g. `"14.714 m²"`,
  German thousands-separator) to numeric `FLAECHE_M2`. Done in
  `data/processed/PARKINFOOGD_clean.csv`. All 1,051 rows parsed successfully.
- **`BADEQUALITAET` (Badestellen water quality code):** dropped from the schema.
  Deprioritized as a modelling attribute — water quality is consistently good
  across Vienna's bathing sites, so it's not a useful discriminating feature for
  activity-plan reasoning.
- **`BEZIRK` for the new sights subset:** `WIENTOURISMUSOGD.csv` has no `BEZIRK`
  column, only `POSTALCODE`. Derived via Vienna's postal code convention
  (`BEZIRK = (POSTALCODE - 1000) / 10`, valid for 1010–1230 in steps of 10) — all
  247 rows mapped cleanly, no unmapped postcodes.

## Known open items (not yet decided, not blocking)

- Opening hours (Büchereien's `OEFFNUNGSZEITEN1..6`, Parks' `OEFF_ZEITEN`) are
  free text — parsing into structured queryable hours is a stretch goal, not
  in scope for the first pass.
- Live/temporal signals beyond Wiener Linien: Schwimmbäder occupancy
  (`AUSLASTUNG_*`) and Badestellen water-quality test dates
  (`UNTERSUCHUNGSDATUM`) are both live-ish but not yet wired into any reasoning
  logic — revisit when building the Reasoning Layer.
