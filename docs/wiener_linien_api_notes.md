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

## Open questions for KG Modelling week

- Where to source the static RBL stop list (name ↔ RBL ↔ coordinates mapping) —
  needed before `monitor` calls are useful.
- Whether routing data (mentioned but not detailed in this doc) is GTFS-based —
  check data.gv.at listing.
