"""
Configuration and Device Registry for TP-Link Tapo Smart Plugs.

Loads settings from .env and provides a centralized, reusable
registry mapping logical plug names (e.g., 'sprinkler', 'ac', 'heater',
'humidifier', 'fan') to IP addresses, protocol options, and automation
parameters.  Automation thresholds are persisted in a JSON settings file
so they can be tweaked at runtime through the API.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, List

# ─── Load Environment Variables ───
# Try loading via python-dotenv; if not installed, use robust fallback parser
ENV_PATHS = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]

# Path for persisted automation settings (JSON file next to this module)
AUTOMATION_SETTINGS_PATH = Path(__file__).resolve().parent / "automation_settings.json"


def load_env_file():
    """Load variables from .env into os.environ if not already set."""
    # Try using python-dotenv if installed
    try:
        from dotenv import load_dotenv
        for p in ENV_PATHS:
            if p.exists():
                load_dotenv(dotenv_path=p, override=False)
                return
    except ImportError:
        pass

    # Built-in lightweight fallback parser for .env
    for p in ENV_PATHS:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
                return
            except Exception as e:
                print(f"[config] Warning loading {p}: {e}")

load_env_file()


# ─── Data Class for Plug Devices ───
@dataclass
class PlugDevice:
    name: str              # Logical identifier (e.g. 'sprinkler', 'ac', 'heater')
    display_name: str      # Human-readable title
    env_ip_var: str        # Name of .env variable for IP
    ip: Optional[str]      # Resolved IP address
    device_type: str = "smart"
    encrypt_type: str = "tpap"
    no_https: bool = True
    icon: str = "🔌"
    role_description: str = ""

    @property
    def is_configured(self) -> bool:
        """Return True if an IP address is defined and not a placeholder."""
        if not self.ip:
            return False
        ip = self.ip.strip()
        return bool(ip and ip != "127.0.0.1" and not ip.startswith("your_"))


# ─── Device Registry ───
# To add a new plug, simply add an entry to PLUG_DEFINITIONS.
PLUG_DEFINITIONS = [
    {
        "name": "sprinkler",
        "display_name": "Sprinkler",
        "env_ip_var": "TAPO_SPRINKLER_IP",
        "default_ip": "192.168.1.14",
        "icon": "🌱",
        "role_description": "Scheduled irrigation (timed cycle)"
    },
    {
        "name": "ac",
        "display_name": "Air Conditioner",
        "env_ip_var": "TAPO_AC_IP",
        "default_ip": "192.168.1.15",
        "icon": "❄️",
        "role_description": "High-temperature cooling"
    },
    {
        "name": "heater",
        "display_name": "Space Heater",
        "env_ip_var": "TAPO_HEATER_IP",
        "default_ip": "192.168.1.16",
        "icon": "🔥",
        "role_description": "Low-temperature heating"
    },
    {
        "name": "humidifier",
        "display_name": "Humidifier",
        "env_ip_var": "TAPO_HUMIDIFIER_IP",
        "default_ip": "192.168.1.17",
        "icon": "💧",
        "role_description": "Humidity maintenance (ON < 93%, OFF > 96%)"
    },
    {
        "name": "fan",
        "display_name": "Fan",
        "env_ip_var": "TAPO_FAN_IP",
        "default_ip": "192.168.1.18",
        "icon": "🌀",
        "role_description": "Humidity exhaust & scheduled air circulation"
    },
]


def get_device_registry() -> Dict[str, PlugDevice]:
    """
    Build and return the active device registry,
    resolving current IP addresses from environment variables.
    """
    registry = {}
    for d in PLUG_DEFINITIONS:
        name = d["name"]
        env_var = d["env_ip_var"]
        ip = os.getenv(env_var, d.get("default_ip"))

        registry[name] = PlugDevice(
            name=name,
            display_name=d["display_name"],
            env_ip_var=env_var,
            ip=ip,
            device_type="smart",
            encrypt_type="tpap",
            no_https=True,
            icon=d.get("icon", "🔌"),
            role_description=d.get("role_description", "")
        )
    return registry


def get_device(plug_name: str) -> Optional[PlugDevice]:
    """Retrieve a device by its logical name (case-insensitive)."""
    registry = get_device_registry()
    return registry.get(plug_name.lower().strip())


# ─── Global Tapo Credentials ───
def get_tapo_credentials() -> tuple[Optional[str], Optional[str]]:
    """Return (email, password) from environment."""
    email = os.getenv("TAPO_EMAIL")
    password = os.getenv("TAPO_PASSWORD")
    return email, password


# ─── Automation Settings Defaults ───
# These match the new automation rules exactly and serve as fallback when
# no persisted settings file exists yet.

AUTOMATION_DEFAULTS: dict = {
    "enabled": True,
    "window_size": 30,

    # Humidifier — ON when humidity < 93%, OFF when humidity > 96%
    "humidifier_humid_low": 93.0,
    "humidifier_humid_high": 96.0,

    # AC (Cooling) — ON when temp > 26°C, OFF when temp < 23°C
    "ac_temp_high": 26.0,
    "ac_temp_low": 23.0,

    # Heater — ON when temp < 22°C, OFF at temp >= 26°C
    "heater_temp_low": 22.0,
    "heater_temp_high": 26.0,

    # Fan humidity trigger — ON for 3 mins when humidity > 96%
    "fan_humid_trigger_threshold": 96.0,
    "fan_humidity_trigger_duration_mins": 3,

    # Fan scheduled cycle — ON for 5 mins every 4 hours
    "fan_schedule_interval_hours": 4,
    "fan_schedule_duration_mins": 5,

    # Sprinkler scheduled cycle — ON for 5 mins every 2 hours
    "sprinkler_schedule_interval_hours": 2,
    "sprinkler_schedule_duration_mins": 5,
}


def _load_settings_file() -> dict:
    """Load persisted settings from JSON file, returning {} on any error."""
    if AUTOMATION_SETTINGS_PATH.exists():
        try:
            with open(AUTOMATION_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[config] Warning reading {AUTOMATION_SETTINGS_PATH}: {e}")
    return {}


def _save_settings_file(data: dict) -> None:
    """Persist settings dict to JSON file (atomic-ish write)."""
    try:
        with open(AUTOMATION_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[config] Error saving settings: {e}")


def get_automation_settings() -> dict:
    """
    Return automation rules thresholds and parameters.

    Resolution order:
      1. Persisted JSON settings file (automation_settings.json)
      2. Environment variables (legacy compat — only for 'enabled' and 'window_size')
      3. AUTOMATION_DEFAULTS
    """
    # Start from defaults
    settings = dict(AUTOMATION_DEFAULTS)

    # Override enabled / window_size from env if set (backward compat)
    env_enabled = os.getenv("AUTOMATION_ENABLED")
    if env_enabled is not None:
        settings["enabled"] = env_enabled.lower() in ("true", "1", "yes")
    env_window = os.getenv("AUTOMATION_READINGS_WINDOW")
    if env_window is not None:
        try:
            settings["window_size"] = int(env_window)
        except ValueError:
            pass

    # Layer persisted file on top (UI-tweaked values win)
    persisted = _load_settings_file()
    settings.update(persisted)

    return settings


def update_automation_settings(updates: dict) -> dict:
    """
    Merge *updates* into the persisted settings file and return the
    resulting full settings dict.  Only keys present in AUTOMATION_DEFAULTS
    are accepted; unknown keys are silently ignored.
    """
    persisted = _load_settings_file()

    for key, value in updates.items():
        if key in AUTOMATION_DEFAULTS and value is not None:
            persisted[key] = value

    _save_settings_file(persisted)

    # Return the fully-resolved settings
    return get_automation_settings()


# ─── Startup Validation ───
def validate_config() -> List[str]:
    """
    Validate environment configuration at server startup.
    Returns a list of warning/error messages.
    """
    issues = []
    email, password = get_tapo_credentials()

    if not email or "your_tapo" in email.lower():
        issues.append("TAPO_EMAIL is not configured or using default placeholder.")
    if not password or "your_tapo" in password.lower():
        issues.append("TAPO_PASSWORD is not configured or using default placeholder.")

    registry = get_device_registry()
    for name, dev in registry.items():
        if not dev.ip or dev.ip.startswith("your_"):
            issues.append(f"Smart plug '{name}' has no valid IP configured ({dev.env_ip_var}).")

    return issues
