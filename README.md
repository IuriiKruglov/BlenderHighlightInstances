# Highlight Instances — Blender Addon

<img width="693" height="611" alt="image" src="https://github.com/user-attachments/assets/2c0017c4-7271-4b65-a55f-120822115277" />

---

## What it does

Highlight Instances scans your scene for linked duplicate objects — objects that share the same underlying mesh data-block — and draws a colored viewport overlay on each one. Every instance group gets a unique random color, making it easy to visually identify which objects are instances of what at a glance.

The overlay is drawn purely via Blender's GPU draw handler and never touches your materials or mesh data.

---

## Installation

1. Download `highlight_instances.py`
2. In Blender, go to **Edit → Preferences → Add-ons → Install**
3. Select the downloaded file
4. Enable the addon by ticking its checkbox

---

## Usage

Open the **N-panel** in the 3D Viewport (press `N`) and navigate to the **Instances** tab.

### Buttons

| Button | Description |
|---|---|
| **Highlight Instances** | Scans the scene and enables the colored overlay |
| **Remove Highlight** | Turns off the overlay (same button, toggled) |
| **Randomize Colors** (↺) | Re-rolls all group colors with new random values |
| **Refresh Groups** (⟳) | Re-scans the scene — use after adding or removing instances |
| **Select** icon on each row | Selects all instances of that specific group |
| **Select Active Group** | Selects all instances of whatever object is currently active |

### Instance group list

When the highlight is active, the panel shows a list of all detected instance groups with their mesh data-block name and instance count. Each row has a select button to quickly isolate that group in the viewport.

---

## How instances are detected

Objects are grouped by their **mesh data-block name** — the same mechanism Blender uses internally for linked duplicates created with `Alt+D`. Objects linked by `Shift+D` (copy) are not considered instances and will not appear in the list.

---

## Overlay appearance

Each group's overlay consists of two GPU draw passes:

- **Base fill** — a semi-transparent color layer drawn at the original mesh surface
- **Shell** — a more opaque layer drawn with vertices offset outward along their normals, giving the overlay visible physical thickness (default: 10 mm)

Both passes use alpha blending and depth testing so the overlay respects scene geometry.

---

## Color range

Random colors are generated in HSV space with excluded hue ranges to avoid confusion with Blender's built-in UI colors:

- **Excluded:** Red (`0.00–0.05`, `0.95–1.00`) and Blue (`0.55–0.72`)
- **Allowed:** Yellows, greens, cyans, magentas, purples

---

## Notes

- The overlay state (on/off) is saved per scene
- Colors are randomized fresh each time you enable the highlight; use **Randomize Colors** to re-roll without toggling
- The addon cleans up all GPU handlers and scene properties on unregister — no leftover data

---


| v0.3 | Red and blue excluded from random color range |
| v0.4 | Shell thickness pass added via vertex normal offset |
| v0.5 | Face culling removed from both draw passes |
| v1.0 | Per-group select buttons added to N-panel; stable release |
