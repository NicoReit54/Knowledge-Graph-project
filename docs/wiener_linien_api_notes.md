# Wiener Linien Open Data — API Notes

Source: https://www.wienerlinien.at/open-data, wienerlinien-echtzeitdaten-dokumentation.pdf

## Access

- No API key required. Older docs reference a `sender` param — ignore/omit it.
- CC BY license, commercial use allowed with attribution.
- Fair-use: min. 15s polling interval recommended.
- Base domain: `http://www.wienerlinien.at/ogd_realtime/`
- Static reference data (stop list w/ GPS, elevators, etc.) refreshed every 6h via
  Vienna's central open data portal (data.gv.at / Datendrehscheibe).

## Available datasets

- Echtzeit-Abfahrtsdaten (real-time departures) — the `monitor` endpoint
- Betriebsstörungen / Aufzugsausfälle (disruptions / elevator outages)
- Hinweise / News (maintenance notices)
- Routing
- Geodaten von Haltestellen und Aufzügen (stop + elevator geo data)
- Statistikdaten (tram/bus/subway operations stats)
- Modified stop list with GPS coordinates

## `monitor` endpoint (departures)

`GET .../monitor?rbl=<RBL>&activateTrafficInfo=stoerungkurz&activateTrafficInfo=stoerunglang&activateTrafficInfo=aufzugsinfo`

- `rbl` = stop ID (from the static stop list), repeatable for multiple stops
- Returns per stop: geo coordinates (WGS84), stop name/municipality, and per line:
  name, direction, `towards`, `barrierFree` (accessibility flag), `type` (ptTram,
  ptBusNight, ...), and departures with `timePlanned` / `timeReal` / `countdown` (min).
- Linked disruptions surface via `trafficInfos` (category: stoerunglang, stoerungkurz,
  aufzugsinfo) with optional `time.start` / `time.end` windows.

## Relevance to the KG

Maps cleanly onto the one-pager's "transport links" + "temporal (live) data":

- **Stop** node: RBL id, name, lat/long, municipality
- **Line** node + **Departure** edges: scheduled vs. real-time, countdown
- **barrierFree** flag: useful for accessibility-constrained routing/reasoning
- **Disruption** node (stoerunglang/kurz, aufzugsinfo): time-bounded, linked to
  stops/lines — directly usable as a live routing constraint in the Reasoning Layer
- Elevator outages relevant if POI proximity/routing needs to account for
  accessibility at interchange stations

## Static reference data (data/raw/)

Downloaded from data.wien.gv.at (semicolon-delimited CSV, no auth needed):

- `wienerlinien-ogd-haltestellen.csv` (1,960 rows) — one row per named **stop**:
  `HALTESTELLEN_ID`, `NAME`, `WGS84_LAT`/`WGS84_LON`, `DIVA` (groups platforms),
  `GEMEINDE`
- `wienerlinien-ogd-steige.csv` (7,363 rows) — one row per **platform/direction**,
  this is where the **RBL number** actually lives (`RBL_NUMMER` — the ID the
  `monitor` endpoint needs): `STEIG_ID`, `FK_HALTESTELLEN_ID`, `FK_LINIEN_ID`,
  `RICHTUNG` (H/R), `RBL_NUMMER`, own `STEIG_WGS84_LAT`/`LON` (platform-level,
  slightly more precise than the stop-level coords)
- `wienerlinien-ogd-linien.csv` (198 rows) — one row per **line**: `LINIEN_ID`,
  `BEZEICHNUNG` (line name, e.g. "U4", "13A"), `VERKEHRSMITTEL` (mode: ptTram,
  ptBusCity, ptMetro, ptTrainS, ...), `ECHTZEIT` (realtime-supported flag)

**Join path to build the KG's transport subgraph:**
`steige.RBL_NUMMER` → used directly in `monitor?rbl=...` calls
`steige.FK_HALTESTELLEN_ID` → `haltestellen.HALTESTELLEN_ID` (which stop this platform belongs to)
`steige.FK_LINIEN_ID` → `linien.LINIEN_ID` (which line serves this platform)

So a natural KG shape: `Stop` (from haltestellen) —hasPlatform→ `Platform` (from
steige, carries RBL + direction) —servedBy→ `Line` (from linien, carries mode).
Live departures/disruptions from the `monitor` API then attach to `Platform` via RBL.

## Open questions for KG Modelling week

- Whether routing data (mentioned but not detailed in this doc) is GTFS-based —
  check data.gv.at listing.
- `DIVA` on the stops file vs `RBL_NUMMER` on the platforms file: DIVA is a
  higher-level stop-area grouping, RBL is what the realtime API actually keys on —
  keep both, don't conflate them in the schema.
