# Timeline

Hard deadline: 2026-09-30. Self-target for a working core: end of Aug / early Sep.
Constraint: ~25h/week part-time job alongside this.

## Actual progress (updated 2026-08-25)

**All 5 pipeline phases have a first working version, including both
previously-requested Service Layer extensions** (district filter, 1-to-5-stop
planner via beam search). Still within the original plan's week 2 (Aug
17-23), already well past week 5's "Service Layer" goal:

| Original week | Planned focus | Actual status as of 2026-08-18 |
|---|---|---|
| 1 (Aug 10–16) | Data Collection & EDA + start KG Modelling | **Done** |
| 2 (Aug 17–23) | Finish KG Modelling + start KG Creation | **Done**, plus KG Creation, Reasoning Layer, and Service Layer, all first-pass complete |
| 3 (Aug 24–30) | Finish KG Creation | already done |
| 4 (Aug 31–Sep 6) | Reasoning Layer | done: GTFS routing with up to 2 transfers + preference filtering; live data (RBL) still open |
| 5 (Sep 7–13) | Service Layer / demo | done: multi-stop itineraries with visit times + walk-time limits; interactive notebook demo |
| 6 (Sep 14–20) | Integration, testing, catch-up buffer | not started |
| 7 (Sep 21–27) | Documentation, polish | ongoing (docs kept current throughout rather than saved for this week) |
| 8 (Sep 28–30) | Final buffer / submission | not started |

This leaves a very large buffer before 2026-09-30, roughly 5 of the original
8 weeks unclaimed, and no outstanding Service Layer requests. Worth deciding
deliberately what to do with it: live data (RBL), a return trip in
itineraries, GNN exploration (stretch goal), integration/testing/polish
(weeks 6-7's original focus), or just banking the slack given the 25h/week
job constraint hasn't changed.

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
feeds, turned out fine), and Reasoning Layer (where most focus LOs live: LO5,
LO6, LO7, LO9, LO11, in progress). GNN exploration is a stretch goal, first
thing to cut if behind schedule (currently not at risk of needing to cut it).
