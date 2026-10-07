# convrain

โค้ดของระบบตรวจจับและพยากรณ์เวลาฝนเริ่ม / หนักสุด / หยุด ของฝน convective จากดาวเทียม Himawari อย่างเดียว
เขียนตามเอกสาร **Satellite-only Convective Rain Onset Workflow** (ขั้น 0–6 = หัวข้อ 3–9, แผนพัฒนา = หัวข้อ 13–18)
ส่วนทำนายเวลา (ขั้น 5) อยู่ที่ `convrain/scope/` — วิธีทำงานและสมการอยู่ใน `convrain/scope/README.md`

> **สถานะ:** โค้ดทุกส่วนทดสอบกับข้อมูลจำลอง (unit test + demo ตั้งแต่ต้นจนจบ) และรันกับภาพ Himawari จริงเหนือไทยได้
> ค่า threshold ใน `config/default.yaml` ตั้งเป็นค่าของไทย (เขตร้อน) แล้ว

---

## 1. โครงสร้าง

```
convrain/
├── config/default.yaml        ค่าตั้งค่าทุกขั้น ตั้งเป็นค่าของไทย (แต่ละการทดลองเขียนไฟล์ทับเฉพาะค่าที่ต่าง)
├── config/japan.yaml          ทับค่าสำหรับญี่ปุ่น (โดเมน, เกณฑ์อุณหภูมิ +10 K, ภาพพื้นที่ญี่ปุ่น)
├── config/thailand_phs.yaml   โดเมนรอบเรดาร์พิษณุโลก (ข้อมูลตัวอย่าง)
├── data/                      ข้อมูลตัวอย่างจริงของไทยและญี่ปุ่น (ดูข้อ 3.1)
├── convrain/
│   ├── ingest.py              ขั้น 0  อ่าน AHI, crop, BT/BTD, geometry, QC        (หัวข้อ 3)
│   ├── detect.py              ขั้น 1  multi-threshold + watershed                (หัวข้อ 4)
│   ├── motion.py              ขั้น 2  DIS optical flow (motion field เดียว)      (หัวข้อ 5)
│   ├── track.py               ขั้น 3  online tracking + Kalman filter            (หัวข้อ 6)
│   ├── features.py            ขั้น 4  interest fields + แนวโน้ม Lagrangian         (หัวข้อ 7)
│   ├── scope/                 ขั้น 5  เวลาฝนเริ่ม / หนักสุด / หยุด รายวัตถุและรายจุด
│   ├── intensity.py           ขั้น 6  rain rate LUT + สถานะ lifecycle            (หัวข้อ 9.1–9.3)
│   ├── parallax.py            ขั้น 6  parallax correction                        (หัวข้อ 9.4)
│   ├── output.py                      JSON / GeoJSON / Parquet / CSV รายจุด + validation (หัวข้อ 9.5)
│   ├── labels.py                      label จากเรดาร์ (ตรวจผลรายวัตถุ)             (หัวข้อ 10)
│   ├── evaluate.py                    POD/FAR/CSI, timing, Brier, bootstrap        (หัวข้อ 10.4)
│   ├── experiment.py                  replay, LUT, แบ่งข้อมูลตามวัน                (หัวข้อ 15–17)
│   ├── pipeline.py                    รวมขั้น 0–6 เป็น step() ต่อ scan
│   └── synthetic.py                   ข้อมูลจำลองสำหรับทดสอบ
├── scripts/                   คำสั่งตาม Phase ของแผนพัฒนา (ดูข้อ 4)
├── web/                       เว็บไซต์ Interactive Nowcast
├── examples/                  ตัวอย่าง output จากข้อมูลจำลอง (JSON, footprints, animation track)
└── tests/                     unit test
```

ในโค้ดทุกไฟล์มีหัวข้อกำกับแบบ `# [ขั้น 3.2] ...` ตรงกับขั้นย่อยในเอกสาร

## 2. ติดตั้ง

```bash
conda env create -f environment.yml && conda activate convrain
# หรือ
python -m venv convrain_env
source convrain_env/bin/activate
pip install -r requirements.txt
```

## 3. ลองรันทันที (ข้อมูลจำลอง ไม่ต้องมีข้อมูลจริง)

```bash
python -m pytest -q tests                       # unit test
python scripts/demo_synthetic.py --out outputs/demo
```

