# 🌡️ ESP32 + DHT22 Wireless Logger & Automation — Implementation Plan

> **Last updated:** 2026-11-22 18:15 IST

## Project Architecture

```
DHT22 Sensor ──OUT──→ ESP32 (GPIO27) ──Wi-Fi──→ Home Router ──→ FastAPI Server (Windows Laptop)
                                                                   │
                                ┌──────────────────────────────────┴──────────────────────────────────┐
                                ▼                                                                     ▼
                        SQLite Database (sensor_data.db)                                 Tapo Smart Plug Controller
                        (readings & plug action logs)                                    (TPAP protocol via python-kasa)
                                │                                                                     │
                                └──────────────────────────────────┬──────────────────────────────────┘
                                                                   ▼
                                                Browser Dashboard (Glassmorphism Dark UI)
                                                - Live Gauges & Dual History Charts
                                                - 5 Plug Device Cards (Sprinkler, AC, Heater, Humidifier, Fan)
                                                - UI-Tweakable Automation Thresholds Panel
                                                - Real-time Scheduler Countdowns & Action Buttons
```

## File Structure

```
G:\ESP32_WiFi_DHT22\
├── project.md                    # Project spec
├── implementation_plan.md        # This file
├── setup_guide.md                # Step-by-step walkthrough
├── esp32_sketch/
│   └── esp32_sketch.ino          # Arduino code for ESP32
└── server/
    ├── main.py                   # FastAPI server & endpoints
    ├── config.py                 # Device registry & SQL-backed settings
    ├── database.py               # Async SQLite database setup & SQL settings tables
    ├── models.py                 # Pydantic data & settings models
    ├── sensor_data.db            # SQLite DB containing readings, history & automation_settings
    ├── automation/
    │   ├── __init__.py
    │   ├── plug_rules.py         # Environmental moving average rules
    │   └── scheduler.py          # Background periodic & timer scheduler
    ├── services/
    │   └── smart_plug_service.py # python-kasa TPAP hardware communicator
    └── templates/
        └── dashboard.html        # Real-time dashboard with Settings Panel
```

---

## Active Automation Rules (All UI-Tweakable)

| # | Device | Condition / Rule | Default Threshold | Tweakable via UI |
|---|--------|------------------|-------------------|-------------------|
| 1 | 💨 Humidifier | Turn ON if humidity is low | `< 93.0%` | ✅ `humidifier_humid_low` |
| 2 | 💨 Humidifier | Turn OFF if humidity is high | `> 96.0%` | ✅ `humidifier_humid_high` |
| 3 | 🌱 Water Sprinkler | Scheduled irrigation cycle | 5 mins ON every 2 hours | ✅ Interval & Duration |
| 4 | ❄️ Air Conditioner | Turn ON if temperature is high | `> 26.0°C` | ✅ `ac_temp_high` |
| 5 | ❄️ Air Conditioner | Turn OFF if temperature cooled | `< 23.0°C` | ✅ `ac_temp_low` |
| 6 | 🔥 Space Heater | Turn ON if cold, latching until target | ON if `< 22.0°C`, OFF at `>= 26.0°C` | ✅ Low & High Temp |
| 7 | 🌀 Fan (Humidity) | Turn ON for exhaust if humidity high | ON for 3 mins if `> 96.0%` | ✅ Trigger % & Duration |
| 8 | 🌀 Fan (Scheduled) | Periodic air circulation | 5 mins ON every 4 hours | ✅ Interval & Duration |
| 9 | ⚡ Safety Interlock | AC and Heater mutual exclusion | Never run simultaneously | ✅ Auto-enforced |

---

## Progress Tracker

| # | Step | Status |
|---|------|--------|
| 1.1 | Verify ESP32 on COM15 | ✅ Done — COM15 confirmed |
| 1.2 | Find laptop IPv4 address | ✅ Done — **192.168.1.2** |
| 1.3 | Install Arduino CLI | ✅ Done |
| 1.4 | Install ESP32 board support & DHT library | ✅ Done |
| 2.1 | Erase ESP32 flash memory | ✅ Done |
| 2.2 | Edit Arduino sketch (Wi-Fi credentials) | ✅ Done — SSID `"WIFI"`, IP `"192.168.1.2"` |
| 2.3 | Compile & upload sketch | ✅ Done |
| 2.4 | Verify via Serial Monitor | ✅ Done — 27.70°C, 59.00% confirmed |
| 3.1 | Install Python packages | ✅ Done (`fastapi`, `uvicorn`, `aiosqlite`, `jinja2`) |
| 3.2 | Start FastAPI server | ✅ Done (`uvicorn main:app --host 0.0.0.0 --port 8000`) |
| 3.3 | Configure Windows Firewall | ✅ Done — Port 8000 allowed |
| 3.4 | Open dashboard in browser | ✅ Done — `http://localhost:8000` |
| 4.1 | Tapo Smart Plug Integration | ✅ Done — Registered Sprinkler, AC, Heater, Humidifier, Fan |
| 4.2 | Implement 8 Automation Rules | ✅ Done — Temperature, Humidity, and Timed Schedules |
| 4.3 | UI Settings Configuration Panel | ✅ Done — Live threshold tweaking & persistent SQLite table storage |
| 4.4 | Persistent SQL Tables for Automation | ✅ Done — `automation_settings` & `automation_rules` in `sensor_data.db` |
| 5 | Integration & Independent Power Test | 🔲 Next: test independent power bank & hardware plug verification |

---

## Configuration Values

| Value | Status | Set To |
|-------|--------|--------|
| `WIFI_SSID` | ✅ Set | `"WIFI"` |
| `WIFI_PASSWORD` | ✅ Set | `"electrostatic"` |
| `SERVER_IP` | ✅ Set | `"192.168.1.2"` |
| `SERVER_PORT` | ✅ Set | `8000` |
| `DHT_PIN` | ✅ Set | GPIO27 |
| COM Port | ✅ Confirmed | COM15 |
| Conda Env | ✅ Confirmed | `arduino-env` |
| Humidifier Default IP | ✅ Configured | `192.168.1.17` (`TAPO_HUMIDIFIER_IP`) |
| Fan Default IP | ✅ Configured | `192.168.1.18` (`TAPO_FAN_IP`) |
