"""
Service Layer: turns the Reasoning Layer's building blocks (category/amenity
matching + GTFS travel time) into actual activity PLANS, not just ranked POI
lists -- per the one-pager's motivation ("someone else planned a day... for
you"), a single ranked list of parks is a search result, not a plan.

Scope, deliberately:
- Plans are at most 2 stops (origin -> stop1 -> stop2). More stops is a
  straightforward extension of the same pattern but multiplies the search
  cost; 2 stops already demonstrates real multi-stop plan generation.
- The time budget is a TRAVEL-time budget only (origin->stop1 + stop1->stop2),
  not a trip-duration budget -- it does not model time actually spent AT each
  stop (visiting a museum, walking a dog in a park, etc.). Stated plainly
  rather than silently assumed, same spirit as the "direct connections only"
  and other limitations documented in docs/reasoning_layer_decisions.md.
- Uses the same GtfsRouter/find_pois building blocks as the rest of the
  Reasoning Layer -- no new KG queries or ontology needed here, this is
  purely an orchestration layer on top of what already exists.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reasoning.gtfs_routing import GtfsRouter, format_seconds, parse_gtfs_time
from reasoning.preference_filter import find_pois


def _seconds_to_hms(total_seconds: int) -> str:
    """Inverse of parse_gtfs_time -- handles the >24:00:00 GTFS convention."""
    h, rem = divmod(int(total_seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _single_stop_plans(g, router, origin_lon, origin_lat, interest,
                        time_budget_min, depart_after, top_n):
    results = find_pois(g, router, origin_lon, origin_lat,
                         poi_classes=interest.get("poi_classes"),
                         required_amenities=interest.get("required_amenities"),
                         max_travel_time_min=time_budget_min,
                         depart_after=depart_after, top_n=top_n)
    plans = []
    for r in results:
        plans.append({
            "stops": [{**r, "label": interest.get("label", "stop"), "leg_travel_min": r["travel_time_min"]}],
            "total_travel_min": r["travel_time_min"],
        })
    return plans


def plan_activities(g, router: GtfsRouter, origin_lon: float, origin_lat: float,
                     interests: list, time_budget_min: float = 90,
                     depart_after: str = "14:00:00", top_stop1_candidates: int = 8,
                     top_plans: int = 5) -> list:
    """
    interests: list of 1 or 2 dicts, each like
        {"label": "a park", "poi_classes": ["Park"], "required_amenities": ["Dogs allowed"]}
    (required_amenities optional). One interest -> ranked single-stop
    suggestions. Two interests -> 2-stop plans (order matters: interests[0]
    is visited first), each within time_budget_min total travel time.

    Returns a list of plans, each {"stops": [...], "total_travel_min": ...},
    best (least total travel time) first.
    """
    if len(interests) == 1:
        return sorted(_single_stop_plans(g, router, origin_lon, origin_lat, interests[0],
                                          time_budget_min, depart_after, top_plans),
                       key=lambda p: p["total_travel_min"])[:top_plans]

    if len(interests) != 2:
        raise ValueError("plan_activities supports 1 or 2 interests, not more (see module docstring)")

    interest1, interest2 = interests
    # top_stop1_candidates by travel time, NOT yet capped by the full budget --
    # leg 2 still needs to fit, so a generous first-leg candidate pool is kept
    stop1_candidates = find_pois(g, router, origin_lon, origin_lat,
                                  poi_classes=interest1.get("poi_classes"),
                                  required_amenities=interest1.get("required_amenities"),
                                  depart_after=depart_after, top_n=top_stop1_candidates)

    plans = []
    for c1 in stop1_candidates:
        if not c1["reachable"] or c1["travel_time_min"] >= time_budget_min:
            continue
        remaining_budget = time_budget_min - c1["travel_time_min"]

        # arrival clock time at stop1 becomes the departure time for leg 2 --
        # chaining legs correctly, not just adding minutes to a budget
        arrive_stop1_s = parse_gtfs_time(depart_after) + c1["travel_time_min"] * 60
        depart_leg2 = _seconds_to_hms(round(arrive_stop1_s))

        leg2_reachability = router.reachable_from(c1["lon"], c1["lat"], depart_leg2)
        stop2_candidates = find_pois(g, router, c1["lon"], c1["lat"],
                                      poi_classes=interest2.get("poi_classes"),
                                      required_amenities=interest2.get("required_amenities"),
                                      max_travel_time_min=remaining_budget,
                                      depart_after=depart_leg2, top_n=3)

        for c2 in stop2_candidates:
            plans.append({
                "stops": [
                    {**c1, "label": interest1.get("label", "stop 1"), "leg_travel_min": c1["travel_time_min"]},
                    {**c2, "label": interest2.get("label", "stop 2"), "leg_travel_min": c2["travel_time_min"]},
                ],
                "total_travel_min": c1["travel_time_min"] + c2["travel_time_min"],
            })

    plans.sort(key=lambda p: p["total_travel_min"])
    return plans[:top_plans]


def format_plan(plan: dict, depart_after: str = "14:00:00") -> str:
    """Human-readable rendering of one plan -- for print()ing in a notebook
    or demo, not meant as the final UI."""
    lines = []
    clock_s = parse_gtfs_time(depart_after)
    lines.append(f"Depart at {depart_after}")
    for stop in plan["stops"]:
        clock_s += stop["leg_travel_min"] * 60
        transfers = stop.get("num_transfers")
        transfer_txt = f", {transfers} transfer{'s' if transfers != 1 else ''}" if transfers is not None else ""
        lines.append(f"  -> {stop['label']}: {stop['name']} "
                      f"(arrive ~{_seconds_to_hms(round(clock_s))[:5]}, "
                      f"{stop['leg_travel_min']:.1f} min travel{transfer_txt})")
    lines.append(f"Total travel time: {plan['total_travel_min']:.1f} min "
                 "(visiting time at each stop not included)")
    return "\n".join(lines)
