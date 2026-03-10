/*
 * VisionClaw Firmware — XIAO ESP32-S3 Sense
 *
 * Streams camera frames + audio to OpenClaw Gateway via WebSocket.
 * Receives AI responses as audio/text for bone conduction + HUD.
 *
 * Hardware:
 *   - Seeed Studio XIAO ESP32-S3 Sense
 *   - OV2640 camera (built-in)
 *   - PDM microphone (built-in)
 *   - Optional: bone conduction exciter + MAX98357A
 *   - Optional: 0.96" OLED HUD
 *   - Privacy LED on GPIO 2
 *
 * IMPORTANT: Set Arduino IDE settings:
 *   Board: XIAO_ESP32S3
 *   PSRAM: OPI PSRAM
 *   Flash Mode: QIO 80MHz
 *   Partition: Huge APP (3MB No OTA)
 */

#include "esp_camera.h"
#include "WiFi.h"
#include "ArduinoWebsockets.h"
#include "esp_timer.h"
#include "driver/i2s.h"
#include "base64.h"

using namespace websockets;

// ═══════════════════════════════════════
// CONFIGURATION — EDIT THESE
// ═══════════════════════════════════════

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// OpenClaw Gateway WebSocket endpoint
const char* WS_SERVER = "ws://<your-domain>/ws/glasses";
// For local dev: "ws://192.168.1.100:18789/ws/glasses"

// Camera settings
#define FRAME_SIZE   FRAMESIZE_VGA   // 640x480 — good balance of quality/speed
#define JPEG_QUALITY 12              // 0-63, lower = better quality, more data
#define FRAME_RATE   2               // Frames per second to stream

// Privacy LED
#define PRIVACY_LED_PIN 2
#define CAMERA_ACTIVE   true

// ═══════════════════════════════════════
// XIAO ESP32-S3 Sense Camera Pins
// ═══════════════════════════════════════

#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM  10
#define SIOD_GPIO_NUM  40
#define SIOC_GPIO_NUM  39
#define Y9_GPIO_NUM    48
#define Y8_GPIO_NUM    11
#define Y7_GPIO_NUM    12
#define Y6_GPIO_NUM    14
#define Y5_GPIO_NUM    16
#define Y4_GPIO_NUM    18
#define Y3_GPIO_NUM    17
#define Y2_GPIO_NUM    15
#define VSYNC_GPIO_NUM 38
#define HREF_GPIO_NUM  47
#define PCLK_GPIO_NUM  13

// ═══════════════════════════════════════
// GLOBALS
// ═══════════════════════════════════════

WebsocketsClient ws;
bool wsConnected = false;
unsigned long lastFrameTime = 0;
unsigned long frameInterval = 1000 / FRAME_RATE;
int reconnectAttempts = 0;

// ═══════════════════════════════════════
// CAMERA INIT
// ═══════════════════════════════════════

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0       = Y2_GPIO_NUM;
  config.pin_d1       = Y3_GPIO_NUM;
  config.pin_d2       = Y4_GPIO_NUM;
  config.pin_d3       = Y5_GPIO_NUM;
  config.pin_d4       = Y6_GPIO_NUM;
  config.pin_d5       = Y7_GPIO_NUM;
  config.pin_d6       = Y8_GPIO_NUM;
  config.pin_d7       = Y9_GPIO_NUM;
  config.pin_xclk     = XCLK_GPIO_NUM;
  config.pin_pclk     = PCLK_GPIO_NUM;
  config.pin_vsync    = VSYNC_GPIO_NUM;
  config.pin_href     = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn     = PWDN_GPIO_NUM;
  config.pin_reset    = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode    = CAMERA_GRAB_LATEST;

  // Use PSRAM for frame buffer
  if (psramFound()) {
    config.frame_size   = FRAME_SIZE;
    config.jpeg_quality = JPEG_QUALITY;
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    Serial.println("[CAM] PSRAM found — using high quality");
  } else {
    config.frame_size   = FRAMESIZE_QVGA;
    config.jpeg_quality = 20;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
    Serial.println("[CAM] WARNING: No PSRAM! Enable OPI PSRAM in Arduino IDE");
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[CAM] Init failed: 0x%x\n", err);
    return false;
  }

  // Optimize sensor settings
  sensor_t* s = esp_camera_sensor_get();
  s->set_brightness(s, 1);
  s->set_saturation(s, 0);
  s->set_whitebal(s, 1);
  s->set_awb_gain(s, 1);
  s->set_exposure_ctrl(s, 1);
  s->set_aec2(s, 1);

  Serial.println("[CAM] Camera initialized OK");
  return true;
}

// ═══════════════════════════════════════
// WIFI
// ═══════════════════════════════════════

void initWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("[WIFI] Connecting");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WIFI] Connection failed!");
  }
}

