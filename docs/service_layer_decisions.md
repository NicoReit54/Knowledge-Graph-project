# Service Layer decisions log

Decisions made while building the Service Layer (`service/activity_planner.py`
+ `notebooks/06_service_layer.ipynb`). Same pattern as
`docs/kg_modelling_decisions.md` and `docs/reasoning_layer_decisions.md` —
captured here so nothing gets re-litigated, and so the next session can pick
up directly instead of re-deriving context.

## Status: both previously-requested extensions are done (2026-08-25)

District filtering and the up-to-5-stop planner (the two things this doc
used to list under "Requested next") are both built and verified. Nothing
outstanding from Nico is currently queued in this doc — check `README.md` /
`TIMELINE.md` for what's next overall (return-trip modelling and live data
are the natural next increments, not requested yet).

## Plan scope: 1 to 5 stops, itinerary budget (not travel-only)

**Decision:** `plan_activities()` accepts 1 to 5 "interests" (POI
categories/amenities), producing an origin → stop1 → ... → stopN itinerary
in exactly the order given. `time_budget_min` covers travel AND visiting
time at every stop (not travel alone), but does NOT include a return trip
home, and does NOT auto-scale with stop count — 5 interests at default
visit times can need several hundred minutes before travel is even counted;
an infeasible budget just yields zero plans (same graceful degradation as
the original 2-stop version), not an error or a silently-shrunk plan.
**Why:** per the one-pager's motivation ("someone else planned a day... for
you"), a single ranked POI list isn't a "plan." Originally capped at 2 stops
as the smallest scope proving multi-stop generation; extended to 5 on
request once the search algorithm could support it without exploding in
cost (see "Search algorithm" below).
**How to apply:** `MAX_STOPS = 5` in `service/activity_planner.py` is the
one place that cap lives — raising it further is a one-line change, but see
the beam-search cost note below before doing so casually.

## Search algorithm: bounded beam search, not exhaustive branching

**Decision:** for N > 1 stops, the search proceeds stage by stage (one per
interest). After each stage, only the `beam_width` best partial itineraries
(ranked by cumulative travel + visit time so far) are kept and expanded into
the next stage; the rest are discarded. This bounds cost to roughly
`beam_width x N` `GtfsRouter.reachable_from()` calls (the expensive
operation — a network-wide search, ~0.2-0.4s each) instead of
`candidates^N`, which would be minutes of runtime for 5 stops (naive full
branching: 8 candidates x 4 remaining stages > 600 calls).
**Why:** requested extension from 2 to 5 stops, explicitly discussed before
building (see the conversation this doc originates from) rather than just
extending the 2-stop loop — the same "scope the search before assuming it's
a small tweak" approach used for the direct-only → 2-transfer GTFS routing
extension. Beam search was chosen over alternatives (full branching:
intractable; greedy nearest-only: no ability to recover from a locally
suboptimal early choice) as the standard bounded approach for this kind of
staged search problem.
**Measured on this graph/environment** (5-interest query from Karlsplatz,
`time_budget_min=600`): ~18s at `beam_width=2`, ~26s at `beam_width=3`,
~34s at `beam_width=4` (the default), ~50s+ at `beam_width=6`. Cost grows
roughly linearly with `beam_width`, not steeply — matches the
`beam_width x N` reachable_from()-call model above. 1-2 stop searches finish
in a few seconds regardless. These are this graph's numbers on this
sandboxed environment (which has shown 2-16s variance on similar operations
before, see [[feedback-kg-project-workflow]]) — a rough guide, not a
portable benchmark.
**How to apply:** `beam_width` is exposed as a caller-facing parameter
(default 4) precisely because it's a real speed/quality knob, not an
implementation detail — the notebook 06 widget exposes it as a slider so a
user can trade search quality for a faster interactive response. It is a
heuristic: a narrower beam can miss a better itinerary that a wider beam
would find (Section 7 of the notebook shows a case where `beam_width=2`
happened to find the same best plan as `beam_width=4` — not guaranteed in
general, just what this example showed).

## Stop order: exactly as given, not searched (confirmed with Nico before building)

