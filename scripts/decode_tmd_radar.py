"""
ถอดภาพเรดาร์ TMD พิษณุโลก (PPI รัศมี 240 km, JPEG ทุก 15 นาที) → dBZ บนกริดดาวเทียมไทย 0.02° ของ data/Thai
ใช้ตรวจผล / ปรับเทียบเท่านั้น (ไม่ใช่ข้อมูลเข้าตอนรันจริง)

    python scripts/decode_tmd_radar.py --jpg-dir data/Thai/ground/radar_phs/raw_jpeg/20261005 \
        --palette data/Thai/ground/radar_phs/raw_jpeg/PHS_palette.json --out runs/radar_decoded
    → radar_<วัน>.npz: dbz[t, y, x] (NaN = นอกพื้นที่วัด, 0 = วัดได้แต่ไม่มีฝน), time_vals, lat, lon, valid

วิธี: สีแต่ละพิกเซล → แถบสีที่ใกล้ที่สุดใน palette ถ้าห่าง ≤ 20 (RGB); เรขาคณิต azimuthal equidistant รอบสถานี
(16.7765°N 100.2161°E, จุดศูนย์กลางภาพ 436.01, 391.29 px, 0.66011 km/px); ตัดพิกเซลที่มีสีใน > 60 % ของทุกภาพ
(วงระยะ / ตัวอักษร / clutter) และระยะ < 10 km หรือ > 230 km
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

CX, CY, KPX = 436.01, 391.29, 0.66011
LAT0, LON0 = 16.7765, 100.2161
PLOT = (75, 0, 800, 757)                 # กรอบพื้นที่แผนที่ในภาพ (x0, y0, x1, y1)
TOL, STATIC = 20.0, 0.60
LAT, LON, RES = (14.4, 19.2), (97.6, 102.8), 0.02


def grid_pixels():
    """กริดดาวเทียมไทย → พิกัดพิกเซลในภาพเรดาร์ + พื้นที่ที่ใช้ได้"""
    ny, nx = int(round((LAT[1] - LAT[0]) / RES)), int(round((LON[1] - LON[0]) / RES))
    lat = LAT[1] - RES * (np.arange(ny) + 0.5)                          # แถว 0 = เหนือสุด
    lon = LON[0] + RES * (np.arange(nx) + 0.5)
    la, lo = np.meshgrid(np.radians(lat), np.radians(lon), indexing="ij")
    p0, l0 = np.radians(LAT0), np.radians(LON0)
    c = np.arccos(np.clip(np.sin(p0) * np.sin(la) + np.cos(p0) * np.cos(la) * np.cos(lo - l0), -1, 1))
    k = np.where(c > 0, c / np.sin(np.maximum(c, 1e-12)), 1.0)
    E = 6371.0088 * k * np.cos(la) * np.sin(lo - l0)
    N = 6371.0088 * k * (np.cos(p0) * np.sin(la) - np.sin(p0) * np.cos(la) * np.cos(lo - l0))
    x, y = np.rint(CX + E / KPX).astype(int), np.rint(CY - N / KPX).astype(int)
    rng = np.hypot(E, N)
    ok = (rng >= 10) & (rng <= 230) & (x >= PLOT[0]) & (x < PLOT[2]) & (y >= PLOT[1]) & (y < PLOT[3])
    return lat, lon, np.clip(x, 0, 799), np.clip(y, 0, 799), ok


def decode(path, rgb, dbz, yy, xx):
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), np.float32)[yy, xx]
    d2 = ((a[:, :, None, :] - rgb[None, None]) ** 2).sum(-1)
    return np.where(np.sqrt(d2.min(-1)) <= TOL, dbz[d2.argmin(-1)], np.nan).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jpg-dir", required=True)
    ap.add_argument("--palette", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    p = json.loads(Path(args.palette).read_text())
    rgb, dbz = np.array(p["rgb"], np.float32), np.array(p["dbz"], np.float32)
    lat, lon, x, y, ok = grid_pixels()
    files = sorted(Path(args.jpg_dir).glob("PHS_*Z.jpg"))
    imgs, times = [], []
    for f in files:
        imgs.append(decode(f, rgb, dbz, y, x))
        s = f.stem.split("_")                                              # PHS_YYYYMMDD_HHMMZ
        times.append(np.datetime64(f"{s[1][:4]}-{s[1][4:6]}-{s[1][6:]}T{s[2][:2]}:{s[2][2:4]}"))
    A = np.stack(imgs)
    valid = ok & ~(np.isfinite(A).mean(0) > STATIC)
    A = np.where(valid[None], np.nan_to_num(A, nan=0.0), np.nan).astype(np.float32)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    day = str(times[0])[:10].replace("-", "")
    np.savez_compressed(out / f"radar_{day}.npz", dbz=A, time_vals=np.array(times), lat=lat.astype(np.float32),
                        lon=lon.astype(np.float32), valid=valid)
    print(f"{len(files)} ภาพ → {out / f'radar_{day}.npz'} (พื้นที่วัดได้ {int(valid.sum())} ช่อง)")


if __name__ == "__main__":
    main()