demo ทำครบ Phase 2–7: replay วันจำลอง (พร้อมเกจเสมือนทุก 6 pixel) → rain rate LUT + ปรับเทียบส่วนทำนายเวลาด้วยเรดาร์จำลอง
→ ประเมินเวลาฝนเริ่ม / หนักสุด / หยุด บนวัน test → รันแบบ real-time และเขียน output
จากนั้นส่งออกข้อมูลจำลอง 1 วันเป็นไฟล์ (`outputs/demo/scans`, `outputs/demo/radar`) ไว้ลองสคริปต์ของข้อมูลจริงได้

**ตัวเลขความแม่นยำจากข้อมูลจำลองไม่ได้บอกความแม่นยำกับข้อมูลจริง** ข้อมูลจำลองใช้เพื่อตรวจว่าโค้ดทุกขั้นทำงานร่วมกันได้เท่านั้น

## 3.1 ข้อมูลตัวอย่างจริง (`data/`) — ไทยและญี่ปุ่น

```
data/
├── Thai/                                      โดเมนรัศมี 240 km รอบเรดาร์พิษณุโลก (config/thailand_phs.yaml)
│   ├── satellite/th_20261005.npz, th_20261006.npz      Himawari-9 IR 8 แบนด์ (B08–B16) ทุก 10 นาที 03:00–16:50 UTC
│   └── ground/
│       ├── radar_phs/raw_jpeg/<วัน>/PHS_*.jpg          ภาพเรดาร์ TMD พิษณุโลก ทุก 15 นาที (+ PHS_palette.json)
│       ├── radar_phs/decoded/radar_<วัน>.npz           ภาพเดียวกันที่ถอดเป็น dBZ บนกริดดาวเทียมแล้ว
│       └── gauges_thaiwater/gauges_hourly_20261005_06.csv   มาตรวัดฝนรายชั่วโมง (ThaiWater) ในรัศมีเรดาร์
└── Japan/                                     คันโต – คันไซ (config/japan.yaml)
    ├── satellite/jp_20230726.npz                       Himawari-9 พื้นที่ญี่ปุ่น B08, B11, B13, B15 ทุก 10 นาที 02:00–11:50 UTC
    └── ground/
        ├── amedas_10min/20230726/<สถานี>.csv, stations.csv   มาตรวัดฝน 10 นาทีของ JMA (AMeDAS) 266 สถานี
        └── radar_jma/radar_20230726.npz                เรดาร์ผสม JMA 1 km ทุก 10 นาที: lev (ดัชนีระดับ, 0 = ไม่มีข้อมูล),
                                                         level_table (มม./ชม. ของระดับ 1, 2, …), lat, lon, time_vals
```

ภาพดาวเทียมใน `satellite/` คืออุณหภูมิสว่างที่ถอดจากไฟล์ HSD ของ Himawari แล้วตัดเฉพาะโดเมน (ไม่ผ่านการประมวลผลอื่น)
รูปแบบเดียวกันทั้งสองประเทศ: `Bnn` (เวลา, y, x) K, `lat`, `lon`, `SAZ` (มุมเซนิธดาวเทียม), `time_vals` — อ่านด้วย `scripts/replay_npz.py`
ข้อมูลภาคพื้นใช้ตรวจผล / ปรับเทียบเท่านั้น ไม่ใช่ข้อมูลเข้าตอนรันจริง
ที่มา: Himawari-9 — JMA ผ่าน NOAA Open Data (AWS); เรดาร์พิษณุโลก — กรมอุตุนิยมวิทยา (TMD) ผ่านคลังภาพสาธารณะ
tmd-radar-archive; มาตรวัดฝนไทย — ThaiWater (สสน. / HII และหน่วยงานร่วม); AMeDAS และเรดาร์ — กรมอุตุนิยมวิทยาญี่ปุ่น (JMA)

