"""
Unit tests สำหรับการเพิ่มประสิทธิภาพการตรวจจับเมฆพาความร้อน (Cloud Detection Enhancement Specification):
1. H-Minima Local Prominence Core Detection (แก้ปัญหา Anvil Masking)
2. Hybrid Thermodynamic-Dynamic Warm Cumulus Masking (จับเมฆฝนอุ่น 278-283 K)
3. Deep-Core Multi-Spectral Cirrus Protection
4. Dual-Area Threshold (min_area_px = 5, min_core_px = 3)
5. Decaying Re-intensification Onset Recovery
"""
from datetime import datetime, timezone
import numpy as np
import pytest

from conftest import blob, make_scan
from convrain.config import load_config
from convrain.detect import candidate_mask, detect_objects, _find_cores_hybrid
from convrain.pipeline import ConvRainPipeline


def test_h_minima_anvil_masking_split(cfg, t0):
    """
    ทดสอบการแยกเซลล์เกิดใหม่ (240 K) ที่อยู่ใต้ร่มเงา Anvil ของพายุลูกเก่า (215 K)
    ทั้งสองเซลล์เชื่อมต่อกันที่ระดับ 245 K
    """
    cfg["detect"]["thresholds_k"] = [278.0, 263.0, 248.0, 233.0, 218.0]
    cfg["detect"]["min_area_px"] = 5
    cfg["detect"]["min_core_px"] = 3
    cfg["detect"]["prominence_k"] = 4.0

    # พายุลูกเดิมที่ 215 K เชื่อมกับเซลล์ใหม่ที่ 240 K
    bt = np.minimum(blob((80, 80), 40, 30, 8, 215.0), blob((80, 80), 40, 48, 6, 240.0))
    scan = make_scan(bt, t0, cfg)

    det = detect_objects(scan, cfg)
    # ต้องสามารถแยกออกเป็น 2 objects อิสระจากกันได้ด้วย H-minima
    assert len(det.objects) == 2, f"Expected 2 objects from anvil splitting, got {len(det.objects)}"
    mins = sorted(o.min_bt for o in det.objects)
    assert abs(mins[0] - 215.0) < 1.0
    assert abs(mins[1] - 240.0) < 1.0


def test_warm_cumulus_cooling_detection(cfg, t0):
    """
    ทดสอบการตรวจจับเมฆฝนอุ่น / Early Cumulus ที่อุณหภูมิยอดเมฆ 280 K (+7°C)
    ซึ่งอุ่นกว่า 278 K แต่กำลังยกตัวและเย็นตัวลงอย่างรวดเร็ว (ΔBT < -3.0 K)
    """
    # ภาพปัจจุบัน: เมฆที่ 280 K
    curr_bt = blob((60, 60), 30, 30, 6, 280.0, bg=295.0)
    # ภาพก่อนหน้า: เมฆที่ 286 K (เย็นตัวลง 6.0 K ใน 10 นาที)
    prev_bt = blob((60, 60), 30, 30, 6, 286.0, bg=295.0)

    scan = make_scan(curr_bt, t0, cfg)
    mask = candidate_mask(scan, cfg, prev_ir=prev_bt)

    # พิกเซลตรงกลางต้องผ่าน candidate_mask ด้วยเงื่อนไข cooling
    assert mask[30, 30] == True, "Warm cumulus with rapid cooling should be captured in candidate mask"

    det = detect_objects(scan, cfg, prev_ir=prev_bt)
    assert len(det.objects) >= 1
    assert det.objects[0].min_bt >= 278.0


def test_cirrus_filter_deep_core_protection(cfg, t0):
    """
    ทดสอบการปกป้องแกนเมฆหนา (Deep Core: BTD_WV > -12.0)
    ไม่ให้ถูกตัวกรอง Cirrus ตัดทิ้ง แม้จะมี BTD_SW > 3.0 K
    """
    bt = blob((60, 60), 30, 30, 8, 220.0)
    scan = make_scan(bt, t0, cfg)

    # จำลองค่า BTD_SW สูง (เช่น 3.5 K) ที่มักเกิดช่วง glaciation
    scan.bt["B15"] = scan.bt["B13"] - 3.5
    # จำลองสัญญาณแกนลึก BTD_WV > -12.0
    scan.bt["B08"] = scan.bt["B13"] - 5.0

    mask = candidate_mask(scan, cfg)
    assert mask[30, 30] == True, "Deep convective core must be protected from thin cirrus filtering"


def test_dual_area_threshold(cfg, t0):
    """
    ทดสอบเกณฑ์พื้นที่ 2 ระดับ: min_area_px = 5 และ min_core_px = 3
    """
    cfg["detect"]["min_area_px"] = 5
    cfg["detect"]["min_core_px"] = 3
    bt = blob((60, 60), 30, 30, 1.5, 230.0)  # ยอดเมฆขนาดเล็ก
    scan = make_scan(bt, t0, cfg)
    det = detect_objects(scan, cfg)
    if det.objects:
        assert det.objects[0].area_px >= 5
