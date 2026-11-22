"""
Smart Plug Automation Rules Module.

Evaluates moving averages of the most recent valid sensor readings
from the SQLite database and makes automated ON/OFF decisions for each
registered TP-Link Tapo smart plug based on temperature and humidity.

Active Environmental Rules:
  1. Humidifier:
     - Turn ON if average humidity < 93% (tweakable).
     - Turn OFF if average humidity > 96% (tweakable).
     - Deadband (93% - 96%): maintain current state.

  2. Air Conditioner (AC):
     - Turn ON if average temperature > 26°C (tweakable).
     - Turn OFF if average temperature < 23°C (tweakable).
     - Deadband (23°C - 26°C): maintain current state.

  3. Space Heater:
     - Turn ON if average temperature < 22°C (tweakable).
     - Stays ON until average temperature reaches 26°C (tweakable), then turns OFF.
     - Deadband (22°C - 26°C): latching state (maintains ON if heating, OFF if idle).

  4. Fan (Humidity Trigger):
     - Turn ON for 3 minutes (tweakable) whenever average humidity exceeds 96% (tweakable).
     - Handled via background scheduler timer.

  5. Safety Interlocks:
     - Mutual exclusion between AC and Space Heater (never run simultaneously).
"""

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

from config import get_automation_settings, get_device_registry
from database import get_recent_readings_for_automation, get_plug_state_record
from services.smart_plug_service import control_plug
from automation.scheduler import scheduler

# Concurrency lock to prevent simultaneous automation evaluations
_EVALUATION_LOCK = asyncio.Lock()