```bash
# ไทย: จุดเสมือนจากเรดาร์ → replay 2 วัน → ประเมินเวลาฝนเริ่ม / หนักสุด / หยุด
python scripts/ground_to_points.py radar --npz data/Thai/ground/radar_phs/decoded/radar_20261005.npz \
    data/Thai/ground/radar_phs/decoded/radar_20261006.npz --step 4 --out runs/th_ground
python scripts/replay_npz.py --npz data/Thai/satellite/th_20261005.npz data/Thai/satellite/th_20261006.npz \
    --config config/thailand_phs.yaml --points runs/th_ground/points.csv --out runs/th --collect-timing-rows
python scripts/evaluate_timing.py --rows runs/th/timing_rows.parquet --rain runs/th_ground/rain_points.csv --builtin --out reports/th
python scripts/calibrate_timing.py --rows runs/th/timing_rows.parquet --rain runs/th_ground/rain_points.csv --out models/th

# ญี่ปุ่น: สถานี AMeDAS เป็นจุด → replay → ประเมิน (วันเดียว)
python scripts/ground_to_points.py amedas --dir data/Japan/ground/amedas_10min/20230726 \
    --stations data/Japan/ground/amedas_10min/stations.csv --out runs/jp_ground
python scripts/replay_npz.py --npz data/Japan/satellite/jp_20230726.npz --config config/japan.yaml \
    --points runs/jp_ground/points.csv --out runs/jp --collect-timing-rows
python scripts/evaluate_timing.py --rows runs/jp/timing_rows.parquet --rain runs/jp_ground/rain_points.csv --builtin --out reports/jp

# ถอดภาพเรดาร์ TMD วันอื่นจาก JPEG เอง / มาตรวัดฝนไทยเป็นจุดพยากรณ์
python scripts/decode_tmd_radar.py --jpg-dir data/Thai/ground/radar_phs/raw_jpeg/20261005 \
    --palette data/Thai/ground/radar_phs/raw_jpeg/PHS_palette.json --out runs/radar_decoded
python scripts/ground_to_points.py thaiwater --csv data/Thai/ground/gauges_thaiwater/gauges_hourly_20261005_06.csv --out runs/th_gauges
```

ไฟล์ HSD ดิบ (ตอนรันจริง) ใช้ `preprocess_ahi.py` / `run_realtime.py` กับ config เดียวกัน: ไทย `satellite.area: FLDK`,
ญี่ปุ่น `config/japan.yaml` (`satellite.area: JP01` = ภาพพื้นที่ญี่ปุ่น)

## 4. ขั้นตอนกับข้อมูลจริง (ตามแผนพัฒนา)

| Phase | คำสั่ง | ผลลัพธ์ |
|---|---|---|
| 0 | `python scripts/preprocess_ahi.py --hsd-dir RAW --out-dir data/scans` | NetCDF ที่ crop แล้ว 1 ไฟล์ต่อ scan |
| 0 | regrid เรดาร์ลง grid ดาวเทียมด้วย `convrain.labels.regrid_to_satellite` แล้วบันทึกเป็น `radar_YYYYMMDDTHHMMZ.nc` (ตัวแปร `dbz`) | ไฟล์เรดาร์ต่อ frame (ตรวจผล / LUT เท่านั้น) |
| 2–3 | `python scripts/replay.py --scans-dir data/scans --radar-dir data/radar --points gauges.csv --out runs/2025 --collect-lut --collect-timing-rows --no-json` | ตาราง object-scan + tracks + คู่ข้อมูล LUT + แถวสำหรับปรับเทียบเวลา |
| 2 | `python scripts/plot_tracks.py --scans-dir data/scans --run-dir runs/case01 --gif` | ภาพซ้อน track ไว้ตรวจด้วยตา (ต้อง replay โดยไม่ใส่ `--no-json`) |
| 5 | `python scripts/build_lut.py --pairs runs/train/lut_pairs.npz --out models/v1/rain_lut.npz` | rain rate LUT (ใช้เฉพาะวันในชุด train) |
| 5 | `python scripts/calibrate_timing.py --rows runs/train/timing_rows.parquet --rain rain_points.csv --out models/v1` | ค่าคงที่ของส่วนทำนายเวลา (`timing_params.json`) |
| 6 | `python scripts/evaluate_timing.py --rows runs/2025/timing_rows.parquet --rain rain_points.csv --out reports/v1` | เวลาฝนเริ่ม / หนักสุด / หยุด: MAE, % ภายใน ±5–30 นาที, ช่วง 50/80 % เทียบนาฬิกาตายตัว (เว้นทีละวัน) |
| 7 | `python scripts/run_realtime.py --watch-dir INCOMING --out nowcast --models-dir models/v1 --points points.csv` | output ทุก 10 นาที + `monitor.csv` + state สำหรับ restart |
| 7 | `python run_web.py --port 8000` | เว็บไซต์ Interactive Nowcast + ระบุพิกัด GPS เพื่อดูเวลาฝนตก |

