"""
FastAPI Server for ESP32 DHT22 Sensor Logger & Tapo Smart Plug Automation.

Endpoints:
  Sensor Data:
    POST /api/readings               — Receive sensor data from ESP32
    GET  /api/readings/latest        — Get the most recent reading (JSON)
    GET  /api/readings/history       — Get recent readings (JSON)
    POST /api/readings/clear         — Clear historical sensor data

  Smart Plug Control & Automation (Phase 2):
    POST /api/plugs/{plug_name}/on   — Turn a smart plug ON
    POST /api/plugs/{plug_name}/off  — Turn a smart plug OFF
    GET  /api/plugs                  — Get state of all registered plugs
    GET  /api/plugs/{plug_name}      — Get state of a specific plug
    GET  /api/plugs/history          — Retrieve smart plug action history
    GET  /api/plugs/timeline         — Chronological plug events for chart overlays
    POST /api/automation/evaluate    — Manually evaluate automation rules
    GET  /api/automation/status      — Get current automation settings and status

  Dashboard:
    GET  /                           — Browser dashboard
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, List

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import get_device_registry, validate_config, get_automation_settings
from database import (
    init_db,
    insert_reading,
    get_latest_reading,
    get_recent_readings,
    get_reading_count,
    get_readings_by_range,
    delete_readings,
    get_plug_history_records,
    get_plug_timeline_events,
)
from models import (
    SensorReading,
    SensorReadingResponse,
    LatestReadingResponse,
    ClearHistoryRequest,
    ClearHistoryResponse,
    PlugControlResponse,
    PlugStateInfo,
    AutomationStatusResponse,
)
from services.smart_plug_service import (
    control_plug,
    get_plug_state,
    get_all_plugs_status,
)
from automation.plug_rules import evaluate_automation_rules


# ─── App Lifecycle ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the database and validate environment on startup."""
    print()
    print("═══════════════════════════════════════════════════════")
    print("  ESP32 DHT22 Logger & Tapo Smart Plug Automation Server")
    print("═══════════════════════════════════════════════════════")
    await init_db()
    count = await get_reading_count()
    print(f"  Existing sensor readings in database: {count}")

    # Validate Smart Plug Configuration
    issues = validate_config()
    registry = get_device_registry()
    print(f"  Registered Smart Plugs ({len(registry)}):")
    for name, dev in registry.items():
        status_ip = dev.ip if dev.is_configured else "IP NOT SET"
        print(f"    - {dev.icon} {dev.display_name} ({name}): {status_ip}")

    if issues:
        print("  ⚠️  Configuration Warnings:")
        for issue in issues:
            print(f"    • {issue}")
    else:
        print("  ✅ All smart plug credentials and IP addresses configured.")

    auto_cfg = get_automation_settings()
    auto_status = "ENABLED" if auto_cfg["enabled"] else "DISABLED"
    print(f"  🤖 Automation: {auto_status} (Sliding Window: {auto_cfg['window_size']} readings)")
    print(f"  Dashboard: http://localhost:8000")
    print("═══════════════════════════════════════════════════════")
    print()

    yield
    print("Server shutting down. Database preserved.")


app = FastAPI(
    title="ESP32 DHT22 & Tapo Smart Plug Automation",
    description="ESP32 Temperature & Humidity logger with automated TP-Link Tapo smart plug control",
    version="2.0.0",
    lifespan=lifespan
)

# ─── Templates ────────────────────────────────────────────────
templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=templates_dir)


# ─── Sensor Readings API Routes ───────────────────────────────