def evaluate_humidifier_rule(
    avg_humid: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate Humidifier rule.

    Rules:
      - Turn ON when avg_humid < humidifier_humid_low (default < 93.0%)
      - Turn OFF when avg_humid > humidifier_humid_high (default > 96.0%)
      - Between low and high: maintain current state (hysteresis)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    low_h = settings.get("humidifier_humid_low", 93.0)
    high_h = settings.get("humidifier_humid_high", 96.0)

    if avg_humid < low_h:
        if current_state != "ON":
            return ("ON", f"Low humidity ({avg_humid:.1f}% < {low_h:.1f}% threshold) - Humidifier turned ON")
        return (None, f"Humidity is low ({avg_humid:.1f}%), Humidifier already ON")

    if avg_humid > high_h:
        if current_state != "OFF":
            return ("OFF", f"High humidity reached ({avg_humid:.1f}% > {high_h:.1f}% threshold) - Humidifier turned OFF")
        return (None, f"Humidity is sufficient ({avg_humid:.1f}%), Humidifier already OFF")

    return (None, f"Humidity ({avg_humid:.1f}%) within optimal deadband [{low_h:.1f}% - {high_h:.1f}%]")


def evaluate_ac_rule(
    avg_temp: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate AC (Air Conditioner) cooling rule.

    Rules:
      - Turn ON when avg_temp > ac_temp_high (default > 26.0°C)
      - Turn OFF when avg_temp < ac_temp_low (default < 23.0°C)
      - Between ac_temp_low and ac_temp_high: maintain current state (hysteresis)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    high = settings.get("ac_temp_high", 26.0)
    low = settings.get("ac_temp_low", 23.0)

    if avg_temp > high:
        if current_state != "ON":
            return ("ON", f"High temp ({avg_temp:.1f}°C > {high:.1f}°C threshold) - AC cooling turned ON")
        return (None, f"Temp is high ({avg_temp:.1f}°C), AC already ON")

    if avg_temp < low:
        if current_state != "OFF":
            return ("OFF", f"Temp cooled down ({avg_temp:.1f}°C < {low:.1f}°C threshold) - AC cooling turned OFF")
        return (None, f"Temp is normal ({avg_temp:.1f}°C), AC already OFF")

    return (None, f"Temp ({avg_temp:.1f}°C) within comfortable deadband [{low:.1f}°C - {high:.1f}°C]")


def evaluate_heater_rule(
    avg_temp: float,
    current_state: str,
    settings: dict
) -> tuple[Optional[str], str]:
    """
    Evaluate Space Heater rule.

    Rules:
      - Turn ON when avg_temp < heater_temp_low (default < 22.0°C)
      - Turn OFF when avg_temp >= heater_temp_high (default >= 26.0°C)
      - Between 22.0°C and 26.0°C: latching hysteresis
        (If currently ON, stays ON until 26°C target is reached; if OFF, stays OFF)

    Returns:
      (desired_action, reason) -> desired_action is "ON", "OFF", or None (no change)
    """
    low = settings.get("heater_temp_low", 22.0)
    high = settings.get("heater_temp_high", 26.0)

    if avg_temp < low:
        if current_state != "ON":
            return ("ON", f"Low temp ({avg_temp:.1f}°C < {low:.1f}°C threshold) - Heater turned ON until {high:.1f}°C")
        return (None, f"Temp is low ({avg_temp:.1f}°C), Heater already ON")

    if avg_temp >= high:
        if current_state != "OFF":
            return ("OFF", f"Target temp reached ({avg_temp:.1f}°C >= {high:.1f}°C threshold) - Heater turned OFF")
        return (None, f"Temp is warm ({avg_temp:.1f}°C), Heater already OFF")

    # In deadband [low, high)
    if current_state == "ON":
        return (None, f"Heater active ({avg_temp:.1f}°C) heating up to target {high:.1f}°C")

    return (None, f"Temp ({avg_temp:.1f}°C) in deadband [{low:.1f}°C - {high:.1f}°C], Heater idle")


async def evaluate_automation_rules() -> Dict[str, Any]:
    """
    Main entry point for evaluating automated plug rules.

    Process:
      1. Verify automation is globally enabled.
      2. Retrieve recent sensor readings (window_size, default 30).
      3. Validate readings exist; fail safe if fewer.
      4. Compute moving averages for temperature and humidity.
      5. Evaluate rules for Humidifier, AC, Heater, and Fan humidity trigger.
      6. Enforce safety constraints (AC and Heater cannot both run).
      7. Issue commands asynchronously only when state changes are necessary.
      8. Return evaluation summary.
    """
    settings = get_automation_settings()
    now_iso = datetime.now().isoformat()

    if not settings.get("enabled", True):
        return {
            "enabled": False,
            "window_size": settings.get("window_size", 30),
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
            "window_size": settings.get("window_size", 30),
            "available_readings": 0,
            "avg_temperature": None,
            "avg_humidity": None,
            "actions_taken": [],
            "message": "Automation evaluation already in progress. Skipping duplicate tick.",
            "timestamp": now_iso
        }

    async with _EVALUATION_LOCK:
        window_size = settings.get("window_size", 30)
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

        # Fail safe if insufficient readings
        if valid_count < window_size:
            msg = (
                f"Insufficient sensor data: {valid_count}/{window_size} valid readings available. "
                f"Automation held for safety until {window_size} readings are accumulated."
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

        # Fetch current state of registered plugs from database
        plug_states = {}
        for plug_name in registry.keys():
            record = await get_plug_state_record(plug_name)
            plug_states[plug_name] = record["current_state"] if record else "UNKNOWN"

        # ─── 1. Evaluate Humidifier Rule ───
        humidifier_action = None
        humidifier_reason = ""
        if "humidifier" in registry:
            humidifier_action, humidifier_reason = evaluate_humidifier_rule(
                avg_humid=avg_humid,
                current_state=plug_states.get("humidifier", "UNKNOWN"),
                settings=settings
            )

        # ─── 2. Evaluate AC Rule ───
        ac_action = None
        ac_reason = ""
        if "ac" in registry:
            ac_action, ac_reason = evaluate_ac_rule(
                avg_temp=avg_temp,
                current_state=plug_states.get("ac", "UNKNOWN"),
                settings=settings
            )

        # ─── 3. Evaluate Heater Rule ───
        heater_action = None
        heater_reason = ""
        if "heater" in registry:
            heater_action, heater_reason = evaluate_heater_rule(
                avg_temp=avg_temp,
                current_state=plug_states.get("heater", "UNKNOWN"),
                settings=settings
            )

        # ─── Safety Interlock: Mutual Exclusion between AC and Heater ───
        if ac_action == "ON" and heater_action == "ON":
            if avg_temp > settings.get("ac_temp_high", 26.0):
                heater_action = "OFF"
                heater_reason = "Safety interlock: AC prioritized for extreme heat"
            else:
                ac_action = "OFF"
                ac_reason = "Safety interlock: Heater prioritized for cold"

        if ac_action == "ON" and plug_states.get("heater") == "ON":
            await control_plug(
                plug_name="heater",
                action="OFF",
                trigger_source="automation",
                reason="Safety interlock: Shutting off Heater before starting AC",
                temperature=avg_temp,
                humidity=avg_humid,
                sensor_readings_count=valid_count
            )
            plug_states["heater"] = "OFF"

        if heater_action == "ON" and plug_states.get("ac") == "ON":
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

        # ─── Execute Decisions for Humidifier, AC, Heater ───
        planned_actions = [
            ("humidifier", humidifier_action, humidifier_reason),
            ("ac", ac_action, ac_reason),
            ("heater", heater_action, heater_reason),
        ]

        for plug_name, action, reason in planned_actions:
            if plug_name not in registry or action is None:
                continue

            current_s = plug_states.get(plug_name, "UNKNOWN")
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

        # ─── 4. Evaluate Fan Humidity Trigger (Humidity > 96% -> ON for 3 mins) ───
        fan_humid_threshold = settings.get("fan_humid_trigger_threshold", 96.0)
        fan_duration = settings.get("fan_humidity_trigger_duration_mins", 3.0)

        if "fan" in registry and avg_humid > fan_humid_threshold:
            triggered = scheduler.trigger_fan_humidity_cycle(
                duration_mins=fan_duration,
                reason=f"High humidity ({avg_humid:.1f}% > {fan_humid_threshold:.1f}% threshold) - 3m exhaust"
            )
            if triggered:
                actions_taken.append({
                    "plug": "fan",
                    "action": "ON",
                    "reason": f"High humidity ({avg_humid:.1f}% > {fan_humid_threshold:.1f}%) - Timer {fan_duration:.0f}m",
                    "success": True,
                    "message": f"Fan turned ON for {fan_duration:.0f} minutes"
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
