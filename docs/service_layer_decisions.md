# Service Layer decisions log

Decisions made while building the Service Layer (`service/activity_planner.py`
+ `notebooks/06_service_layer.ipynb`).

## Plan scope: 1 to 5 stops, itinerary budget (not travel-only)

**Decision:** 
`plan_activities()` accepts 1 to 5 "interests" (POI
categories/amenities), producing an origin → stop1 → ... → stopN itinerary
in exactly the order given. 

`time_budget_min` covers travel AND visiting
time at every stop (not travel alone), but does NOT include a return trip
home, and does NOT auto-scale with stop count. 5 interests at default visit
times can need several hundred minutes before travel is even counted; an
infeasible budget just yields zero plans.

**How to use:** 
`MAX_STOPS = 5` in `service/activity_planner.py` is the
one place that cap lives. Raising it further is a one-line change, but mind
the beam-search cost note below before doing so casually.

## Search algorithm: bounded beam search, not exhaustive branching

**Decision:** 
for N > 1 stops, the search proceeds stage by stage (one per
interest). After each stage, only the `beam_width` best partial itineraries
(ranked by cumulative travel + visit time so far) are kept and expanded into
the next stage; the rest are discarded. This bounds cost to roughly
`beam_width x N` `GtfsRouter.reachable_from()` calls (the expensive
operation, a network-wide search, ~0.2-0.4s each) instead of
`candidates^N`, which would be minutes of runtime for 5 stops (naive full
branching: 8 candidates x 4 remaining stages > 600 calls).

**How to use:** `beam_width` is accessible as a caller-facing parameter
(default 4) precisely because it's a speed/quality tuning point. 
The notebook 06 widget uses it as a slider so a potential
user can trade search quality for a faster interactive response. It is a
heuristic: a narrower beam can miss a better itinerary that a wider beam
would find (Section 7 of the notebook shows a case where `beam_width=2`
happened to find the same best plan as `beam_width=4`, not guaranteed in
general, just what this example showed).

## Stop order: exactly as given, not searched

**Decision:** the planner visits interests in exactly the order the caller
lists them. It does not try alternate orderings of the same interests to
find a faster overall route:

**Why:** The alternative is a small traveling-salesman
problem layered on top of the beam search, multiplying cost by up to
`N! = 120` for 5 stops, for a benefit that's often small in a dense,
well-connected city like Vienna I would argue.
Fixed order was chosen specifically to
keep the beam-search cost bound above intact, searching orderings would
mean re-running the whole beam search per ordering.

**How to use:** if a plan's stop order looks suboptimal, the "fix"
is for the caller to reorder the `interests` list themselves and compare.
Obviously an annoying limitation but good enough for a POV. #TODO

## POI deduplication within a plan

**Decision:** a POI (by URI) already used at an earlier stop in the same
itinerary is excluded from later-stage candidates, even if it would
otherwise be the fastest/best match.

**Why:** Well, it does not make sense to visit the same museum twice in one day, 
even if it is the fastest route to the next interest.

## Visit durations: stated assumptions, not data

**Decision:** `DEFAULT_VISIT_MINUTES` per POI class (Museum 90, Library 30,
Park 45, PlaygroundArea 45, SwimmingPool 90, BathingSite 90,
TouristAttraction 30), rough, explicitly not derived from any survey or
dataset. Overridable per query via `visit_minutes` in the interest dict.

**Why:** Otherwise we would not have an itinerary but rather a travel-only route. 

**How to use:** if real visit-duration data ever becomes available (e.g.
from a survey or from Wien Tourismus), we can easily swap the dict's source.
`plan_activities()` doesn't care where visit_minutes comes from, only that it's a number.

## Max walk time: hard constraint, not a soft preference

**Decision:** `max_walk_min`, used throughout `GtfsRouter._nearby_stops()`
`reachable_from()`, `travel_time_to()`, `estimate_travel_time()`, 
`find_pois()`, and `plan_activities()`. 
When set, a leg with nothing walkable within the limit is dropped, not done
by walking farther anyway.

**Why:** Useful for mobility constraints (e.g. a stroller) but also just personal
preference. Otherwise I could just send a person walking from one end of the city to the other, 
and they would be "within budget" if they were willing to take 100 minutes.

## District filtering: per-interest, not plan-wide

**Decision:** `find_pois()` has a `district` parameter (number 1-23,
`"BezirkN"`, or a case-insensitive substring of the district's `rdfs:label`,
resolved via `resolve_district()` in `reasoning/preference_filter.py`);
`plan_activities()` reads `district` out of each interest dict rather than
taking one plan-wide argument.

**Why:** every POI already carries `schema:containedInPlace` to a
`viennakg:District` from KG Modelling, so this needed zero new ingestion,
purely a query/API surface change. Simply to create more extensive itineraries,
where a user might actually need to transfer multiple times! E.g. if you start in the 
first district and do not have this option, you mostly end up walking around in the first
without using any public transport.

**How to use:** applied as an early candidate-set filter in
`_candidate_pois()`, before travel-time computation, so a district filter
also shrinks the routing workload, not just the final display list. The
notebook 06 widget shows it as an independent dropdown per interest slot.

## Transfer coverage varies a lot by POI category and origin

**Observation** from Karlsplatz (major interchange),
almost every nearby museum/park needs 0 transfers, while swimming pools
(spread toward the city edges) needed a widened search (`top_plans=40`) before
a transfer example even showed up among the fastest-ranked options (see
`notebooks/06_service_layer.ipynb` section 5). Worth keeping in mind when
demonstrating or testing multi-transfer behavior. Also the reason for 
the district filtering implementation above.