// ═══════════════════════════════════════
// WEBSOCKET
// ═══════════════════════════════════════

void onMessageCallback(WebsocketsMessage message) {
  String data = message.data();
  Serial.printf("[WS] Received: %s\n", data.substring(0, 100).c_str());

  // TODO: Parse JSON response
  // - "response" type: play audio via I2S
  // - "hud" type: display text on OLED
  // - "command" type: execute device command (sleep, wake, etc.)
}

void onEventsCallback(WebsocketsEvent event, String data) {
  if (event == WebsocketsEvent::ConnectionOpened) {
    Serial.println("[WS] Connected to OpenClaw Gateway!");
    wsConnected = true;
    reconnectAttempts = 0;

    // Send handshake
    ws.send("{\"type\":\"handshake\",\"device\":\"visionclaw\",\"version\":\"0.1.0\",\"capabilities\":[\"camera\",\"microphone\",\"imu\"]}");
  }
  else if (event == WebsocketsEvent::ConnectionClosed) {
    Serial.println("[WS] Disconnected!");
    wsConnected = false;
  }
  else if (event == WebsocketsEvent::GotPing) {
    ws.pong();
  }
}

void connectWebSocket() {
  ws.onMessage(onMessageCallback);
  ws.onEvent(onEventsCallback);

  Serial.printf("[WS] Connecting to %s\n", WS_SERVER);
  ws.connect(WS_SERVER);
}

void reconnectWithBackoff() {
  // Exponential backoff: 1s, 2s, 4s, 8s, 16s, max 30s
  int delay_ms = min(1000 * (1 << reconnectAttempts), 30000);
  Serial.printf("[WS] Reconnecting in %dms (attempt %d)\n", delay_ms, reconnectAttempts + 1);
  delay(delay_ms);
  reconnectAttempts++;
  connectWebSocket();
}

// ═══════════════════════════════════════
// FRAME CAPTURE & STREAM
// ═══════════════════════════════════════

void captureAndStream() {
  if (!wsConnected) return;

  unsigned long now = millis();
  if (now - lastFrameTime < frameInterval) return;
  lastFrameTime = now;

  // Privacy LED on
  digitalWrite(PRIVACY_LED_PIN, HIGH);

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] Capture failed");
    return;
  }

  // Base64 encode the JPEG
  String b64 = base64::encode(fb->buf, fb->len);

  // Build JSON message
  String msg = "{\"type\":\"frame\",\"data\":\"";
  msg += b64;
  msg += "\",\"timestamp\":";
  msg += String(now);
  msg += ",\"resolution\":\"";
  msg += String(fb->width);
  msg += "x";
  msg += String(fb->height);
  msg += "\",\"size\":";
  msg += String(fb->len);
  msg += "}";

  // Send via WebSocket
  ws.send(msg);

  Serial.printf("[STREAM] Frame sent: %dx%d, %d bytes JPEG, %d bytes b64\n",
    fb->width, fb->height, fb->len, b64.length());

  esp_camera_fb_return(fb);

  // Privacy LED off (brief flash)
  digitalWrite(PRIVACY_LED_PIN, LOW);
}

// ═══════════════════════════════════════
// SETUP & LOOP
// ═══════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n╔══════════════════════════════════╗");
  Serial.println("║   VisionClaw v0.1.0              ║");
  Serial.println("║   OpenClaw Smart Glasses Firmware ║");
  Serial.println("╚══════════════════════════════════╝\n");

  // Privacy LED
  pinMode(PRIVACY_LED_PIN, OUTPUT);
  digitalWrite(PRIVACY_LED_PIN, LOW);

  // Check PSRAM
  if (psramFound()) {
    Serial.printf("[SYS] PSRAM: %d bytes free\n", ESP.getFreePsram());
  } else {
    Serial.println("[SYS] WARNING: No PSRAM detected! Enable OPI PSRAM in Arduino IDE.");
  }

  Serial.printf("[SYS] Free heap: %d bytes\n", ESP.getFreeHeap());

  // Init camera
  if (!initCamera()) {
    Serial.println("[FATAL] Camera init failed. Halting.");
    while (1) delay(1000);
  }

  // Init WiFi
  initWiFi();

  // Connect to OpenClaw Gateway
  if (WiFi.status() == WL_CONNECTED) {
    connectWebSocket();
  }
}

void loop() {
  // Maintain WebSocket
  if (wsConnected) {
    ws.poll();
    captureAndStream();
  } else if (WiFi.status() == WL_CONNECTED) {
    reconnectWithBackoff();
  } else {
    // WiFi dropped — reconnect
    Serial.println("[WIFI] Lost connection, reconnecting...");
    initWiFi();
  }

  // Small delay to prevent watchdog
  delay(10);
}
