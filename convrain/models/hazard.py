"""
ขั้น 5: โมเดล onset แบบ discrete-time hazard  (เอกสาร หัวข้อ 8.2)

ตอบ 2 คำถามพร้อมกัน: (1) เมฆก้อนนี้จะให้ฝนหรือไม่ (2) ถ้าให้ จะเริ่มเมื่อไร

รูปแบบที่ implement: "direct multi-step hazard"
    ใช้ feature ณ เวลาพยากรณ์ t (ไม่ต้อง extrapolate feature ไปอนาคต) และเพิ่ม feature k
    h_k = P(event ในช่วง (t+(k−1)·10, t+k·10] นาที | ยังไม่เกิดถึงต้นช่วง k, feature ณ t)
    k = 1..6 ครอบคลุม 60 นาที

    S_j = Π_{i≤j} (1 − h_i)          ความน่าจะเป็นที่ยังไม่ตกถึงท้ายช่วง j
    P(onset ≤ 30) = 1 − S_3,  P(onset ≤ 60) = 1 − S_6
    เวลา onset ที่คาด = จุดที่ 1 − S ข้าม 0.5, ช่วงความไม่แน่นอน = จุดที่ข้าม 0.25 และ 0.75

คลาสเดียวกันนี้ใช้กับ peak และ stop rain ได้ (เปลี่ยนคอลัมน์ event เท่านั้น, หัวข้อ 9.2–9.3)

อ้างอิง: Singer & Willett (1993), Mecikalski et al. (2015), Ke et al. (2017, LightGBM)
"""
from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from ..features import MODEL_FEATURES


