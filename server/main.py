"""
FastAPI Server for ESP32 DHT22 Sensor Logger & Tapo Smart Plug Automation.

Endpoints:
  Sensor Data:
    POST /api/readings               — Receive sensor data from ESP32
    GET  /api/readings/latest        — Get the most recent reading (JSON)
    GET  /api/readings/history       — Get recent readings (JSON)
    POST /api/readings/clear         — Clear historical sensor data

  Smart Plug Control & Automation:
    POST /api/plugs/{plug_name}/on   — Turn a smart plug ON
    POST /api/plugs/{plug_name}/off  — Turn a smart plug OFF
    GET  /api/plugs                  — Get state of all registered plugs
    GET  /api/plugs/{plug_name}      — Get state of a specific plug
    GET  /api/plugs/history          — Retrieve smart plug action history
    GET  /api/plugs/timeline         — Chronological plug events for chart overlays

  Automation & Scheduling (Tweakable via UI):
    GET  /api/automation/settings    — Get all current thresholds & schedule settings
    POST /api/automation/settings    — Update thresholds & schedule settings (persisted)
    GET  /api/automation/status      — Overview of rules and active parameters
    POST /api/automation/evaluate    — Manually evaluate environmental automation rules
    GET  /api/automation/scheduler   — Get background scheduler status and countdowns
    POST /api/automation/scheduler/sprinkler/run-now — Immediately run 5m sprinkler cycle
    POST /api/automation/scheduler/fan/run-now       — Immediately run 5m fan cycle

  Dashboard:
    GET  /                           — Browser dashboard
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from config import (
    get_device_registry,
    validate_config,
    get_automation_settings,
    update_automation_settings
)
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
    AutomationSettingsUpdate
)
from services.smart_plug_service import (
    control_plug,
    get_plug_state,
    get_all_plugs_status,
)
from automation.plug_rules import evaluate_automation_rules
from automation.scheduler import scheduler


# ─── App Lifecycle ────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and start background scheduler on startup."""
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
    auto_status = "ENABLED" if auto_cfg.get("enabled", True) else "DISABLED"
    print(f"  🤖 Automation: {auto_status} (Sliding Window: {auto_cfg.get('window_size', 30)} readings)")
    print(f"  Dashboard: http://localhost:8000")
    print("═══════════════════════════════════════════════════════")
    print()

    # Start background scheduler for periodic sprinkler, fan, and timers
    await scheduler.start()

    yield

    # Shutdown
    print("Server shutting down...")
    await scheduler.stop()
    print("Database preserved.")


app = FastAPI(
    title="ESP32 DHT22 & Tapo Smart Plug Automation",
    description="ESP32 Temperature & Humidity logger with automated TP-Link Tapo smart plug control and UI-tweakable rules",
    version="2.1.0",
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

    # Trigger automation asynchronously in the background so ESP32 is not blocked
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


# ─── Smart Plug API Endpoints ─────────────────────────────────

@app.post("/api/plugs/{plug_name}/on", response_model=PlugControlResponse)
async def turn_plug_on(plug_name: str):
    """Turn a registered smart plug ON."""
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
        reason="Manual UI / API request"
    )

    status_code = status.HTTP_200_OK if result["success"] else status.HTTP_502_BAD_GATEWAY
    return JSONResponse(status_code=status_code, content=result)


@app.post("/api/plugs/{plug_name}/off", response_model=PlugControlResponse)
async def turn_plug_off(plug_name: str):
    """Turn a registered smart plug OFF."""
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
        reason="Manual UI / API request"
    )

    status_code = status.HTTP_200_OK if result["success"] else status.HTTP_502_BAD_GATEWAY
    return JSONResponse(status_code=status_code, content=result)


@app.get("/api/plugs")
async def get_all_plugs(refresh: bool = False):
    """Get state and metadata of all registered smart plugs."""
    return await get_all_plugs_status(refresh_physical=refresh)


@app.get("/api/plugs/{plug_name}")
async def get_single_plug(plug_name: str, refresh: bool = False):
    """Get state and metadata of a specific smart plug."""
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
    """Get historical log of smart plug actions."""
    return await get_plug_history_records(plug_name=plug_name, limit=limit, hours=hours)


