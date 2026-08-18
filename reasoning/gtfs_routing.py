"""
Direct-connection travel-time estimation using Wiener Linien's GTFS feed.

Implements the scoping decision in docs/reasoning_layer_decisions.md:
- GTFS-based, direct (no-transfer) connections only -- not full multi-transfer
  routing.
- GTFS stays tabular (pandas), never modelled as RDF triples -- stop_times.txt
  alone is 7.1M rows for the full year.
- No formal RDF-level link between GTFS stops and viennakg:Stop/Platform.
  Both are joined to a query point by coordinates independently: GTFS stops
  for travel-time computation, viennakg:Stop (with its RBL) for live
  departure/disruption lookups later. They resolve to the same physical
  places in practice without needing an explicit sameAs-style triple.

The 7.1M-row stop_times.txt is pre-filtered down to one representative
service day (Wiener Linien trips only) via `preprocess_day()`, producing the
much smaller data/processed/gtfs_wl_<date>_stop_times.csv /
_trips.csv this module actually queries. Re-run preprocessing to switch days.

Usage:
    from reasoning.gtfs_routing import GtfsRouter
    router = GtfsRouter(date="20260815")
    router.estimate_travel_time(16.3695, 48.2065, 16.3800, 48.1980, depart_after="14:00:00")
"""

import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_GTFS = ROOT / "data" / "raw" / "gtfs"
PROCESSED = ROOT / "data" / "processed"

