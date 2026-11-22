"""
Smart Plug Automation Rules Module.

Evaluates moving averages of the most recent 30 valid sensor readings
from the SQLite database and makes automated ON/OFF decisions for each
registered TP-Link Tapo smart plug based on temperature and humidity.

Key Features:
  - 30-reading sliding window requirement (fails safe if < 30 readings)
  - Configurable hysteresis thresholds to prevent rapid on/off flapping
  - Conflict prevention (e.g., mutual exclusion between AC and Heater)
  - Non-blocking execution with concurrency guard (evaluation lock)
  - Distinguishes manual overrides from automation decisions
  - Avoids sending redundant commands when plug is already in desired verified state
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from config import get_automation_settings, get_device_registry
from database import get_recent_readings_for_automation, get_plug_state_record
from services.smart_plug_service import control_plug

# Concurrency lock to prevent simultaneous automation evaluations
_EVALUATION_LOCK = asyncio.Lock()


def evaluate_ac_rule(
    avg_temp: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate AC (Air Conditioner) cooling rule.

    Rules:
      - Turn ON when avg_temp > ac_temp_high (e.g. > 28.0°C)
      - Turn OFF when avg_temp < ac_temp_low (e.g. < 25.0°C)
      - Between ac_temp_low and ac_temp_high: maintain current state (hysteresis)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    high = settings["ac_temp_high"]
    low = settings["ac_temp_low"]

    if avg_temp > high:
        if current_state != "ON":
            return ("ON", f"High temp ({avg_temp:.1f}°C > {high:.1f}°C threshold) - Cooling required")
        return (None, f"Temp is high ({avg_temp:.1f}°C), AC already ON")

    if avg_temp < low:
        if current_state != "OFF":
            return ("OFF", f"Temp cooled down ({avg_temp:.1f}°C < {low:.1f}°C threshold) - Cooling turned off")
        return (None, f"Temp is normal ({avg_temp:.1f}°C), AC already OFF")

    return (None, f"Temp ({avg_temp:.1f}°C) within comfortable deadband [{low:.1f}°C - {high:.1f}°C]")


def evaluate_heater_rule(
    avg_temp: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate Space Heater heating rule.

    Rules:
      - Turn ON when avg_temp < heater_temp_low (e.g. < 18.0°C)
      - Turn OFF when avg_temp > heater_temp_high (e.g. > 21.0°C)
      - Between heater_temp_low and heater_temp_high: maintain current state (hysteresis)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    low = settings["heater_temp_low"]
    high = settings["heater_temp_high"]

    if avg_temp < low:
        if current_state != "ON":
            return ("ON", f"Low temp ({avg_temp:.1f}°C < {low:.1f}°C threshold) - Heating required")
        return (None, f"Temp is low ({avg_temp:.1f}°C), Heater already ON")

    if avg_temp > high:
        if current_state != "OFF":
            return ("OFF", f"Temp warmed up ({avg_temp:.1f}°C > {high:.1f}°C threshold) - Heating turned off")
        return (None, f"Temp is normal ({avg_temp:.1f}°C), Heater already OFF")

    return (None, f"Temp ({avg_temp:.1f}°C) within comfortable deadband [{low:.1f}°C - {high:.1f}°C]")


def evaluate_sprinkler_rule(
    avg_humid: float,
    avg_temp: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate Sprinkler irrigation & humidity rule.

    Rules:
      - Turn ON when avg_humid < sprinkler_humid_low (e.g. < 45.0%)
        AND avg_temp >= sprinkler_min_temp (freeze protection e.g. >= 15.0°C)
      - Turn OFF when avg_humid >= sprinkler_humid_high (e.g. >= 65.0%)
        OR avg_temp < sprinkler_min_temp (freeze protection emergency shutoff)
      - Between humid_low and humid_high: maintain current state (hysteresis)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    low_h = settings["sprinkler_humid_low"]
    high_h = settings["sprinkler_humid_high"]
    min_t = settings["sprinkler_min_temp"]

    # Freeze protection shutoff
    if avg_temp < min_t:
        if current_state != "OFF":
            return ("OFF", f"Freeze safety lock: avg temp {avg_temp:.1f}°C < {min_t:.1f}°C - Sprinkler shut off")
        return (None, f"Sprinkler held OFF due to low temperature ({avg_temp:.1f}°C < {min_t:.1f}°C)")

    # Low humidity condition
    if avg_humid < low_h:
        if current_state != "ON":
            return ("ON", f"Low humidity ({avg_humid:.1f}% < {low_h:.1f}% threshold) - Irrigation required")
        return (None, f"Humidity is low ({avg_humid:.1f}%), Sprinkler already ON")

    # High humidity condition
    if avg_humid >= high_h:
        if current_state != "OFF":
            return ("OFF", f"Adequate humidity reached ({avg_humid:.1f}% >= {high_h:.1f}% threshold) - Irrigation turned off")
        return (None, f"Humidity is sufficient ({avg_humid:.1f}%), Sprinkler already OFF")

    return (None, f"Humidity ({avg_humid:.1f}%) within optimal band [{low_h:.1f}% - {high_h:.1f}%]")


async def evaluate_automation_rules() -> Dict[str, Any]:
    """
    Main entry point for evaluating automated plug rules.

    Process:
      1. Verify automation is globally enabled.
      2. Retrieve recent sensor readings (default 30).
      3. Validate that 30 valid readings exist; if fewer, safely abort.
      4. Compute moving averages for temperature and humidity.
      5. Evaluate rules for each registered plug.
      6. Enforce safety constraints (e.g. AC and Heater cannot both run).
      7. Issue commands asynchronously only when state changes are necessary.
      8. Persist results and return an evaluation summary.
    """
    settings = get_automation_settings()
    now_iso = datetime.now().isoformat()

    if not settings["enabled"]:
        return {
            "enabled": False,
            "window_size": settings["window_size"],
            "available_readings": 0,
            "avg_temperature": None,
            "avg_humidity": None,
            "actions_taken": [],
            "message": "Automation is globally disabled in configuration.",
            "timestamp": now_iso
        }

    # Prevent concurrent evaluations
    if _EVALUATION_LOCK.locked():
        return {
            "enabled": True,
            "window_size": settings["window_size"],
            "available_readings": 0,
            "avg_temperature": None,
            "avg_humidity": None,
            "actions_taken": [],
            "message": "Automation evaluation already in progress. Skipping duplicate tick.",
            "timestamp": now_iso
        }

    async with _EVALUATION_LOCK:
        window_size = settings["window_size"]
        raw_readings = await get_recent_readings_for_automation(limit=window_size)

        # Filter valid sensor readings
        valid_readings = [
            r for r in raw_readings
            if r.get("temperature") is not None
            and r.get("humidity") is not None
            and -40.0 <= r["temperature"] <= 80.0
            and 0.0 <= r["humidity"] <= 100.0
        ]

        valid_count = len(valid_readings)

        # Requirement: Do not trigger automation if fewer than 30 valid readings are available
        if valid_count < window_size:
            msg = (
                f"Insufficient sensor data: {valid_count}/{window_size} valid readings available. "
                f"Automation skipped for safety until {window_size} readings are accumulated."
            )
            return {
                "enabled": True,
                "window_size": window_size,
                "available_readings": valid_count,
                "avg_temperature": None,
                "avg_humidity": None,
                "actions_taken": [],
                "message": msg,
                "timestamp": now_iso
            }

        # Calculate moving averages
        avg_temp = round(sum(r["temperature"] for r in valid_readings) / valid_count, 2)
        avg_humid = round(sum(r["humidity"] for r in valid_readings) / valid_count, 2)

        registry = get_device_registry()
        actions_taken = []

        # Fetch current state of all plugs from database
        plug_states = {}
        for plug_name in registry.keys():
            record = await get_plug_state_record(plug_name)
            plug_states[plug_name] = record["current_state"] if record else "UNKNOWN"

        # ─── Evaluate AC Rule ───
        ac_action = None
        ac_reason = ""
        if "ac" in registry:
            ac_action, ac_reason = evaluate_ac_rule(
                avg_temp=avg_temp,
                current_state=plug_states.get("ac", "UNKNOWN"),
                settings=settings
            )

        # ─── Evaluate Heater Rule ───
        heater_action = None
        heater_reason = ""
        if "heater" in registry:
            heater_action, heater_reason = evaluate_heater_rule(
                avg_temp=avg_temp,
                current_state=plug_states.get("heater", "UNKNOWN"),
                settings=settings
            )

        # ─── Safety Interlock: Mutual Exclusion between AC and Heater ───
        # Never allow AC and Heater to run concurrently.
        if ac_action == "ON" and heater_action == "ON":
            # Resolving conflict by temperature priority
            if avg_temp > settings["ac_temp_high"]:
                heater_action = "OFF"
                heater_reason = "Safety interlock: AC prioritized for extreme heat"
            else:
                ac_action = "OFF"
                ac_reason = "Safety interlock: Heater prioritized for extreme cold"

        if ac_action == "ON" and plug_states.get("heater") == "ON":
            # Turn heater off first if AC turns on
            await control_plug(
                plug_name="heater",
                action="OFF",
                trigger_source="automation",
                reason="Safety interlock: Shutting off heater before starting AC",
                temperature=avg_temp,
                humidity=avg_humid,
                sensor_readings_count=valid_count
            )
            plug_states["heater"] = "OFF"

        if heater_action == "ON" and plug_states.get("ac") == "ON":
            # Turn AC off first if heater turns on
            await control_plug(
                plug_name="ac",
                action="OFF",
                trigger_source="automation",
                reason="Safety interlock: Shutting off AC before starting Heater",
                temperature=avg_temp,
                humidity=avg_humid,
                sensor_readings_count=valid_count
            )
            plug_states["ac"] = "OFF"

        # ─── Evaluate Sprinkler Rule ───
        sprinkler_action = None
        sprinkler_reason = ""
        if "sprinkler" in registry:
            sprinkler_action, sprinkler_reason = evaluate_sprinkler_rule(
                avg_humid=avg_humid,
                avg_temp=avg_temp,
                current_state=plug_states.get("sprinkler", "UNKNOWN"),
                settings=settings
            )

        # Execute decisions for each plug
        planned_actions = [
            ("ac", ac_action, ac_reason),
            ("heater", heater_action, heater_reason),
            ("sprinkler", sprinkler_action, sprinkler_reason),
        ]

        for plug_name, action, reason in planned_actions:
            if plug_name not in registry or action is None:
                continue

            current_s = plug_states.get(plug_name, "UNKNOWN")
            # Only trigger command if state is changing or not yet verified
            if current_s != action or current_s == "UNKNOWN":
                result = await control_plug(
                    plug_name=plug_name,
                    action=action,
                    trigger_source="automation",
                    reason=reason,
                    temperature=avg_temp,
                    humidity=avg_humid,
                    sensor_readings_count=valid_count
                )
                actions_taken.append({
                    "plug": plug_name,
                    "action": action,
                    "reason": reason,
                    "success": result.get("success", False),
                    "message": result.get("message", "")
                })

        summary_msg = (
            f"Evaluated {valid_count} readings (avg temp: {avg_temp:.1f}°C, avg humid: {avg_humid:.1f}%). "
            f"Actions executed: {len(actions_taken)}."
        )

        return {
            "enabled": True,
            "window_size": window_size,
            "available_readings": valid_count,
            "avg_temperature": avg_temp,
            "avg_humidity": avg_humid,
            "actions_taken": actions_taken,
            "message": summary_msg,
            "timestamp": now_iso
        }
