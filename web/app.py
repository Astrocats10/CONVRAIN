"""
CONVRAIN Precision Satellite Convective Nowcasting Platform
FastAPI Application Server
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from web.data_loader import ConvrainDataLoader

app = FastAPI(
    title="CONVRAIN Precision Nowcast Platform",
    description="Precision Satellite Convective Nowcasting Platform (Heads-Up Display HUD)",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

loader = ConvrainDataLoader()

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "CONVRAIN Platform API is running. UI not found in static/."}


@app.get("/api/sources")
def get_source_info():
    """Information about active data directory and loaded scans."""
    return loader.get_source_info()


@app.get("/api/scans")
def list_scans():
    """List all available scans (observed 10-min scans + nowcast forecast steps)."""
    scans = loader.list_scans()
    return {"total": len(scans), "scans": scans}


@app.get("/api/scans/latest")
def get_latest_scan():
    """Get latest observed scan data."""
    return loader.get_scan(None)


@app.get("/api/scans/{stamp}")
def get_scan_by_stamp(stamp: str):
    """Get scan data for specific timestamp (or forecast step)."""
    return loader.get_scan(stamp)


@app.get("/api/telemetry")
def get_telemetry(stamp: Optional[str] = None):
    """Zone A: Telemetry indicators & SpaceX Mission Control latency breakdown."""
    return loader.get_telemetry(stamp)


@app.get("/api/nowcast/point")
def get_point_nowcast(
    lat: float = Query(..., description="Latitude"),
    lon: float = Query(..., description="Longitude"),
    stamp: Optional[str] = Query(None, description="Scan stamp"),
):
    """
    Scenario 1: Pinpoint Coordinate Prediction
    Calculates rain onset risk, ETA countdown, nearest cloud physics, and confidence.
    """
    return loader.get_point_nowcast(lat=lat, lon=lon, stamp=stamp)


@app.get("/api/objects/{track_id}/history")
def get_object_history(track_id: str):
    """Multi-scan timeseries history for Bento Grid and Micro-timeseries chart."""
    history = loader.get_object_history(track_id)
    return {
        "track_id": track_id,
        "total_scans": len(history),
        "history": history,
    }


@app.get("/api/objects/{track_id}/export")
def export_object_csv(track_id: str):
    """Export track timeseries data as downloadable CSV."""
    csv_text = loader.export_track_csv(track_id)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=track_{track_id}.csv"},
    )


@app.get("/api/closed_tracks")
def get_closed_tracks():
    """Historical Mode: closed tracks archive."""
    if loader._closed_tracks_df is not None and not loader._closed_tracks_df.empty:
        return {
            "total": len(loader._closed_tracks_df),
            "tracks": loader._closed_tracks_df.head(100).to_dict(orient="records"),
        }
    return {"total": 0, "tracks": []}


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="CONVRAIN Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8500)
    parser.add_argument("--data-dir", default=None, help="Path to CONVRAIN_OUTPUT directory")
    args = parser.parse_args()

    global loader
    if args.data_dir:
        loader = ConvrainDataLoader(args.data_dir)

    print("=" * 70)
    print("🛰️  CONVRAIN PRECISION NOWCASTING PLATFORM")
    print(f"📡 Data Source: {loader.base_dir.resolve()}")
    print(f"🌐 Server Address: http://localhost:{args.port}")
    print("=" * 70)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