WALKING_SPEED_MPS = 1.4  # ~5 km/h, standard trip-planner default
MAX_WALK_TO_STOP_M = 1500  # beyond this a "nearest stop" isn't realistic


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def haversine_m(lon1, lat1, lon2, lat2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def parse_gtfs_time(t: str) -> int:
    """GTFS times can exceed 24:00:00 for trips past midnight (still the same
    service day). Returns seconds since midnight, uncapped."""
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def format_seconds(total_seconds: float) -> str:
    minutes = round(total_seconds / 60)
    h, m = divmod(minutes, 60)
    return f"{h}h {m}min" if h else f"{m} min"


# --------------------------------------------------------------------------
# Preprocessing: full-year GTFS -> one service day, Wiener Linien only
# --------------------------------------------------------------------------

def resolve_active_services(date_str: str) -> set:
    """GTFS service_id resolution: weekday pattern from calendar.txt, adjusted
    by calendar_dates.txt's per-date additions/removals (exception_type 1/2)."""
    calendar = pd.read_csv(RAW_GTFS / "calendar.txt", dtype=str)
    calendar_dates = pd.read_csv(RAW_GTFS / "calendar_dates.txt", dtype=str)

    weekday_col = pd.Timestamp(date_str).day_name().lower()
    base_active = set(calendar.loc[
        (calendar[weekday_col] == "1") &
        (calendar["start_date"] <= date_str) &
        (calendar["end_date"] >= date_str),
        "service_id"
    ])

    exceptions_today = calendar_dates[calendar_dates["date"] == date_str]
    added = set(exceptions_today.loc[exceptions_today["exception_type"] == "1", "service_id"])
    removed = set(exceptions_today.loc[exceptions_today["exception_type"] == "2", "service_id"])

    return (base_active - removed) | added


def preprocess_day(date_str: str, chunksize: int = 500_000) -> tuple[Path, Path]:
    """Filters stop_times.txt (7.1M rows, all agencies, full year) down to just
    Wiener Linien trips active on `date_str`. Slow (scans the full file once);
    only needs to be re-run when switching to a different representative day.
    Returns (stop_times_path, trips_path) of the cached, filtered CSVs."""
    routes = pd.read_csv(RAW_GTFS / "routes.txt", dtype=str)
    trips = pd.read_csv(RAW_GTFS / "trips.txt", dtype=str)

    active_services = resolve_active_services(date_str)
    wl_routes = set(routes.loc[routes["agency_id"] == "04", "route_id"])
    wl_trips_today = trips[
        trips["route_id"].isin(wl_routes) & trips["service_id"].isin(active_services)
    ]

    valid_trip_ids = set(wl_trips_today["trip_id"])
    chunks_kept = []
    reader = pd.read_csv(
        RAW_GTFS / "stop_times.txt",
        dtype=str,
        usecols=["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
        chunksize=chunksize,
    )
    for chunk in reader:
        matched = chunk[chunk["trip_id"].isin(valid_trip_ids)]
        if len(matched):
            chunks_kept.append(matched)

    stop_times_today = pd.concat(chunks_kept, ignore_index=True)
    stop_times_today["stop_sequence"] = stop_times_today["stop_sequence"].astype(int)

    stop_times_path = PROCESSED / f"gtfs_wl_{date_str}_stop_times.csv"
    trips_path = PROCESSED / f"gtfs_wl_{date_str}_trips.csv"
    stop_times_today.to_csv(stop_times_path, index=False)
    wl_trips_today.to_csv(trips_path, index=False)
    return stop_times_path, trips_path


# --------------------------------------------------------------------------
# The router
# --------------------------------------------------------------------------

class GtfsRouter:
    def __init__(self, date: str = "20260815"):
        self.date = date
        stop_times_path = PROCESSED / f"gtfs_wl_{date}_stop_times.csv"
        trips_path = PROCESSED / f"gtfs_wl_{date}_trips.csv"
        if not stop_times_path.exists() or not trips_path.exists():
            stop_times_path, trips_path = preprocess_day(date)

        self.stop_times = pd.read_csv(stop_times_path, dtype={"stop_sequence": int})
        self.trips = pd.read_csv(trips_path, dtype=str)
        self.stops = pd.read_csv(RAW_GTFS / "stops.txt", dtype=str)
        self.stops["stop_lat"] = self.stops["stop_lat"].astype(float)
        self.stops["stop_lon"] = self.stops["stop_lon"].astype(float)
        self.routes = pd.read_csv(RAW_GTFS / "routes.txt", dtype=str)

        self.trip_to_route = dict(zip(self.trips["trip_id"], self.trips["route_id"]))
        self.route_name = dict(zip(self.routes["route_id"], self.routes["route_short_name"]))

        # precomputed once, reused by both direct_trips() and _reachable_stops()
        self.stop_times["dep_s"] = self.stop_times["departure_time"].map(parse_gtfs_time)
        self.stop_times["arr_s"] = self.stop_times["arrival_time"].map(parse_gtfs_time)

        # index stop_times by stop_id for fast "which trips call here" lookups
        self._by_stop = {sid: df for sid, df in self.stop_times.groupby("stop_id")}
        self._stop_name = dict(zip(self.stops["stop_id"], self.stops["stop_name"]))

    def nearest_stop(self, lon: float, lat: float) -> dict:
        """Vectorized haversine over all stops -- matters here since this gets
        called twice per estimate_travel_time() and the notebook calls that
        in a loop; the naive .apply() version was slow enough to time out a
        modest batch search."""
        import numpy as np
        lons = self.stops["stop_lon"].to_numpy()
        lats = self.stops["stop_lat"].to_numpy()
        R = 6371000
        p1, p2 = math.radians(lat), np.radians(lats)
        dphi = np.radians(lats - lat)
        dlambda = np.radians(lons - lon)
        a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlambda / 2) ** 2
        dists = 2 * R * np.arcsin(np.sqrt(a))
        idx = int(np.argmin(dists))
        row = self.stops.iloc[idx]
        return {"stop_id": row["stop_id"], "stop_name": row["stop_name"],
                "lon": row["stop_lon"], "lat": row["stop_lat"], "distance_m": float(dists[idx])}

    def _nearby_stops(self, lon: float, lat: float, max_walk_m: float = MAX_WALK_TO_STOP_M,
                       strict: bool = False) -> list:
        """All stops within walking distance, not just the single nearest one.
        Matters because a single 'nearest stop' can land on a specific
        platform that happens to be poorly connected for *boarding* (e.g. near
        the END of most trip patterns -- an alighting-heavy platform) even
        when a slightly farther platform at the same named stop is a much
        better boarding point. Returns [(stop_id, walk_seconds), ...].

        `strict=False` (default): if nothing is within max_walk_m, falls back
        to the single nearest stop anyway -- avoids ordinary queries coming
        back empty just because the default radius happened to be a little
        too small somewhere sparse.
        `strict=True`: no fallback -- returns [] if nothing qualifies. Used
        when the caller has stated a real constraint (e.g. a mobility-limited
        max walk time) that must not be silently violated by walking someone
        farther than they said they could."""
        import numpy as np
        lons = self.stops["stop_lon"].to_numpy()
        lats = self.stops["stop_lat"].to_numpy()
        R = 6371000
        p1, p2 = math.radians(lat), np.radians(lats)
        dphi = np.radians(lats - lat)
        dlambda = np.radians(lons - lon)
        a = np.sin(dphi / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dlambda / 2) ** 2
        dists = 2 * R * np.arcsin(np.sqrt(a))
        within = np.where(dists <= max_walk_m)[0]
        if len(within) == 0:
            if strict:
                return []
            # fall back to the single nearest stop even if it's outside max_walk_m
            idx = int(np.argmin(dists))
            within = [idx]
        return [(self.stops.iloc[i]["stop_id"], dists[i] / WALKING_SPEED_MPS) for i in within]

    def _reachable_stops(self, origin_frontier: dict, max_transfers: int = 2,
                          transfer_buffer_s: int = 180) -> dict:
        """Round-based (RAPTOR-lite) reachability search from a SET of origin
        stops (not just one), each with its own "available to board" time --
        typically every stop within walking distance of a real-world
        coordinate, via _nearby_stops(), each offset by its own walk time.
        Using multiple origin platforms rather than a single 'nearest stop'
        matters: a single nearest platform can be an unlucky pick (e.g. an
        alighting-heavy platform near the end of most trip patterns) even
        when a slightly farther platform at the same named stop boards well.

        Round 0 finds every stop reachable with zero transfers from ANY origin
        stop (this generalizes what direct_trips() checks pairwise -- here for
        all destinations from a whole origin area at once, the natural shape
        for a many-destination search like preference_filter's), round 1 adds
        stops reachable with one transfer (boarding again, after a flat
        `transfer_buffer_s`, from anywhere round 0 reached), round 2 adds a
        second transfer. A later round only overwrites a stop's entry if it
        gets there STRICTLY EARLIER -- so a fast direct (round-0) connection
        is never displaced by a slower multi-transfer one; it just doesn't get
        re-found in a later round, and the round-0 answer stands as recorded.

        Returns {stop_id: {"arrival_s", "transfers", "trip_id", "board_stop",
        "board_time_s"}}. `board_stop`/`trip_id` let a caller reconstruct the
        journey leg by leg by following board_stop back towards the origin.
        Vectorized (pandas merges), not a per-stop Python loop -- needed at
        this graph's scale (390K stop_times rows/day, 4.3K stops)."""
        st = self.stop_times
        best = {sid: {"arrival_s": t, "transfers": 0, "trip_id": None,
                       "board_stop": None, "board_time_s": None}
                for sid, t in origin_frontier.items()}
        frontier = dict(origin_frontier)

        for round_num in range(max_transfers + 1):
            if not frontier:
                break
            frontier_df = pd.DataFrame({"stop_id": list(frontier.keys()),
                                         "avail_s": list(frontier.values())})

            board = st.merge(frontier_df, on="stop_id")
            board = board[board["dep_s"] >= board["avail_s"]]
            if board.empty:
                break
            # earliest boardable departure per (frontier stop, trip) -- catching
            # a later run of the same trip from the same stop is never useful
            board = board.sort_values("dep_s").drop_duplicates(subset=["stop_id", "trip_id"], keep="first")
            board = board.rename(columns={"stop_id": "board_stop", "stop_sequence": "board_seq",
                                           "dep_s": "board_dep_s"})[["trip_id", "board_stop", "board_seq",
                                                                      "board_dep_s", "avail_s"]]

            onward = st[["trip_id", "stop_id", "stop_sequence", "arr_s"]].rename(
                columns={"stop_id": "dest_stop", "stop_sequence": "dest_seq"})
            merged = board.merge(onward, on="trip_id")
            merged = merged[merged["dest_seq"] > merged["board_seq"]]
            if merged.empty:
                break

            # best (earliest) arrival per destination stop this round; ties on
            # arrival time (common -- a frequent line can have multiple
            # platforms/trips landing on the exact same downstream arrival)
            # are broken by preferring the boarding option that was reachable
            # EARLIEST at its origin (smallest avail_s -- for round 0 this
            # means shortest walk; for later rounds, least idle transfer
            # time). Without this, an arbitrary row-order pick could surface a
            # 17-minute walk over a 2-minute one for an identical total time.
            merged = merged.sort_values(["arr_s", "avail_s"], ascending=[True, True])
            merged = merged.drop_duplicates(subset=["dest_stop"], keep="first")

            new_frontier = {}
            for row in merged.itertuples(index=False):
                dest, arr = row.dest_stop, row.arr_s
                if dest not in best or arr < best[dest]["arrival_s"]:
                    best[dest] = {"arrival_s": arr, "transfers": round_num, "trip_id": row.trip_id,
                                  "board_stop": row.board_stop, "board_time_s": row.board_dep_s}
                    new_frontier[dest] = arr + transfer_buffer_s
            frontier = new_frontier

        return best

    def _reconstruct_legs(self, best: dict, dest_stop_id: str) -> list:
        """Walk backward from the destination via each stop's recorded
        board_stop until reaching an origin stop (trip_id is None there),
        turning the flat `best` reachability dict into an ordered list of
        journey legs."""
        legs = []
        cur = dest_stop_id
        while best[cur]["trip_id"] is not None:
            info = best[cur]
            legs.append({
                "line": self.route_name.get(self.trip_to_route.get(info["trip_id"])),
                "board_stop_id": info["board_stop"],
                "board_stop_name": self._stop_name.get(info["board_stop"]),
                "board_time_s": info["board_time_s"],
                "alight_stop_id": cur,
                "alight_stop_name": self._stop_name.get(cur),
                "alight_time_s": info["arrival_s"],
            })
            cur = info["board_stop"]
        legs.reverse()
        return legs

    def direct_trips(self, origin_stop_id: str, dest_stop_id: str) -> pd.DataFrame:
        """All same-trip, same-direction connections between two stops on the
        preprocessed day -- the 'direct connection only' constraint lives here:
        no join across different trip_ids is attempted."""
        o = self._by_stop.get(origin_stop_id)
        d = self._by_stop.get(dest_stop_id)
        if o is None or d is None:
            return pd.DataFrame()

        merged = o.merge(d, on="trip_id", suffixes=("_o", "_d"))
        merged = merged[merged["stop_sequence_o"] < merged["stop_sequence_d"]]
        if merged.empty:
            return merged

        merged["route_id"] = merged["trip_id"].map(self.trip_to_route)
        merged["line"] = merged["route_id"].map(self.route_name)
        merged["dep_s"] = merged["departure_time_o"].map(parse_gtfs_time)
        merged["arr_s"] = merged["arrival_time_d"].map(parse_gtfs_time)
        merged["ride_s"] = merged["arr_s"] - merged["dep_s"]
        return merged.sort_values("dep_s")

    def reachable_from(self, origin_lon, origin_lat, depart_after: str = "12:00:00",
                        max_transfers: int = 2, transfer_buffer_s: int = 180,
                        max_walk_min: float = None) -> dict:
        """The expensive part of routing (the round-based search over the
        whole network) done ONCE for a given origin+time. Returns an opaque
        bundle to pass into travel_time_to() for fast, cheap per-destination
        lookups -- the right shape for checking many candidate destinations
        from one origin (e.g. preference_filter.find_pois() ranking a whole
        category of POIs), instead of paying the full search cost again for
        every candidate the way calling estimate_travel_time() in a loop
        would.

        max_walk_min: if given, a hard cap on how far someone can walk to
        reach a boarding stop (e.g. 10 for a stroller/mobility constraint) --
        no fallback to a farther stop if nothing qualifies (see
        _nearby_stops(strict=...)). If None, uses the generous
        MAX_WALK_TO_STOP_M default with its normal fallback behavior."""
        depart_s = parse_gtfs_time(depart_after)
        max_walk_m = max_walk_min * 60 * WALKING_SPEED_MPS if max_walk_min is not None else MAX_WALK_TO_STOP_M
        origin_candidates = self._nearby_stops(origin_lon, origin_lat, max_walk_m=max_walk_m,
                                                strict=max_walk_min is not None)
        origin_frontier = {sid: depart_s + walk_s for sid, walk_s in origin_candidates}
        best = self._reachable_stops(origin_frontier, max_transfers=max_transfers,
                                      transfer_buffer_s=transfer_buffer_s)
        return {"best": best, "depart_s": depart_s, "max_transfers": max_transfers,
                "max_walk_min": max_walk_min}

    def travel_time_to(self, reachability: dict, dest_lon, dest_lat, max_walk_min: float = None) -> dict:
        """Fast per-destination lookup against a bundle from reachable_from().
        Considers every stop within walking distance of the destination (see
        _nearby_stops), not just the single nearest one, same reasoning as
        reachable_from() does on the origin side.

        max_walk_min: caps the FINAL walk from the last transit stop to the
        destination. Defaults to whatever was passed to the reachable_from()
        call this bundle came from, so a single max_walk_min setting applies
        consistently to both ends of the trip unless overridden here."""
        best = reachability["best"]
        depart_s = reachability["depart_s"]
        effective_max_walk_min = max_walk_min if max_walk_min is not None else reachability.get("max_walk_min")
        max_walk_m = (effective_max_walk_min * 60 * WALKING_SPEED_MPS
                      if effective_max_walk_min is not None else MAX_WALK_TO_STOP_M)
        dest_candidates = self._nearby_stops(dest_lon, dest_lat, max_walk_m=max_walk_m,
                                              strict=effective_max_walk_min is not None)
        dest_walk = dict(dest_candidates)

        reached = [(sid, best[sid]["arrival_s"] + dest_walk[sid])
                   for sid, _ in dest_candidates if sid in best]

        if not reached:
            walk_note = (f" (max walk time set to {effective_max_walk_min:.0f} min -- "
                         "try relaxing it if this keeps happening)" if effective_max_walk_min is not None else "")
            return {
                "found_direct_connection": False,
                "note": f"No connection within {reachability['max_transfers']} transfer(s) "
                        f"from this origin on this service day ({self.date}){walk_note}.",
            }

        dest_stop_id, _ = min(reached, key=lambda x: x[1])
        legs = self._reconstruct_legs(best, dest_stop_id)
        num_transfers = best[dest_stop_id]["transfers"]
        walk1_s = legs[0].get("_origin_walk_s", None) if legs else None
        walk2_s = dest_walk[dest_stop_id]
        total_s = (best[dest_stop_id]["arrival_s"] - depart_s) + walk2_s

        return {
            "found_direct_connection": True,  # kept for backward compatibility with callers
            "num_transfers": num_transfers,
            "line": legs[0]["line"] if legs else None,
            "legs": legs,
            "walk_from_stop_min": walk2_s / 60,
            "total_travel_min": total_s / 60,
            "total_travel_str": format_seconds(total_s),
            "origin_stop": {"stop_id": legs[0]["board_stop_id"], "stop_name": legs[0]["board_stop_name"]} if legs else None,
            "dest_stop": {"stop_id": dest_stop_id, "stop_name": self._stop_name.get(dest_stop_id)},
        }

    def estimate_travel_time(self, origin_lon, origin_lat, dest_lon, dest_lat,
                              depart_after: str = "12:00:00", max_transfers: int = 2,
                              transfer_buffer_s: int = 180, max_walk_min: float = None) -> dict:
        """One-off origin-to-destination estimate: walk to any GTFS stop
        within walking distance -> up to `max_transfers` transit legs
        (round-based search, see _reachable_stops) -> walk from whichever
        nearby stop was actually reached to the destination. For checking
        many destinations from the SAME origin (e.g. ranking a whole POI
        category), use reachable_from() once + travel_time_to() per candidate
        instead -- this function pays the full network search cost every call.

        max_walk_min: hard cap on walking time at EACH end (e.g. 10 for a
        stroller/mobility constraint) -- see reachable_from()/travel_time_to()
        docstrings. None (default) uses the generous MAX_WALK_TO_STOP_M
        default with its normal fallback behavior.

        Direct (0-transfer) connections are never excluded: they're found in
        round 0 of the same search that finds 1- and 2-transfer options, and
        only ever get displaced by a later round if that round reaches the
        SAME destination platform strictly faster -- a slower multi-transfer
        route can never crowd out a faster direct one.

        Returns a dict with a leg-by-leg breakdown, or a clear
        found_direct_connection=False result if nothing at all connects the
        two areas within `max_transfers` on this service day (which, with a
        tight max_walk_min, may simply mean nothing was walkable at one end)."""
        reachability = self.reachable_from(origin_lon, origin_lat, depart_after,
                                            max_transfers, transfer_buffer_s, max_walk_min)
        result = self.travel_time_to(reachability, dest_lon, dest_lat, max_walk_min)
        if result["found_direct_connection"] and result.get("legs"):
            max_walk_m = (max_walk_min * 60 * WALKING_SPEED_MPS if max_walk_min is not None
                          else MAX_WALK_TO_STOP_M)
            origin_candidates = dict(self._nearby_stops(origin_lon, origin_lat, max_walk_m=max_walk_m,
                                                          strict=max_walk_min is not None))
            board_stop = result["legs"][0]["board_stop_id"]
            walk1_s = origin_candidates.get(board_stop, 0)
            result["walk_to_stop_min"] = walk1_s / 60
        return result
