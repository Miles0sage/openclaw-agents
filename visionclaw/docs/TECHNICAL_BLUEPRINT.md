# VisionClaw — Technical Engineering Framework for Agentic DIY Smart Glasses

**Sub-project of OpenClaw | Open Source**

## Architecture Overview

VisionClaw is an open-source smart glasses platform that turns a $15 microcontroller into an AI-powered wearable. The glasses stream video and audio to the OpenClaw gateway, which orchestrates distributed AI models for real-time visual understanding, voice commands, and task execution.

```
[XIAO ESP32-S3] --WebSocket--> [OpenClaw Gateway] ---> [Groq STT/LLM]
   Camera + Mic                   /ws/glasses          [Gemini Vision]
   IMU + Bone Audio                                    [Memory/Skills]
```

---

## Hardware Platform

### Core: Seeed Studio XIAO ESP32-S3 Sense

| Spec          | Value                                 |
| ------------- | ------------------------------------- |
| Processor     | Dual-core Xtensa LX7 @ 240 MHz        |
| PSRAM         | 8 MB OPI (MUST enable in Arduino IDE) |
| Internal SRAM | 512 KB                                |
| Camera        | OV2640 2MP                            |
| Microphone    | Integrated PDM                        |
| Connectivity  | Wi-Fi 802.11 b/g/n, BLE 5.0           |
| Size          | 21x17.5mm                             |
| Price         | ~$15                                  |

### Bill of Materials

| Component               | Purpose                 | Est. Cost |
| ----------------------- | ----------------------- | --------- |
| XIAO ESP32-S3 Sense     | Main MCU + camera + mic | $15       |
| 400mAh LiPo battery     | Power (2-3hr runtime)   | $8        |
| Bone conduction exciter | Private audio output    | $12       |
| MAX98357A I2S amp       | Audio amplifier         | $4        |
| BHI260AP IMU breakout   | Gesture control         | $10       |
| 0.96" OLED (optional)   | HUD display             | $8        |
| Red LED + resistor      | Privacy indicator       | $0.50     |
| Generic eyeglass hinges | Frame mechanics         | $3        |
| **Total**               |                         | **~$60**  |

### Memory Management

Raw 2MP image in RGB565: `1600 x 1200 x 2 bytes = 3.84 MB`

Internal SRAM (512KB) is insufficient. **OPI PSRAM must be enabled** in Arduino IDE:

- Board: XIAO_ESP32S3
- PSRAM: OPI PSRAM
- Flash Mode: QIO 80MHz

### Sensor Fusion & EgoTrigger

| Sensor     | Component       | Function                       | Power              |
| ---------- | --------------- | ------------------------------ | ------------------ |
| Camera     | OV2640          | Visual context, OCR            | High (active only) |
| Microphone | Integrated PDM  | Voice commands, STT            | Moderate           |
| IMU        | BHI260AP        | Gesture control, head tracking | Low (always-on)    |
| Audio Out  | Bone conduction | Private AI responses           | Moderate           |

**EgoTrigger**: IMU detects head gestures (double-tap, head tilt) to wake camera + Wi-Fi from deep sleep. Extends battery from 2hr → 6-8hr for typical use.

---

## Software Architecture

### Firmware (ESP32-S3)

The firmware handles:

1. Camera capture → JPEG compression → WebSocket stream
2. PDM microphone → Opus encoding → WebSocket stream
3. IMU monitoring → gesture detection → wake triggers
4. I2S audio playback from AI responses
5. Wi-Fi management with exponential backoff

**WebSocket Protocol** to OpenClaw Gateway:

```json
// Glasses → Gateway (image frame)
{
  "type": "frame",
  "data": "<base64 JPEG>",
  "timestamp": 1709420000,
  "resolution": "640x480"
}

// Glasses → Gateway (audio chunk)
{
  "type": "audio",
  "data": "<base64 Opus>",
  "timestamp": 1709420000,
  "duration_ms": 250
}

// Glasses → Gateway (gesture)
{
  "type": "gesture",
  "gesture": "double_tap|head_nod|head_shake|look_up",
  "timestamp": 1709420000
}

// Gateway → Glasses (AI response audio)
{
  "type": "response",
  "audio": "<base64 PCM>",
  "text": "I can see a restaurant menu...",
  "action": null
}

// Gateway → Glasses (HUD text)
{
  "type": "hud",
  "text": "Meeting at 3pm",
  "duration_ms": 5000
}
```

### Backend: OpenClaw Gateway Integration

The gateway receives multimodal streams and orchestrates:

