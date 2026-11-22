"""
Pydantic models for request/response validation.
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class SensorReading(BaseModel):
    """
    Model for incoming sensor data from the ESP32.
    The ESP32 sends JSON like: {"temperature": 25.30, "humidity": 48.50}
    """
    temperature: float = Field(..., description="Temperature in Celsius", ge=-40, le=80)
    humidity: float = Field(..., description="Relative humidity percentage", ge=0, le=100)


class SensorReadingResponse(BaseModel):
    """Model for the API response after storing a reading."""
    id: int
    temperature: float
    humidity: float
    timestamp: str
    status: str = "ok"


class LatestReadingResponse(BaseModel):
    """Model for the latest reading API endpoint."""
    id: Optional[int] = None
    temperature: Optional[float] = None
    humidity: Optional[float] = None
    timestamp: Optional[str] = None
    total_readings: int = 0
    status: str = "ok"


class ClearHistoryRequest(BaseModel):
    """Request model for clearing history."""
    clear_all: bool = False
    hours: Optional[float] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class ClearHistoryResponse(BaseModel):
    """Response model after clearing history."""
    status: str = "ok"
    deleted_count: int
    remaining_count: int
    message: str


# ─── Smart Plug Models ───

class PlugControlResponse(BaseModel):
    """Response model for POST /api/plugs/{plug_name}/on or off."""
    plug: str
    requested_action: str
    success: bool
    message: str
    resulting_state: Optional[str] = None
    is_verified: bool = False


class PlugStateInfo(BaseModel):
    """Model representing current status of a smart plug."""
    plug_name: str
    display_name: str
    ip: Optional[str] = None
    current_state: str = "UNKNOWN"
    is_verified: bool = False
    last_successful_check: Optional[str] = None
    last_attempted_action: Optional[str] = None
    last_action_result: Optional[str] = None
    icon: str = "🔌"
    role_description: str = ""
    updated_at: Optional[str] = None


class AutomationStatusResponse(BaseModel):
    """Status report of recent automation evaluation."""
    enabled: bool
    window_size: int
    available_readings: int
    avg_temperature: Optional[float] = None
    avg_humidity: Optional[float] = None
    actions_taken: List[dict] = []
    message: str
    timestamp: str


