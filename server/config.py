"""
Configuration and Device Registry for TP-Link Tapo Smart Plugs.

Loads settings from .env and provides a centralized, reusable
registry mapping logical plug names (e.g., 'sprinkler', 'ac', 'heater')
to IP addresses, protocol options, and automation parameters.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Optional, List

# ─── Load Environment Variables ───
# Try loading via python-dotenv; if not installed, use robust fallback parser
ENV_PATHS = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]

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
        "role_description": "Irrigation & humidity control"
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
    }
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


# ─── Automation Settings ───
def get_automation_settings() -> dict:
    """Return automation rules thresholds and parameters."""
    return {
        "enabled": os.getenv("AUTOMATION_ENABLED", "true").lower() in ("true", "1", "yes"),
        "window_size": int(os.getenv("AUTOMATION_READINGS_WINDOW", "30")),
        # AC (Cooling)
        "ac_temp_high": float(os.getenv("AC_TEMP_HIGH", "28.0")),
        "ac_temp_low": float(os.getenv("AC_TEMP_LOW", "25.0")),
        # Heater (Heating)
        "heater_temp_low": float(os.getenv("HEATER_TEMP_LOW", "18.0")),
        "heater_temp_high": float(os.getenv("HEATER_TEMP_HIGH", "21.0")),
        # Sprinkler (Moisture)
        "sprinkler_humid_low": float(os.getenv("SPRINKLER_HUMID_LOW", "45.0")),
        "sprinkler_humid_high": float(os.getenv("SPRINKLER_HUMID_HIGH", "65.0")),
        "sprinkler_min_temp": float(os.getenv("SPRINKLER_MIN_TEMP", "15.0")),
    }


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
