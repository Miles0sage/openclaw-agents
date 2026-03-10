"""
VisionClaw Smart Glasses — Blender Frame Generator
====================================================

Opens Blender, paste this into Scripting tab, hit Run.
Generates a complete glasses frame with cavities for all electronics.

Export: File → Export → STL → Print at 100% scale

All dimensions in MILLIMETERS (Blender units set to mm).

Component Dimensions (real-world measured):
  XIAO ESP32-S3 Sense:  21.0 x 17.5 x 7.0 mm (with camera module)
  OV2640 Camera Module:  8.5 x  8.5 x 5.0 mm (on the XIAO board)
  400mAh LiPo Battery:  50.0 x 25.0 x 3.5 mm (LP502535 form factor)
  TP4056 USB-C Charger: 25.0 x 19.0 x 3.5 mm
  MAX98357A I2S Amp:    25.4 x 17.8 x 3.0 mm (Adafruit breakout)
  Bone Conduction Exciter: 25.0 dia x 8.0 mm (disc transducer)
  0.96" SSD1306 OLED:   27.0 x 27.0 x 4.0 mm (module with pins)
  OLED Screen Only:     23.7 x 12.8 x 1.5 mm
  BHI260AP IMU:         14.0 x 14.0 x 2.5 mm (breakout)
  Privacy LED:           5.0 dia x 2.0 mm
  Spring Hinges:        30.0 x  5.0 x 2.5 mm (each side)
  Beam Splitter Prism:  25.0 x 25.0 x 2.0 mm
  Magnifying Lens:      15.0 dia x 3.0 mm

Frame Dimensions (standard adult medium):
  Total width:         142.0 mm (face width)
  Lens width:           52.0 mm each
  Bridge width:         18.0 mm
  Temple length:       140.0 mm
  Front frame height:   38.0 mm
  Front frame depth:    10.0 mm (thicker than normal for electronics)
  Temple cross-section: 12.0 x 22.0 mm (wider than normal for components)
"""

import bpy
import bmesh
import math
from mathutils import Vector

# ═══════════════════════════════════════════════════════════
# CLEANUP — remove default objects
# ═══════════════════════════════════════════════════════════

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Set units to millimeters
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 0.001  # 1 unit = 1mm
bpy.context.scene.unit_settings.length_unit = 'MILLIMETERS'

# ═══════════════════════════════════════════════════════════
# DIMENSIONS (all in mm)
# ═══════════════════════════════════════════════════════════

# Overall frame
TOTAL_WIDTH = 142.0
LENS_W = 52.0
LENS_H = 34.0
BRIDGE_W = 18.0
FRAME_THICKNESS = 5.0  # plastic wall thickness
FRAME_DEPTH = 10.0     # front-to-back

# Temples (arms)
TEMPLE_LENGTH = 140.0
TEMPLE_W = 12.0        # wider than normal for electronics
TEMPLE_H = 22.0        # taller than normal for battery
TEMPLE_WALL = 2.0      # wall thickness of temple shell
TEMPLE_TIP_CURVE = 35.0  # curve length behind ear
TEMPLE_TAPER_START = 100.0  # where temple starts narrowing

# Hinge
HINGE_L = 30.0
HINGE_W = 5.0
HINGE_H = 2.5
HINGE_SCREW_DIA = 1.4  # M1.4 screw

# Component cavities (with 0.5mm tolerance on each side)
TOL = 0.5

# XIAO ESP32-S3 — right temple, near hinge
XIAO_W = 21.0 + TOL*2   # 22.0
XIAO_D = 17.5 + TOL*2   # 18.5
XIAO_H = 7.0 + TOL*2    # 8.0

# Battery — left temple, main cavity
BATT_W = 50.0 + TOL*2   # 51.0
BATT_D = 25.0            # fills temple width
BATT_H = 3.5 + TOL*2    # 4.5

# TP4056 charger — left temple end
TP4056_W = 25.0 + TOL*2
TP4056_D = 19.0 + TOL*2
TP4056_H = 3.5 + TOL*2

# MAX98357A amp — right temple, behind XIAO
AMP_W = 25.4 + TOL*2
AMP_D = 17.8 + TOL*2
AMP_H = 3.0 + TOL*2

