"""
Baseline ที่ระบบใหม่ต้องชนะ  (เอกสาร หัวข้อ 10.4 และ 14 Phase 1)

B2  : MB06InterestFields  — นับ interest fields ตาม Mecikalski & Bedka (2006)
B2' : ExtrapolationBaseline — extrapolate BT แกนเย็นด้วย cooling rate ไปหาค่า BT ตอน onset
      (คือ CTC extrapolation ของ workflow เดิม แต่ใช้ค่าที่ผ่าน Kalman แล้ว, หัวข้อ 8.3)
B3  : ClimatologyBaseline — ความน่าจะเป็น onset ตามเวลาท้องถิ่นของวัน

ทุกคลาสคืนตารางรูปแบบเดียวกับ HazardModel.predict() เพื่อใช้ evaluation ชุดเดียวกัน
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# =====================================================================
# B2: interest fields ของ Mecikalski & Bedka (2006)
# ค่าตั้งต้นจาก MB06 (GOES) — ตรวจกับตาราง interest field ในเปเปอร์ก่อนใช้จริง
# และจูน threshold ใหม่ด้วยชุด train ของไทย
# ช่อง 6.5 µm ของ GOES ↔ B08 (6.2) ของ AHI, 13.3 µm ↔ B16
# cooling ต่อ 15 นาทีประมาณจากค่าต่อ 10 นาที × 1.5
# =====================================================================
MB06_DEFAULTS = {
    "cool15_max": -4.0,        # ΔBT/15 นาที < −4 K
    "btd_wv_range": (-35.0, -10.0),
    "btd_co2_range": (-25.0, -5.0),
    "trend_wv15_min": 3.0,     # แนวโน้ม BTD 6.5–10.7 > +3 K/15 นาที
    "trend_co2_15_min": 3.0,   # แนวโน้ม BTD 13.3–10.7 > +3 K/15 นาที
    "below0_window_min": 30.0, # ลดต่ำกว่า 0 °C ภายใน 30 นาทีที่ผ่านมา
    "n_required": 7,           # MB06 ใช้ 7 จาก 8 fields
}


class MB06InterestFields:
    def __init__(self, **overrides):
        self.p = {**MB06_DEFAULTS, **overrides}

    def score(self, rows: pd.DataFrame) -> pd.DataFrame:
        p = self.p
        f = rows
        c15 = f["d_cold_bt_10"] * 1.5
        fields = pd.DataFrame({
            "bt_below_0c": f["min_bt"] < 273.15,
            "below_0c_recent": f["min_since_below_0c"] <= p["below0_window_min"],
            "cool_15": c15 < p["cool15_max"],
            "cool_30_lt_15": f["d_cold_bt_30"] < c15,
            "btd_wv_in_range": f["btd_wv_cold"].between(*p["btd_wv_range"]),
            "btd_co2_in_range": f["btd_co2_cold"].between(*p["btd_co2_range"]),
            "btd_wv_trend": f["d_btd_wv_10"] * 1.5 > p["trend_wv15_min"],
            "btd_co2_trend": f["d_btd_co2_10"] * 1.5 > p["trend_co2_15_min"],
        }, index=f.index)
        return fields.fillna(False).astype(int)

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        s = self.score(rows).sum(axis=1)
        prob = s / 8.0
        flag = (s >= self.p["n_required"]).astype(float)
        # MB06 รายงาน lead time ~30–45 นาที จึงถือว่า flag = onset ภายใน 60 นาที
        return pd.DataFrame({
            "object_id": rows["object_id"].values, "p30": prob.values, "p60": np.maximum(prob, flag).values,
            "eta_lo_min": np.where(flag, 15.0, np.nan), "eta_median_min": np.where(flag, 30.0, np.nan),
            "eta_hi_min": np.where(flag, 45.0, np.nan),
        })


# =====================================================================
# B2': extrapolation ของ BT แกนเย็น (CTC extrapolation แบบ smooth)
# =====================================================================
class ExtrapolationBaseline:
    def __init__(self, onset_bt: float = 245.0, min_cooling: float = -0.5, spread_min: float = 10.0):
        self.onset_bt = onset_bt          # BT แกนเย็นตอน onset (เรียนจากข้อมูลด้วย fit)
        self.min_cooling = min_cooling    # K/10 นาที ต้องเย็นลงเร็วกว่านี้จึงจะ extrapolate
        self.spread_min = spread_min

    def fit(self, df: pd.DataFrame, event_col: str = "t_onset") -> "ExtrapolationBaseline":
        """onset_bt = มัธยฐานของ cold_bt ใน scan แรกที่ ≥ เวลา onset ของแต่ละ track"""
        t = pd.to_datetime(df["time"], utc=True)
        ev = pd.to_datetime(df[event_col], utc=True)
        at = df[(ev.notna()) & (t >= ev)].assign(_t=t).sort_values("_t").groupby("object_id").head(1)
        if len(at):
            self.onset_bt = float(at["cold_bt"].median())
        return self

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        bt = rows["cold_bt_kf"].values
        rate = rows["cooling_rate_kf"].values
        eta = np.where(bt <= self.onset_bt, 0.0,
                       np.where(rate < self.min_cooling, (self.onset_bt - bt) / rate * 10.0, np.nan))
        eta = np.where(eta > 120, np.nan, eta)
        return pd.DataFrame({
            "object_id": rows["object_id"].values,
            "p30": np.where(eta <= 30, 1.0, 0.0), "p60": np.where(eta <= 60, 1.0, 0.0),
            "eta_lo_min": np.maximum(eta - self.spread_min, 0), "eta_median_min": eta,
            "eta_hi_min": eta + self.spread_min,
        })


# =====================================================================
# B3: climatology ตามเวลาท้องถิ่น
# =====================================================================
class ClimatologyBaseline:
    def __init__(self):
        self.table: pd.Series | None = None

    def fit(self, df: pd.DataFrame, event_col: str = "t_onset", horizon_min: int = 30) -> "ClimatologyBaseline":
        t = pd.to_datetime(df["time"], utc=True)
        ev = pd.to_datetime(df[event_col], utc=True)
        y = ((ev > t) & (ev <= t + pd.Timedelta(minutes=horizon_min))).astype(float)
        hour = np.floor(df["lst_hours"]).astype(int)
        self.table = y.groupby(hour).mean()
        return self

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        hour = np.floor(rows["lst_hours"]).astype(int)
        p = hour.map(self.table).fillna(float(self.table.mean())).values
        return pd.DataFrame({"object_id": rows["object_id"].values, "p30": p, "p60": np.clip(p * 1.6, 0, 1),
                             "eta_lo_min": np.nan, "eta_median_min": np.nan, "eta_hi_min": np.nan})