**Decision:** the planner visits interests in exactly the order the caller
lists them. It does not try alternate orderings of the same interests to
find a faster overall route.
**Why:** explicitly asked and confirmed before implementation — the
alternative (also searching orderings) is a small traveling-salesman
problem layered on top of the beam search, multiplying cost by up to
`N! = 120` for 5 stops, for a benefit that's often small in a dense,
well-connected city like Vienna. Fixed order was chosen specifically to
keep the beam-search cost bound above intact — searching orderings would
mean re-running the whole beam search per ordering.
**How to apply:** if a plan's stop order looks suboptimal, the intended
fix is for the caller to reorder the `interests` list themselves and
compare — the tool won't do this automatically, and that's a scope choice,
not a bug to route around.

## POI deduplication within a plan

**Decision:** a POI (by URI) already used at an earlier stop in the same
itinerary is excluded from later-stage candidates, even if it would
otherwise be the fastest/best match.
**Why:** became a real correctness concern once plans could have enough
stops that overlap is plausible (e.g. asking for "a park" three times with
a wide budget and no other filter) — at 2 stops this essentially never
came up, but it's not safe to assume that holds at 5.
**How to apply:** tracked as a `visited_uris` set threaded through each
partial itinerary during the beam search (see
`service/activity_planner.py`). Verified directly in
`notebooks/06_service_layer.ipynb` Section 7 with a 3x "Park" interest
query, wide budget, no other filters — confirmed 3 distinct parks chosen,
not the same one repeated.

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
chaining/search logic — `plan_activities()` doesn't care where
visit_minutes came from, only that it's a number.

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

## District filtering: per-interest, not plan-wide

**Decision:** `find_pois()` has a `district` parameter (number 1-23,
`"BezirkN"`, or a case-insensitive substring of the district's `rdfs:label`,
resolved via `resolve_district()` in `reasoning/preference_filter.py`);
`plan_activities()` reads `district` out of each interest dict rather than
taking one plan-wide argument.
**Why:** every POI already carries `schema:containedInPlace` → a
`viennakg:District` from KG Modelling, so this needed zero new ingestion —
purely a query/API surface change. Per-interest (not plan-wide) because a
plan spanning several different districts is a completely normal, useful
request ("a park in the 6th district, then a museum wherever's fastest") —
see `notebooks/06_service_layer.ipynb` section 6. An unresolvable district
string raises `ValueError` rather than silently matching zero POIs, since a
typo there would otherwise look identical to "genuinely nothing in this
district."
**How to apply:** applied as an early candidate-set filter in
`_candidate_pois()`, before travel-time computation — so a district filter
also shrinks the routing workload, not just the final display list. The
notebook 06 widget exposes it as an independent dropdown per interest slot.

## POI descriptions: composed from structured fields, not a real text field

**Decision:** `describe_poi()` in `reasoning/preference_filter.py` builds a
best-effort human-readable string per POI from whatever structured fields it
has (district label, address, area, opening hours, phone/email, url,
tourist-attraction subcategory, true-valued amenities) and attaches it as
`description` on every result from `find_pois()` / stop dict from
`plan_activities()`. `format_plan()` prints it indented under each stop by
default (`show_description=True`).
**Why:** checked first — there is no `schema:description` (or any free-text
description) anywhere in the 80K+-triple graph, across any of the 7 POI
source datasets. Rather than silently omitting descriptions or fabricating
text not backed by the KG, this composes a description strictly from fields
that are actually present, so it's honest about being KG-derived rather than
editorial content.
**How to apply:** coverage is uneven by design — `BathingSite` has almost no
structured fields beyond name/location/district, so its description is
often just the district; `Library`/`Museum`/`TouristAttraction` tend to be
richer (address, contact, hours, url). Don't read a short description as
"nothing interesting here" — it means the source dataset for that POI class
just didn't include much. If richer POI data is ever ingested, extend
`describe_poi()`'s field list rather than switching to a different
mechanism — the compose-from-structured-fields approach itself doesn't need
to change.

## Transfer coverage varies a lot by POI category and origin

**Observation, not really a decision:** from Karlsplatz (a major interchange),
almost every nearby museum/park needs 0 transfers, while swimming pools
(spread toward the city edges) needed a widened search (`top_plans=40`) before
a transfer example even showed up among the fastest-ranked options (see
`notebooks/06_service_layer.ipynb` section 5). Worth remembering when
demonstrating or testing multi-transfer behavior: don't assume the first
POI category tried will show it, pick categories/origins deliberately.
