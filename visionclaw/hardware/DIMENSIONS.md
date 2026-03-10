# VisionClaw Frame — Dimensions & Assembly Reference

## Frame Overview (3 Printable Pieces)

```
          ┌──────────── 142mm total width ────────────┐
          │                                            │
    ┌─────┼─── LEFT TEMPLE ───┐ ┌ FRONT ┐ ┌─── RIGHT TEMPLE ───┼─────┐
    │     │  140mm long       │ │       │ │  140mm long         │     │
    │     │  Battery + Charger│ │ 38mm  │ │  MCU + Amp + Bone   │     │
    │     │                   │ │ tall  │ │                     │     │
    └─────┘                   └─┘       └─┘                     └─────┘
      ▲ ear hook                                          ear hook ▲
      │ bone cond.                                   bone cond.    │
```

## Piece 1: Front Frame

```
Width:  142mm
Height:  38mm (lens height 34mm + 2mm frame top + 2mm frame bottom)
Depth:   10mm (thicker than normal glasses — houses OLED & camera)

        ┌───────────────── 142mm ─────────────────┐
        │                                          │
        │   ┌─ OLED ─┐        ┌── Camera ─┐ LED   │
   38mm │   │ pocket  │  bridge │  10mm hole│  ●    │
        │   └─────────┘  18mm  └───────────┘       │
        │                                          │
        │  ┌── 52mm ──┐       ┌── 52mm ──┐        │
        │  │ Left Lens │       │Right Lens│        │
        │  │  Opening  │       │ Opening  │        │
        │  └───────────┘       └──────────┘        │
        │                                          │
        │ [hinge slot]                [hinge slot]  │
        └──────────────────────────────────────────┘
```

### Front Frame Cavities

| Feature            | Size                   | Position                              |
| ------------------ | ---------------------- | ------------------------------------- |
| Left lens opening  | 52 x 34mm              | Center-left, 9mm from left edge       |
| Right lens opening | 52 x 34mm              | Center-right, 9mm from right edge     |
| Bridge             | 18mm wide              | Center between lenses                 |
| Camera hole        | 10mm dia, through-hole | Right side, 4mm from edge, above lens |
| Privacy LED hole   | 6mm dia, through-hole  | 10mm left of camera                   |
| OLED pocket        | 28 x 28 x 4.5mm        | Above left lens, rear-facing          |
| Beam splitter slot | 26 x 26 x 2.5mm        | Inside left lens area, 45° angle      |
| Hinge slots        | 30 x 5 x 2.5mm         | Both sides, bottom rear               |
| Hinge screw holes  | 1.4mm dia              | Through each hinge slot               |

## Piece 2: Right Temple (Electronics)

```
     HINGE END                                    EAR END
     ┌─────────────────── 140mm ───────────────────────┐
     │                                                  │
     │  ┌─XIAO──┐ ┌IMU┐ ┌──AMP───┐    ┌──BONE──┐     │
     │  │21x17.5│ │14 │ │ 25x18  │    │ 25mm ◎ │     │
22mm │  │  x7mm │ │x14│ │  x3mm  │    │  x8mm  │     │
     │  └───────┘ └───┘ └────────┘    └────────┘     │
     │    USB-C                                        │
     │    ▼ port                    wire channel ─────→│
     └─────────────────────────────────────────────────┘
     │← 12mm →│
        wide

Component positions from hinge end:
  XIAO ESP32-S3:    5mm — 27mm    (front of temple)
  IMU BHI260AP:    30mm — 45mm
  Wire channel:    top edge, full length
  MAX98357A Amp:   50mm — 77mm
  Bone conduction: 115mm — 140mm  (behind ear, touching skull)
  USB-C opening:   bottom face at XIAO position
```

### Right Temple Cavities

| Component       | Cavity Size       | From Hinge  | Notes                    |
| --------------- | ----------------- | ----------- | ------------------------ |
| XIAO ESP32-S3   | 22 x 18.5 x 8mm   | 5mm         | USB-C port faces down    |
| BHI260AP IMU    | 15 x 15 x 3.5mm   | 30mm        | Flat against inner wall  |
| MAX98357A Amp   | 26.4 x 18.8 x 4mm | 50mm        | Speaker wires exit rear  |
| Bone conduction | 26mm dia x 9mm    | 115mm       | Flat face contacts skull |
| USB-C port      | 9 x 3.5mm hole    | At XIAO     | Bottom face of temple    |
| Wire channel    | 3mm dia tube      | Full length | Top inner edge           |

## Piece 3: Left Temple (Power)

```
     HINGE END                                    EAR END
     ┌─────────────────── 140mm ───────────────────────┐
     │                                                  │
     │  ┌──── BATTERY ─────────┐  ┌─TP4056──┐         │
22mm │  │  50 x 25 x 3.5mm    │  │ 25x19mm │  USB-C  │
     │  │  400mAh LiPo         │  │ charger │  port → │
     │  └──────────────────────┘  └─────────┘         │
     │                                                  │
     │              wire channel ─────────────→         │
     └─────────────────────────────────────────────────┘

Component positions from hinge end:
  Battery:   10mm — 61mm   (main cavity, centered)
  TP4056:    80mm — 106mm  (charge controller)
  USB-C:     temple end    (exposed for charging)
  Wire ch:   top edge, full length
```

### Left Temple Cavities

| Component      | Cavity Size     | From Hinge  | Notes                  |
| -------------- | --------------- | ----------- | ---------------------- |
| 400mAh LiPo    | 51 x 25 x 4.5mm | 10mm        | Fills temple width     |
| TP4056 charger | 26 x 20 x 4.5mm | 80mm        | USB-C faces temple end |
| Charge port    | 9 x 3.5mm hole  | 140mm       | End of temple, exposed |
| Wire channel   | 3mm dia tube    | Full length | Top inner edge         |

## Assembly Order

1. Print all 3 pieces in PETG (see settings below)
2. Wet sand: 200 → 400 → 800 grit
3. Insert spring hinges into front frame slots, secure with M1.4 screws
4. Solder wiring harness:
   - XIAO → camera (ribbon cable, already connected)
   - XIAO → MAX98357A amp (I2S: BCLK, LRCLK, DIN, VIN, GND)
   - XIAO → BHI260AP IMU (I2C: SDA, SCL, VIN, GND)
   - XIAO → Privacy LED (GPIO 2 → 220Ω → LED → GND)
   - Battery → TP4056 → XIAO (power circuit)
   - MAX98357A → Bone conduction exciter (speaker+ and speaker-)
5. Route wires through wire channels
6. Seat all components in cavities (friction fit, dab of hot glue)
7. Attach temples to front frame via hinges
8. Optional: XTC-3D epoxy coat for smooth finish
9. Optional: Spray paint (automotive primer + matte clear coat)

## PETG Print Settings

| Setting      | Value                               |
| ------------ | ----------------------------------- |
| Material     | PETG (Overture recommended)         |
| Nozzle temp  | 235°C                               |
| Bed temp     | 85°C                                |
| Layer height | 0.15mm                              |
| Walls        | 4 perimeters                        |
| Infill       | 30% gyroid                          |
| Speed        | 40 mm/s                             |
| Fan          | 15%                                 |
| Retraction   | 6.5mm @ 25mm/s                      |
| Supports     | Tree (for lens openings & cavities) |

### Print Orientation

- **Front frame**: upright (lens openings facing you), supports under bridge
- **Temples**: flat on long side, cavity openings facing up
- **Print time**: ~2hr front + ~1.5hr each temple = ~5hr total
