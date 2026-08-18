# Service Layer decisions log

Decisions made while building the Service Layer (`service/activity_planner.py`
+ `notebooks/06_service_layer.ipynb`). Same pattern as
`docs/kg_modelling_decisions.md` and `docs/reasoning_layer_decisions.md` —
captured here so nothing gets re-litigated, and so the next session can pick
up directly instead of re-deriving context.

## Requested next (starting point for the next session)

Nico asked for two extensions, not yet started:

1. **A district filter per stop/POI.** Every POI already carries a
   `schema:containedInPlace` link to a `viennakg:District` in the KG (from KG
   Modelling — see `docs/kg_schema_design.md`), so the data is there; this is
   about exposing it as an actual filter option in `find_pois()` /
   `plan_activities()` / the notebook 06 widget (e.g. "only look in Bezirk 1,
   7, 8"), not new KG work.
2. **A planner that handles up to 5 stops**, not just 2. `plan_activities()`
   currently hardcodes the 2-interest case (see "Plan scope" below) — this
   needs generalizing the stop1→stop2 chaining pattern into an N-stop loop.
   Worth thinking through before starting: search cost multiplies with each
   additional stop (`top_stop1_candidates` candidates × similar branching at
   each subsequent stop), so either the candidate pool per stop needs to
   shrink as stops increase, or some pruning/beam-search approach is needed
   to keep a 5-stop search tractable — this is not just "loop the existing
   2-stop code," it's closer in spirit to how the direct-only → 2-transfer
   GTFS routing extension needed real algorithmic thought, not just more
   iterations. Scope this properly before diving in (similar to how the
   multi-transfer routing decision got an explicit options discussion before
   building) rather than assuming it is a small tweak.

## Plan scope: 2 stops, itinerary budget (not travel-only)

**Decision:** `plan_activities()` supports 1 or 2 "interests" (POI
categories/amenities), producing origin → stop1 → stop2 plans. `time_budget_min`
covers travel AND visiting time at each stop (not travel alone — that was the
original, narrower version), but does NOT include a return trip home.
**Why:** per the one-pager's motivation ("someone else planned a day... for
you"), a single ranked POI list isn't a "plan." 2 stops was chosen as the
smallest scope that genuinely demonstrates multi-stop plan generation, given
each additional stop requires its own `reachable_from()` search per
candidate from the previous stop (real cost, not free). Visit time needed to
be in the budget for the output to be a genuine itinerary rather than "here's
a chain of transport links" (Nico's own framing when asking for this).
**How to apply:** extending to N stops means revisiting this cost tradeoff
explicitly (see "Requested next" above), not just changing a loop bound.

## Visit durations: stated assumptions, not data

**Decision:** `DEFAULT_VISIT_MINUTES` per POI class (Museum 90, Library 30,
Park 45, PlaygroundArea 45, SwimmingPool 90, BathingSite 90,
TouristAttraction 30) — rough, explicitly not derived from any survey or
dataset. Overridable per query via `visit_minutes` in the interest dict.
**Why:** some default is needed to turn travel time into a real itinerary,
but presenting a guess as measured fact would be dishonest. Making it
overridable rather than hardcoded keeps the tool honest about the
uncertainty instead of hiding it.
**How to apply:** if real visit-duration data ever becomes available (e.g.
from a survey or from Wien Tourismus), swap the dict's source, not the
chaining logic — `plan_activities()` doesn't care where visit_minutes came
from, only that it's a number.

## Max walk time: hard constraint, not a soft preference

**Decision:** `max_walk_min`, threaded through `GtfsRouter._nearby_stops()`
(gained a `strict` mode), `reachable_from()`/`travel_time_to()`/
`estimate_travel_time()`, `find_pois()`, and `plan_activities()`. When set,
a leg with nothing walkable within the limit is dropped, not approximated by
walking farther anyway.
**Why:** requested specifically for mobility constraints (e.g. a stroller) —
silently exceeding a stated walking limit isn't a minor rounding error for
someone who genuinely can't walk farther, so this needed to behave
differently from the time budget (a soft ranking preference where "a little
over" is often fine).
**How to apply:** any new routing entry point should default `max_walk_min`
to `None` (unrestricted, current generous fallback behavior) and only switch
to strict/no-fallback mode when a caller explicitly sets a value — don't
make strict mode the default, since most queries have no such constraint.

## Transfer coverage varies a lot by POI category and origin

**Observation, not really a decision:** from Karlsplatz (a major interchange),
almost every nearby museum/park needs 0 transfers, while swimming pools
(spread toward the city edges) needed a widened search (`top_plans=40`) before
a transfer example even showed up among the fastest-ranked options (see
`notebooks/06_service_layer.ipynb` section 5). Worth remembering when
demonstrating or testing multi-transfer behavior: don't assume the first
POI category tried will show it, pick categories/origins deliberately.