# Bone conduction — right temple tip
BONE_DIA = 25.0 + TOL*2
BONE_H = 8.0 + TOL*2

# IMU — right temple, between XIAO and amp
IMU_W = 14.0 + TOL*2
IMU_D = 14.0 + TOL*2
IMU_H = 2.5 + TOL*2

# OLED module — left side of front frame
OLED_W = 27.0 + TOL*2
OLED_D = 27.0 + TOL*2
OLED_H = 4.0 + TOL*2

# Privacy LED — right side front, next to camera
LED_DIA = 5.0 + TOL*2
LED_H = 2.0 + TOL*2

# Beam splitter — left lens area
PRISM_W = 25.0 + TOL*2
PRISM_D = 25.0 + TOL*2
PRISM_H = 2.0 + TOL*2

# Wire channels
WIRE_DIA = 3.0  # channel diameter for wire routing


# ═══════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════

def create_box(name, w, d, h, location=(0,0,0), color=(0.2, 0.2, 0.2, 1.0)):
    """Create a box mesh with given dimensions centered at location."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (w/2, d/2, h/2)
    bpy.ops.object.transform_apply(scale=True)

    # Material
    mat = bpy.data.materials.new(name=f"mat_{name}")
    mat.diffuse_color = color
    obj.data.materials.append(mat)

    return obj

def create_cylinder(name, dia, h, location=(0,0,0), color=(0.2, 0.2, 0.2, 1.0)):
    """Create a cylinder with given diameter and height."""
    bpy.ops.mesh.primitive_cylinder_add(radius=dia/2, depth=h, location=location)
    obj = bpy.context.active_object
    obj.name = name

    mat = bpy.data.materials.new(name=f"mat_{name}")
    mat.diffuse_color = color
    obj.data.materials.append(mat)

    return obj

def boolean_subtract(target_name, cutter_name):
    """Boolean difference: subtract cutter from target."""
    target = bpy.data.objects[target_name]
    cutter = bpy.data.objects[cutter_name]

    mod = target.modifiers.new(name=f"cut_{cutter_name}", type='BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter

    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)

    # Hide cutter
    cutter.hide_set(True)
    cutter.hide_render = True


# ═══════════════════════════════════════════════════════════
# BUILD THE FRAME — 3 PIECES
# ═══════════════════════════════════════════════════════════

# Color codes
FRAME_COLOR = (0.08, 0.08, 0.08, 1.0)   # matte black
CAVITY_COLOR = (1.0, 0.3, 0.1, 0.5)      # orange = cut cavity
COMPONENT_COLOR = (0.1, 0.7, 0.3, 0.8)   # green = component preview

# ─────────────────────────────────────────
# PIECE 1: FRONT FRAME
# ─────────────────────────────────────────

# Main front frame body (rectangular, will be refined)
front = create_box(
    "Front_Frame",
    w=TOTAL_WIDTH,
    d=FRAME_DEPTH,
    h=LENS_H + FRAME_THICKNESS*2,
    location=(0, 0, 0),
    color=FRAME_COLOR
)

# Cut out left lens opening
lens_left = create_box(
    "Lens_Left_Cut",
    w=LENS_W,
    d=FRAME_DEPTH + 2,
    h=LENS_H,
    location=(-(BRIDGE_W/2 + LENS_W/2), 0, 0),
    color=CAVITY_COLOR
)
boolean_subtract("Front_Frame", "Lens_Left_Cut")

# Cut out right lens opening
lens_right = create_box(
    "Lens_Right_Cut",
    w=LENS_W,
    d=FRAME_DEPTH + 2,
    h=LENS_H,
    location=((BRIDGE_W/2 + LENS_W/2), 0, 0),
    color=CAVITY_COLOR
)
boolean_subtract("Front_Frame", "Lens_Right_Cut")

# Camera hole — right side outer edge, front-facing
cam_x = TOTAL_WIDTH/2 - FRAME_THICKNESS - 4   # near right edge
cam_hole = create_cylinder(
    "Camera_Hole",
    dia=10.0,  # camera lens + housing
    h=FRAME_DEPTH + 2,
    location=(cam_x, 0, LENS_H/2 + 2),  # above right lens
    color=CAVITY_COLOR
)
# Rotate to face forward
cam_hole.rotation_euler = (math.pi/2, 0, 0)
bpy.ops.object.transform_apply(rotation=True)
boolean_subtract("Front_Frame", "Camera_Hole")

# Privacy LED hole — just left of camera
led_x = cam_x - 10
led_hole = create_cylinder(
    "LED_Hole",
    dia=LED_DIA,
    h=FRAME_DEPTH + 2,
    location=(led_x, 0, LENS_H/2 + 2),
    color=CAVITY_COLOR
)
led_hole.rotation_euler = (math.pi/2, 0, 0)
bpy.ops.object.transform_apply(rotation=True)
boolean_subtract("Front_Frame", "LED_Hole")

# OLED + Prism cavity — left side upper front frame
# Pocket in the front frame above left lens
oled_cavity = create_box(
    "OLED_Cavity",
    w=OLED_W,
    d=OLED_D,
    h=OLED_H,
    location=(-(BRIDGE_W/2 + LENS_W/2), -FRAME_DEPTH/2 + OLED_D/2, LENS_H/2 + FRAME_THICKNESS/2),
    color=CAVITY_COLOR
)
boolean_subtract("Front_Frame", "OLED_Cavity")

# Hinge mounting points — slots on each side
for side in [-1, 1]:
    name = f"Hinge_Slot_{'L' if side < 0 else 'R'}"
    hinge_slot = create_box(
        name,
        w=HINGE_L,
        d=HINGE_W,
        h=HINGE_H,
        location=(side * (TOTAL_WIDTH/2 - HINGE_L/2 + 5),
                  -FRAME_DEPTH/2 + HINGE_W/2,
                  0),
        color=CAVITY_COLOR
    )
    boolean_subtract("Front_Frame", name)

    # Screw hole
    screw = create_cylinder(
        f"Hinge_Screw_{'L' if side < 0 else 'R'}",
        dia=HINGE_SCREW_DIA,
        h=HINGE_W + 2,
        location=(side * (TOTAL_WIDTH/2 - 10), -FRAME_DEPTH/2 + HINGE_W/2, 0),
        color=CAVITY_COLOR
    )
    boolean_subtract("Front_Frame", f"Hinge_Screw_{'L' if side < 0 else 'R'}")


# ─────────────────────────────────────────
# PIECE 2: RIGHT TEMPLE (MCU + Amp + Bone Conduction)
# ─────────────────────────────────────────

# Temple shell — hollow box
rt_x_start = TOTAL_WIDTH/2 + 2  # gap for hinge
rt = create_box(
    "Right_Temple",
    w=TEMPLE_LENGTH,
    d=TEMPLE_W,
    h=TEMPLE_H,
    location=(rt_x_start + TEMPLE_LENGTH/2, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    color=FRAME_COLOR
)

# Hollow out the interior (leave TEMPLE_WALL thickness walls)
rt_hollow = create_box(
    "RT_Hollow",
    w=TEMPLE_LENGTH - TEMPLE_WALL*2,
    d=TEMPLE_W - TEMPLE_WALL*2,
    h=TEMPLE_H - TEMPLE_WALL*2,
    location=(rt_x_start + TEMPLE_LENGTH/2, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    color=CAVITY_COLOR
)
boolean_subtract("Right_Temple", "RT_Hollow")

# XIAO ESP32-S3 cavity — near hinge end
xiao_cavity = create_box(
    "XIAO_Cavity",
    w=XIAO_W,
    d=XIAO_D,
    h=XIAO_H,
    location=(rt_x_start + 5 + XIAO_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              -TEMPLE_H/2 + TEMPLE_WALL + XIAO_H/2),
    color=COMPONENT_COLOR
)

# IMU cavity — behind XIAO
imu_cavity = create_box(
    "IMU_Cavity",
    w=IMU_W,
    d=IMU_D,
    h=IMU_H,
    location=(rt_x_start + 5 + XIAO_W + 3 + IMU_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              -TEMPLE_H/2 + TEMPLE_WALL + IMU_H/2),
    color=COMPONENT_COLOR
)

# MAX98357A amp cavity — middle of temple
amp_cavity = create_box(
    "AMP_Cavity",
    w=AMP_W,
    d=AMP_D,
    h=AMP_H,
    location=(rt_x_start + 50 + AMP_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              -TEMPLE_H/2 + TEMPLE_WALL + AMP_H/2),
    color=COMPONENT_COLOR
)

# Bone conduction cavity — temple tip (behind ear)
bone_cavity = create_cylinder(
    "Bone_Conduction_Cavity",
    dia=BONE_DIA,
    h=BONE_H,
    location=(rt_x_start + TEMPLE_LENGTH - 20,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              0),
    color=COMPONENT_COLOR
)

# USB-C port opening — side of temple for XIAO programming
usbc_hole = create_box(
    "USBC_Hole",
    w=9.0,   # USB-C width
    d=TEMPLE_W + 2,
    h=3.5,   # USB-C height
    location=(rt_x_start + 5 + XIAO_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              -TEMPLE_H/2),
    color=CAVITY_COLOR
)
boolean_subtract("Right_Temple", "USBC_Hole")

# Wire channel — runs length of temple
wire_channel = create_cylinder(
    "RT_Wire_Channel",
    dia=WIRE_DIA,
    h=TEMPLE_LENGTH - 10,
    location=(rt_x_start + TEMPLE_LENGTH/2,
              -FRAME_DEPTH/2 + TEMPLE_W - TEMPLE_WALL - WIRE_DIA/2,
              TEMPLE_H/2 - TEMPLE_WALL - WIRE_DIA/2),
    color=CAVITY_COLOR
)
wire_channel.rotation_euler = (0, math.pi/2, 0)
bpy.ops.object.transform_apply(rotation=True)
boolean_subtract("Right_Temple", "RT_Wire_Channel")


# ─────────────────────────────────────────
# PIECE 3: LEFT TEMPLE (Battery + Charger)
# ─────────────────────────────────────────

lt_x_start = -(TOTAL_WIDTH/2 + 2)

lt = create_box(
    "Left_Temple",
    w=TEMPLE_LENGTH,
    d=TEMPLE_W,
    h=TEMPLE_H,
    location=(lt_x_start - TEMPLE_LENGTH/2, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    color=FRAME_COLOR
)

# Hollow interior
lt_hollow = create_box(
    "LT_Hollow",
    w=TEMPLE_LENGTH - TEMPLE_WALL*2,
    d=TEMPLE_W - TEMPLE_WALL*2,
    h=TEMPLE_H - TEMPLE_WALL*2,
    location=(lt_x_start - TEMPLE_LENGTH/2, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    color=CAVITY_COLOR
)
boolean_subtract("Left_Temple", "LT_Hollow")

# Battery cavity — main section of left temple
batt_cavity = create_box(
    "Battery_Cavity",
    w=BATT_W,
    d=TEMPLE_W - TEMPLE_WALL*2,
    h=BATT_H,
    location=(lt_x_start - 10 - BATT_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              0),
    color=COMPONENT_COLOR
)

# TP4056 USB-C charge board — temple end
tp4056_cavity = create_box(
    "TP4056_Cavity",
    w=TP4056_W,
    d=TP4056_D,
    h=TP4056_H,
    location=(lt_x_start - TEMPLE_LENGTH + 15 + TP4056_W/2,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              0),
    color=COMPONENT_COLOR
)

# USB-C charge port — exposed at temple end
charge_port = create_box(
    "Charge_Port",
    w=2,
    d=9.0,
    h=3.5,
    location=(lt_x_start - TEMPLE_LENGTH/2 - TEMPLE_LENGTH/2 + 1,
              -FRAME_DEPTH/2 + TEMPLE_W/2,
              0),
    color=CAVITY_COLOR
)
boolean_subtract("Left_Temple", "Charge_Port")

# Wire channel
lt_wire = create_cylinder(
    "LT_Wire_Channel",
    dia=WIRE_DIA,
    h=TEMPLE_LENGTH - 10,
    location=(lt_x_start - TEMPLE_LENGTH/2,
              -FRAME_DEPTH/2 + TEMPLE_W - TEMPLE_WALL - WIRE_DIA/2,
              TEMPLE_H/2 - TEMPLE_WALL - WIRE_DIA/2),
    color=CAVITY_COLOR
)
lt_wire.rotation_euler = (0, math.pi/2, 0)
bpy.ops.object.transform_apply(rotation=True)
boolean_subtract("Left_Temple", "LT_Wire_Channel")


# ═══════════════════════════════════════════════════════════
# COMPONENT PREVIEW OBJECTS (green, for visualization)
# These show where each component sits — delete before export
# ═══════════════════════════════════════════════════════════

previews = bpy.data.collections.new("Component_Previews")
bpy.context.scene.collection.children.link(previews)

def add_preview(name, w, d, h, loc, collection):
    """Add a green preview box showing component placement."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.active_object
    obj.name = f"PREVIEW_{name}"
    obj.scale = (w/2, d/2, h/2)
    bpy.ops.object.transform_apply(scale=True)

    mat = bpy.data.materials.new(name=f"mat_preview_{name}")
    mat.diffuse_color = COMPONENT_COLOR
    mat.blend_method = 'BLEND' if hasattr(mat, 'blend_method') else 'OPAQUE'
    obj.data.materials.append(mat)

    # Move to preview collection
    for col in obj.users_collection:
        col.objects.unlink(obj)
    collection.objects.link(obj)

