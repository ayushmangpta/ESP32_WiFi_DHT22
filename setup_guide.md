# 🌡️ ESP32 + DHT22 Wireless Logger — Step-by-Step Setup Guide

> **Last updated:** 2026-10-25 00:36 IST  
> ✅ = Completed | 🔲 = Pending | ▶️ = Current step

---

## 📍 Phase 1: Prepare Your Laptop

### ✅ Step 1.1 — Verify ESP32 on COM15

**What:** Confirm Windows sees your ESP32 on COM15.

**How:**
1. Plug your ESP32 into your laptop via USB.
2. Press `Win + X` → Click **Device Manager**.
3. Expand **Ports (COM & LPT)**.
4. You should see something like:
   - `Silicon Labs CP210x USB to UART Bridge (COM15)` **or**
   - `USB-SERIAL CH340 (COM15)`

> [!TIP]
> If you see a different COM port number (e.g., COM3, COM7), note that number — you'll use it instead of COM15 in all commands below.

> [!WARNING]
> If you don't see any COM port:
> - Try a different USB cable (some cables are charge-only).
> - Install the driver: [CP210x driver](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) or [CH340 driver](https://www.wch-ic.com/downloads/CH341SER_ZIP.html).
**Result:** ESP32 detected on **COM15**. ✓
---

### ✅ Step 1.2 — Find Your Laptop's IPv4 Address

**What:** Find the IP address your ESP32 will use to send data to your laptop.

**How:**
1. Press `Win + R` → type `cmd` → press Enter.
2. In the black Command Prompt window, type:
   ```
   ipconfig
   ```
3. Look for the section titled **Wireless LAN adapter Wi-Fi** (or similar).
4. Find the line **IPv4 Address . . . : 192.168.X.X**
5. Write down this number. Example: `192.168.1.42`

> [!NOTE]
> If you're connected via Ethernet cable instead of Wi-Fi, look for **Ethernet adapter** instead.
> If you see multiple adapters, use the one that has a `192.168.x.x` or `10.x.x.x` address.
**Result:** IPv4 = **192.168.1.2** ✓
---

### ✅ Step 1.3 — Install Arduino CLI

**What:** Install the command-line tool for compiling and uploading Arduino code to your ESP32.

**How:**
1. Press `Win + R` → type `cmd` → press Enter.
2. Run:
   ```
   winget install ArduinoSA.CLI
   ```
3. **Close the Command Prompt** and open a **new** one (so it picks up the new PATH).
4. Verify it installed:
   ```
   arduino-cli version
   ```
   You should see something like `arduino-cli Version: 0.35.x`

> [!WARNING]
> If `winget` is not recognized, download Arduino CLI manually from:
> https://arduino.github.io/arduino-cli/latest/installation/
> Extract the `.zip` and add the folder to your system PATH.
**Result:** Arduino CLI installed. ✓
---

### ✅ Step 1.4 — Install ESP32 Board Support & Libraries
**What:** Download the ESP32 compiler toolchain and the DHT22 sensor library.

**How (run each command one at a time in Command Prompt):**

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

This last command downloads ~300 MB. It may take several minutes.

Then install the sensor library:
```
arduino-cli lib install "DHT sensor library" "Adafruit Unified Sensor"
```

**Expected output:** Each command should end without errors. The last one should say something like `Installed DHT sensor library`.

---

## 📍 Phase 2: Erase & Program the ESP32

### Step 2.1 — Erase ESP32 Flash Memory

**What:** Wipe all previous code and data from the ESP32 to start fresh.

**How:**
1. Open **Anaconda Prompt** (search for it in Start menu).
2. Activate your conda environment:
   ```
   conda activate arduino-env
   ```
3. Install the erase tool:
   ```
   pip install esptool
   ```
4. Erase the ESP32 (make sure it's plugged in via USB):
   ```
   python -m esptool --port COM15 erase_flash
   ```

**Expected output:**
```
Connecting...
Erasing flash (this may take a while)...
Chip erase completed successfully in X.Xs
```

> [!NOTE]
> Replace `COM15` with your actual port number from Step 1.1.
> If it says "Failed to connect": hold down the **BOOT** button on the ESP32 while running the command.

---

### Step 2.2 — Edit the Arduino Sketch

**What:** Set your Wi-Fi credentials and server IP in the code.

**How:**
1. Open the file `G:\ESP32_WiFi_DHT22\esp32_sketch\esp32_sketch.ino` in any text editor (Notepad, VS Code, etc.).
2. Find these three lines near the top and change them:

```cpp
const char* WIFI_SSID     = "YOUR_WIFI_SSID";      // ← Your Wi-Fi name
const char* WIFI_PASSWORD  = "YOUR_WIFI_PASSWORD";   // ← Your Wi-Fi password
const char* SERVER_IP   = "YOUR_LAPTOP_IP";          // ← IP from Step 1.2 (e.g., "192.168.1.42")
```

3. **Save** the file.

> [!CAUTION]
> Keep the quotation marks `"..."` around each value! The code won't work without them.
> Your Wi-Fi must be **2.4 GHz**. The ESP32 cannot connect to 5 GHz networks.

---

### Step 2.3 — Compile & Upload the Sketch

**What:** Compile the Arduino code and flash it to the ESP32.

**How (run in Command Prompt — NOT Anaconda Prompt):**

```
arduino-cli compile --fqbn esp32:esp32:esp32 G:\ESP32_WiFi_DHT22\esp32_sketch
```

**Expected output:** Should end with `Sketch uses X bytes (X%)...`

Then upload to the ESP32:
```
arduino-cli upload --fqbn esp32:esp32:esp32 --port COM15 G:\ESP32_WiFi_DHT22\esp32_sketch
```

**Expected output:** Should end with `Leaving... Hard resetting via RTS pin...`

> [!TIP]
> If upload fails with "Failed to connect", hold the **BOOT** button on the ESP32 while running the upload command. Release it when you see "Connecting..."

---

### Step 2.4 — Open Serial Monitor to Verify

**What:** Watch the ESP32's output to see if it connects to Wi-Fi and reads the sensor.

**How:**
```
arduino-cli monitor --port COM15 --config baudrate=115200
```

**Expected output (success):**
```
═══════════════════════════════════════════
  ESP32 + DHT22 Wireless Logger Starting  
═══════════════════════════════════════════
  DHT22 on GPIO: 27
  Server target: 192.168.1.42:8000
═══════════════════════════════════════════
✓ DHT22 sensor initialized.
Connecting to Wi-Fi: YourNetworkName
.....
╔════════════════════════════════════════╗
║      ✓ Wi-Fi CONNECTED!               ║
║  IP Address: 192.168.1.100            ║
║  Signal (RSSI): -45 dBm              ║
╚════════════════════════════════════════╝
─── Sensor Reading ───────────────────────
  Temperature: 25.30 °C
  Humidity:    48.50 %
```

You'll also see HTTP errors like `HTTP Error: -1` — that's normal! The Python server isn't running yet.

**Press `Ctrl+C` to exit** the serial monitor when you're satisfied.

---

## 📍 Phase 3: Set Up the Python Server

### Step 3.1 — Install Python Packages

**What:** Install FastAPI and other required Python packages in your conda environment.

**How:**
1. Open **Anaconda Prompt**.
2. Activate your environment:
   ```
   conda activate arduino-env
   ```
3. Install packages:
   ```
   pip install fastapi uvicorn aiosqlite jinja2 python-multipart
   ```

**Expected output:** Should end with `Successfully installed ...`

---

### Step 3.2 — Start the Server

**What:** Launch the Python server that receives data from the ESP32.

**How:**
```
conda activate arduino-env
cd G:\ESP32_WiFi_DHT22\server
uvicorn main:app --host 0.0.0.0 --port 8000
```

**Expected output:**
```
═══════════════════════════════════════════════
  ESP32 DHT22 Sensor Logger — Server Starting  
═══════════════════════════════════════════════
✓ Database ready at: G:\ESP32_WiFi_DHT22\server\sensor_data.db
  Existing readings in database: 0
  Dashboard: http://localhost:8000
  API endpoint: http://localhost:8000/api/readings
═══════════════════════════════════════════════

INFO:     Uvicorn running on http://0.0.0.0:8000
```

> [!IMPORTANT]
> **Keep this window open!** The server stops when you close it.
> The `--host 0.0.0.0` makes the server reachable from other devices on your Wi-Fi.

---

### Step 3.3 — Allow Through Windows Firewall

**What:** Windows Firewall may block the ESP32 from reaching your server. Let's allow it.

**How:**
1. When you start the server, Windows might show a firewall popup — click **Allow access**.
2. If no popup appeared, do it manually:
   - Press `Win` → search **Windows Defender Firewall** → Open it.
   - Click **Advanced settings** (left panel).
   - Click **Inbound Rules** → **New Rule** (right panel).
   - Select **Port** → **Next**.
   - Select **TCP** → **Specific local ports** → type `8000` → **Next**.
   - Select **Allow the connection** → **Next**.
   - Check all three (Domain, Private, Public) → **Next**.
   - Name it `ESP32 Sensor Logger` → **Finish**.

---

### Step 3.4 — Open the Dashboard

**What:** View your sensor data in a browser.

**How:**
1. Open your browser (Chrome, Edge, Firefox).
2. Go to: **http://localhost:8000**

You should see a beautiful dark dashboard with:
- Two large gauge cards (Temperature & Humidity) showing `--` until data arrives
- A chart section
- A readings table saying "Waiting for sensor data…"

> [!TIP]
> To view the dashboard from your **phone** or another device on the same Wi-Fi:
> Open `http://YOUR_LAPTOP_IP:8000` (e.g., `http://192.168.1.42:8000`).

---

## 📍 Phase 4: Integration Test

**What:** Verify the full system works end-to-end.

**How:**
1. Make sure the **Python server is running** (Step 3.2 terminal still open).
2. The **ESP32 should already be running** (it auto-starts after upload).
3. In the server terminal, you should start seeing:
   ```
   📡 Received: 25.30°C, 48.50%  [id=1]
   📡 Received: 25.31°C, 48.40%  [id=2]
   ```
4. In your browser at `http://localhost:8000`, the dashboard should now show:
   - ✅ Live temperature and humidity values
   - ✅ A chart with data points
   - ✅ A table of recent readings
   - ✅ Green "Receiving data" status badge

> [!WARNING]
> If you don't see readings after 30 seconds:
> 1. Check the ESP32 Serial Monitor — is it showing HTTP errors?
> 2. Verify the `SERVER_IP` in the sketch matches your laptop's IP (Step 1.2).
> 3. Verify port 8000 is allowed in Windows Firewall (Step 3.3).
> 4. Make sure both ESP32 and laptop are on the **same Wi-Fi network**.

---

## 📍 Phase 5: Independent Power

### Step 5.1 — Power ESP32 Without USB

1. Unplug the ESP32 from your laptop.
2. Plug the ESP32 into a **USB phone charger** or **power bank** using a USB cable.
3. The ESP32 will automatically boot, connect to Wi-Fi, and start sending data.
4. Check the dashboard — readings should continue arriving.

---

## 🔄 How to Stop and Restart

| Action | How | Data Loss? |
|--------|-----|-----------|
| **Stop the server** | Press `Ctrl+C` in the Anaconda Prompt | ❌ No — database is preserved |
| **Restart the server** | Re-run the `uvicorn` command (Step 3.2) | ❌ No — old readings are still there |
| **Reset the ESP32** | Press the **RST** button on the board | ❌ No — it reconnects and resumes |
| **Clear all data** | Delete `G:\ESP32_WiFi_DHT22\server\sensor_data.db` | ⚠️ Yes — starts fresh |

---

## 🛠️ Troubleshooting Quick Reference

| Problem | Fix |
|---------|-----|
| ESP32 not on any COM port | Try different USB cable, install CP210x/CH340 driver |
| "Failed to connect" during upload | Hold **BOOT** button, release after "Connecting…" |
| Wi-Fi won't connect | Check SSID/password are correct, must be 2.4 GHz |
| HTTP Error -1 in Serial Monitor | Server not running, wrong IP, or firewall blocking |
| Dashboard says "Waiting for data" | ESP32 not sending, or server not receiving — check both |
| `ModuleNotFoundError` in Python | Run `pip install fastapi uvicorn aiosqlite jinja2` again |
| Port 8000 already in use | Use `--port 8001` and update `SERVER_PORT` in the sketch |