ทุกสคริปต์รับ `--config my.yaml` ที่ระบุเฉพาะค่าที่ต่างจาก `config/default.yaml`
ไม่ใส่ `--models-dir` = ใช้ rain rate prior และค่าคงที่ของส่วนทำนายเวลาที่ติดมากับโค้ด
`gauges.csv` / `points.csv` = คอลัมน์ `key, lat, lon`; `rain_points.csv` = `key, time` + `rain_mm_10min` หรือ `dbz`

## 5. Output (หัวข้อ 9.5)

```
nowcast/
├── json/objects_20260925T0720Z.json          เอกสารต่อ scan ตามตัวอย่างในเอกสาร
├── geojson/objects_20260925T0720Z.geojson     FeatureCollection ของจุด (เปิดใน QGIS)
├── geojson/footprints_20260925T0720Z.geojson  polygon ของแต่ละ object (แก้ parallax แล้ว)
├── timeseries/date=2026-09-25/scan_0720.parquet   หนึ่งแถวต่อ object ต่อ scan
└── points/date=2026-09-25/points_0720.csv        เวลาฝนเริ่ม / หนักสุด / หยุด รายจุด (ถ้าตั้งจุดไว้)
```

ช่อง `onset` (P30, P60, ETA ± ช่วง) และ `intensity.peak_eta / stop_eta` ของแต่ละ object มาจากส่วนทำนายเวลา (ประเมินที่พื้นใต้ศูนย์กลางแกนเมฆ)
ทุก scan ผ่านการตรวจด้วย JSON Schema และกฎข้าม field ก่อนเขียน (`output.validate_output`)
`footprint_polygon` อ้างอิงไฟล์ footprints ของ scan เดียวกัน (`footprints_<stamp>.geojson#<object_id>`)

## 6. จุดที่โค้ดต่างจากเอกสาร หรือต้องตัดสินใจเพิ่ม

1. **ขั้น 5 ทำนายเป็นเวลา (ควอนไทล์) ไม่ใช่ความน่าจะเป็นต่อช่วงอย่างเดียว:** ได้ ETA ของฝนเริ่ม / หนักสุด / หยุด พร้อมช่วง 50 / 80 %
   และ P30 / P60 ของฝนเริ่มจากสมการเดียวกัน (รายละเอียดใน `convrain/scope/README.md`)
2. **Kalman filter ใช้ BT เฉลี่ยของ pixel ที่เย็นที่สุด 10%** แทน min BT เดี่ยว เพื่อลดผลของ noise ของ pixel เดียว
3. **Rain rate ก่อน calibrate ใช้ GOES auto-estimator** (Vicente et al. 1998) เป็น prior ซึ่ง calibrate สำหรับสหรัฐฯ ต้องแทนด้วย LUT จากข้อมูลไทย
4. **Z-R สำหรับแปลงเรดาร์เป็น rain rate** ใน LUT ใช้ค่า convective ทั่วไป (a=300, b=1.4) ควรปรับด้วย rain gauge ของไทย;
   การปรับเทียบเวลารายจุดใช้ Marshall–Palmer (30 dBZ ≈ 0.5 มม. / 10 นาที)
5. **Land mask และความสูงภูมิประเทศ** ต้องเตรียมไฟล์เอง แล้วตั้ง `ingest.static_file` ถ้าไม่ตั้ง feature เหล่านี้จะเป็น NaN
   (ส่วนทำนายเวลาไม่ใช้ค่าเหล่านี้)
6. **Stop fallback:** track ที่ยังไม่มีแกนลึก (ส่วนทำนายเวลายังไม่ออกคำทำนาย) และกำลังสลาย ใช้การอุ่นขึ้นของยอดเมฆแทน

## 7. เวลาประมวลผล

บนข้อมูลจำลอง 160×160 pixel ใช้ ~100 ms ต่อ scan บน CPU core เดียว (ดู `timings.csv`)
ภาพจริงเหนือไทย 240×260 pixel (รัศมี 240 km รอบพิษณุโลก, 8 แบนด์ IR) กับจุด ~2,200 จุด: มัธยฐาน ~0.5 วินาทีต่อ scan
(p95 ~0.7) บนโน้ตบุ๊กทั่วไป
