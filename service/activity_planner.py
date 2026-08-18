"""
Service Layer: turns the Reasoning Layer's building blocks (category/amenity
matching + GTFS travel time) into actual activity PLANS, not just ranked POI
lists -- per the one-pager's motivation ("someone else planned a day... for
you"), a single ranked list of parks is a search result, not a plan.

Scope, deliberately:
- Plans are at most 2 stops (origin -> stop1 -> stop2). More stops is a
  straightforward extension of the same pattern but multiplies the search
  cost; 2 stops already demonstrates real multi-stop plan generation.
- `time_budget_min` covers travel AND visiting time at each stop (a real
  itinerary budget, e.g. "I have 3 hours this afternoon"), but does NOT
  include a return trip home -- the plan ends when you're done at the last
  stop. Visit durations default to DEFAULT_VISIT_MINUTES per POI class
  (rough, stated assumptions -- not derived from any data source -- and
  overridable per interest via "visit_minutes").
- Uses the same GtfsRouter/find_pois building blocks as the rest of the
  Reasoning Layer -- no new KG queries or ontology needed here, this is
  purely an orchestration layer on top of what already exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.gtfs_routing import GtfsRouter, format_seconds, parse_gtfs_time
from reasoning.preference_filter import find_pois

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


def _single_stop_plans(g, router, origin_lon, origin_lat, interest,
                        time_budget_min, depart_after, top_n):
    visit_min = _visit_minutes_for(interest)
    # only travel time is known ahead of the find_pois() call, so budget for
    # travel alone here and subtract the visit afterwards
    results = find_pois(g, router, origin_lon, origin_lat,
                         poi_classes=interest.get("poi_classes"),
                         required_amenities=interest.get("required_amenities"),
                         max_travel_time_min=max(time_budget_min - visit_min, 0),
                         depart_after=depart_after, top_n=top_n)
    plans = []
    for r in results:
        plans.append({
            "stops": [{**r, "label": interest.get("label", "stop"),
                       "leg_travel_min": r["travel_time_min"], "visit_min": visit_min}],
            "total_travel_min": r["travel_time_min"],
            "total_itinerary_min": r["travel_time_min"] + visit_min,
        })
    return plans


def plan_activities(g, router: GtfsRouter, origin_lon: float, origin_lat: float,
                     interests: list, time_budget_min: float = 90,
                     depart_after: str = "14:00:00", top_stop1_candidates: int = 8,
                     top_plans: int = 5) -> list:
    """
    interests: list of 1 or 2 dicts, each like
        {"label": "a park", "poi_classes": ["Park"], "required_amenities": ["Dogs allowed"],
         "visit_minutes": 60}
    (required_amenities and visit_minutes both optional -- visit_minutes falls
    back to DEFAULT_VISIT_MINUTES for the POI class). One interest -> ranked
    single-stop suggestions. Two interests -> 2-stop plans (order matters:
    interests[0] is visited first), each fitting travel + both visits within
    time_budget_min (no return trip included).

    Returns a list of plans, each {"stops": [...], "total_travel_min": ...,
    "total_itinerary_min": ...}, best (least total itinerary time) first.
    """
    if len(interests) == 1:
        return sorted(_single_stop_plans(g, router, origin_lon, origin_lat, interests[0],
                                          time_budget_min, depart_after, top_plans),
                       key=lambda p: p["total_itinerary_min"])[:top_plans]

    if len(interests) != 2:
        raise ValueError("plan_activities supports 1 or 2 interests, not more (see module docstring)")

    interest1, interest2 = interests
    visit1 = _visit_minutes_for(interest1)
    visit2 = _visit_minutes_for(interest2)

    # top_stop1_candidates by travel time, NOT yet capped by the full budget --
    # leg 2 (plus both visits) still needs to fit, so a generous first-leg
    # candidate pool is kept rather than pre-filtering too aggressively
    stop1_candidates = find_pois(g, router, origin_lon, origin_lat,
                                  poi_classes=interest1.get("poi_classes"),
                                  required_amenities=interest1.get("required_amenities"),
                                  depart_after=depart_after, top_n=top_stop1_candidates)

    plans = []
    for c1 in stop1_candidates:
        if not c1["reachable"]:
            continue
        used_so_far = c1["travel_time_min"] + visit1
        remaining_for_leg2_travel = time_budget_min - used_so_far - visit2
        if remaining_for_leg2_travel <= 0:
            continue

        # arrival clock time at stop1 PLUS the time spent there becomes the
        # departure time for leg 2 -- chaining the actual itinerary, not just
        # subtracting minutes from a budget
        depart_leg2_s = parse_gtfs_time(depart_after) + (c1["travel_time_min"] + visit1) * 60
        depart_leg2 = _seconds_to_hms(round(depart_leg2_s))

        stop2_candidates = find_pois(g, router, c1["lon"], c1["lat"],
                                      poi_classes=interest2.get("poi_classes"),
                                      required_amenities=interest2.get("required_amenities"),
                                      max_travel_time_min=remaining_for_leg2_travel,
                                      depart_after=depart_leg2, top_n=3)

        for c2 in stop2_candidates:
            total_travel = c1["travel_time_min"] + c2["travel_time_min"]
            plans.append({
                "stops": [
                    {**c1, "label": interest1.get("label", "stop 1"),
                     "leg_travel_min": c1["travel_time_min"], "visit_min": visit1},
                    {**c2, "label": interest2.get("label", "stop 2"),
                     "leg_travel_min": c2["travel_time_min"], "visit_min": visit2},
                ],
                "total_travel_min": total_travel,
                "total_itinerary_min": total_travel + visit1 + visit2,
            })

    plans.sort(key=lambda p: p["total_itinerary_min"])
    return plans[:top_plans]


def format_plan(plan: dict, depart_after: str = "14:00:00") -> str:
    """Human-readable itinerary rendering -- arrive/visit-until per stop, not
    just travel legs. For print()ing in a notebook or demo, not meant as the
    final UI."""
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
    lines.append(f"Done at {_seconds_to_hms(round(clock_s))[:5]} -- "
                 f"{plan['total_travel_min']:.1f} min travel + "
                 f"{plan['total_itinerary_min'] - plan['total_travel_min']:.0f} min visiting "
                 f"= {plan['total_itinerary_min']:.0f} min total (no return trip included)")
    return "\n".join(lines)
