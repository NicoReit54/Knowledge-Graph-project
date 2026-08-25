"""
Service Layer: turns the Reasoning Layer's building blocks (category/amenity
matching + GTFS travel time) into actual activity PLANS, not just ranked POI
lists -- per the one-pager's motivation ("someone else planned a day... for
you"), a single ranked list of parks is a search result, not a plan.

Scope, deliberately:
- Plans are 1 to 5 stops (origin -> stop1 -> stop2 -> ... -> stopN), built via
  a bounded BEAM SEARCH, not exhaustive branching -- see the "Why beam
  search" note below. Full unbounded search (try every candidate at every
  stage) is combinatorially infeasible past ~2 stops.
- Stop ORDER is exactly the order `interests` are given in -- the search
  does not try alternate orderings of the same interests to find a faster
  route. That's a deliberate scope decision (see docs/service_layer_decisions.md),
  not an oversight: searching over orderings too is a much bigger problem
  (small traveling-salesman instance) that multiplies cost by up to N!
  orderings on top of the beam search already required per ordering.
- The same POI is never suggested twice within one plan (tracked by URI
  across stages) -- a real correctness concern once plans have enough stops
  that overlap becomes likely, not just a theoretical edge case.
- `time_budget_min` covers travel AND visiting time at every stop (a real
  itinerary budget, e.g. "I have 3 hours this afternoon"), but does NOT
  include a return trip home -- the plan ends when you're done at the last
  stop. It also does NOT auto-scale with the number of stops: 5 interests at
  their default visit times can easily need several hundred minutes before
  travel is even counted, and an infeasible budget just yields zero plans
  (the same graceful-degradation behavior as before), not an error or a
  silently-shrunk plan. Visit durations default to DEFAULT_VISIT_MINUTES per
  POI class (rough, stated assumptions -- not derived from any data source
  -- and overridable per interest via "visit_minutes").
- Uses the same GtfsRouter/find_pois building blocks as the rest of the
  Reasoning Layer -- no new KG queries or ontology needed here, this is
  purely an orchestration layer on top of what already exists.
- Each interest can carry its own "district" filter (see find_pois()'s
  docstring in reasoning/preference_filter.py) -- e.g. "a park in the 6th
  district, then a library anywhere" is expressed as two interests with
  different district values, not a single plan-wide filter, since a plan
  naturally can span more than one district.
- Each returned stop also carries a best-effort "description" string
  (composed from whatever structured KG fields that POI has -- there's no
  free-text description in the data, see preference_filter.describe_poi())
  and the POI's "uri", flowing through automatically since stops are built
  by spreading find_pois()'s result dicts.

Why beam search: the expensive operation per candidate stop is
GtfsRouter.reachable_from() (a network-wide search from that stop's
location, ~0.2-0.4s), triggered once per find_pois() call. Naive full
branching (evaluate every candidate at every stage) costs O(C^N) such calls
for N stops and C candidates per stage -- e.g. 8 candidates x 4 remaining
stages is >600 calls for a 5-stop plan, minutes of runtime. Beam search
instead keeps only the `beam_width` best partial itineraries after each
stage (ranked by cumulative time-so-far) and only expands those, capping
cost at O(beam_width x N) reachable_from() calls regardless of how many
candidate POIs exist per category -- for beam_width=6 and 5 stops, at most
~25 calls. The tradeoff: this is a heuristic, not an exhaustive search --
a partial itinerary that looks slightly worse after 2 stops but would lead
to a much better plan by stop 4 can get pruned before that upside is ever
seen. Same bounded-not-exhaustive spirit as capping GTFS transfers at 2
rather than searching unboundedly (see docs/reasoning_layer_decisions.md).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.gtfs_routing import GtfsRouter, format_seconds, parse_gtfs_time
from reasoning.preference_filter import find_pois

MAX_STOPS = 5

# Rough, stated assumptions -- not derived from any survey or dataset, just
# reasonable defaults for a typical visit. Override per-interest via
# {"visit_minutes": N} when the default doesn't fit (e.g. a quick photo stop
# at a TouristAttraction vs. a leisurely one).
DEFAULT_VISIT_MINUTES = {
    "Museum": 90,
    "Library": 30,
    "BathingSite": 90,
    "Park": 45,
    "SwimmingPool": 90,
    "PlaygroundArea": 45,
    "TouristAttraction": 30,
}


def _seconds_to_hms(total_seconds: int) -> str:
    """Inverse of parse_gtfs_time -- handles the >24:00:00 GTFS convention."""
    h, rem = divmod(int(total_seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _visit_minutes_for(interest: dict) -> float:
    if "visit_minutes" in interest and interest["visit_minutes"] is not None:
        return interest["visit_minutes"]
    poi_classes = interest.get("poi_classes") or []
    return DEFAULT_VISIT_MINUTES.get(poi_classes[0], 45) if poi_classes else 45


def plan_activities(g, router: GtfsRouter, origin_lon: float, origin_lat: float,
                     interests: list, time_budget_min: float = 90,
                     depart_after: str = "14:00:00", beam_width: int = 4,
                     top_plans: int = 5, max_walk_min: float = None) -> list:
    """
    interests: list of 1 to 5 dicts, each like
        {"label": "a park", "poi_classes": ["Park"], "required_amenities": ["Dogs allowed"],
         "district": 6, "visit_minutes": 60}
    (required_amenities, district, and visit_minutes all optional --
    visit_minutes falls back to DEFAULT_VISIT_MINUTES for the POI class;
    district restricts that stop's candidates to one Vienna district, see
    reasoning/preference_filter.py's resolve_district() for accepted formats
    -- a number 1-23, "BezirkN", or a label substring). Stops are visited in
    EXACTLY the order interests are given -- the search does not try
    alternate orderings (see module docstring for why). Each interest's
    district filter applies only to that stop -- a plan can span several
    different districts by design. The same POI is never suggested twice
    within one plan.

    beam_width: how many candidate POIs to consider at each stage, AND how
    many partial itineraries survive pruning between stages (both the same
    knob -- see module docstring's "Why beam search" for the cost/quality
    tradeoff this controls). Higher = better plans, more runtime. Measured
    on this graph/environment for a 5-stop search: ~18s at beam_width=2,
    ~26s at beam_width=3, ~34s at beam_width=4 (the default -- chosen as
    the point where more width stopped meaningfully improving the best plan
    found in testing), ~50s+ at beam_width=6. Cost grows roughly linearly
    with beam_width, not steeply, since it's the number of reachable_from()
    network searches that scales, one per surviving partial itinerary per
    stage. 1-2 stop searches finish in a few seconds at any beam_width.
    Lower this for a snappier interactive widget at the cost of missing
    some better itineraries; these are this environment's numbers and this
    project's small candidate pool, so treat them as a rough guide, not a
    guarantee, if run elsewhere.

    max_walk_min: hard cap on walking time to/from a transit stop, applied
    consistently to every leg of the plan (e.g. 10 for someone with a
    stroller or other mobility constraint) -- set once here rather than per
    leg. None (default) leaves walking unrestricted (beyond GtfsRouter's
    generous built-in default). See GtfsRouter.reachable_from()'s docstring
    for what this changes: with a hard limit set, a leg with no stop within
    range is skipped rather than silently walked farther than requested.

    Returns a list of plans, each {"stops": [...], "total_travel_min": ...,
    "total_itinerary_min": ...}, best (least total itinerary time) first.
    Each stop dict includes "description" (best-effort, from whatever KG
    fields that POI has) and "uri" alongside the usual name/travel fields.
    """
    if not interests or len(interests) > MAX_STOPS:
        raise ValueError(f"plan_activities supports 1 to {MAX_STOPS} interests, got {len(interests)}")

    visit_minutes = [_visit_minutes_for(i) for i in interests]

    # Beam search state: each "partial" is one candidate itinerary-so-far.
    # Starts as a single empty itinerary rooted at the origin.
    beam = [{
        "stops": [],
        "lon": origin_lon,
        "lat": origin_lat,
        "clock_s": parse_gtfs_time(depart_after),
        "total_travel_min": 0.0,
        "total_visit_min": 0.0,
        "visited_uris": set(),
    }]

    for interest, visit_min in zip(interests, visit_minutes):
        next_beam = []
        for partial in beam:
            used_so_far = partial["total_travel_min"] + partial["total_visit_min"]
            remaining_for_leg_travel = time_budget_min - used_so_far - visit_min
            if remaining_for_leg_travel <= 0:
                continue  # can't afford this stop's visit even with zero travel

            candidates = find_pois(g, router, partial["lon"], partial["lat"],
                                    poi_classes=interest.get("poi_classes"),
                                    required_amenities=interest.get("required_amenities"),
                                    district=interest.get("district"),
                                    max_travel_time_min=remaining_for_leg_travel,
                                    depart_after=_seconds_to_hms(round(partial["clock_s"])),
                                    top_n=beam_width, max_walk_min=max_walk_min)

            for c in candidates:
                if not c["reachable"] or c["uri"] in partial["visited_uris"]:
                    continue  # unreachable (shouldn't occur given max_travel_time_min) or already visited this trip
                next_beam.append({
                    "stops": partial["stops"] + [{**c, "label": interest.get("label", "stop"),
                                                   "leg_travel_min": c["travel_time_min"],
                                                   "visit_min": visit_min}],
                    "lon": c["lon"],
                    "lat": c["lat"],
                    "clock_s": partial["clock_s"] + (c["travel_time_min"] + visit_min) * 60,
                    "total_travel_min": partial["total_travel_min"] + c["travel_time_min"],
                    "total_visit_min": partial["total_visit_min"] + visit_min,
                    "visited_uris": partial["visited_uris"] | {c["uri"]},
                })

        # prune: keep only the best `beam_width` partial itineraries (by
        # cumulative time so far) before expanding the next stage -- this is
        # what keeps cost linear in beam_width x len(interests) instead of
        # exponential in len(interests)
        next_beam.sort(key=lambda p: p["total_travel_min"] + p["total_visit_min"])
        beam = next_beam[:beam_width]
        if not beam:
            break  # budget exhausted for every surviving branch -- no point continuing

    plans = [{
        "stops": p["stops"],
        "total_travel_min": p["total_travel_min"],
        "total_itinerary_min": p["total_travel_min"] + p["total_visit_min"],
    } for p in beam if len(p["stops"]) == len(interests)]  # only full-length plans

    plans.sort(key=lambda p: p["total_itinerary_min"])
    return plans[:top_plans]


def format_plan(plan: dict, depart_after: str = "14:00:00", show_description: bool = True) -> str:
    """Human-readable itinerary rendering -- arrive/visit-until per stop, not
    just travel legs. For print()ing in a notebook or demo, not meant as the
    final UI. show_description prints each stop's best-effort KG-derived
    description (address, amenities, etc.) on an indented line beneath it,
    when one is available (blank descriptions are skipped, not printed
    empty)."""
    lines = []
    clock_s = parse_gtfs_time(depart_after)
    lines.append(f"Depart at {depart_after}")
    for stop in plan["stops"]:
        clock_s += stop["leg_travel_min"] * 60
        arrive_str = _seconds_to_hms(round(clock_s))[:5]
        transfers = stop.get("num_transfers")
        transfer_txt = f", {transfers} transfer{'s' if transfers != 1 else ''}" if transfers is not None else ""
        clock_s += stop["visit_min"] * 60
        leave_str = _seconds_to_hms(round(clock_s))[:5]
        lines.append(f"  -> {stop['label']}: {stop['name']} "
                      f"(arrive {arrive_str}, {stop['leg_travel_min']:.1f} min travel{transfer_txt}; "
                      f"visit until {leave_str}, {stop['visit_min']:.0f} min)")
        if show_description and stop.get("description"):
            lines.append(f"     {stop['description']}")
    lines.append(f"Done at {_seconds_to_hms(round(clock_s))[:5]} -- "
                 f"{plan['total_travel_min']:.1f} min travel + "
                 f"{plan['total_itinerary_min'] - plan['total_travel_min']:.0f} min visiting "
                 f"= {plan['total_itinerary_min']:.0f} min total (no return trip included)")
    return "\n".join(lines)