1. **STT** → Groq Whisper-v3 (sub-second latency)
2. **Vision** → Gemini 2.5 Flash or local Moondream via Ollama
3. **Reasoning** → Claude/GPT-4o for complex tasks
4. **Action** → OpenClaw skills (memory, scheduling, search, etc.)
5. **TTS** → ElevenLabs or local Piper for response audio

### Latency Targets

| Stage                              | Target   | Backend           |
| ---------------------------------- | -------- | ----------------- |
| Audio capture → STT                | < 500ms  | Groq Whisper-v3   |
| Image → Vision analysis            | < 1000ms | Gemini Flash      |
| Full round-trip (voice → response) | < 2000ms | Combined pipeline |

---

## Optical Engineering (Optional HUD)

### Prism-Based Display

Using a 0.96" OLED + magnifying lens + 45-degree beam splitter:

**Thin Lens Equation**: `1/f = 1/d_o + 1/d_i`

For focus-free HUD: place display at focal point (`d_o = f`), image appears at infinity.

### AMOLED Notes (T-Glass V2 / JD9613 driver)

- Only supports 1/2 screen RAM → no full-screen high-res
- No hardware rotation → must rotate in frame buffer (CPU cost)
- Consider starting camera-only, add HUD in v2

---

## 3D Printing: PETG Frame Fabrication

### Print Settings (Overture PETG)

| Parameter    | Value          | Why                          |
| ------------ | -------------- | ---------------------------- |
| Nozzle temp  | 230-240°C      | Layer bonding                |
| Bed temp     | 85-90°C        | Prevents warping             |
| Layer height | 0.15-0.2mm     | Surface finish vs speed      |
| Wall count   | 3-4 perimeters | Thin-wall strength           |
| Print speed  | 35-45 mm/s     | PETG needs slow for strength |
| Fan speed    | 0-20%          | Maintains tenacity           |
| Retraction   | 6.5mm @ 25mm/s | Reduces stringing            |

### Post-Processing

1. **Wet sanding**: 200 → 400 → 800 → 2000 grit
2. **Epoxy coat**: XTC-3D self-leveling for injection-mold finish
3. **Heat polish**: 230°C heat gun for micro-scratch removal
4. **Privacy LED**: Red LED on GPIO, active during camera capture

---

## 7-Day Build Sprint

| Day | Focus                                   | Deliverable                               |
| --- | --------------------------------------- | ----------------------------------------- |
| 1   | Hardware procurement + makerspace setup | Parts ordered, workspace ready            |
| 2   | Firmware flash + camera/Wi-Fi test      | Streaming JPEG to browser                 |
| 3   | CAD design + first PETG print           | Temple arms + front cover                 |
| 4   | OpenClaw gateway WebSocket endpoint     | Glasses → Gateway pipeline working        |
| 5   | STT/TTS + audio hardware                | Voice commands + bone conduction response |
| 6   | Field testing + thermal calibration     | Battery life + latency benchmarks         |
| 7   | Post-processing + UX polish             | Finished product                          |

---

## Arizona Resources

| Resource               | Location                      | Tools                                       |
| ---------------------- | ----------------------------- | ------------------------------------------- |
| Coco-op Makerspace     | 1155 W Kaibab Lane, Flagstaff | Prusa 3D printers, laser cutters, soldering |
| Flagstaff Tool Library | Via Coco-op membership        | Precision hand tools                        |
| Salter Lab (UA)        | AME Building, Tucson          | Reflow ovens, water jet cutting             |
| Phoenix Forge          | 535 W Van Buren St, Phoenix   | Advanced electronics lab                    |
| CREATE Makerspace      | AZ Science Center, Phoenix    | STEAM and rapid prototyping                 |

---

## Open Source Comparison

| Project        | MCU            | Display           | Software         | Integration              |
| -------------- | -------------- | ----------------- | ---------------- | ------------------------ |
| **VisionClaw** | XIAO ESP32-S3  | Optional OLED HUD | OpenClaw Gateway | Full agentic (75+ tools) |
| OpenGlass      | XIAO ESP32-S3  | None              | Node.js/Expo     | Groq, OpenAI             |
| T-Glass V2     | ESP32-S3 FN4R2 | 1.1" AMOLED       | ESP-IDF/LVGL     | BLE notifications        |
| eyeOS          | RPi/Jetson     | Various           | Python/YOLOv8    | Object detection         |

**VisionClaw's edge**: Direct integration with OpenClaw's 75+ agentic tools — not just vision/voice, but task execution, memory, scheduling, web search, trading, research, and more.
