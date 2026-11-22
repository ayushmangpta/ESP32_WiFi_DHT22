# Phase 2: Smart Plug Automation Based on Temperature and Humidity

This document provides complete architectural, configuration, and operational documentation for **Phase 2** of the ESP32 DHT22 Environmental Monitor: automated and manual control of **TP-Link Tapo P110** smart plugs using the TPAP protocol.

---

## 1. System Architecture Overview

```
                      ┌──────────────────────┐
                      │    ESP32 + DHT22     │
                      │  (Every 5 seconds)   │
                      └──────────┬───────────┘
                                 │ HTTP POST /api/readings
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Server (Port 8000)                      │
│                                                                        │
│  ┌────────────────────┐   asyncio.create_task   ┌───────────────────┐  │
│  │ Sensor Ingestion   ├────────────────────────►│ Automation Engine │  │
│  │ (Non-blocking)     │                         │ (30-sample window)│  │
│  └────────┬───────────┘                         └─────────┬─────────┘  │
│           │                                               │            │
│           ▼                                               ▼            │
│  ┌────────────────────┐                         ┌───────────────────┐  │
│  │ SQLite Database    │◄────────────────────────┤ Smart Plug Service│  │
│  │ - readings         │                         │ (async subprocess)│  │
│  │ - smart_plug_state │                         └─────────┬─────────┘  │
│  │ - smart_plug_hist  │                                   │            │
│  └────────────────────┘                                   │            │
└───────────────────────────────────────────────────────────┼────────────┘
                                                            │
                       TPAP Protocol CLI Commands           │
                      (python-kasa with --type smart)       │
                                                            │
           ┌────────────────────────┬───────────────────────┴───────────────────────┐
           ▼                        ▼                                               ▼
┌─────────────────────┐  ┌─────────────────────┐                         ┌─────────────────────┐
│ 🌱 Tapo P110        │  │ ❄️ Tapo P110        │                         │ 🔥 Tapo P110        │
│ Sprinkler / Humid   │  │ Air Conditioner     │                         │ Space Heater        │
│ (192.168.1.14)      │  │ (192.168.1.15)      │                         │ (192.168.1.16)      │
└─────────────────────┘  └─────────────────────┘                         └─────────────────────┘
```

---

## 2. TPAP Protocol & Smart Plug Communication

Tapo P110 smart plugs require the **TPAP** (Tapo Protocol with AES encryption) authentication handshake over port 80. Standard Kasa protocols will fail on these hardware revisions.

### 2.1 python-kasa TPAP Development Build

A specific development branch of `python-kasa` is required:

```bash
conda activate arduino-env
python -m pip install --no-cache-dir "git+https://github.com/ZeliardM/python-kasa.git@feature/tpap"
```

The CLI executable is located at:
`C:\Users\Lenovo\miniconda3\envs\arduino-env\Scripts\kasa.exe`

### 2.2 Working CLI Command Template

```bash
kasa --host <DEVICE_IP> \
     --type smart \
     --encrypt-type tpap \
     --no-https \
     --username "<YOUR_TAPO_EMAIL>" \
     --password "<YOUR_TAPO_PASSWORD>" \
     <ACTION>
```

- `<ACTION>`: `on`, `off`, or omitted to query hardware state.
- **Security**: The application scrubs passwords from all logs, database history tables, and exception messages.

---

## 3. Environment Configuration (`.env`)

All credentials, device IP addresses, and automation thresholds are stored in `server/.env`.

### 3.1 `.env` File Specification

```dotenv
# Tapo Cloud Account Credentials
TAPO_EMAIL=your_tapo_email@example.com
TAPO_PASSWORD=your_tapo_password

# Device IP Addresses
TAPO_SPRINKLER_IP=192.168.1.14
TAPO_AC_IP=192.168.1.15
TAPO_HEATER_IP=192.168.1.16

# Automation Engine Configuration
AUTOMATION_ENABLED=true
AUTOMATION_READINGS_WINDOW=30

# Air Conditioner (Cooling) Thresholds
AC_TEMP_HIGH=28.0
AC_TEMP_LOW=25.0

# Space Heater (Heating) Thresholds
HEATER_TEMP_LOW=18.0
HEATER_TEMP_HIGH=21.0

# Sprinkler (Irrigation & Humidity) Thresholds
SPRINKLER_HUMID_LOW=45.0
SPRINKLER_HUMID_HIGH=65.0
SPRINKLER_MIN_TEMP=15.0
```

> [!IMPORTANT]
> The `.env` file is excluded in `.gitignore` to prevent secret exposure in version control. A `.env.example` file is provided as a template.