@app.post("/api/readings", response_model=SensorReadingResponse)
async def receive_reading(reading: SensorReading):
    """
    Receive a sensor reading from the ESP32.
    Saves to SQLite database and triggers non-blocking automation evaluation.
    """
    row_id = await insert_reading(reading.temperature, reading.humidity)
    latest = await get_latest_reading()

    # Trigger automation asynchronously in the background so the ESP32 is not blocked
    asyncio.create_task(evaluate_automation_rules())

    return SensorReadingResponse(
        id=row_id,
        temperature=reading.temperature,
        humidity=reading.humidity,
        timestamp=latest["timestamp"] if latest else "",
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
    """Get readings for the dashboard chart and table."""
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
    """Clear historical sensor readings."""
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


# ─── Smart Plug API Endpoints (Phase 2) ───────────────────────

@app.post("/api/plugs/{plug_name}/on", response_model=PlugControlResponse)
async def turn_plug_on(plug_name: str):
    """
    Turn a registered smart plug ON.
    Validates plug name, issues kasa command via TPAP, and logs action to database.
    """
    registry = get_device_registry()
    name_clean = plug_name.lower().strip()
    if name_clean not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Smart plug '{plug_name}' not found. Registered devices: {list(registry.keys())}"
        )

    result = await control_plug(
        plug_name=name_clean,
        action="ON",
        trigger_source="manual",
        reason="Manual API request"
    )

    status_code = status.HTTP_200_OK if result["success"] else status.HTTP_502_BAD_GATEWAY
    return JSONResponse(status_code=status_code, content=result)


@app.post("/api/plugs/{plug_name}/off", response_model=PlugControlResponse)
async def turn_plug_off(plug_name: str):
    """
    Turn a registered smart plug OFF.
    Validates plug name, issues kasa command via TPAP, and logs action to database.
    """
    registry = get_device_registry()
    name_clean = plug_name.lower().strip()
    if name_clean not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Smart plug '{plug_name}' not found. Registered devices: {list(registry.keys())}"
        )

    result = await control_plug(
        plug_name=name_clean,
        action="OFF",
        trigger_source="manual",
        reason="Manual API request"
    )

    status_code = status.HTTP_200_OK if result["success"] else status.HTTP_502_BAD_GATEWAY
    return JSONResponse(status_code=status_code, content=result)


@app.get("/api/plugs")
async def get_all_plugs(refresh: bool = False):
    """
    Get the state and metadata of all registered smart plugs.
    Pass ?refresh=true to actively query physical hardware via kasa CLI.
    """
    return await get_all_plugs_status(refresh_physical=refresh)


@app.get("/api/plugs/{plug_name}")
async def get_single_plug(plug_name: str, refresh: bool = False):
    """
    Get the state and metadata of a specific smart plug.
    Pass ?refresh=true to actively query physical hardware via kasa CLI.
    """
    registry = get_device_registry()
    name_clean = plug_name.lower().strip()
    if name_clean not in registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Smart plug '{plug_name}' not found. Registered devices: {list(registry.keys())}"
        )

    return await get_plug_state(name_clean, refresh_physical=refresh)


@app.get("/api/plugs/history/events")
@app.get("/api/plugs/history")
async def get_plug_history(
    plug_name: Optional[str] = None,
    limit: int = 50,
    hours: Optional[float] = None
):
    """Get historical log of attempted smart plug actions."""
    return await get_plug_history_records(plug_name=plug_name, limit=limit, hours=hours)


@app.get("/api/plugs/timeline")
async def get_plug_timeline(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    hours: Optional[float] = None
):
    """
    Get chronological plug events (oldest first) within a timeframe.
    Used for overlaying trigger markers on the dashboard temperature/humidity chart.
    """
    return await get_plug_timeline_events(start_time=start_time, end_time=end_time, hours=hours)


# ─── Automation API Routes ────────────────────────────────────

@app.post("/api/automation/evaluate", response_model=AutomationStatusResponse)
async def trigger_automation_evaluation():
    """Manually trigger an automation rules evaluation tick."""
    return await evaluate_automation_rules()


@app.get("/api/automation/status")
async def get_automation_status():
    """Get current automation thresholds, sliding window size, and operational settings."""
    settings = get_automation_settings()
    return {
        "status": "active" if settings["enabled"] else "disabled",
        "settings": settings,
        "rules_description": {
            "sprinkler": f"ON when humidity < {settings['sprinkler_humid_low']}% & temp >= {settings['sprinkler_min_temp']}°C; OFF when humidity >= {settings['sprinkler_humid_high']}% or temp < {settings['sprinkler_min_temp']}°C",
            "ac": f"ON when temp > {settings['ac_temp_high']}°C; OFF when temp < {settings['ac_temp_low']}°C",
            "heater": f"ON when temp < {settings['heater_temp_low']}°C; OFF when temp > {settings['heater_temp_high']}°C"
        }
    }


# ─── Dashboard Route ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the browser dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html")
