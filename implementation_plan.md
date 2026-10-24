# 🌡️ ESP32 + DHT22 Wireless Logger — Implementation Plan

> **Last updated:** 2026-10-25 00:36 IST

## Project Architecture

```
DHT22 Sensor ──OUT──→ ESP32 (GPIO27) ──Wi-Fi──→ Home Router ──→ FastAPI Server (Windows Laptop) ──→ SQLite DB ──→ Browser Dashboard
```

## File Structure

```
G:\ESP32_WiFi_DHT22\
├── project.md                    # Your project spec
├── implementation_plan.md        # This file
├── setup_guide.md                # Step-by-step walkthrough
├── esp32_sketch/
│   └── esp32_sketch.ino          # Arduino code for ESP32
└── server/
    ├── main.py                   # FastAPI server
    ├── database.py               # SQLite database setup
    ├── models.py                 # Data models
    └── templates/
        └── dashboard.html        # Browser dashboard
```

---

## Progress Tracker

| # | Step | Status |
|---|------|--------|
| 1.1 | Verify ESP32 on COM15 | ✅ Done — COM15 confirmed |
| 1.2 | Find laptop IPv4 address | ✅ Done — **192.168.1.2** |
| 1.3 | Install Arduino CLI | ✅ Done |
| 1.4 | Install ESP32 board support & DHT library | ✅ Done |
| 2.1 | Erase ESP32 flash memory | ✅ Done |
| 2.2 | Edit Arduino sketch (Wi-Fi credentials) | ✅ Done — SSID, password & IP all set |
| 2.3 | Compile & upload sketch | ✅ Done |
| 2.4 | Verify via Serial Monitor | ✅ Done — 27.70°C, 59.00% confirmed |
| 3.1 | Install Python packages | ▶️ Next step |
| 3.2 | Start FastAPI server | 🔲 Pending |
| 3.3 | Configure Windows Firewall | 🔲 Pending |
| 3.4 | Open dashboard in browser | 🔲 Pending |
| 4 | Integration test (end-to-end) | 🔲 Pending |
| 5 | Independent power (no USB) | 🔲 Pending |

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

---

## What Each File Does

| File | Role |
|------|------|
| `esp32_sketch.ino` | Reads DHT22 every 5s, connects Wi-Fi, HTTP POSTs JSON `{temperature, humidity}` to server |
| `main.py` | FastAPI app — `POST /api/readings` receives data, `GET /` serves dashboard |
| `database.py` | Async SQLite — auto-creates `sensor_data.db` and `readings` table |
| `models.py` | Pydantic schemas for request/response validation |
| `dashboard.html` | Dark-mode real-time dashboard with Chart.js graphs, auto-polls every 3s |
