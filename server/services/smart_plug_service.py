"""
Smart Plug Service for TP-Link Tapo P110 Plugs.

Communicates with Tapo P110 smart plugs via python-kasa CLI using the
TPAP encryption protocol. Ensures non-blocking async execution, per-plug
concurrency serialization, credential sanitization, and state persistence.
"""

import sys
import shutil
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from config import get_device, get_device_registry, get_tapo_credentials, PlugDevice
from database import (
    upsert_plug_state,
    get_plug_state_record,
    get_all_plug_states,
    insert_plug_history
)

# Per-plug locks to serialize commands and prevent race conditions
_PLUG_LOCKS: Dict[str, asyncio.Lock] = {}

def _get_lock(plug_name: str) -> asyncio.Lock:
    plug_key = plug_name.lower().strip()
    if plug_key not in _PLUG_LOCKS:
        _PLUG_LOCKS[plug_key] = asyncio.Lock()
    return _PLUG_LOCKS[plug_key]


def find_kasa_executable() -> str:
    """
    Locate the 'kasa' CLI executable.
    Checks the active Python environment's Scripts folder first, then system PATH.
    """
    # 1. Check active Python environment Scripts directory (e.g. conda env)
    scripts_dir = Path(sys.prefix) / "Scripts"
    candidate = scripts_dir / "kasa.exe"
    if candidate.exists():
        return str(candidate)

    # 2. Check which on PATH
    which_path = shutil.which("kasa")
    if which_path:
        return which_path

    # 3. Fallback
    return "kasa"


def sanitize_message(text: str, secret: Optional[str]) -> str:
    """Scrub passwords and secrets from log messages and error strings."""
    if not text or not secret:
        return text or ""
    return text.replace(secret, "******")


async def execute_kasa_cli(
    dev: PlugDevice,
    action: Optional[str] = None,
    timeout_seconds: float = 12.0
) -> tuple[int, str, str]:
    """
    Execute the kasa CLI command using the working TPAP configuration.
    Command format:
      kasa --host {ip} --type smart --encrypt-type tpap --no-https --username {email} --password {password} [{action}]

    Returns (returncode, stdout, stderr).
    """
    email, password = get_tapo_credentials()
    if not email or not password:
        return (1, "", "Tapo credentials not configured in environment (.env).")

    kasa_bin = find_kasa_executable()

    cmd = [
        kasa_bin,
        "--host", dev.ip,
        "--type", dev.device_type,
        "--encrypt-type", dev.encrypt_type,
        "--username", email,
        "--password", password,
    ]
    if dev.no_https:
        cmd.append("--no-https")

    if action:
        cmd.append(action.lower().strip())

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return (proc.returncode, stdout, stderr)

    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return (1, "", f"Communication with plug '{dev.name}' at {dev.ip} timed out after {timeout_seconds}s.")

    except FileNotFoundError:
        return (1, "", f"Could not find 'kasa' executable at '{kasa_bin}'. Please install python-kasa with TPAP support.")

    except Exception as e:
        return (1, "", f"Execution error: {str(e)}")


async def control_plug(
    plug_name: str,
    action: str,
    trigger_source: str = "manual",
    reason: str = "",
    temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    sensor_readings_count: Optional[int] = None
) -> Dict[str, Any]:
    """
    Main controller for toggling a smart plug ON or OFF.
    Includes concurrency locking, state verification, history logging, and database update.
    """
    plug_key = plug_name.lower().strip()
    action_clean = action.upper().strip()

    if action_clean not in ("ON", "OFF"):
        return {
            "plug": plug_key,
            "requested_action": action,
            "success": False,
            "message": f"Invalid action '{action}'. Must be 'on' or 'off'.",
            "resulting_state": None,
            "is_verified": False
        }

    dev = get_device(plug_key)
    if not dev:
        return {
            "plug": plug_key,
            "requested_action": action_clean,
            "success": False,
            "message": f"Smart plug '{plug_key}' is not registered in device registry.",
            "resulting_state": None,
            "is_verified": False
        }

    if not dev.is_configured:
        return {
            "plug": plug_key,
            "requested_action": action_clean,
            "success": False,
            "message": f"Smart plug '{plug_key}' IP address is not configured ({dev.env_ip_var}).",
            "resulting_state": None,
            "is_verified": False
        }

    _, password = get_tapo_credentials()
    lock = _get_lock(plug_key)

    async with lock:
        # Retrieve previous state
        prev_record = await get_plug_state_record(plug_key)
        previous_state = prev_record["current_state"] if prev_record else "UNKNOWN"

        # For automated rules, avoid sending duplicate commands if already verified in desired state
        if trigger_source == "automation" and prev_record and prev_record.get("is_verified") and prev_record.get("current_state") == action_clean:
            return {
                "plug": plug_key,
                "requested_action": action_clean,
                "success": True,
                "message": f"Plug '{dev.display_name}' is already {action_clean}.",
                "resulting_state": action_clean,
                "is_verified": True
            }

        # If temperature or humidity not supplied (e.g. manual toggle), fetch latest reading for context
        if temperature is None or humidity is None:
            try:
                from database import get_latest_reading
                latest = await get_latest_reading()
                if latest:
                    if temperature is None:
                        temperature = latest.get("temperature")
                    if humidity is None:
                        humidity = latest.get("humidity")
            except Exception:
                pass

        # Execute kasa command
        code, stdout, stderr = await execute_kasa_cli(dev, action=action_clean.lower())
        sanitized_err = sanitize_message(stderr.strip(), password)
        sanitized_out = sanitize_message(stdout.strip(), password)

        success = (code == 0)
        now_iso = datetime.now().isoformat()

        if success:
            resulting_state = action_clean
            # In python-kasa, turning on/off successfully applies the state
            is_verified = True
            err_msg = None
            msg = f"Plug '{dev.display_name}' turned {action_clean} successfully."
            action_result = "SUCCESS"
            succ_check = now_iso

            print(f"  🔌 [Plug] {dev.display_name} ({dev.ip}) -> {action_clean} [{trigger_source}]: OK")
        else:
            resulting_state = previous_state  # Don't change state on failure
            is_verified = False
            err_msg = sanitized_err or sanitized_out or "Command failed."
            msg = f"Failed to turn {action_clean} plug '{dev.display_name}': {err_msg}"
            action_result = "FAILED"
            succ_check = prev_record.get("last_successful_check") if prev_record else None

            print(f"  ❌ [Plug Error] {dev.display_name} -> {action_clean} failed: {err_msg}")

        # Update database state table
        await upsert_plug_state(
            plug_name=plug_key,
            current_state=resulting_state,
            is_verified=is_verified,
            last_successful_check=succ_check,
            last_attempted_action=action_clean,
            last_action_result=action_result
        )

        # Log event in history table
        await insert_plug_history(
            plug_name=plug_key,
            plug_ip=dev.ip,
            requested_action=action_clean,
            previous_state=previous_state,
            resulting_state=resulting_state if success else None,
            success=success,
            trigger_source=trigger_source,
            temperature=temperature,
            humidity=humidity,
            sensor_readings_count=sensor_readings_count,
            reason=reason or f"{trigger_source.capitalize()} request",
            error_message=err_msg
        )

        return {
            "plug": plug_key,
            "requested_action": action_clean,
            "success": success,
            "message": msg,
            "resulting_state": resulting_state,
            "is_verified": is_verified
        }