@app.get("/api/plugs/timeline")
async def get_plug_timeline(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    hours: Optional[float] = None
):
    """Get chronological plug events (oldest first) within a timeframe."""
    return await get_plug_timeline_events(start_time=start_time, end_time=end_time, hours=hours)


# ─── Automation & Settings API Routes ─────────────────────────

@app.get("/api/automation/settings")
async def get_settings():
    """Retrieve all current automation thresholds and schedule intervals."""
    return get_automation_settings()


@app.post("/api/automation/settings")
async def update_settings(payload: AutomationSettingsUpdate):
    """
    Update automation settings & thresholds.
    Persists to automation_settings.json and takes effect immediately.
    """
    updates = payload.model_dump(exclude_unset=True)
    updated = update_automation_settings(updates)
    return {
        "status": "ok",
        "message": "Automation settings updated and saved successfully.",
        "settings": updated
    }


@app.get("/api/automation/scheduler")
async def get_scheduler_status():
    """Get real-time status of the background scheduler and countdowns."""
    return scheduler.get_status()


@app.post("/api/automation/scheduler/sprinkler/run-now")
async def run_sprinkler_now(duration_mins: Optional[float] = None):
    """Immediately start a sprinkler cycle for duration_mins (default from settings)."""
    settings = get_automation_settings()
    duration = duration_mins or settings.get("sprinkler_schedule_duration_mins", 5.0)
    scheduler.trigger_sprinkler_cycle(
        duration_mins=duration,
        reason=f"Manual Run Now trigger ({duration:.0f}m)"
    )
    return {"status": "ok", "message": f"Sprinkler cycle started for {duration:.0f} minutes."}


@app.post("/api/automation/scheduler/fan/run-now")
async def run_fan_now(duration_mins: Optional[float] = None):
    """Immediately start a fan cycle for duration_mins (default from settings)."""
    settings = get_automation_settings()
    duration = duration_mins or settings.get("fan_schedule_duration_mins", 5.0)
    scheduler.trigger_fan_cycle(
        duration_mins=duration,
        reason=f"Manual Run Now trigger ({duration:.0f}m)",
        source="scheduled"
    )
    return {"status": "ok", "message": f"Fan cycle started for {duration:.0f} minutes."}


@app.post("/api/automation/evaluate", response_model=AutomationStatusResponse)
async def trigger_automation_evaluation():
    """Manually trigger an automation rules evaluation tick."""
    return await evaluate_automation_rules()


@app.get("/api/automation/status")
async def get_automation_status():
    """Get current automation status and detailed rules descriptions."""
    settings = get_automation_settings()
    return {
        "status": "active" if settings.get("enabled", True) else "disabled",
        "settings": settings,
        "rules_description": {
            "humidifier": f"ON when humidity < {settings.get('humidifier_humid_low', 93)}%; OFF when humidity > {settings.get('humidifier_humid_high', 96)}%",
            "ac": f"ON when temp > {settings.get('ac_temp_high', 26)}°C; OFF when temp < {settings.get('ac_temp_low', 23)}°C",
            "heater": f"ON when temp < {settings.get('heater_temp_low', 22)}°C; stays ON until temp >= {settings.get('heater_temp_high', 26)}°C",
            "fan_humidity": f"ON for {settings.get('fan_humidity_trigger_duration_mins', 3)} mins when humidity > {settings.get('fan_humid_trigger_threshold', 96)}%",
            "fan_schedule": f"Scheduled ON for {settings.get('fan_schedule_duration_mins', 5)} mins every {settings.get('fan_schedule_interval_hours', 4)} hours",
            "sprinkler_schedule": f"Scheduled ON for {settings.get('sprinkler_schedule_duration_mins', 5)} mins every {settings.get('sprinkler_schedule_interval_hours', 2)} hours"
        }
    }


# ─── Dashboard Route ──────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the browser dashboard."""
    return templates.TemplateResponse(request=request, name="dashboard.html")
