"""
ข้อมูลภาคพื้น → จุด (points.csv: key, lat, lon) + ฝนรายจุด (rain_points.csv) สำหรับ replay --points,
calibrate_timing.py และ evaluate_timing.py  — ข้อมูลภาคพื้นใช้ตรวจ / ปรับเทียบเท่านั้น ไม่ใช่ข้อมูลเข้าตอนรันจริง

    amedas    : มาตรวัดฝน 10 นาทีของญี่ปุ่น (1 ไฟล์ต่อสถานี: t_end_jst, t_mid_utc, rain_mm_10min) + stations.csv
                → rain_points.csv (key, time = กลางช่วง UTC, rain_mm_10min)
    radar     : เรดาร์ที่ถอดแล้วบนกริดดาวเทียม (dbz[t, y, x], lat, lon, valid, time_vals) → จุดเสมือนทุก --step พิกเซล
                ในพื้นที่ที่เรดาร์วัดได้ → rain_points.csv (key, time, dbz)
    thaiwater : มาตรวัดฝนรายชั่วโมงของไทย → points.csv ของสถานีจริง + rain_hourly.csv (ตรวจคร่าวๆ รายชั่วโมงเท่านั้น
                หยาบเกินไปสำหรับนิยามฝนเริ่ม / หยุดราย 10 นาที)

รัน:
    python scripts/ground_to_points.py amedas --dir data/Japan/ground/amedas_10min/20230726 \
        --stations data/Japan/ground/amedas_10min/stations.csv --out runs/jp_ground
    python scripts/ground_to_points.py radar --npz data/Thai/ground/radar_phs/decoded/radar_20261005.npz \
        data/Thai/ground/radar_phs/decoded/radar_20261006.npz --step 4 --out runs/th_ground
    python scripts/ground_to_points.py thaiwater --csv data/Thai/ground/gauges_thaiwater/gauges_hourly_20261005_06.csv \
        --out runs/th_gauges
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def amedas(args) -> tuple[pd.DataFrame, pd.DataFrame]:
    st = pd.read_csv(args.stations)
    rows = []
    for f in sorted(Path(args.dir).glob("*.csv")):
        d = pd.read_csv(f, parse_dates=["t_mid_utc"])
        rows.append(pd.DataFrame({"key": f.stem, "time": d.t_mid_utc.dt.tz_localize("UTC"),
                                  "rain_mm_10min": d.rain_mm_10min}))
    rain = pd.concat(rows, ignore_index=True)
    return st[st.key.isin(rain.key.unique())][["key", "lat", "lon"]], rain


def radar(args) -> tuple[pd.DataFrame, pd.DataFrame]:
    pts, rows = None, []
    for path in args.npz:
        z = np.load(path)
        ii, jj = np.nonzero(z["valid"])
        keep = (ii % args.step == 0) & (jj % args.step == 0)
        ii, jj = ii[keep], jj[keep]
        keys = np.array([f"g{i}_{j}" for i, j in zip(ii, jj)])
        if pts is None:
            pts = pd.DataFrame({"key": keys, "lat": z["lat"][ii], "lon": z["lon"][jj]})
        times = pd.to_datetime(z["time_vals"]).tz_localize("UTC")
        V = z["dbz"][:, ii, jj]
        rows.append(pd.DataFrame({"key": np.tile(keys, len(times)), "time": np.repeat(times, len(keys)),
                                  "dbz": V.ravel()}))
    return pts, pd.concat(rows, ignore_index=True).dropna(subset=["dbz"])


def thaiwater(args) -> tuple[pd.DataFrame, pd.DataFrame]:
    G = pd.read_csv(args.csv)
    pts = G.drop_duplicates("code")[["code", "lat", "lon"]].rename(columns={"code": "key"})
    rain = G.rename(columns={"code": "key", "obs_utc": "time_end"})[["key", "time_end", "rain_1h"]]
    return pts, rain


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    a = sub.add_parser("amedas")
    a.add_argument("--dir", required=True)
    a.add_argument("--stations", required=True)
    r = sub.add_parser("radar")
    r.add_argument("--npz", nargs="+", required=True)
    r.add_argument("--step", type=int, default=4, help="ระยะห่างของจุดเสมือน (พิกเซล)")
    t = sub.add_parser("thaiwater")
    t.add_argument("--csv", required=True)
    for p in (a, r, t):
        p.add_argument("--out", required=True)
    args = ap.parse_args()

    pts, rain = {"amedas": amedas, "radar": radar, "thaiwater": thaiwater}[args.kind](args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pts.to_csv(out / "points.csv", index=False)
    name = "rain_hourly.csv" if args.kind == "thaiwater" else "rain_points.csv"
    rain.to_csv(out / name, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    print(f"{len(pts):,} จุด → {out / 'points.csv'};  {len(rain):,} แถว → {out / name}")


if __name__ == "__main__":
    main()
