# 🌡️ ESP32 + DHT22 Wireless Logger — Step-by-Step Setup Guide

> **Last updated:** 2026-10-25 00:36 IST  
> ✅ = Completed | 🔲 = Pending | ▶️ = Current step

---

## 📍 Phase 1: Prepare Your Laptop

### ✅ Step 1.1 — Verify ESP32 on COM15
**Result:** ESP32 detected on **COM15**. ✓

### ✅ Step 1.2 — Find Your Laptop's IPv4 Address
**Result:** IPv4 = **192.168.1.2** ✓

### ✅ Step 1.3 — Install Arduino CLI
**Result:** Arduino CLI installed. ✓

---

### ✅ Step 1.4 — Install ESP32 Board Support & Libraries
**Result:** ESP32 board support and DHT library installed. ✓

**What:** Download the ESP32 compiler and the DHT22 sensor library.

**How — Run each command one at a time:**

```
arduino-cli config init
```
```
arduino-cli config add board_manager.additional_urls https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```
```
arduino-cli core update-index
```
```
arduino-cli core install esp32:esp32
```

*(This downloads ~300 MB — may take several minutes)*

Then install the sensor library:
```
arduino-cli lib install "DHT sensor library" "Adafruit Unified Sensor"
```

---

## 📍 Phase 2: Erase & Program the ESP32

### ✅ Step 2.1 — Erase ESP32 Flash Memory
**Result:** Flash erased successfully. ✓

---

### ✅ Step 2.2 — Edit Arduino Sketch (Wi-Fi Credentials)
**Result:** All values set in `esp32_sketch.ino` ✓
- SSID: `"WIFI"`
- Password: `"electrostatic"`
- Server IP: `"192.168.1.2"`
- Server Port: `8000`
- DHT Pin: GPIO27

---

### ✅ Step 2.3 — Compile & Upload the Sketch
**Result:** Compiled and uploaded successfully. ✓

---

### ✅ Step 2.4 — Verify via Serial Monitor
**Result:** Sensor reading confirmed — **27.70°C, 59.00%**. HTTP Error -1 expected (server not running yet). ✓

---

### 🔲 Step 2.4 — Verify via Serial Monitor

```
arduino-cli monitor --port COM15 --config baudrate=115200
```

**Expected (success):**
```
✓ Wi-Fi CONNECTED!
  IP Address: 192.168.1.XXX
─── Sensor Reading ───────────────────
  Temperature: 25.30 °C
  Humidity:    48.50 %
  ✗ HTTP Error: -1       ← Normal! Server isn't running yet
```

Press `Ctrl+C` to exit.

---

## 📍 Phase 3: Set Up the Python Server

### ▶️ Step 3.1 — Install Python Packages

**How — Open Anaconda Prompt:**
```
conda activate arduino-env
pip install fastapi uvicorn aiosqlite jinja2 python-multipart
```

---

### 🔲 Step 3.2 — Start the Server

```
conda activate arduino-env
cd G:\ESP32_WiFi_DHT22\server
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected:**
```
ESP32 DHT22 Sensor Logger — Server Starting
✓ Database ready at: G:\ESP32_WiFi_DHT22\server\sensor_data.db
INFO:     Uvicorn running on http://0.0.0.0:8000
```

> **Keep this window open!** Server stops if you close it.

---

### 🔲 Step 3.3 — Windows Firewall

When starting the server, Windows may show a firewall popup → click **Allow access**.

If no popup:
1. `Win` → search **Windows Defender Firewall** → open it
2. **Advanced settings** → **Inbound Rules** → **New Rule**
3. **Port** → **TCP** → **8000** → **Allow** → Name: `ESP32 Sensor Logger`

---

### 🔲 Step 3.4 — Open the Dashboard

Open browser → **http://localhost:8000**

From phone/other device: **http://192.168.1.2:8000**

---

## 📍 Phase 4: Integration Test

With both server running and ESP32 powered:
- Server terminal shows: `📡 Received: 25.30°C, 48.50%  [id=1]`
- Dashboard shows live temperature, humidity, chart, and table
- Green "Receiving data" badge appears

---

## 📍 Phase 5: Independent Power

1. Unplug ESP32 from laptop USB
2. Plug into USB phone charger or power bank
3. Dashboard should continue showing new readings

---

## 🔄 Stop & Restart

| Action | Command | Data Lost? |
|--------|---------|-----------|
| Stop server | `Ctrl+C` in Anaconda Prompt | No |
| Restart server | Re-run `uvicorn` command | No |
| Reset ESP32 | Press **RST** button | No |
| Clear all data | Delete `server\sensor_data.db` | Yes |

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---------|-----|
| No COM port | Different USB cable, install CP210x/CH340 driver |
| "Failed to connect" | Hold **BOOT** button during upload |
| Wi-Fi won't connect | Check SSID/password, must be 2.4 GHz |
| HTTP Error -1 | Server not running, wrong IP, or firewall |
| Dashboard "Waiting for data" | Check both ESP32 serial output and server terminal |
| `ModuleNotFoundError` | `pip install fastapi uvicorn aiosqlite jinja2` |
| Port 8000 in use | Use `--port 8001` and update `SERVER_PORT` in sketch |