async def turn_on(plug_name: str, trigger_source: str = "manual", reason: str = "") -> Dict[str, Any]:
    """Turn a smart plug ON."""
    return await control_plug(plug_name, action="ON", trigger_source=trigger_source, reason=reason)


async def turn_off(plug_name: str, trigger_source: str = "manual", reason: str = "") -> Dict[str, Any]:
    """Turn a smart plug OFF."""
    return await control_plug(plug_name, action="OFF", trigger_source=trigger_source, reason=reason)


async def get_plug_state(plug_name: str, refresh_physical: bool = False) -> Dict[str, Any]:
    """
    Get the state of a plug.
    By default returns cached DB record.
    If refresh_physical is True, queries the hardware via kasa CLI.
    """
    plug_key = plug_name.lower().strip()
    dev = get_device(plug_key)
    if not dev:
        return {
            "plug_name": plug_key,
            "display_name": plug_name,
            "error": "Device not found in registry"
        }

    db_state = await get_plug_state_record(plug_key)

    if not refresh_physical or not dev.is_configured:
        return {
            "plug_name": dev.name,
            "display_name": dev.display_name,
            "ip": dev.ip,
            "current_state": db_state["current_state"] if db_state else "UNKNOWN",
            "is_verified": db_state["is_verified"] if db_state else False,
            "last_successful_check": db_state["last_successful_check"] if db_state else None,
            "last_attempted_action": db_state["last_attempted_action"] if db_state else None,
            "last_action_result": db_state["last_action_result"] if db_state else None,
            "icon": dev.icon,
            "role_description": dev.role_description,
            "updated_at": db_state["updated_at"] if db_state else None
        }

    # Query physical device state via kasa CLI (no action = query info)
    lock = _get_lock(plug_key)
    async with lock:
        code, stdout, stderr = await execute_kasa_cli(dev, action=None)
        _, password = get_tapo_credentials()

        if code == 0:
            out_lower = stdout.lower()
            # Detect ON/OFF state in kasa output
            is_on = "device state: on" in out_lower or "device state: true" in out_lower or "== on" in out_lower or "state: true" in out_lower
            is_off = "device state: off" in out_lower or "device state: false" in out_lower or "== off" in out_lower or "state: false" in out_lower

            current_state = "ON" if is_on else ("OFF" if is_off else "UNKNOWN")
            is_verified = (current_state != "UNKNOWN")
            now_iso = datetime.now().isoformat()

            await upsert_plug_state(
                plug_name=dev.name,
                current_state=current_state,
                is_verified=is_verified,
                last_successful_check=now_iso,
                last_action_result="SUCCESS"
            )

            return {
                "plug_name": dev.name,
                "display_name": dev.display_name,
                "ip": dev.ip,
                "current_state": current_state,
                "is_verified": is_verified,
                "last_successful_check": now_iso,
                "last_attempted_action": db_state["last_attempted_action"] if db_state else None,
                "last_action_result": "SUCCESS",
                "icon": dev.icon,
                "role_description": dev.role_description,
                "updated_at": now_iso
            }
        else:
            return {
                "plug_name": dev.name,
                "display_name": dev.display_name,
                "ip": dev.ip,
                "current_state": db_state["current_state"] if db_state else "UNKNOWN",
                "is_verified": False,
                "last_successful_check": db_state["last_successful_check"] if db_state else None,
                "last_attempted_action": db_state["last_attempted_action"] if db_state else None,
                "last_action_result": "FAILED",
                "icon": dev.icon,
                "role_description": dev.role_description,
                "error": sanitize_message(stderr.strip(), password),
                "updated_at": db_state["updated_at"] if db_state else None
            }


async def get_all_plugs_status(refresh_physical: bool = False) -> List[Dict[str, Any]]:
    """Retrieve state for all registered plugs."""
    registry = get_device_registry()
    results = []
    for name in registry.keys():
        st = await get_plug_state(name, refresh_physical=refresh_physical)
        results.append(st)
    return results
