"""
FastAPI Server for ESP32 DHT22 Sensor Logger.

Endpoints:
  POST /api/readings         — Receive sensor data from ESP32
  GET  /api/readings/latest  — Get the most recent reading (JSON)
  GET  /api/readings/history — Get recent readings (JSON)
  GET  /                     — Browser dashboard

Run with:
  conda activate arduino-env
  cd G:\\ESP32_WiFi_DHT22\\server
  uvicorn main:app --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from typing import Optional
import os

from database import (
    init_db,
    insert_reading,
    get_latest_reading,
    get_recent_readings,
    get_reading_count,
    get_readings_by_range,
    delete_readings
)
from models import (
    SensorReading,
    SensorReadingResponse,
    LatestReadingResponse,
    ClearHistoryRequest,
    ClearHistoryResponse
)


# ─── App Lifecycle ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database when the server starts."""
    print()
    print("═══════════════════════════════════════════════")
    print("  ESP32 DHT22 Sensor Logger — Server Starting  ")
    print("═══════════════════════════════════════════════")
    await init_db()
    count = await get_reading_count()
    print(f"  Existing readings in database: {count}")
    print(f"  Dashboard: http://localhost:8000")
    print(f"  API endpoint: http://localhost:8000/api/readings")
    print("═══════════════════════════════════════════════")
    print()
    yield
    print("Server shutting down. Database preserved.")


app = FastAPI(
    title="ESP32 DHT22 Sensor Logger",
    description="Receives temperature & humidity from ESP32 via Wi-Fi",
    version="1.0.0",
    lifespan=lifespan
)

# ─── Templates ────────────────────────────────────────────────
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


# ─── API Routes ───────────────────────────────────────────────

@app.post("/api/readings", response_model=SensorReadingResponse)
async def receive_reading(reading: SensorReading):
    """
    Receive a sensor reading from the ESP32.
    The ESP32 sends: POST /api/readings  {"temperature": 25.3, "humidity": 48.5}
    """
    row_id = await insert_reading(reading.temperature, reading.humidity)
    latest = await get_latest_reading()
    
    print(f"  📡 Received: {reading.temperature:.2f}°C, {reading.humidity:.2f}%  [id={row_id}]")
    
    return SensorReadingResponse(
        id=row_id,
        temperature=reading.temperature,
        humidity=reading.humidity,
        timestamp=latest["timestamp"],
        status="ok"
    )


@app.get("/api/readings/latest", response_model=LatestReadingResponse)
async def latest_reading():
    """Get the most recent sensor reading."""
    latest = await get_latest_reading()
    count = await get_reading_count()
    
    if latest:
        return LatestReadingResponse(
            id=latest["id"],
            temperature=latest["temperature"],
            humidity=latest["humidity"],
            timestamp=latest["timestamp"],
            total_readings=count
        )
    return LatestReadingResponse(total_readings=0, status="no_data")


@app.get("/api/readings/history")
async def reading_history(
    limit: Optional[int] = None,
    hours: Optional[float] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    max_points: int = 1200
):
    """
    Get readings for the dashboard chart and table.
    Supports:
      - limit: e.g. limit=20 or limit=100
      - hours: e.g. hours=1, hours=24, hours=48 (2 days)
      - custom range: start_time and/or end_time (ISO format or YYYY-MM-DDTHH:MM)
      - max_points: maximum points to return for graph smoothness (default 1200)
    """
    if limit is None and hours is None and start_time is None and end_time is None:
        limit = 100

    return await get_readings_by_range(
        start_time=start_time,
        end_time=end_time,
        hours=hours,
        limit=limit,
        max_points=max_points
    )


@app.post("/api/readings/clear", response_model=ClearHistoryResponse)
@app.delete("/api/readings", response_model=ClearHistoryResponse)
async def clear_history(req: ClearHistoryRequest):
    """
    Clear historical sensor readings.
    Supports:
      - clear_all: True (wipe all readings)
      - hours: float (e.g. 1 for last 1 hour, 24 for last 24 hours)
      - start_time & end_time (delete readings within custom date range)
    """
    deleted = await delete_readings(
        clear_all=req.clear_all,
        hours=req.hours,
        start_time=req.start_time,
        end_time=req.end_time
    )
    remaining = await get_reading_count()

    if req.clear_all:
        msg = f"All sensor history cleared ({deleted} records deleted)."
    elif req.hours:
        h_str = f"{int(req.hours)} hour" if req.hours == 1 else f"{int(req.hours)} hours" if req.hours.is_integer() else f"{req.hours} hours"
        msg = f"Cleared {deleted} readings from the last {h_str}."
    else:
        msg = f"Cleared {deleted} readings within the specified date range."

    print(f"  🗑️  Clear readings: {msg} [Remaining: {remaining}]")
    return ClearHistoryResponse(
        status="ok",
        deleted_count=deleted,
        remaining_count=remaining,
        message=msg
    )


# ─── Dashboard Route ─────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the browser dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html")