---

## 4. Device Registry (`server/config.py`)

The device registry centralizes plug definitions so adding new devices requires only a single dictionary entry.

```python
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
```

---

## 5. Reusable Smart Plug Service (`server/services/smart_plug_service.py`)

The plug service isolates low-level CLI execution from HTTP endpoints and automation rules.

### Key Capabilities:
- **`control_plug(plug_name, action, trigger_source, reason, ...)`**: Validates device, checks current state to prevent redundant network commands, executes `kasa` asynchronously, updates `smart_plug_state`, and writes an event into `smart_plug_history`.
- **`turn_on(plug_name)`** & **`turn_off(plug_name)`**: Ergonomic wrappers.
- **`get_plug_state(plug_name, refresh_physical=False)`**: Retrieves current state from database or directly queries the hardware.
- **`get_all_plugs_status()`**: Returns metadata and states for all registered plugs.

### Safety & Concurrency:
- **Per-Device Asyncio Locks (`_PLUG_LOCKS`)**: Serializes operations targeting the same plug to eliminate race conditions between simultaneous manual and automated requests.
- **Redundant Command Suppression**: If a plug is already verified in state `ON` and an `ON` command is requested, the network command is skipped.
- **Secret Sanitization**: Passwords and authorization tokens are scrubbed from stdout and stderr before logging or persisting.

---

## 6. Automation Rules Module (`server/automation/plug_rules.py`)

Automated equipment control is completely decoupled from sensor ingestion and HTTP handlers.

### 6.1 Moving Average Evaluation
- Rules evaluate the average of the most recent **30 valid sensor readings**.
- **Failsafe**: If fewer than 30 valid readings exist in SQLite, automation aborts with an informative warning and never toggles equipment.

### 6.2 Equipment Rules & Hysteresis

| Equipment | Trigger ON Condition | Trigger OFF Condition | Deadband / Hysteresis | Safety Interlock |
| :--- | :--- | :--- | :--- | :--- |
| **Sprinkler** 🌱 | Humidity < 45.0% AND Temp &ge; 15.0°C | Humidity &ge; 65.0% OR Temp < 15.0°C | 45.0% to 65.0% | **Freeze Protection**: Disables irrigation if Temp < 15.0°C |
| **Air Conditioner** ❄️ | Temp > 28.0°C | Temp < 25.0°C | 25.0°C to 28.0°C | **Mutual Exclusion**: Turns OFF Heater before starting AC |
| **Space Heater** 🔥 | Temp < 18.0°C | Temp > 21.0°C | 18.0°C to 21.0°C | **Mutual Exclusion**: Turns OFF AC before starting Heater |

### 6.3 Non-Blocking Execution
When the ESP32 posts a reading to `POST /api/readings`:
```python
# Dispatched as a background task; ESP32 receives instant HTTP 200 OK
asyncio.create_task(evaluate_automation_rules())
```

---

## 7. API Endpoints

### 7.1 Manual Plug Control

#### Turn Plug ON
```http
POST /api/plugs/{plug_name}/on
```
*Example Request:*
```http
POST /api/plugs/sprinkler/on
```
*Example Response (200 OK):*
```json
{
  "plug": "sprinkler",
  "requested_action": "ON",
  "success": true,
  "message": "Plug 'Sprinkler' turned ON successfully.",
  "resulting_state": "ON",
  "is_verified": true
}
```

#### Turn Plug OFF
```http
POST /api/plugs/{plug_name}/off
```
*Example Request:*
```http
POST /api/plugs/sprinkler/off
```
*Example Response (200 OK):*
```json
{
  "plug": "sprinkler",
  "requested_action": "OFF",
  "success": true,
  "message": "Plug 'Sprinkler' turned OFF successfully.",
  "resulting_state": "OFF",
  "is_verified": true
}
```

### 7.2 Plug Status & Metadata

#### Query All Plugs
```http
GET /api/plugs?refresh=false
```

#### Query Single Plug
```http
GET /api/plugs/ac
```

### 7.3 History & Timeline Events

#### Retrieve Action History Records
```http
GET /api/plugs/history?limit=50&hours=24
```

#### Retrieve Chronological Timeline Events (Chart Annotations)
```http
GET /api/plugs/timeline?hours=24
```

### 7.4 Automation Engine Control

