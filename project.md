# Project: ESP32 + DHT22 Wireless Temperature and Humidity Logger

I am an absolute beginner working on a temperature and humidity monitoring project. I am using a Windows laptop.

## 1. My Hardware

- An ESP32 development board with Wi-Fi and Bluetooth, featuring a USB-C connector. (Connects with esp32 dev module)
- A DHT22 temperature and humidity sensor soldered to a small breakout board marked V182. The breakout has `+`, `−`, and `OUT` connections.
- A Windows laptop.
- A USB cable for programming and initially powering the ESP32.
- A home Wi-Fi network.

## 2. My Project Goal

I want to continuously measure temperature and relative humidity using the DHT22 and receive the readings wirelessly on my Windows laptop.

I have chosen **Option : Local Wi-Fi**.

The ESP32 and laptop will connect to the same Wi-Fi network. The ESP32 will send measurements to a Python server running on my laptop. The Python server will save readings to a local SQLite database.

I want to view the current temperature and humidity, as well as historical measurements, using a browser dashboard on my laptop.

The project should work without keeping the ESP32 connected to the laptop by USB after the program has been uploaded. I should be able to power the ESP32 separately, provided it can connect to the same Wi-Fi network and the laptop's server is running.

The laptop must remain on and the Python server must remain running to receive and store the readings.

I may eventually want remote access over the internet, but do not implement cloud or public internet access yet. First, help me complete and test the local Wi-Fi version.

## 3. What I Have Completed

-nothing

## 4. Desired System Architecture

Help me build this system:

**DHT22 → ESP32 → Home Wi-Fi router → Python server on Windows laptop → SQLite database → Browser dashboard**

Requirements:

1. Read temperature in Celsius and relative humidity approximately every 5 seconds.
2. Connect the ESP32 to my 2.4 GHz Wi-Fi network.
3. Send readings to my laptop using a simple local-network protocol such as HTTP.
4. Run a Python server on Windows, preferably using FastAPI.
5. Store each valid measurement in SQLite with a timestamp.
6. Create a simple browser dashboard that displays the latest temperature, humidity, and recent history.
7. Allow me to open the dashboard from my laptop and, if possible, another device connected to the same Wi-Fi.
8. Explain how to stop and restart the logger without losing previously stored readings.
9. Help me troubleshoot Wi-Fi, COM port, firewall, Python, sensor, and database errors.
10. Keep the project beginner-friendly, inexpensive, and locally hosted.

## 5. How I Want You to Guide Me

Treat me as someone with no previous experience in Python, networking, web servers, or databases.

Give me detailed, sequential instructions. For each step:

- Explain what we are doing and why.
- Tell me exactly which application to open and which menu or button to use.
- Provide complete code that I can copy and paste.
- Explain which values I must customize, such as Wi-Fi credentials, laptop IP address, GPIO pin, or API key.
- Tell me how to run the code and what output I should expect.
- Include troubleshooting instructions for common errors.
- Do not assume I know how to use Command Prompt, install Python packages, find a local IP address, or configure Windows Firewall.
- Avoid skipping ahead. Give me one manageable stage at a time and ask me to confirm that it works before proceeding.

Use secure, sensible local-network practices. Do not expose an unauthenticated server to the public internet or ask me to share my Wi-Fi password or other secrets.

## 6. Where to Begin

Start by helping me prepare my Windows laptop for the local Wi-Fi version.
(for python use the conda enviroment "arduino-env")
I need to:
1. make sure the required libraries are installed if not install them and make sure you can see my esp32 on COM-15
2. reset and wipe off any and all data and code from my esp32 connected via usb.
3. program it with a base code with an ability to connect to a wifi network and send the required temp and humidity data and print them in the serial monitor to confirm.
4. Find my laptop's local IPv4 address.
5. Set up Python and install the necessary packages.
6. Create a FastAPI server that accepts ESP32 measurements.
7. Create the SQLite database and table.
8. Test that the server and dashboard work on my laptop.
9. Modify my existing Arduino sketch to connect to Wi-Fi and send readings to the server.
10. Test that measurements are being received and saved.
11. Finally, disconnect the ESP32 from USB, power it independently, and verify that wireless logging continues.

Please begin with the first step and guide me through the entire project in order.