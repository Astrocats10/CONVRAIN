"""
เรขาคณิตของส่วนทำนายเวลา: parallax, ระยะในระนาบสัมผัส, วงรีจากโมเมนต์ที่สอง, พิกเซลเหนือจุดบนพื้น

parallax ใช้สูตรเดียวกับตอนปรับเทียบค่าคงที่ของโมเดลเวลา:
    H = (300 − T) / 6.7 km  (ยอดเมฆเย็นตาม lapse rate จากพื้น 300 K),  เลื่อน H·tan(SAZ) เข้าหาจุดใต้ดาวเทียม
ทุกฟังก์ชันรับพิกัดแบบ 2 มิติ (lat[y, x], lon[y, x]) ของ Scan จึงใช้ได้ทั้งกริด lat/lon ปกติและกริดดาวเทียม
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.spatial import cKDTree

T_SURFACE_K = 300.0
GAMMA_K_PER_KM = 6.7
SUBSAT_LON = 140.7
KM_PER_DEG = 6371.0 * np.pi / 180.0


def cloud_top_height_km(T):
    return np.clip((T_SURFACE_K - np.asarray(T, dtype=float)) / GAMMA_K_PER_KM, 0.0, None)


def parallax_correct(lat, lon, T, saz_deg):
    """ตำแหน่งจริงบนพื้นของยอดเมฆอุณหภูมิ T ที่ดาวเทียมเห็นที่ (lat, lon) → (lat, lon, ระยะเลื่อน km)"""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    shift = cloud_top_height_km(T) * np.tan(np.radians(saz_deg))
    phi, dlon = np.radians(lat), np.radians(SUBSAT_LON - lon)
    b = np.arctan2(np.sin(dlon), -np.sin(phi) * np.cos(dlon))          # ทิศไปจุดใต้ดาวเทียม
    return (lat + shift * np.cos(b) / KM_PER_DEG,
            lon + shift * np.sin(b) / (KM_PER_DEG * np.cos(phi)), shift)


def local_xy(lat, lon, lat0, lon0):
    """ตำแหน่ง (km) ของ (lat, lon) เทียบจุดอ้างอิง: x = ตะวันออก, y = เหนือ"""
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    return (lon - lon0) * KM_PER_DEG * np.cos(np.radians(lat0)), (lat - lat0) * KM_PER_DEG


def moments(lat_px, lon_px, lat_c, lon_c):
    """โมเมนต์ที่สอง (km²) ของกลุ่มพิกเซลรอบจุดศูนย์กลาง → (sxx, syy, sxy)"""
    x, y = local_xy(lat_px, lon_px, lat_c, lon_c)
    return float(np.mean(x * x)), float(np.mean(y * y)), float(np.mean(x * y))


def ellipse_d2(px, py, sxx, syy, sxy, cap=16.0):
    """ระยะ Mahalanobis² ของจุด (px, py km จากศูนย์กลาง) ถึงวงรีแกน; d² = 4 = ขอบวงรีสม่ำเสมอ; เสื่อม / ไกล → cap"""
    det = sxx * syy - sxy ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        d2 = (syy * px ** 2 - 2 * sxy * px * py + sxx * py ** 2) / det
    ok = np.isfinite(d2) & (det > 1e-9)
    return np.where(ok, np.minimum(d2, cap), cap)


class GroundIndex:
    """ดัชนีค้นหาพิกเซลของภาพ 1 ภาพบนพื้น (ระนาบ km รอบละติจูดกลางของโดเมน)"""

    def __init__(self, lat, lon, lat0: float | None = None):
        self.lat0 = float(np.nanmean(lat)) if lat0 is None else lat0
        self.kx = KM_PER_DEG * np.cos(np.radians(self.lat0))
        ok = np.isfinite(lat) & np.isfinite(lon)
        self.idx = np.flatnonzero(ok)
        self.tree = cKDTree(np.c_[np.asarray(lon)[ok] * self.kx, np.asarray(lat)[ok] * KM_PER_DEG])

    def xy(self, lat, lon):
        return np.c_[np.asarray(lon, dtype=float) * self.kx, np.asarray(lat, dtype=float) * KM_PER_DEG]


def corrected_index(B13, B15, lat, lon, saz, lat0: float):
    """ดัชนีของทุกพิกเซลที่ตำแหน่งหลังแก้ parallax ด้วย B13 ของตัวเอง (สร้างครั้งเดียวต่อภาพ)"""
    ok = np.isfinite(B13) & np.isfinite(saz)
    la, lo, _ = parallax_correct(lat[ok], lon[ok], B13[ok], saz[ok])
    return GroundIndex(la, lo, lat0), B13[ok], B15[ok]


def above_points(ci, pt_lat, pt_lon, match_km: float):
    """
    B13 และ B15 ของพิกเซลที่อยู่ "เหนือ" แต่ละจุดจริงๆ (ci = corrected_index ของภาพ): เลือกพิกเซลที่ตำแหน่งหลังแก้
    parallax ห่างจุด ≤ match_km; หลายพิกเซล → B13 เย็นที่สุด (เมฆสูงสุดบังเมฆต่ำ); ไม่มีเลย → NaN
    """
    g, b13, b15 = ci
    out13, out15 = np.full(len(pt_lat), np.nan), np.full(len(pt_lat), np.nan)
    for i, hits in enumerate(g.tree.query_ball_point(g.xy(pt_lat, pt_lon), r=match_km)):
        if hits:
            j = hits[int(np.argmin(b13[hits]))]
            out13[i], out15[i] = b13[j], b15[j]
    return out13, out15


def shifted_pixels(index: GroundIndex, shape, pt_lat, pt_lon, saz, top_k: float):
    """(แถว, คอลัมน์) ในภาพที่ยอดเมฆเย็น top_k ซึ่งอยู่เหนือจุดจริงจะปรากฏ (ย้อน parallax คงที่)"""
    _, nearest = index.tree.query(index.xy(pt_lat, pt_lon))
    r0, c0 = np.unravel_index(index.idx[nearest], shape)
    la_s, lo_s, _ = parallax_correct(pt_lat, pt_lon, np.full(len(pt_lat), top_k), saz[r0, c0])
    la_img = 2 * np.asarray(pt_lat, dtype=float) - la_s
    lo_img = 2 * np.asarray(pt_lon, dtype=float) - lo_s
    _, k = index.tree.query(index.xy(la_img, lo_img))
    return np.unravel_index(index.idx[k], shape)


def disc_min(img, r, c, radius_px: int):
    """ค่าต่ำสุดของภาพในจานรัศมี radius_px รอบ (r, c) ของแต่ละจุด"""
    yy, xx = np.mgrid[-radius_px:radius_px + 1, -radius_px:radius_px + 1]
    m = yy ** 2 + xx ** 2 <= radius_px ** 2
    rr = np.clip(np.asarray(r)[:, None] + yy[m][None], 0, img.shape[0] - 1)
    cc = np.clip(np.asarray(c)[:, None] + xx[m][None], 0, img.shape[1] - 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)          # จานที่ไม่มีข้อมูลเลย → NaN
        return np.nanmin(img[rr, cc], 1)
