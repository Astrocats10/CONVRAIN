"""
CONVRAIN Precision Satellite Convective Nowcasting Platform
Data Loader Engine
Loads and indexes data from CONVRAIN_OUTPUT (monitor CSV, timeseries CSV, closed tracks CSV, footprints and objects GeoJSON).
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from shapely.geometry import Point, shape, mapping, LineString
from shapely.affinity import translate

CANDIDATE_DIRS = [
    Path("CONVRAIN_OUTPUT"),
    Path("CONVRAIN_Outputs_check"),
    Path("CONVRAIN_Outputs_latest"),
    Path("CONVRAIN_Outputs"),
    Path("runs/real_nowcast"),
    Path("runs/test_real"),
    Path("runs/2025/realtime"),
    Path("nowcast"),
    Path("examples"),
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometers."""
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate initial compass bearing from point 1 to point 2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    deg = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return round(deg, 1)


def compass_cardinal(deg: float) -> str:
    """Convert bearing degrees into 8-point compass cardinal."""
    dirs = [
        (22.5, "N"),
        (67.5, "NE"),
        (112.5, "E"),
        (157.5, "SE"),
        (202.5, "S"),
        (247.5, "SW"),
        (292.5, "NW"),
        (337.5, "NNW"),
        (360.0, "N"),
    ]
    deg = deg % 360.0
    for threshold, name in dirs:
        if deg <= threshold:
            return name
    return "N"


def compass_thai(deg: float) -> str:
    """Convert bearing degrees to Thai cardinal name."""
    dirs = [
        (22.5, "เหนือ"),
        (67.5, "ตะวันออกเฉียงเหนือ"),
        (112.5, "ตะวันออก"),
        (157.5, "ตะวันออกเฉียงใต้"),
        (202.5, "ใต้"),
        (247.5, "ตะวันตกเฉียงใต้"),
        (292.5, "ตะวันตก"),
        (337.5, "ตะวันตกเฉียงเหนือ"),
        (360.0, "เหนือ"),
    ]
    deg = deg % 360.0
    for threshold, name in dirs:
        if deg <= threshold:
            return name
    return "เหนือ"


def safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or pd.isna(val):
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def safe_float_or_none(val: Any) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except Exception:
        return None


def parse_timestamp_iso(stamp_str: str) -> tuple[datetime, str, str]:
    """Parse timestamp into datetime, ISO UTC string, and Thai local time string."""
    try:
        # e.g. 20261014T1420Z or 2026-10-14T14:20:00Z
        if "T" in stamp_str and stamp_str.endswith("Z") and len(stamp_str) == 16:
            dt = datetime.strptime(stamp_str, "%Y%m%dT%H%MZ").replace(tzinfo=timezone.utc)
        elif stamp_str.endswith("Z"):
            clean_ts = stamp_str[:-1]
            dt = datetime.fromisoformat(clean_ts).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(stamp_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)

    utc_str = dt.strftime("%H:%M UTC")
    dt_th = dt.astimezone(timezone(timedelta(hours=7)))
    thai_str = dt_th.strftime("%H:%M น.")
    iso_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt, iso_str, f"{thai_str} ({utc_str})"