# Add all component previews
add_preview("XIAO_ESP32S3", 21, 17.5, 7,
    (rt_x_start + 5 + 11, -FRAME_DEPTH/2 + TEMPLE_W/2, -3),
    previews)

add_preview("Battery_400mAh", 50, 25, 3.5,
    (lt_x_start - 10 - 25, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    previews)

add_preview("MAX98357A_Amp", 25.4, 17.8, 3,
    (rt_x_start + 50 + 13, -FRAME_DEPTH/2 + TEMPLE_W/2, -5),
    previews)

add_preview("Bone_Conduction", 25, 25, 8,
    (rt_x_start + TEMPLE_LENGTH - 20, -FRAME_DEPTH/2 + TEMPLE_W/2, 0),
    previews)

add_preview("OLED_Display", 27, 27, 4,
    (-(BRIDGE_W/2 + LENS_W/2), -FRAME_DEPTH/2 + 13.5, LENS_H/2 + 5),
    previews)


# ═══════════════════════════════════════════════════════════
# FINAL SETUP
# ═══════════════════════════════════════════════════════════

# Add subdivision surface to front frame for smoother edges
front = bpy.data.objects["Front_Frame"]
mod = front.modifiers.new(name="Smooth", type='SUBSURF')
mod.levels = 1
mod.render_levels = 2

# Select all frame pieces
bpy.ops.object.select_all(action='DESELECT')
for name in ["Front_Frame", "Right_Temple", "Left_Temple"]:
    if name in bpy.data.objects:
        bpy.data.objects[name].select_set(True)

# Frame camera to fit
bpy.ops.view3d.camera_to_view_selected() if bpy.context.area else None

print("\n" + "="*60)
print("VisionClaw Frame Generated!")
print("="*60)
print(f"\nTotal width:     {TOTAL_WIDTH}mm")
print(f"Temple length:   {TEMPLE_LENGTH}mm")
print(f"Frame depth:     {FRAME_DEPTH}mm")
print(f"\n3 pieces to print:")
print(f"  1. Front_Frame  — holds camera, LED, OLED prism, hinges")
print(f"  2. Right_Temple — XIAO ESP32-S3, IMU, amp, bone conduction")
print(f"  3. Left_Temple  — 400mAh battery, TP4056 USB-C charger")
print(f"\nGreen objects = component previews (delete before STL export)")
print(f"\nTo export for printing:")
print(f"  1. Delete 'Component_Previews' collection")
print(f"  2. Select one piece at a time")
print(f"  3. File → Export → STL")
print(f"  4. Check 'Selection Only'")
print(f"  5. Print at 100% scale, 0.15mm layer height, PETG")
print("="*60)
