/*
 * ESP32 + DHT22 Wireless Temperature & Humidity Logger
 * 
 * This sketch reads temperature (°C) and humidity (%) from a DHT22 sensor
 * every 5 seconds and sends the data via HTTP POST to a FastAPI server
 * running on your Windows laptop over the local Wi-Fi network.
 * 
 * WIRING:
 *   DHT22 V182 Breakout Board:
 *     +    → ESP32 3.3V (or 5V)
 *     −    → ESP32 GND
 *     OUT  → ESP32 GPIO27 (D27)
 *
 * ========== YOU MUST EDIT THESE VALUES ==========
 */

// ─── Wi-Fi Credentials ──────────────────────────────────────
// Replace with YOUR Wi-Fi network name and password
const char* WIFI_SSID     = "WIFI";      // ← Change this
const char* WIFI_PASSWORD  = "";   // ← Change this

// ─── Server Settings ────────────────────────────────────────
// Replace with YOUR laptop's IPv4 address (run 'ipconfig' to find it)
const char* SERVER_IP   = "192.168.1.2";      // ← Your laptop's IPv4 address
const int   SERVER_PORT = 8000;               // ← Change if your server uses a different port

// ─── Sensor Settings ────────────────────────────────────────
#define DHT_PIN   27        // GPIO pin connected to DHT22 OUT
#define DHT_TYPE  DHT22     // Sensor type

// ─── Timing ─────────────────────────────────────────────────
const unsigned long SEND_INTERVAL_MS = 5000;  // Send readings every 5 seconds

// ═══════════════════════════════════════════════════════════
// DO NOT EDIT BELOW THIS LINE (unless you know what you're doing)
// ═══════════════════════════════════════════════════════════

#include <WiFi.h>
#include <HTTPClient.h>
#include <DHT.h>

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastSendTime = 0;
int  wifiRetryCount = 0;
bool wifiWasConnected = false;

// ─── Connect to Wi-Fi ───────────────────────────────────────
void connectToWiFi() {
  Serial.println();
  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(WIFI_SSID);
  
  WiFi.mode(WIFI_STA);        // Station mode (client)
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    wifiWasConnected = true;
    wifiRetryCount = 0;
    Serial.println();
    Serial.println("╔════════════════════════════════════╗");
    Serial.println("║      ✓ Wi-Fi CONNECTED!            ║");
    Serial.print(  "║  IP Address: ");
    Serial.print(WiFi.localIP());
    Serial.println("       ║");
    Serial.print(  "║  Signal (RSSI): ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm        ║");
    Serial.println("╚════════════════════════════════════╝");
  } else {
    Serial.println();
    Serial.println("✗ Wi-Fi connection FAILED!");
    Serial.println("  Check your SSID and password.");
    Serial.println("  Make sure your router is on and broadcasting 2.4 GHz.");
  }
}

// ─── Send data to the server ────────────────────────────────
void sendDataToServer(float temperature, float humidity) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("✗ Wi-Fi not connected. Attempting to reconnect...");
    connectToWiFi();
    if (WiFi.status() != WL_CONNECTED) {
      return;  // Still not connected, skip this reading
    }
  }
  
  // Build the server URL
  String url = "http://" + String(SERVER_IP) + ":" + String(SERVER_PORT) + "/api/readings";
  
  // Build JSON payload
  String jsonPayload = "{\"temperature\":" + String(temperature, 2) + 
                        ",\"humidity\":" + String(humidity, 2) + "}";
  
  Serial.print("Sending to: ");
  Serial.println(url);
  Serial.print("  Payload: ");
  Serial.println(jsonPayload);
  
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);  // 5-second timeout
  
  int httpResponseCode = http.POST(jsonPayload);
  
  if (httpResponseCode > 0) {
    String response = http.getString();
    Serial.print("  ✓ Server response (HTTP ");
    Serial.print(httpResponseCode);
    Serial.print("): ");
    Serial.println(response);
  } else {
    Serial.print("  ✗ HTTP Error: ");
    Serial.println(httpResponseCode);
    Serial.println("    Check that the server is running and the IP address is correct.");
    Serial.println("    Check Windows Firewall is allowing port " + String(SERVER_PORT) + ".");
  }
  
  http.end();
}

// ─── SETUP ──────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  delay(1000);  // Give serial monitor time to open
  
  Serial.println();
  Serial.println("═══════════════════════════════════════════");
  Serial.println("  ESP32 + DHT22 Wireless Logger Starting  ");
  Serial.println("═══════════════════════════════════════════");
  Serial.print("  DHT22 on GPIO: ");
  Serial.println(DHT_PIN);
  Serial.print("  Server target: ");
  Serial.print(SERVER_IP);
  Serial.print(":");
  Serial.println(SERVER_PORT);
  Serial.println("═══════════════════════════════════════════");
  
  // Initialize DHT sensor
  dht.begin();
  Serial.println("✓ DHT22 sensor initialized.");
  
  // Connect to Wi-Fi
  connectToWiFi();
}

// ─── LOOP ───────────────────────────────────────────────────
void loop() {
  unsigned long currentTime = millis();
  
  // Only send at the configured interval
  if (currentTime - lastSendTime >= SEND_INTERVAL_MS) {
    lastSendTime = currentTime;
    
    // Read sensor data
    float humidity    = dht.readHumidity();
    float temperature = dht.readTemperature();  // Celsius
    
    // Check if readings are valid
    if (isnan(humidity) || isnan(temperature)) {
      Serial.println("✗ Failed to read from DHT22 sensor!");
      Serial.println("  Check wiring: OUT→GPIO27, +→3.3V, −→GND");
      return;
    }
    
    // Print readings to Serial Monitor
    Serial.println("─── Sensor Reading ───────────────────────");
    Serial.print("  Temperature: ");
    Serial.print(temperature, 2);
    Serial.println(" °C");
    Serial.print("  Humidity:    ");
    Serial.print(humidity, 2);
    Serial.println(" %");
    
    // Send to server
    sendDataToServer(temperature, humidity);
    Serial.println();
  }
}