def generate_organic_cloud_polygon(
    lon: float,
    lat: float,
    area_km2: float,
    seed_str: str = "",
    speed_ms: float = 0.0,
    direction_deg: float = 0.0,
    n_points: int = 24,
) -> dict:
    """Generate a natural, undulating, multi-harmonic organic convective cloud contour."""
    base_r_km = math.sqrt(max(10.0, area_km2) / math.pi)
    h = abs(hash(seed_str)) if seed_str else 42
    phase1 = (h % 100) / 100.0 * 2 * math.pi
    phase2 = ((h // 100) % 100) / 100.0 * 2 * math.pi
    phase3 = ((h // 10000) % 100) / 100.0 * 2 * math.pi
    lobe_factor = 0.18 + ((h % 15) / 100.0)
    dir_rad = math.radians(direction_deg)
    coords = []
    r_deg_lat = 1.0 / 111.0
    r_deg_lon = 1.0 / (111.0 * max(0.01, math.cos(math.radians(lat))))
    for i in range(n_points):
        theta = 2 * math.pi * i / n_points
        w1 = math.sin(2 * theta + phase1) * lobe_factor
        w2 = math.cos(3 * theta + phase2) * (lobe_factor * 0.5)
        w3 = math.sin(5 * theta + phase3) * (lobe_factor * 0.25)
        elongation = 0.12 * math.cos(theta - dir_rad) if speed_ms > 1.0 else 0.0
        r_km = base_r_km * (1.0 + w1 + w2 + w3 + elongation)
        dx = r_km * math.sin(theta) * r_deg_lon
        dy = r_km * math.cos(theta) * r_deg_lat
        coords.append([round(lon + dx, 5), round(lat + dy, 5)])
    coords.append(coords[0])
    return {"type": "Polygon", "coordinates": [coords]}


class ConvrainDataLoader:
    def __init__(self, base_dir: Path | str | None = None):
        self.base_dir = Path(base_dir) if base_dir else self._find_best_dir()
        self._cache_json: dict[str, dict] = {}
        self._cache_geojson: dict[str, dict] = {}
        self._footprint_cache: dict[str, dict] = {}
        self._monitor_df: Optional[pd.DataFrame] = None
        self._timeseries_df: Optional[pd.DataFrame] = None
        self._closed_tracks_df: Optional[pd.DataFrame] = None
        self._timeseries_by_obj: dict[str, pd.DataFrame] = {}
        self._timeseries_by_scan: dict[str, pd.DataFrame] = {}
        self._observed_stamps: list[str] = []
        self._last_check_time = 0.0
        self._last_file_count = 0
        self._init_data()

    def check_reload(self):
        """Check if new scans arrived in base_dir and dynamically hot-reload data."""
        now = time.time()
        if now - getattr(self, "_last_check_time", 0.0) < 5.0:
            return
        self._last_check_time = now

        try:
            current_files = list(self.base_dir.glob("objects_*.geojson")) + list(self.base_dir.glob("footprints_*.geojson"))
            file_count = len(current_files)
            if file_count != getattr(self, "_last_file_count", 0):
                print(f"[DataLoader] Real-time update detected! File count changed from {getattr(self, '_last_file_count', 0)} to {file_count}. Hot-reloading data...")
                self._last_file_count = file_count
                self._init_data()
        except Exception as e:
            print(f"[DataLoader] Error checking reload: {e}")

    def _find_best_dir(self) -> Path:
        for p in CANDIDATE_DIRS:
            if p.exists():
                # check if it contains geojson or csv
                if any(p.glob("*.csv")) or any(p.glob("*.geojson")):
                    return p
                if (p / "json").exists() and any((p / "json").glob("*.json")):
                    return p
        return Path("CONVRAIN_OUTPUT")

    def _init_data(self):
        """Load CSVs and build indexes."""
        if not self.base_dir.exists():
            return

        self._last_file_count = len(list(self.base_dir.glob("objects_*.geojson")) + list(self.base_dir.glob("footprints_*.geojson")))

        # 1. Load monitor_*.csv
        mon_files = sorted(self.base_dir.glob("monitor_*.csv")) or sorted(self.base_dir.glob("monitor.csv"))
        if mon_files:
            try:
                self._monitor_df = pd.read_csv(mon_files[-1])
            except Exception as e:
                print(f"[DataLoader] Warning loading monitor CSV: {e}")

        # 2. Load closed_tracks_*.csv
        ct_files = sorted(self.base_dir.glob("closed_tracks_*.csv")) or sorted(self.base_dir.glob("closed_tracks.csv"))
        if ct_files:
            try:
                self._closed_tracks_df = pd.read_csv(ct_files[-1])
            except Exception as e:
                print(f"[DataLoader] Warning loading closed tracks CSV: {e}")

        # 3. Load timeseries_*.csv
        ts_files = sorted(self.base_dir.glob("timeseries_*.csv")) or sorted(self.base_dir.glob("timeseries.csv"))
        if ts_files:
            try:
                self._timeseries_df = pd.read_csv(ts_files[-1])
                # Index by scan_time
                for st, grp in self._timeseries_df.groupby("scan_time"):
                    self._timeseries_by_scan[st] = grp
                    # Convert to stamp format e.g. 20261014T1420Z
                    try:
                        dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
                        stamp = dt.strftime("%Y%m%dT%H%MZ")
                        self._timeseries_by_scan[stamp] = grp
                    except Exception:
                        pass
            except Exception as e:
                print(f"[DataLoader] Warning loading timeseries CSV: {e}")

        # 4. Discover all observed scan timestamps
        stamps_set = set()
        for f in self.base_dir.glob("footprints_*.geojson"):
            m = re.search(r"footprints_(\d{8}T\d{4}Z)", f.name)
            if m:
                stamps_set.add(m.group(1))
        for f in self.base_dir.glob("objects_*.geojson"):
            m = re.search(r"objects_(\d{8}T\d{4}Z)", f.name)
            if m:
                stamps_set.add(m.group(1))
        for f in self.base_dir.glob("objects_*.json"):
            m = re.search(r"objects_(\d{8}T\d{4}Z)", f.name)
            if m:
                stamps_set.add(m.group(1))

        # Also add any stamps from timeseries
        if self._timeseries_df is not None and "scan_time" in self._timeseries_df:
            for st in self._timeseries_df["scan_time"].unique():
                try:
                    dt = datetime.fromisoformat(st.replace("Z", "+00:00"))
                    stamps_set.add(dt.strftime("%Y%m%dT%H%MZ"))
                except Exception:
                    pass

        self._observed_stamps = sorted(list(stamps_set))
        
        # 5. Populate global footprint cache from all footprints_*.geojson
        for f in sorted(self.base_dir.glob("footprints_*.geojson")):
            try:
                with open(f, encoding="utf-8") as fp:
                    fc = json.load(fp)
                    for feat in fc.get("features", []):
                        oid = feat.get("id") or feat.get("properties", {}).get("object_id")
                        if oid and feat.get("geometry"):
                            self._footprint_cache[oid] = feat["geometry"]
            except Exception:
                pass

        print(f"[DataLoader] Loaded from {self.base_dir.resolve()}: {len(self._observed_stamps)} observed scans, {len(self._footprint_cache)} cached real footprints")

    def get_source_info(self) -> dict[str, Any]:
        self.check_reload()
        return {
            "current_dir": str(self.base_dir.resolve()),
            "exists": self.base_dir.exists(),
            "scan_count": len(self._observed_stamps),
            "has_monitor": self._monitor_df is not None,
            "has_timeseries": self._timeseries_df is not None,
        }

    def list_scans(self) -> list[dict[str, Any]]:
        """List observed scans plus Nowcast forecast steps (+10m to +60m)."""
        self.check_reload()
        scans = []
        for stamp in self._observed_stamps:
            dt, iso_str, thai_str = parse_timestamp_iso(stamp)
            # Check warnings count from timeseries if available
            n_cells = 0
            n_warnings = 0
            ts_grp = self._timeseries_by_scan.get(stamp)
            if ts_grp is not None:
                n_cells = len(ts_grp)
                n_warnings = int((ts_grp["warning"] == True).sum()) if "warning" in ts_grp else 0
            elif self._monitor_df is not None:
                # check monitor
                row = self._get_monitor_row(iso_str)
                if row:
                    n_cells = int(row.get("n_objects", 0))
                    n_warnings = int(row.get("n_warnings", 0))

            scans.append({
                "stamp": stamp,
                "scan_time": iso_str,
                "thai_time": dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
                "utc_time": dt.strftime("%H:%M UTC"),
                "display_time": thai_str,
                "is_forecast": False,
                "offset_min": 0,
                "active_cells": n_cells,
                "onset_warnings": n_warnings,
            })

        # Add Nowcast forecast steps from latest observed stamp
        if self._observed_stamps:
            latest_stamp = self._observed_stamps[-1]
            latest_dt, _, _ = parse_timestamp_iso(latest_stamp)
            # Forecast steps: +10, +20, +30, +45, +60 mins
            for offset in [10, 20, 30, 45, 60]:
                f_dt = latest_dt + timedelta(minutes=offset)
                f_stamp = f_dt.strftime("%Y%m%dT%H%MZ")
                f_iso = f_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                f_thai = f_dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น.")
                f_utc = f_dt.strftime("%H:%M UTC")
                scans.append({
                    "stamp": f"forecast_{f_stamp}",
                    "scan_time": f_iso,
                    "thai_time": f_thai,
                    "utc_time": f_utc,
                    "display_time": f"{f_thai} (+{offset}m Nowcast)",
                    "is_forecast": True,
                    "offset_min": offset,
                    "active_cells": scans[-1]["active_cells"] if scans else 0,
                    "onset_warnings": scans[-1]["onset_warnings"] if scans else 0,
                })

        return scans

    def _get_monitor_row(self, iso_time: str) -> Optional[dict]:
        if self._monitor_df is None or self._monitor_df.empty:
            return None
        # Try match exact
        m = self._monitor_df[self._monitor_df["scan_time"] == iso_time]
        if not m.empty:
            return m.iloc[-1].to_dict()
        # Fallback to latest
        return self._monitor_df.iloc[-1].to_dict()

    def get_telemetry(self, stamp: Optional[str] = None) -> dict[str, Any]:
        """Telemetry bar & SpaceX Mission Control data."""
        self.check_reload()
        latest_stamp = self._observed_stamps[-1] if self._observed_stamps else "20261014T1420Z"
        if stamp and stamp.startswith("forecast_"):
            stamp = latest_stamp
        if not stamp:
            stamp = latest_stamp

        dt, iso_str, thai_str = parse_timestamp_iso(stamp)
        mon_row = self._get_monitor_row(iso_str) or {}

        # Latencies
        prep_ms = float(mon_row.get("preprocess_ms", 0.97))
        det_ms = float(mon_row.get("detect_ms", 398.82))
        mot_ms = float(mon_row.get("motion_ms", 86.29))
        trk_ms = float(mon_row.get("track_ms", 80.80))
        feat_ms = float(mon_row.get("features_ms", 137.88))
        onset_ms = float(mon_row.get("onset_model_ms", 826.72))
        stg6_ms = float(mon_row.get("stage6_ms", 1720.39))
        tot_ms = float(mon_row.get("total_ms", 3372.40))

        # Latency in seconds
        latency_s = round(tot_ms / 1000.0, 2)

        # Active cells and warnings
        n_objects = int(mon_row.get("n_objects", 683))
        n_warnings = int(mon_row.get("n_warnings", 27))

        # Boundary buffer warnings
        err_str = str(mon_row.get("errors", ""))
        boundary_logs = []
        if err_str and err_str != "nan":
            items = [item.strip() for item in err_str.split(";") if item.strip()]
            boundary_logs = items[:50]  # First 50 items

        return {
            "satellite": "HIMAWARI-9 BAND 13 (10.4 μm)",
            "scan_stamp": stamp,
            "scan_time": iso_str,
            "scan_time_thai": dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
            "scan_time_utc": dt.strftime("%H:%M UTC"),
            "pipeline_latency_s": latency_s,
            "pipeline_latency_ms": tot_ms,
            "active_cells": n_objects,
            "onset_warnings": n_warnings,
            "status": "HEALTHY",
            "boundary_flag": len(boundary_logs) > 0,
            "boundary_count": len(boundary_logs),
            "boundary_logs": boundary_logs,
            "stages": [
                {"stage": "Stage 1", "name": "Satellite Ingestion & Calib", "ms": round(prep_ms, 2), "pct": round(prep_ms / tot_ms * 100, 1)},
                {"stage": "Stage 2", "name": "Parallax Geometry Engine", "ms": round(det_ms * 0.15, 2), "pct": round((det_ms * 0.15) / tot_ms * 100, 1)},
                {"stage": "Stage 3", "name": "Cloud Object Identification", "ms": round(det_ms * 0.85, 2), "pct": round((det_ms * 0.85) / tot_ms * 100, 1)},
                {"stage": "Stage 4", "name": "Overlap Tracking Engine", "ms": round(trk_ms, 2), "pct": round(trk_ms / tot_ms * 100, 1)},
                {"stage": "Stage 5", "name": "Physics Extraction (dTb/dt)", "ms": round(feat_ms + mot_ms, 2), "pct": round((feat_ms + mot_ms) / tot_ms * 100, 1)},
                {"stage": "Stage 6", "name": "Onset ML Inference & Output", "ms": round(onset_ms + stg6_ms, 2), "pct": round((onset_ms + stg6_ms) / tot_ms * 100, 1)},
            ],
        }

    def get_scan(self, stamp: Optional[str] = None) -> dict[str, Any]:
        """
        Load or compute scan features:
        - Ground Footprints (true parallax-corrected impact zone)
        - Raw Satellite Footprints (dashed outline)
        - Parallax Shift Vectors
        - Motion Vectors & Forecast Cones
        - Telemetry stats
        """
        self.check_reload()
        if not self._observed_stamps:
            return {"error": "No scan data available"}

        is_forecast = False
        offset_min = 0
        target_stamp = stamp

        if target_stamp and target_stamp.startswith("forecast_"):
            is_forecast = True
            m_dt = re.search(r"forecast_(\d{8}T\d{4}Z)", target_stamp)
            f_stamp = m_dt.group(1) if m_dt else self._observed_stamps[-1]
            latest_stamp = self._observed_stamps[-1]
            dt_f, _, _ = parse_timestamp_iso(f_stamp)
            dt_base, _, _ = parse_timestamp_iso(latest_stamp)
            offset_min = max(0, int((dt_f - dt_base).total_seconds() / 60))
            base_stamp = latest_stamp
        else:
            if not target_stamp or target_stamp not in self._observed_stamps:
                target_stamp = self._observed_stamps[-1]
            base_stamp = target_stamp

        dt, iso_str, thai_str = parse_timestamp_iso(target_stamp if not is_forecast else f_stamp)

        # 1. Load base footprints GeoJSON
        fp_file = self.base_dir / f"footprints_{base_stamp}.geojson"
        fc_fp = None
        if fp_file.exists():
            try:
                with open(fp_file, encoding="utf-8") as f:
                    fc_fp = json.load(f)
            except Exception as e:
                print(f"[DataLoader] Error loading {fp_file}: {e}")

        # 2. Load objects GeoJSON / JSON
        obj_file = self.base_dir / f"objects_{base_stamp}.geojson"
        fc_obj = None
        if obj_file.exists():
            try:
                with open(obj_file, encoding="utf-8") as f:
                    fc_obj = json.load(f)
            except Exception:
                pass

        if fc_obj is None:
            obj_json_file = self.base_dir / f"objects_{base_stamp}.json"
            if obj_json_file.exists():
                try:
                    with open(obj_json_file, encoding="utf-8") as f:
                        doc = json.load(f)
                        # convert doc to GeoJSON FeatureCollection
                        feats = []
                        for o in doc.get("objects", []):
                            feats.append({
                                "type": "Feature",
                                "geometry": o.get("geometry", {"type": "Point", "coordinates": [100.5, 13.75]}),
                                "properties": o,
                            })
                        fc_obj = {"type": "FeatureCollection", "features": feats}
                except Exception:
                    pass

        # 3. Get timeseries rows for base scan
        ts_grp = self._timeseries_by_scan.get(base_stamp)
        if ts_grp is None:
            ts_grp = self._timeseries_by_scan.get(iso_str)
        ts_dict = {}
        if ts_grp is not None:
            for _, r in ts_grp.iterrows():
                ts_dict[r["object_id"]] = r.to_dict()

        # Build feature maps
        fp_by_id = {}
        if fc_fp and "features" in fc_fp:
            for feat in fc_fp["features"]:
                oid = feat.get("id") or feat.get("properties", {}).get("object_id")
                if oid:
                    fp_by_id[oid] = feat

        obj_by_id = {}
        if fc_obj and "features" in fc_obj:
            for feat in fc_obj["features"]:
                oid = feat.get("properties", {}).get("object_id")
                if oid:
                    obj_by_id[oid] = feat

        all_oids = sorted(list(set(fp_by_id.keys()) | set(obj_by_id.keys()) | set(ts_dict.keys())))

        # Output collections
        out_footprints = []
        out_raw_footprints = []
        out_parallax_vectors = []
        out_motion_vectors = []

        for oid in all_oids:
            ts_row = ts_dict.get(oid, {})
            obj_feat = obj_by_id.get(oid)
            fp_feat = fp_by_id.get(oid)

            # Coordinates & shift
            pc_lat = safe_float(ts_row.get("lat_pc_x"), (obj_feat["geometry"]["coordinates"][1] if obj_feat else 13.75))
            pc_lon = safe_float(ts_row.get("lon_pc_x"), (obj_feat["geometry"]["coordinates"][0] if obj_feat else 100.5))
            raw_lat = safe_float(ts_row.get("lat"), pc_lat)
            raw_lon = safe_float(ts_row.get("lon"), pc_lon)
            shift_km = safe_float(ts_row.get("parallax_shift_km"), 0.0)

            # Metrics
            min_bt = safe_float(ts_row.get("min_bt"), 230.0)
            cooling_rate = safe_float(ts_row.get("cooling_rate_kf"), 0.0)
            area_km2 = safe_float(ts_row.get("area_km2"), 100.0)
            area_growth = safe_float(ts_row.get("area_growth_kf"), 0.0)
            p30 = safe_float(ts_row.get("p30"), 0.0)
            p60 = safe_float(ts_row.get("p60"), 0.0)
            warning = bool(ts_row.get("warning", False)) or (p30 >= 0.5)
            status = str(ts_row.get("status", "developing") or "developing")
            if status == "nan":
                status = "developing"
            speed_ms = safe_float(ts_row.get("speed_ms"), 5.0)
            direction_deg = safe_float(ts_row.get("direction_deg"), 70.0)
            speed_kmh = round(speed_ms * 3.6, 1)
            eta_median_min = safe_float_or_none(ts_row.get("eta_median_min"))
            if eta_median_min is not None:
                eta_median_min = round(eta_median_min, 1)

            # Bearing
            b_deg = bearing_deg(raw_lat, raw_lon, pc_lat, pc_lon)
            cardinal = compass_cardinal(b_deg)

            # Calculate advection translation for forecast steps
            dx_deg_lon = 0.0
            dy_deg_lat = 0.0
            if is_forecast and offset_min > 0:
                dist_km = (speed_ms * 60.0 * offset_min) / 1000.0
                rad_dir = math.radians(direction_deg)
                dy_km = dist_km * math.cos(rad_dir)
                dx_km = dist_km * math.sin(rad_dir)
                dy_deg_lat = dy_km / 111.0
                dx_deg_lon = dx_km / (111.0 * max(0.01, math.cos(math.radians(pc_lat))))
                pc_lat += dy_deg_lat
                pc_lon += dx_deg_lon
                raw_lat += dy_deg_lat
                raw_lon += dx_deg_lon

            # Footprint geometry
            geom = None
            if fp_feat and "geometry" in fp_feat and fp_feat["geometry"]:
                geom = fp_feat["geometry"]
                if is_forecast and offset_min > 0:
                    try:
                        sh_geom = shape(geom)
                        sh_trans = translate(sh_geom, xoff=dx_deg_lon, yoff=dy_deg_lat)
                        geom = mapping(sh_trans)
                    except Exception:
                        pass
            elif oid in self._footprint_cache:
                # Use real cloud footprint geometry cached from other scans, translated to current location!
                cached_geom = self._footprint_cache[oid]
                try:
                    sh_orig = shape(cached_geom)
                    c = sh_orig.centroid
                    dx = pc_lon - c.x
                    dy = pc_lat - c.y
                    sh_trans = translate(sh_orig, xoff=dx, yoff=dy)
                    if is_forecast and offset_min > 0:
                        sh_trans = translate(sh_trans, xoff=dx_deg_lon, yoff=dy_deg_lat)
                    geom = mapping(sh_trans)
                except Exception:
                    geom = generate_organic_cloud_polygon(pc_lon, pc_lat, area_km2, oid, speed_ms, direction_deg)
            elif area_km2 > 0:
                geom = generate_organic_cloud_polygon(pc_lon, pc_lat, area_km2, oid, speed_ms, direction_deg)

            props = {
                "object_id": oid,
                "track_id": f"#CR-{oid.replace('obj_', '')}",
                "pc_lat": round(pc_lat, 4),
                "pc_lon": round(pc_lon, 4),
                "raw_lat": round(raw_lat, 4),
                "raw_lon": round(raw_lon, 4),
                "parallax_shift_km": round(shift_km, 2),
                "parallax_bearing": cardinal,
                "min_bt": round(min_bt, 1),
                "min_bt_c": round(min_bt - 273.15, 1),
                "cooling_rate": round(cooling_rate, 2),
                "area_km2": round(area_km2, 1),
                "area_growth": round(area_growth, 1),
                "p30": round(p30, 2),
                "p60": round(p60, 2),
                "warning": warning,
                "status": status,
                "speed_ms": round(speed_ms, 1),
                "speed_kmh": speed_kmh,
                "direction_deg": round(direction_deg, 1),
                "compass_dir": compass_cardinal(direction_deg),
                "compass_thai": compass_thai(direction_deg),
                "eta_median_min": eta_median_min,
                "is_forecast": is_forecast,
            }

            if geom:
                out_footprints.append({
                    "type": "Feature",
                    "geometry": geom,
                    "properties": props,
                })

                # Compute Raw Satellite footprint outline shifted by +(raw - pc)
                d_lat = raw_lat - pc_lat
                d_lon = raw_lon - pc_lon
                try:
                    sh_geom = shape(geom)
                    sh_raw = translate(sh_geom, xoff=d_lon, yoff=d_lat)
                    out_raw_footprints.append({
                        "type": "Feature",
                        "geometry": mapping(sh_raw),
                        "properties": {**props, "is_raw_satellite": True},
                    })
                except Exception:
                    pass

            # Parallax vector line
            if shift_km > 0.1:
                out_parallax_vectors.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [round(raw_lon, 5), round(raw_lat, 5)],
                            [round(pc_lon, 5), round(pc_lat, 5)],
                        ],
                    },
                    "properties": {
                        "object_id": oid,
                        "shift_km": round(shift_km, 2),
                        "bearing": cardinal,
                    },
                })

            # Motion vector arrow & trajectory cone (30-60 min)
            if speed_ms > 0.5:
                # 30 min and 60 min points
                dt30_km = (speed_ms * 1800.0) / 1000.0
                dt60_km = (speed_ms * 3600.0) / 1000.0
                r_dir = math.radians(direction_deg)
                dy30 = (dt30_km * math.cos(r_dir)) / 111.0
                dx30 = (dt30_km * math.sin(r_dir)) / (111.0 * max(0.01, math.cos(math.radians(pc_lat))))
                dy60 = (dt60_km * math.cos(r_dir)) / 111.0
                dx60 = (dt60_km * math.sin(r_dir)) / (111.0 * max(0.01, math.cos(math.radians(pc_lat))))

                out_motion_vectors.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [round(pc_lon, 5), round(pc_lat, 5)],
                            [round(pc_lon + dx30, 5), round(pc_lat + dy30, 5)],
                            [round(pc_lon + dx60, 5), round(pc_lat + dy60, 5)],
                        ],
                    },
                    "properties": {
                        "object_id": oid,
                        "speed_kmh": speed_kmh,
                        "direction_deg": direction_deg,
                        "compass_dir": compass_cardinal(direction_deg),
                    },
                })

        return {
            "stamp": target_stamp,
            "scan_time": iso_str,
            "thai_time": dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
            "utc_time": dt.strftime("%H:%M UTC"),
            "display_time": thai_str,
            "is_forecast": is_forecast,
            "offset_min": offset_min,
            "telemetry": self.get_telemetry(base_stamp),
            "summary": {
                "total_objects": len(out_footprints),
                "onset_warnings": sum(1 for f in out_footprints if f["properties"].get("warning")),
                "active_raining": sum(1 for f in out_footprints if f["properties"].get("status") in ["raining", "mature"]),
            },
            "footprints": {"type": "FeatureCollection", "features": out_footprints},
            "raw_footprints": {"type": "FeatureCollection", "features": out_raw_footprints},
            "parallax_vectors": {"type": "FeatureCollection", "features": out_parallax_vectors},
            "motion_vectors": {"type": "FeatureCollection", "features": out_motion_vectors},
        }

    def get_point_nowcast(self, lat: float, lon: float, stamp: Optional[str] = None) -> dict[str, Any]:
        """
        Scenario 1: Pinpoint Coordinate Prediction
        Calculates exact rain onset risk, ETA countdown, nearest cloud physics, and confidence.
        """
        scan_data = self.get_scan(stamp)
        footprints_fc = scan_data.get("footprints", {})
        user_pt = Point(lon, lat)

        inside_feat = None
        min_dist_km = 999999.0
        nearest_feat = None

        for feat in footprints_fc.get("features", []):
            try:
                poly = shape(feat["geometry"])
                if poly.contains(user_pt):
                    inside_feat = feat
                    min_dist_km = 0.0
                    break
                else:
                    props = feat["properties"]
                    d = haversine_km(lat, lon, props["pc_lat"], props["pc_lon"])
                    if d < min_dist_km:
                        min_dist_km = d
                        nearest_feat = feat
            except Exception:
                pass

        scan_dt, _, _ = parse_timestamp_iso(scan_data["scan_time"])

        if inside_feat:
            props = inside_feat["properties"]
            track_id = props["object_id"]
            warning = props.get("warning", False)
            return {
                "coordinate": {"lat": lat, "lon": lon},
                "status": "INSIDE_CELL",
                "severity": "CRIMSON_WARNING" if warning else "DEVELOPING",
                "headline": "มีกลุ่มเมฆพาความร้อนปกคลุมเหนือพิกัดนี้โดยตรง",
                "eta_minutes": 0,
                "eta_time_utc": scan_dt.strftime("%H:%M UTC"),
                "eta_time_thai": scan_dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
                "confidence_score": max(85, round((props.get("p30") or 0.85) * 100)),
                "distance_km": 0.0,
                "track": props,
                "track_history": self.get_object_history(track_id),
            }

        target_feat = nearest_feat
        if target_feat:
            props = target_feat["properties"]
            track_id = props["object_id"]
            speed_kmh = max(5.0, props.get("speed_kmh", 25.0))
            dir_deg = props.get("direction_deg", 70.0)
            warning = props.get("warning", False)

            # Check if moving towards coordinate
            bearing_to_pt = bearing_deg(props["pc_lat"], props["pc_lon"], lat, lon)
            angle_diff = abs((dir_deg - bearing_to_pt + 180) % 360 - 180)

            # ETA calculation
            if angle_diff <= 55 and min_dist_km <= 45.0:
                eta_min = max(5, round((min_dist_km / speed_kmh) * 60))
                eta_dt = scan_dt + timedelta(minutes=eta_min)
                severity = "CRIMSON_WARNING" if warning or eta_min <= 20 else "CONVECTIVE_WATCH"
                conf = max(70, min(95, round(92 - (min_dist_km * 0.4))))
                return {
                    "coordinate": {"lat": lat, "lon": lon},
                    "status": "APPROACHING",
                    "severity": severity,
                    "headline": f"คาดการณ์ฝนเริ่มตกในอีก {eta_min} นาที (ETA {eta_dt.strftime('%H:%M UTC')})",
                    "eta_minutes": eta_min,
                    "eta_time_utc": eta_dt.strftime("%H:%M UTC"),
                    "eta_time_thai": eta_dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
                    "confidence_score": conf,
                    "distance_km": round(min_dist_km, 1),
                    "track": props,
                    "track_history": self.get_object_history(track_id),
                }

            # Cell nearby but not directly heading
            return {
                "coordinate": {"lat": lat, "lon": lon},
                "status": "NEARBY_CELL",
                "severity": "NORMAL",
                "headline": f"ตรวจพบแกนเมฆใกล้สุด {min_dist_km:.1f} กม. (ทิศทางพัดเบี่ยงออก)",
                "eta_minutes": None,
                "eta_time_utc": "-",
                "eta_time_thai": "-",
                "confidence_score": 92,
                "distance_km": round(min_dist_km, 1),
                "track": props,
                "track_history": self.get_object_history(track_id),
            }

        # No cells nearby
        return {
            "coordinate": {"lat": lat, "lon": lon},
            "status": "CLEAR",
            "severity": "SAFE",
            "headline": "สภาพอากาศโปร่ง ปลอดภัยจากฝนฟ้าคะนองใน 60 นาทีข้างหน้า",
            "eta_minutes": None,
            "eta_time_utc": "-",
            "eta_time_thai": "-",
            "confidence_score": 98,
            "distance_km": None,
            "track": None,
            "track_history": [],
        }

    def get_object_history(self, object_id: str) -> list[dict[str, Any]]:
        """Extract multi-scan history for Bento Grid and Micro-timeseries chart."""
        if self._timeseries_df is None or self._timeseries_df.empty:
            return []

        if object_id not in self._timeseries_by_obj:
            obj_rows = self._timeseries_df[self._timeseries_df["object_id"] == object_id]
            self._timeseries_by_obj[object_id] = obj_rows
        else:
            obj_rows = self._timeseries_by_obj[object_id]

        history = []
        for _, r in obj_rows.sort_values("scan_time").iterrows():
            dt, iso_str, thai_str = parse_timestamp_iso(r["scan_time"])
            min_bt = safe_float(r.get("min_bt"), 230.0)
            p30 = r.get("p30")
            p30_val = round(safe_float(p30) * 100, 1)

            history.append({
                "scan_time": iso_str,
                "time_short": dt.strftime("%H:%M"),
                "time_thai": dt.astimezone(timezone(timedelta(hours=7))).strftime("%H:%M น."),
                "min_bt": round(min_bt, 1),
                "min_bt_c": round(min_bt - 273.15, 1),
                "cooling_rate": round(safe_float(r.get("cooling_rate_kf"), 0.0), 2),
                "area_km2": round(safe_float(r.get("area_km2"), 0.0), 1),
                "area_growth": round(safe_float(r.get("area_growth_kf"), 0.0), 1),
                "onset_prob": p30_val,
                "parallax_shift_km": round(safe_float(r.get("parallax_shift_km"), 0.0), 2),
                "speed_kmh": round(safe_float(r.get("speed_ms"), 0.0) * 3.6, 1),
                "direction_deg": round(safe_float(r.get("direction_deg"), 0.0), 1),
                "warning": bool(r.get("warning", False)),
            })
        return history

    def export_track_csv(self, object_id: str) -> str:
        """Export CSV string for the requested track."""
        if self._timeseries_df is None:
            return "object_id,scan_time\n"
        obj_rows = self._timeseries_df[self._timeseries_df["object_id"] == object_id]
        if obj_rows.empty:
            return "object_id,scan_time\n"
        output = io.StringIO()
        obj_rows.to_csv(output, index=False)
        return output.getvalue()
