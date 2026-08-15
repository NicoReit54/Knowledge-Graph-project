# EDA — MUSEUMOGD.csv (Museen und Sammlungen)

## Basics
- 137 records, 8 columns, comma-delimited, CRLF line endings.
- Columns: `FID`, `SHAPE`, `NAME`, `BEZIRK`, `ADRESSE`, `WEITERE_INF`, `SE_SDO_ROWID`, `SE_ANNO_CAD_DATA`

## Geometry
- `SHAPE` is a WKT `POINT (lon lat)` string, already in WGS84 — no reprojection needed.
- All 137 rows parse cleanly; coordinates fall within Vienna's bounding box
  (lon 16.256–16.508, lat 48.145–48.264). No obvious outliers.

## Fields worth keeping
- `NAME` — museum name, no nulls
- `BEZIRK` — district number (1–23), no nulls, skews heavily to district 1 (55/137 —
  unsurprising, Innere Stadt has the museum quarter)
- `ADRESSE` — format is `"<district>., <Street> <number>"`, e.g.
  `"05., Schönbrunnerstraße 99"` — district is redundant with `BEZIRK` but the street
  address itself is clean and consistently formatted
- `WEITERE_INF` — mostly a website URL (135/137 populated), useful as a KG property
  but not for modelling

## Fields to drop
- `SE_SDO_ROWID`, `SE_ANNO_CAD_DATA` — ArcGIS/SDE internal bookkeeping columns.
  `SE_ANNO_CAD_DATA` is 100% null. Neither is meaningful for the KG.
- `FID` — dataset-internal feature ID, not stable/meaningful outside this file;
  fine to drop once a KG-internal ID is minted.

## Data quality issues
- **1 exact duplicate row**: "MAK - Museum für angewandte Kunst" appears twice with
  identical district and address (rows FID 138686-range indices 33 and 125). Needs
  deduplication before ingestion.
- No missing NAME/BEZIRK/ADRESSE/coordinates. Very clean otherwise.
- Address string bundles district + street; if joining spatially with other datasets
  it's safer to rely on `BEZIRK` + coordinates than parsing the address string.

## Suitability for the KG
Good candidate. Clean coordinates (no geocoding needed), consistent schema, small
size (easy to iterate on), and directly usable for spatial-proximity reasoning once
deduplicated. Suggested minimal mapping: `NAME` → `poi:name`, `BEZIRK` → `poi:district`,
parsed `lon`/`lat` → `geo:long`/`geo:lat`, `ADRESSE` → `poi:address`, `WEITERE_INF` →
`poi:website` (optional).
