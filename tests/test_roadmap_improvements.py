"""
Unit tests สำหรับการปรับปรุงตาม Roadmap (Phases 1-3):
1. Optical-flow Back-Sampling และ Split Inheritance (track.py)
2. Adaptive Kalman Gain สำหรับ Explosive Convection (track.py)
3. New Physics / Morphology Features (features.py)
4. Flat GeoJSON Properties & Daily CSV Export (output.py)
5. Constrained Threshold Optimization with POD & FOR (evaluate.py)
6. Conditional Expected ETA & Interaction Features (models/hazard.py)
7. Physical Evidence Check for Lifecycle State Transitions (intensity.py)
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from convrain.config import load_config
from convrain.detect import DetectedObject, Detections
from convrain.evaluate import best_threshold, object_scores
from convrain.features import MODEL_FEATURES, compute_features
from convrain.intensity import update_status
from convrain.models.hazard import HazardModel
from convrain.motion import MotionField
from convrain.output import object_record, to_feature_collection, write_scan_outputs
from convrain.track import KalmanCV, Track, Tracker


def test_kalman_cv_init_rate_and_adaptive_q():
    # 1. ทดสอบการเริ่มต้นด้วย init_rate
    kf = KalmanCV(x0=240.0, q=1.0, r=1.0, init_rate=-5.0)
    assert kf.value == 240.0
    assert kf.rate == -5.0

    # 2. ทดสอบ Adaptive Gain เมื่อเกิดการเปลี่ยนแปลงรวดเร็วจัด (diff > 5.0 K)
    # อุณหภูมิลดลงฮวบจาก 240 เป็น 200 K (ลดลง 40 K ใน 1 scan)
    kf.update(200.0, dt=1.0)
    # ตัวกรองต้องตอบสนองรวดเร็ว ปรับอัตราการเย็นตัวให้ติดลบหนักทันที
    assert kf.rate < -15.0
    assert kf.value < 225.0


def test_optical_flow_back_sampling_and_split_inheritance():
    cfg = load_config()
    tracker = Tracker(cfg)
    t0 = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=10)

    ny, nx = 50, 50
    # จำลอง prev_ir ที่มีอุณหภูมิ 270 K ทั่วไป แต่จุดที่เมฆลอยมาเคยเป็น 265 K
    prev_ir = np.full((ny, nx), 270.0, dtype=np.float32)
    prev_ir[10:20, 10:20] = 265.0

    # Motion field: ลอยมาทางขวา 5 px, ลงล่าง 5 px
    motion = MotionField(
        u_px=np.full((ny, nx), 5.0, dtype=np.float32),
        v_px=np.full((ny, nx), 5.0, dtype=np.float32),
        dt_min=10.0,
        pixel_km=2.0,
    )

    # เมฆเกิดใหม่ที่ตำแหน่ง (15:25, 15:25) ที่มี cold_mean_bt = 235 K (เย็นตัวลง 30 K)
    rr, cc = np.meshgrid(np.arange(15, 25), np.arange(15, 25), indexing="ij")
    obj_new = DetectedObject(
        label=1, rows=rr.ravel(), cols=cc.ravel(), area_px=100, area_km2=400.0,
        centroid_rc=(20.0, 20.0), lat=13.0, lon=100.0, min_bt=230.0,
        cold_mean_bt=235.0, mean_bt=245.0, core_level_k=235.0
    )
    labels = np.zeros((ny, nx), dtype=np.int32)
    labels[obj_new.rows, obj_new.cols] = 1
    det = Detections(labels=labels, objects=[obj_new])

    # อัปเดต tracker ด้วย prev_ir
    upd = tracker.update(det, motion=motion, time=t1, dt_min=10.0, prev_ir=prev_ir)
    assert len(upd.births) == 1
    tr = upd.births[0]

    # init_cooling_rate ต้องไม่เป็น 0.0 (ต้องคำนวณย้อนหลังได้ 235 - 265 = -30 K)
    assert tr.kf_bt.rate < -10.0


def test_new_physics_features_and_model_features():
    for f in ["has_parent", "n_scans", "is_day", "refl_b03_cold", "bt_std", "core_contrast", "edge_gradient_k", "solidity", "accel_cold_bt"]:
        assert f in MODEL_FEATURES


def test_best_threshold_constrained_optimization():
    # สร้างข้อมูล validation สุ่ม
    t0 = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(100):
        has_rain = (i < 40)
        p = 0.7 if (i < 30) else (0.4 if i < 40 else 0.15)
        rows.append({
            "object_id": f"obj_{i}",
            "time": t0,
            "t_onset": t0 + timedelta(minutes=20) if has_rain else pd.NaT,
            "p30": p,
            "eta_median_min": 20.0 if p >= 0.3 else np.nan
        })
    df = pd.DataFrame(rows)

    # ทดสอบ object_scores มี FOR
    scores = object_scores(df, "p30", 30.0, 0.3)
    assert "FOR" in scores
    assert np.isfinite(scores["FOR"])

    # ทดสอบ best_threshold ภายใต้ constraint
    thr, csi = best_threshold(df, "p30", 30.0, min_pod=0.50, max_for=0.15)
    assert 0.1 <= thr <= 0.9
    assert csi > 0.0


def test_flat_geojson_and_daily_csv(tmp_path):
    t0 = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    kf = KalmanCV(x0=230.0, q=1.0, r=1.0)
    kf_area = KalmanCV(x0=5.0, q=0.02, r=0.05)
    tr = Track(
        track_id="test_tr_01", birth_time=t0, last_time=t0,
        obj=DetectedObject(1, np.array([10]), np.array([10]), 1, 4.0, (10, 10), 13.0, 100.0, 220.0, 222.0, 230.0, 235.0),
        kf_bt=kf, kf_area=kf_area
    )
    feats = {"min_bt": 220.0, "cooling_rate_kf": -3.5, "speed_ms": 12.0, "direction_deg": 180.0, "lat": 13.0, "lon": 100.0, "area_km2": 40.0, "core_level_k": 235.0}
    px = {"lat": 13.05, "lon": 100.05, "cth_km": 12.5, "shift_km": 5.2}
    onset = {"p30": 0.65, "p60": 0.85, "eta_median": t0 + timedelta(minutes=20), "eta_lo": t0 + timedelta(minutes=15), "eta_hi": t0 + timedelta(minutes=25)}

    rec = object_record(tr, feats, px, onset, intensity=None, footprint_ref=None, parallax_on=True)
    doc = {"scan_time": t0.isoformat(), "model_version": "v2", "objects": [rec]}

    fc = to_feature_collection(doc)
    props = fc["features"][0]["properties"]
    # Flat properties ต้องมี alias สรุปค่า
    assert props["min_bt"] == 220.0
    assert props["cooling_rate"] == -3.5
    assert props["p30"] == 0.65
    assert props["parallax_shift_km"] == 5.2
    assert props["area_km2"] == 40.0

    # ทดสอบเขียน output และ Daily CSV
    ts_df = pd.DataFrame([{"time": t0, "object_id": "test_tr_01", "p30": 0.65}])
    paths = write_scan_outputs(tmp_path, doc, footprints={}, timeseries=ts_df, write_json=True)
    assert "footprints" in paths
    assert paths["footprints"].exists()
    assert "timeseries_csv" in paths
    assert paths["timeseries_csv"].exists()


def test_hazard_model_conditional_expected_eta():
    t0 = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    # จำลอง training rows
    rows = []
    for i in range(120):
        onset_m = 10 if i < 30 else (25 if i < 60 else None)
        rows.append({
            "object_id": f"tr_{i}",
            "time": t0,
            "t_onset": t0 + timedelta(minutes=onset_m) if onset_m else pd.NaT,
            "min_bt": 220.0 if i < 60 else 270.0,
            "cold_bt": 225.0 if i < 60 else 272.0,
            "mean_bt": 235.0 if i < 60 else 275.0,
            "below_0c": 1.0 if i < 60 else 0.0,
            "min_since_below_0c": 10.0 if i < 60 else 0.0,
            "cold_bt_kf": 225.0 if i < 60 else 272.0,
            "cooling_rate_kf": -6.0 if i < 30 else (-1.0 if i < 60 else 0.5),
            "cooling_rate_std": 0.5,
            "d_cold_bt_10": -5.0 if i < 30 else -1.0,
            "d_cold_bt_20": -10.0 if i < 30 else -2.0,
            "d_cold_bt_30": -15.0 if i < 30 else -3.0,
            "log_area": 4.0,
            "area_growth_kf": 0.1,
            "d_log_area_30": 0.3,
            "btd_wv_cold": 2.0,
            "btd_wv_max": 3.0,
            "btd_73_cold": -5.0,
            "btd_co2_cold": -15.0,
            "d_btd_wv_10": 1.0,
            "d_btd_wv_30": 2.0,
            "d_btd_co2_30": 1.0,
            "d_btd_73_10": 1.0,
            "d_btd_73_30": 2.0,
            "ttd_cold": 1.0,
            "ttd_max": 2.0,
            "d_ttd_10": 0.5,
            "d_ttd_30": 1.0,
            "btd_sw_cold": 0.5,
            "d_btd_sw_10": 0.1,
            "d_btd_sw_30": 0.2,
            "age_min": 20.0,
            "n_scans": 2,
            "has_parent": 0.0,
            "lst_sin": 0.5,
            "lst_cos": 0.5,
            "is_day": 1.0,
            "refl_b03_cold": 0.8,
            "land_frac": 1.0,
            "elev_mean": 50.0,
            "sat_zenith": 35.0,
            "min_cold_bt_track": 220.0,
            "bt_std": 5.0,
            "core_contrast": 10.0,
            "edge_gradient_k": 12.0,
            "solidity": 0.85,
            "accel_cold_bt": -1.0,
        })
    df_train = pd.DataFrame(rows)
    model = HazardModel(estimator="logistic")
    model.fit(df_train, event_col="t_onset")

    # ทดสอบ interaction features และ conditional expected ETA
    test_rows = df_train.iloc[:5].copy()
    pred = model.predict(test_rows)
    assert "p30" in pred
    assert "eta_median_min" in pred
    # สำหรับเมฆที่เย็นเร็วจัด (-6 K/10min), ETA คาดหมายควรอยู่ในช่วงสั้น < 20 นาที
    fast_eta = pred["eta_median_min"].iloc[0]
    assert np.isfinite(fast_eta)
    assert fast_eta < 20.0


def test_intensity_update_status_physical_guard():
    cfg = load_config()
    t0 = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    kf = KalmanCV(x0=260.0, q=1.0, r=1.0)
    kf_area = KalmanCV(x0=5.0, q=0.02, r=0.05)
    tr = Track(
        track_id="tr_decay", birth_time=t0, last_time=t0,
        obj=DetectedObject(1, np.array([10]), np.array([10]), 1, 4.0, (10, 10), 13.0, 100.0, 260.0, 262.0, 265.0, 273.0),
        kf_bt=kf, kf_area=kf_area
    )
    tr.status = "developing"

    # เมฆที่สลายตัวแล้ว (cold_bt = 265 K อุ่นเกินเกณฑ์ 245 K, rate = +1.5 K/10min)
    # ถึงเวลา onset_eta แล้วแต่ไม่มีหลักฐานทางกายภาพ
    feats = {"cold_bt": 265.0, "cooling_rate_kf": 1.5}
    rain = {"rain_rate_max_mmh": 0.0}
    status = update_status(tr, feats, rain, t0 + timedelta(minutes=30), cfg, onset_eta=t0 + timedelta(minutes=20))
    # ต้องไม่เปลี่ยนเป็น raining
    assert status == "developing"
