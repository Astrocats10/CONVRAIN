"""
ขั้น 5 ของ pipeline: เวลาฝนเริ่ม / หนักสุด / หยุด (ใช้ภาพ Himawari อย่างเดียว)

ทุก scan:
  1. สายตระกูลเมฆ + นาฬิกา t0 จาก track ของขั้น 3                 (lineage.py)
  2. ค่าคอลัมน์อากาศเหนือจุด                                        (columns.py)
  3. โมเดลของแต่ละเหตุการณ์ → ควอนไทล์เวลา q10 … q90 + P(ฝนเริ่มภายใน 30 / 60 นาที)   (clock.py, hazard.py)
ผล 2 ระดับ:
  รายวัตถุ  ประเมินที่ศูนย์กลางแกน (d² = 0) → ช่อง onset / peak_eta / stop_eta ของ JSON ต่อ scan
  รายจุด    จุดใน timing.points_file: แต่ละจุดใช้สายตระกูลที่วงรีแกนใกล้ที่สุด ทายเมื่อ d² < d2_max
ไม่มีค่าใดมาจากอนาคต: ใช้เฉพาะ scan นี้และ scan ก่อนหน้า (ต้องส่ง scan ตามลำดับเวลา)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .clock import QCOLS
from .columns import FEATURES, ColumnSampler
from .geometry import ellipse_d2, local_xy
from .hazard import from_dict
from .lineage import LineageBook
from .params import EVENT_MODELS

EVENTS = ("onset", "peak", "stop")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def to_min(t: datetime) -> float:
    t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    return (t - EPOCH).total_seconds() / 60.0


def from_min(m) -> pd.DatetimeIndex:
    """นาทีนับจาก 1970-01-01 UTC → เวลา (ปัดเป็นวินาที)"""
    return pd.to_datetime(np.round(np.asarray(m, dtype=float) * 60.0), unit="s", utc=True)


def load_event_models(params_file: str | Path | None = None) -> dict:
    P = EVENT_MODELS if params_file is None else json.loads(Path(params_file).read_text(encoding="utf-8"))
    return {ev: from_dict(P[ev]) for ev in EVENTS}


def load_points(points_file: str | Path | None) -> pd.DataFrame | None:
    if not points_file:
        return None
    P = pd.read_csv(points_file)
    missing = {"key", "lat", "lon"} - set(P.columns)
    if missing:
        raise ValueError(f"{points_file}: ต้องมีคอลัมน์ key, lat, lon (ขาด {sorted(missing)})")
    return P[["key", "lat", "lon"]].reset_index(drop=True)


@dataclass
class TimingResult:
    objects: dict                       # track_id → {"onset": {...}, "peak": {...}, "stop": {...}, "t0", "age_min"}
    points: pd.DataFrame | None = None  # 1 แถวต่อจุดที่ได้คำทำนาย


class ScopeTiming:
    def __init__(self, cfg: dict, models: dict | None = None, collect_rows: bool = False):
        self.tc = cfg["timing"]
        self.models = models or load_event_models(self.tc.get("params_file"))
        self.points = load_points(self.tc.get("points_file"))
        self.lineages = LineageBook(self.tc)
        self.columns = ColumnSampler(self.tc)
        self.collect_rows = collect_rows
        self.rows_log: list[pd.DataFrame] = []           # แถวรายจุด (ตัวแปรครบ) สำหรับ scripts/calibrate_timing.py

    @property
    def version(self) -> str:
        return "scope-timing" + ("-custom" if self.tc.get("params_file") else "")

    def reset(self) -> None:
        """ข้อมูลขาดนานเกินไป: ล้างสายตระกูล / ภาพเก่า (tracker ของขั้น 3 ก็เริ่มใหม่เช่นกัน)"""
        self.lineages.reset()
        self.columns.scans = []

    # ------------------------------------------------------------------ ทำนาย
    def _predict(self, rows: pd.DataFrame) -> dict:
        out = {}
        for ev in EVENTS:
            m = self.models[ev]
            out[ev] = m.quantiles(rows)
            if ev == "onset":
                out["p30"], out["p60"] = m.prob_within(rows, 30.0), m.prob_within(rows, 60.0)
        # สามเหตุการณ์ทายแยกกัน → จัดลำดับให้ไม่ขัดกันเองในผลที่ส่งออก: เริ่ม ≤ หนักสุด ≤ หยุด (ทุกควอนไทล์)
        out["peak"] = np.maximum(out["peak"], out["onset"])
        out["stop"] = np.maximum(out["stop"], out["peak"])
        return out

    def step(self, scan, tracks) -> TimingResult:
        self.columns.push(scan)
        states = self.lineages.update(tracks, scan)
        live = [s for s in states.values() if s.t0 is not None and s.has_core]
        if not live:
            return TimingResult(objects={})
        t = to_min(scan.time)

        # ---------- รายวัตถุ: ศูนย์กลางแกน
        col = self.columns.sample([s.core_lat_s for s in live], [s.core_lon_s for s in live])
        rows = col.assign(cell_id=[s.track_id for s in live], station="core", t=t,
                          b=[to_min(s.t0) for s in live], d2=0.0, btd=col.st_btd)
        P = self._predict(rows)
        objects = {}
        for i, s in enumerate(live):
            rec = {"t0": s.t0, "t0_censored": s.t0_censored, "age_min": t - rows.b.iat[i]}
            for ev in EVENTS:
                rec[ev] = {c: from_min([P[ev][c].iat[i]])[0].to_pydatetime() for c in QCOLS}
            rec["onset"]["p30"], rec["onset"]["p60"] = float(P["p30"][i]), float(P["p60"][i])
            objects[s.track_id] = rec

        # ---------- รายจุด
        pts = None
        if self.points is not None:
            pts = self._points(live, scan, t)
        return TimingResult(objects=objects, points=pts)

    def _points(self, live, scan, t) -> pd.DataFrame | None:
        P = self.points
        D = np.column_stack([ellipse_d2(*local_xy(P.lat, P.lon, s.core_lat_s, s.core_lon_s), s.core_sxx, s.core_syy,
                                        s.core_sxy, self.tc["d2_max"]) for s in live])
        j = D.argmin(1)
        d2 = D[np.arange(len(P)), j]
        idx = np.nonzero(d2 < self.tc["d2_max"])[0]
        if not len(idx):
            return None
        L = [live[k] for k in j[idx]]
        col = self.columns.sample(P.lat.to_numpy()[idx], P.lon.to_numpy()[idx])
        rows = col.assign(cell_id=[s.track_id for s in L], station=P.key.to_numpy()[idx], t=t,
                          b=[to_min(s.t0) for s in L], d2=d2[idx], btd=col.st_btd)
        if self.collect_rows:
            self.rows_log.append(rows.assign(t0_censored=[s.t0_censored for s in L]))
        pred = self._predict(rows)
        out = pd.DataFrame({"scan_time": scan.time, "point": rows.station, "lat": P.lat.to_numpy()[idx],
                            "lon": P.lon.to_numpy()[idx], "object_id": rows.cell_id, "d2": rows.d2,
                            "age_min": rows.t - rows.b, "t0": from_min(rows.b)})
        for ev in EVENTS:
            for c in QCOLS:
                out[f"{ev}_{c}"] = from_min(pred[ev][c].to_numpy())
        out["onset_p30"], out["onset_p60"] = pred["p30"], pred["p60"]
        for f in FEATURES:
            out[f] = rows[f].to_numpy()
        return out.reset_index(drop=True)