#### Manually Trigger Rule Evaluation
```http
POST /api/automation/evaluate
```
*Example Response:*
```json
{
  "enabled": true,
  "window_size": 30,
  "available_readings": 30,
  "avg_temperature": 29.15,
  "avg_humidity": 41.20,
  "actions_taken": [
    {
      "plug": "ac",
      "action": "ON",
      "reason": "High temp (29.2°C > 28.0°C threshold) - Cooling required",
      "success": true,
      "message": "Plug 'Air Conditioner' turned ON successfully."
    }
  ],
  "message": "Evaluated 30 readings (avg temp: 29.2°C, avg humid: 41.2%). Actions executed: 1.",
  "timestamp": "2026-10-25T02:40:00.123456"
}
```

---

## 8. Database Schema (`sensor_data.db`)

### 8.1 Table: `smart_plug_state`
Maintains the current known and verified status of each registered plug.

```sql
CREATE TABLE IF NOT EXISTS smart_plug_state (
    plug_name TEXT PRIMARY KEY,
    current_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    is_verified INTEGER NOT NULL DEFAULT 0,
    last_successful_check TEXT,
    last_attempted_action TEXT,
    last_action_result TEXT,
    updated_at TEXT NOT NULL
);
```

### 8.2 Table: `smart_plug_history`
Append-only log recording every automated and manual state-change attempt.

```sql
CREATE TABLE IF NOT EXISTS smart_plug_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plug_name TEXT NOT NULL,
    plug_ip TEXT,
    requested_action TEXT NOT NULL,
    previous_state TEXT,
    resulting_state TEXT,
    success INTEGER NOT NULL,
    trigger_source TEXT NOT NULL,
    temperature REAL,
    humidity REAL,
    sensor_readings_count INTEGER,
    reason TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plug_history_created ON smart_plug_history(created_at);
CREATE INDEX IF NOT EXISTS idx_plug_history_plug ON smart_plug_history(plug_name);
```

---

## 9. Dashboard UI Features

The browser dashboard (`http://localhost:8000`) contains four main Phase 2 components:

1. **Smart Plug Interactive Grid**:
   - Live state badges (`ON`, `OFF`, `UNKNOWN`) with status glow.
   - Verification badges (`✓ Hardware Verified` vs `Unverified`).
   - One-click **Turn ON** and **Turn OFF** buttons with instant visual feedback.
2. **Automation Engine Banner**:
   - Displays real-time operational status and rule thresholds.
   - Includes **"⚡ Evaluate Automation Now"** trigger button.
3. **Dual-Axis Environmental Chart with Plug Trigger Markers**:
   - Displays temperature and humidity curves.
   - Renders trigger point markers directly on the graph whenever a plug switches ON (green triangle ▲) or OFF (red diamond ◆).
   - Tooltips show plug name, action, and triggering reason.
4. **Dedicated Smart Plug State Activity Chart**:
   - Stepped-line timeline showing binary state (0 = OFF, 1 = ON) for Sprinkler, AC, and Heater across the selected time range.
5. **Smart Plug Event & Action Log Table**:
   - Searchable table logging all automated and manual actions with timestamps, environmental averages, and decision reasons.

---

## 10. Verification and Testing

### 10.1 Verify CLI Communication
Test direct CLI connectivity from terminal:

```bash
conda activate arduino-env
kasa --host 192.168.1.14 --type smart --encrypt-type tpap --no-https --username "YOUR_TAPO_EMAIL" --password "YOUR_TAPO_PASSWORD" off
```

### 10.2 Verify Server Startup
Start the FastAPI server:

```bash
conda activate arduino-env
cd G:\ESP32_WiFi_DHT22\server
uvicorn main:app --host 0.0.0.0 --port 8000
```

Look for the startup log:
```
═══════════════════════════════════════════════════════
  ESP32 DHT22 Logger & Tapo Smart Plug Automation Server
═══════════════════════════════════════════════════════
  Existing sensor readings in database: 142
  Registered Smart Plugs (3):
    - 🌱 Sprinkler (sprinkler): 192.168.1.14
    - ❄️ Air Conditioner (ac): 192.168.1.15
    - 🔥 Space Heater (heater): 192.168.1.16
  ✅ All smart plug credentials and IP addresses configured.
  🤖 Automation: ENABLED (Sliding Window: 30 readings)
  Dashboard: http://localhost:8000
═══════════════════════════════════════════════════════
```

### 10.3 Test API Control
Turn ON sprinkler via HTTP:

```bash
curl -X POST http://localhost:8000/api/plugs/sprinkler/on
```

Turn OFF sprinkler via HTTP:

```bash
curl -X POST http://localhost:8000/api/plugs/sprinkler/off
```

### 10.4 Test Automation Engine
Trigger manual rule evaluation via HTTP:

```bash
curl -X POST http://localhost:8000/api/automation/evaluate
```
