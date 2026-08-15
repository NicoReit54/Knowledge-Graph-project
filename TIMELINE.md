# Timeline

Hard deadline: 2026-09-30. Self-target for a working core: end of Aug / early Sep.
Constraint: ~25h/week part-time job alongside this.

## Actual progress (updated 2026-08-15)

**Way ahead of the original plan.** Everything through week 4's "Reasoning
Layer" goal is either done or started, still within week 1's dates:

| Original week | Planned focus | Actual status as of 2026-08-15 |
|---|---|---|
| 1 (Aug 10–16) | Data Collection & EDA + start KG Modelling | **Done** — plus KG Modelling, KG Creation, and a first Reasoning Layer piece |
| 2 (Aug 17–23) | Finish KG Modelling + start KG Creation | already done |
| 3 (Aug 24–30) | Finish KG Creation | already done |
| 4 (Aug 31–Sep 6) | Reasoning Layer | started — GTFS direct-connection travel time working; live data (RBL) and full preference/routing reasoning still open |
| 5 (Sep 7–13) | Service Layer / demo | not started |
| 6 (Sep 14–20) | Integration, testing, catch-up buffer | not started |
| 7 (Sep 21–27) | Documentation, polish | not started |
| 8 (Sep 28–30) | Final buffer / submission | not started |

This leaves a large buffer before 2026-09-30. Worth deciding deliberately what
to do with the extra runway: pull the Service Layer forward, spend more time on
GNN exploration (previously scoped as a stretch goal / first thing to cut), or
just bank it given the 25h/week job constraint hasn't changed.

## Original plan (for reference)

| Week | Dates              | Focus                                              |
|------|--------------------|-----------------------------------------------------|
| 1    | Aug 10–16          | Data Collection & EDA + start KG Modelling          |
| 2    | Aug 17–23          | Finish KG Modelling + start KG Creation             |
| 3    | Aug 24–30          | Finish KG Creation                                  |
| 4    | Aug 31–Sep 6       | Reasoning Layer                                     |
| 5    | Sep 7–13           | Service Layer / demo                                |
| 6    | Sep 14–20          | Integration, testing, catch-up buffer               |
| 7    | Sep 21–27          | Documentation, polish                               |
| 8    | Sep 28–30          | Final buffer / submission                           |

Risk areas: KG Creation (schema mapping between static POI data and live transit
feeds — turned out fine), and Reasoning Layer (where most focus LOs live: LO5,
LO6, LO7, LO9, LO11 — in progress). GNN exploration is a stretch goal — first
thing to cut if behind schedule (currently not at risk of needing to cut it).
