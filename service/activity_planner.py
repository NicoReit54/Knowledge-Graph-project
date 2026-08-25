"""
Service Layer: Uses the Reasoning Layer's building blocks (category/amenity
matching + GTFS travel time) to create actual activity PLANS, not just by 
time ranked POI lists. 

Scope for now (can be made more complex later if needed #TODO):
- Plans are 1 to 5 stops (origin -> stop1 -> ... -> stopN), found via a
  bounded beam search, not exhaustive branching (see "Why beam search"
  below). Exhaustive search is combinatorially infeasible past ~2 stops
  on my machine with the full Vienna GTFS graph, and the search is already 
  slow enough.
- Stop order is exactly the order `interests` are given in. The search does
  not try alternate orderings to find a faster route, a deliberate 
  decision (see docs/service_layer_decisions.md): searching orderings too
  is a small traveling-salesman problem, multiplying cost by up to N!.
- The same POI is never suggested twice within one plan, tracked by URI
  across stages. 
  (something that testing revealed we would run into if we didn't)
- `time_budget_min` covers travel and visiting time at every stop, but not
  a return trip home; the plan ends at the last stop. 
  # TODO: in the future to also consider the return trip
- Each interest can carry its own "district" filter (see find_pois() in
  reasoning/preference_filter.py), e.g. "a park in the 6th district, then a
  library anywhere" is two interests with different district values, not a
  plan-wide filter. This was mainly done to see that there will also be multiple
  transfers suggested.
- Each returned stop carries a best-effort "description" and "uri",
  coming through automatically from find_pois()'s result dicts.

Why beam search: the expensive step per candidate is
GtfsRouter.reachable_from(), called once per find_pois() call.
Full branching costs O(C^N) such calls for N stops and C candidates per
stage, e.g. 8 candidates x 4 remaining stages is >600 calls for 5 stops,
minutes of runtime. Beam search keeps only the `beam_width` best partial
itineraries after each stage and only expands those, capping cost at
O(beam_width x N) regardless of candidate pool size. The tradeoff: it's
heuristic and might very well not produce the optimal solution.
# TODO: in the future this should be improved 
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.gtfs_routing import GtfsRouter, format_seconds, parse_gtfs_time
from reasoning.preference_filter import find_pois

MAX_STOPS = 5

# Stated assumptions, not derived from any survey or dataset, seemed like
# reasonable defaults for a typical visit. Override per-interest via
# {"visit_minutes": N} when the default doesn't fit.
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
    """Inverse of parse_gtfs_time, handles the >24:00:00 GTFS convention."""
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
    (required_amenities, district, and visit_minutes all optional; falls
    back to DEFAULT_VISIT_MINUTES for the POI class; district restricts
    that stop's candidates to one Vienna district, see resolve_district()
    in reasoning/preference_filter.py for accepted formats). Stops are
    visited in exactly the order interests are given (see module docstring
    for why). Each interest's district filter applies only to that stop, a
    plan can span several districts by design. The same POI is never
    suggested twice within one plan.

    beam_width: how many candidate POIs to consider at each stage, and how
    many partial itineraries survive pruning between stages (see up top the
    docstring's "Why beam search"). Higher = better plans, more runtime.
    
    On my machine (MacBook Air M1, 2020):
    Measured on this graph for a 5-stop search: ~18s at beam_width=2, ~26s
    at beam_width=3, ~34s at beam_width=4 (the default), ~50s+ at
    beam_width=6. Cost seems to grow roughly linearly with beam_width. 
    1-2 stop searches finish in a few seconds regardless. 
    

    max_walk_min: hard cap on walking time to/from a transit stop, applied
    to every leg (e.g. 10 for a stroller). None (default) leaves walking
    unrestricted. With a hard limit set, a leg with no stop in range is
    skipped rather than walked farther than requested.

    Returns a list of plans, each {"stops": [...], "total_travel_min": ...,
    "total_itinerary_min": ...}, best first. Each stop dict includes
    "description" and "uri" alongside the usual name/travel fields.
    """
    if not interests or len(interests) > MAX_STOPS:
        raise ValueError(f"plan_activities supports 1 to {MAX_STOPS} interests, got {len(interests)}")

    visit_minutes = [_visit_minutes_for(i) for i in interests]

    # each "partial" is one candidate itinerary-so-far, starts empty at origin
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
                    continue  # unreachable (shouldn't happen) or already visited
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

        # keep only the best beam_width partials before the next stage,
        # this is what keeps cost linear instead of exponential
        next_beam.sort(key=lambda p: p["total_travel_min"] + p["total_visit_min"])
        beam = next_beam[:beam_width]
        if not beam:
            break  # budget exhausted for every branch, no point continuing

    plans = [{
        "stops": p["stops"],
        "total_travel_min": p["total_travel_min"],
        "total_itinerary_min": p["total_travel_min"] + p["total_visit_min"],
    } for p in beam if len(p["stops"]) == len(interests)]  # only full-length plans

    plans.sort(key=lambda p: p["total_itinerary_min"])
    return plans[:top_plans]


def format_plan(plan: dict, depart_after: str = "14:00:00", show_description: bool = True) -> str:
    """For printing in a notebook or demo, not the final UI..."""
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
