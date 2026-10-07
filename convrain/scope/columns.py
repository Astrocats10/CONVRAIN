"""
คอลัมน์อากาศเหนือจุดบนพื้น — ค่าที่โมเดลเวลาใช้ (รู้ได้ ณ เวลาภาพเท่านั้น)

  st_b13, st_btd   B13 และ B13 − B15 ของพิกเซลที่อยู่เหนือจุด (แก้ parallax รายพิกเซล)
                   BTD เล็ก = เมฆหนาทึบ (split window); BTD ใหญ่ = cirrus / ทั่งบาง
  d_b13_10/20      B13 ตอนนี้ − 10 / 20 นาทีก่อน ที่จุดเดิมบนพื้น (ลบ = คอลัมน์เย็นลง: ยอดเมฆสูงขึ้นหรือแกนเข้ามา)
  d_btd_10         BTD ตอนนี้ − 10 นาทีก่อน (ลบ = หนาขึ้น)
  warm_20          max(d_b13_20, 0) = คอลัมน์อุ่นขึ้น (แกนผ่านไป / สลาย)
  depth_6          B13 ต่ำสุดในรัศมี ~6 km ของจุด − core_k (ลบ = มีแกนลึกใกล้จุด)
ภาพก่อนหน้าต้องห่าง 10 / 20 นาที (± 2 นาที) ไม่งั้นแนวโน้ม = NaN (โมเดลเติมด้วยค่ากลางของข้อมูลปรับเทียบ)
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from .geometry import GroundIndex, above_points, corrected_index, disc_min, shifted_pixels

FEATURES = ("st_b13", "st_btd", "d_b13_10", "d_b13_20", "d_btd_10", "warm_20", "depth_6")


class ColumnSampler:
    """เก็บภาพล่าสุด ≤ 30 นาที แล้วตอบค่าคอลัมน์ของจุดใดก็ได้ (สถานี, จุดผู้ใช้, ศูนย์กลางแกนเมฆ)"""

    def __init__(self, tc: dict, keep_min: float = 30.0):
        self.tc, self.keep_min = tc, keep_min
        self.scans: list[tuple[datetime, dict]] = []      # (เวลา, {"B13", "B15", "lat", "lon", "saz"})
        self._raw_index: GroundIndex | None = None
        self._raw_key = None

    def push(self, scan) -> None:
        t = scan.time
        if self.scans and t <= self.scans[-1][0]:
            raise ValueError(f"ภาพไม่เรียงเวลา: {t} หลัง {self.scans[-1][0]}")
        img = {"B13": scan.bt["B13"], "B15": scan.bt.get("B15", np.full(scan.shape, np.nan, np.float32)),
               "lat": scan.lat, "lon": scan.lon, "saz": scan.sat_zenith}
        self.scans = [(tp, v) for tp, v in self.scans if (t - tp).total_seconds() / 60 <= self.keep_min]
        self.scans.append((t, img))
        key = (scan.lat.shape, float(scan.lat.flat[0]), float(scan.lon.flat[0]))
        if key != self._raw_key:                         # กริดเปลี่ยน → สร้างดัชนีใหม่
            self._raw_index, self._raw_key = GroundIndex(scan.lat, scan.lon), key

    def _lag(self, minutes: float):
        t = self.scans[-1][0]
        for tp, v in self.scans[:-1]:
            if abs((t - tp).total_seconds() / 60 - minutes) <= 2:
                return v
        return None

    def _above(self, img, lat, lon):
        if "ci" not in img:                              # ดัชนีหลังแก้ parallax: สร้างครั้งเดียวต่อภาพ
            img["ci"] = corrected_index(img["B13"], img["B15"], img["lat"], img["lon"], img["saz"],
                                        self._raw_index.lat0)
        return above_points(img["ci"], lat, lon, self.tc["pixel_match_km"])

    def sample(self, lat, lon) -> pd.DataFrame:
        """ค่าคอลัมน์ ณ ภาพล่าสุด ของจุด (lat, lon) — อาร์เรย์ 1 มิติ"""
        lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
        now = self.scans[-1][1]
        b13, b15 = self._above(now, lat, lon)
        out = pd.DataFrame({"st_b13": b13, "st_btd": b13 - b15})
        for m in (10, 20):
            prev = self._lag(m)
            if prev is None:
                out[f"d_b13_{m}"] = np.nan
                if m == 10:
                    out["d_btd_10"] = np.nan
                continue
            p13, p15 = self._above(prev, lat, lon)
            out[f"d_b13_{m}"] = b13 - p13
            if m == 10:
                out["d_btd_10"] = (b13 - b15) - (p13 - p15)
        out["warm_20"] = out.d_b13_20.clip(lower=0)
        r, c = shifted_pixels(self._raw_index, now["B13"].shape, lat, lon, now["saz"], self.tc["parallax_top_k"])
        out["depth_6"] = disc_min(now["B13"], r, c, int(self.tc["depth_disc_px"])) - self.tc["core_k"]
        return out
