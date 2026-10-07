"""หัวข้อ 10: label ต่อ track จากเรดาร์ (ใช้ตรวจผล / ปรับ LUT เท่านั้น ไม่ใช่ข้อมูลเข้าตอนรันจริง)"""
from datetime import datetime, timedelta, timezone

import pandas as pd

from convrain.labels import build_track_labels

T0 = datetime(2026, 6, 1, 6, 0, tzinfo=timezone.utc)


def test_track_labels(cfg):
    times = [T0 + timedelta(minutes=10 * k) for k in range(8)]
    dbz = [15, 22, 30, 38, 48, 44, 18, 12]
    ts = pd.DataFrame({
        "object_id": "x", "time": times, "radar_max_dbz": dbz, "radar_coverage": 1.0,
        "radar_onset_time": [t if d >= 35 else pd.NaT for t, d in zip(times, dbz)],
    })
    lab = build_track_labels(ts, None, cfg).iloc[0]
    assert lab.t_onset == pd.Timestamp(times[3])
    assert lab.t_peak == pd.Timestamp(times[4])
    assert lab.t_stop == pd.Timestamp(times[6])      # < 20 dBZ สอง scan ติดกัน
    assert not lab.onset_at_birth
