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
import os

from database import init_db, insert_reading, get_latest_reading, get_recent_readings, get_reading_count
from models import SensorReading, SensorReadingResponse, LatestReadingResponse


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
async def reading_history(limit: int = 100):
    """Get recent readings for the dashboard chart and table."""
    readings = await get_recent_readings(limit)
    return {"readings": readings, "count": len(readings)}


# ─── Dashboard Route ─────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the browser dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html")
