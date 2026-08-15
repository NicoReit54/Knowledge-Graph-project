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
        # index stop_times by stop_id for fast "which trips call here" lookups
        self._by_stop = {sid: df for sid, df in self.stop_times.groupby("stop_id")}

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

    def estimate_travel_time(self, origin_lon, origin_lat, dest_lon, dest_lat,
                              depart_after: str = "12:00:00") -> dict:
        """Walk to nearest GTFS stop -> direct transit leg (earliest usable
        departure at/after depart_after + walk time) -> walk to destination.
        Returns a dict with a breakdown, or a clear no_connection result if no
        direct trip links the two nearest stops on the preprocessed day."""
        origin_stop = self.nearest_stop(origin_lon, origin_lat)
        dest_stop = self.nearest_stop(dest_lon, dest_lat)

        walk1_s = origin_stop["distance_m"] / WALKING_SPEED_MPS
        walk2_s = dest_stop["distance_m"] / WALKING_SPEED_MPS
        earliest_board_s = parse_gtfs_time(depart_after) + walk1_s

        options = self.direct_trips(origin_stop["stop_id"], dest_stop["stop_id"])
        usable = options[options["dep_s"] >= earliest_board_s] if not options.empty else options

        result = {
            "origin_stop": origin_stop,
            "dest_stop": dest_stop,
            "walk_to_stop_min": walk1_s / 60,
            "walk_from_stop_min": walk2_s / 60,
        }

        if usable.empty:
            result["found_direct_connection"] = False
            result["note"] = (
                "No direct (no-transfer) connection between the nearest stops on "
                f"this service day ({self.date}) at/after {depart_after} -- either they "
                "aren't on a shared line, or scope is limited to direct connections only."
            )
            return result

        best = usable.iloc[0]  # earliest usable departure -> soonest arrival for direct trips
        total_s = walk1_s + (best["arr_s"] - parse_gtfs_time(depart_after)) + walk2_s

        result.update({
            "found_direct_connection": True,
            "line": best["line"],
            "board_at": best["departure_time_o"],
            "alight_at": best["arrival_time_d"],
            "wait_min": (best["dep_s"] - earliest_board_s) / 60,
            "ride_min": best["ride_s"] / 60,
            "total_travel_min": total_s / 60,
            "total_travel_str": format_seconds(total_s),
        })
        return result