class HazardModel:
    def __init__(self, features: list[str] | None = None, horizon_steps: int = 6, step_min: int = 10,
                 estimator: str = "lightgbm", balance: bool = False, params: dict | None = None,
                 name: str = "onset", min_halfwidth_min: float = 5.0):
        self.features = list(features or MODEL_FEATURES)
        # ความกว้างขั้นต่ำของช่วง ETA (± นาที): scan ทุก 10 นาทีทำให้ความแม่นของเวลามีเพดาน ~±5 นาที
        self.min_halfwidth_min = float(min_halfwidth_min)
        self.horizon_steps = int(horizon_steps)
        self.step_min = int(step_min)
        self.estimator = estimator
        self.balance = balance
        self.params = params or {}
        self.name = name
        self.model = None
        self.calibrator: IsotonicRegression | None = None
        self.version = "untrained"

    # =================================================================
    # [ขั้น 5 / หัวข้อ 10.2] แปลงตาราง object-scan เป็นแถว hazard (1 แถวต่อ object-scan-k)
    # =================================================================
    def expand(self, df: pd.DataFrame, event_col: str, censor_col: str | None = None):
        """
        df ต้องมีคอลัมน์ time, object_id, feature ทั้งหมด, และ event_col (เวลาเกิด event หรือ NaT)
        censor_col (ทางเลือก): เวลาที่ติดตามต่อไม่ได้ เช่น track ออกนอกโดเมน/ถูก merge

        กฎ
            - แถวที่ event เกิดไปแล้ว (event ≤ time) ไม่อยู่ในความเสี่ยง → ตัดทิ้ง
            - ช่วง k ที่เริ่มหลัง event → ตัดทิ้ง (ไม่อยู่ในความเสี่ยงแล้ว)
            - ช่วง k ที่จบหลังเวลา censor (และ event ยังไม่เกิด) → ตัดทิ้ง (ไม่รู้คำตอบ)
            - y = 1 ถ้า event อยู่ในช่วง k
        """
        H, step = self.horizon_steps, pd.Timedelta(minutes=self.step_min)
        t = pd.to_datetime(df["time"], utc=True)
        ev = pd.to_datetime(df[event_col], utc=True)
        keep = ev.isna() | (ev > t)
        base = df.loc[keep].reset_index(drop=True)
        t, ev = t[keep].reset_index(drop=True), ev[keep].reset_index(drop=True)
        cen = (pd.to_datetime(base[censor_col], utc=True) if censor_col and censor_col in base
               else pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns, UTC]"))

        n = len(base)
        idx = np.repeat(np.arange(n), H)
        k = np.tile(np.arange(1, H + 1), n)
        w_start = t.values[idx] + (k - 1) * step.to_timedelta64()
        w_end = t.values[idx] + k * step.to_timedelta64()
        evv, cenv = ev.values[idx], cen.values[idx]
        has_ev, has_cen = ~pd.isna(evv), ~pd.isna(cenv)

        at_risk = ~(has_ev & (evv <= w_start))
        censored = has_cen & (cenv < w_end) & ~(has_ev & (evv <= w_end))
        y = (has_ev & (evv > w_start) & (evv <= w_end)).astype(int)
        m = at_risk & ~censored

        X = self._matrix(base.iloc[idx[m]].reset_index(drop=True), k[m])
        meta = pd.DataFrame({"object_id": base["object_id"].values[idx[m]],
                             "time": t.values[idx[m]], "k": k[m]})
        return X, y[m], meta

    def _matrix(self, rows: pd.DataFrame, k: np.ndarray) -> pd.DataFrame:
        X = rows.reindex(columns=self.features).astype(float)
        X["k"] = k.astype(float)
        return X

    # =================================================================
    # [ขั้น 5] train + calibration
    # =================================================================
    def _make_estimator(self):
        if self.estimator == "lightgbm":
            from lightgbm import LGBMClassifier

            p = dict(n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=20,
                     subsample=0.8, subsample_freq=1, colsample_bytree=0.8, verbose=-1)
            if self.balance:
                p["class_weight"] = "balanced"
            p.update(self.params)
            return LGBMClassifier(**p)
        if self.estimator == "logistic":
            # logistic regression ต้องเติมค่า NaN และ normalize ก่อน (M0 ในหัวข้อ 16)
            return make_pipeline(
                SimpleImputer(strategy="median"), StandardScaler(),
                LogisticRegression(max_iter=2000, class_weight="balanced" if self.balance else None,
                                   **self.params),
            )
        raise ValueError(f"ไม่รู้จัก estimator: {self.estimator}")

    def fit(self, df_train: pd.DataFrame, event_col: str, censor_col: str | None = None,
            df_val: pd.DataFrame | None = None, version: str | None = None) -> "HazardModel":
        """
        train บนชุด train แล้ว calibrate ความน่าจะเป็นด้วย isotonic บนชุด validation
        (จำเป็นเมื่อใช้ class weight เพราะ weight ทำให้ความน่าจะเป็นเพี้ยน, หัวข้อ 8.4)
        """
        X, y, _ = self.expand(df_train, event_col, censor_col)
        if y.sum() == 0:
            raise ValueError("ไม่มี event ในชุด train เลย ตรวจการสร้าง label อีกครั้ง")
        self.model = self._make_estimator()
        self.model.fit(X, y)
        if df_val is not None and len(df_val):
            Xv, yv, _ = self.expand(df_val, event_col, censor_col)
            if len(np.unique(yv)) == 2:
                self.calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                self.calibrator.fit(self.model.predict_proba(Xv)[:, 1], yv)
        self.version = version or f"{self.name}-hazard-{self.estimator}"
        return self

    # =================================================================
    # [ขั้น 5] พยากรณ์: hazard → CDF → P30, P60, ETA ± ช่วง
    # =================================================================
    def predict_hazard(self, rows: pd.DataFrame) -> np.ndarray:
        """คืน h ขนาด (n_object, H)"""
        if self.model is None:
            raise RuntimeError("โมเดลยังไม่ได้ train หรือโหลด")
        n, H = len(rows), self.horizon_steps
        if n == 0:
            return np.zeros((0, H))
        rep = rows.iloc[np.repeat(np.arange(n), H)].reset_index(drop=True)
        X = self._matrix(rep, np.tile(np.arange(1, H + 1), n))
        h = self.model.predict_proba(X)[:, 1]
        if self.calibrator is not None:
            h = self.calibrator.predict(h)
        return np.clip(h, 0.0, 1.0).reshape(n, H)

    def cdf(self, hazard: np.ndarray) -> np.ndarray:
        """F_j = 1 − Π (1 − h_i) ณ ท้ายช่วง j (คอลัมน์ 0 = เวลา 0 มีค่า 0)"""
        surv = np.cumprod(1.0 - hazard, axis=1)
        return np.hstack([np.zeros((hazard.shape[0], 1)), 1.0 - surv])

    def quantile_minutes(self, F: np.ndarray, q: float) -> np.ndarray:
        """เวลา (นาทีจากตอนนี้) ที่ CDF ข้าม q โดย interpolate เชิงเส้นในช่วง; NaN ถ้าเกิน horizon"""
        out = np.full(F.shape[0], np.nan)
        for i, row in enumerate(F):
            j = np.argmax(row >= q)
            if row[j] < q:
                continue
            if j == 0:
                out[i] = 0.0
                continue
            f0, f1 = row[j - 1], row[j]
            frac = (q - f0) / (f1 - f0) if f1 > f0 else 1.0
            out[i] = (j - 1 + frac) * self.step_min
        return out

    def predict(self, rows: pd.DataFrame, quantiles=(0.25, 0.5, 0.75)) -> pd.DataFrame:
        """
        คืนตารางต่อ object: p30, p60, eta_lo_min, eta_median_min, eta_hi_min
        (เวลาเป็นนาทีนับจากเวลา scan)
        """
        h = self.predict_hazard(rows)
        F = self.cdf(h)
        steps30 = min(int(30 // self.step_min), self.horizon_steps)
        steps60 = min(int(60 // self.step_min), self.horizon_steps)
        q_lo, q_med, q_hi = quantiles
        med = self.quantile_minutes(F, q_med)
        hw = self.min_halfwidth_min
        lo = np.fmin(self.quantile_minutes(F, q_lo), np.maximum(med - hw, 0.0))
        hi = np.fmax(self.quantile_minutes(F, q_hi), med + hw)
        hi = np.where(np.isfinite(med), hi, np.nan)
        return pd.DataFrame({
            "object_id": rows["object_id"].values if "object_id" in rows else np.arange(len(rows)),
            "p30": F[:, steps30], "p60": F[:, steps60],
            "eta_lo_min": lo, "eta_median_min": med, "eta_hi_min": hi,
        })

    # =================================================================
    # บันทึก / โหลด
    # =================================================================
    def save(self, path: str | Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: str | Path) -> "HazardModel":
        return joblib.load(path)

    def feature_importance(self) -> pd.Series:
        """ใช้ตรวจว่าโมเดลใช้สัญญาณที่สมเหตุสมผลทางฟิสิกส์ (หัวข้อ 16, Phase 4)"""
        cols = self.features + ["k"]
        if self.estimator == "lightgbm":
            return pd.Series(self.model.feature_importances_, index=cols).sort_values(ascending=False)
        coef = self.model[-1].coef_[0]
        return pd.Series(np.abs(coef), index=cols).sort_values(ascending=False)
