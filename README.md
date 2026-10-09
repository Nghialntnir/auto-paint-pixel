# Pixel Painting

Turn an image into pixel art and paint it in a game or drawing app. Pixel
Painting samples the game's palette, maps the image to those colors, previews
the result, and draws it with mouse clicks.

![Pixel Painting interface](instruc/instruc.png)

> Add your interface screenshot as `instruc/instruc.png` to display it here.

## Get started

### 1. Install

From the project folder, install the dependencies:

```powershell
py -m pip install -r requirements.txt
```

### 2. Launch the app

Start the graphical interface:

```powershell
py bangbang_draw.py
```

To open the command-line workflow for an image:

```powershell
py bangbang_draw.py .\path\to\image.png
```

Use a path to an image on your computer; example artwork is intentionally not
bundled in this repository.

## Graphical interface

1. **Choose an image.** Select **Browse...** and open a local PNG, JPEG, BMP,
   or GIF.
2. **Set drawing options.** Choose the longest grid edge, the number of game
   palette colors, and optional dithering. A larger grid produces more detail
   and more clicks.
3. **Select the drawing area.** Click **Select drawing area**, switch to the
   game during the countdown, and drag from the canvas's top-left to its
   bottom-right corner.
4. **Capture the palette.** Click **Capture game palette**, then click the
   center of each game color swatch in order. The app saves each sampled RGB
   color and its screen position.
5. **Preview and optionally skip colors.** Click **Generate preview**. The
   preview shows the mapped image and the pixel count for each color. In
   **Colors to skip**, click colors you do not want painted; use **Ctrl+click**
   to add or remove individual selections. Selected colors are excluded from
   drawing. Skipping is optional.
6. **Draw.** Click **Start** and switch to the game during the countdown.
   Pixel Painting verifies the game window is active before sending clicks.

### Manual color selection

Normally, Pixel Painting clicks each captured palette swatch automatically.
To select colors yourself, enable **Select each game color manually (confirm
with F10)** in Drawing settings.

- To confirm every color yourself, select the requested swatch in the game
  each time and press **F10** or click **Confirm selected color (F10)**.
- To select only the first color yourself, also enable **After first manual
  color, auto-select the rest**. Select the first swatch and confirm with F10.
  The app paints that color, then clicks the captured swatch positions and
  paints all remaining colors without asking you to confirm each one.

The automatic option is available only when a game palette with screen
positions has been captured. A custom hex palette has no captured positions,
so its colors must be selected manually.

### Pause and safety controls

| Control | Action |
| --- | --- |
| **F10** | Confirm the game color currently selected in manual mode. |
| **F11** | Pause or resume drawing. |
| **F12** | Stop drawing immediately. |
| **Pause / Resume / Stop** | The same controls are available as GUI buttons. |
| Top-left screen corner | PyAutoGUI emergency failsafe; move the pointer there to stop. |

## Command line

The CLI uses the same saved game calibration and preview output as the GUI:

```powershell
py bangbang_draw.py .\path\to\image.png --grid 60 --dither
```

On first use, follow the prompts to select the drawing area and palette. Inspect
`preview.png` before drawing. When asked which colors to skip, enter
comma-separated 1-based palette numbers (for example, `1,3`) or leave the
response blank to draw every color. Invalid values are rejected and prompted
again.

For each color, enter:

| Input | Action |
| --- | --- |
| `y` | Draw this color. |
| `s` | Skip this color. |
| `q` | Stop drawing. |
| `a` | Draw this and all remaining colors without more prompts. |

### Examples

```powershell
# Increase detail, use 12 game colors, and enable dithering.
py bangbang_draw.py .\path\to\image.png --grid 80 --colors 12 --dither

# Use a custom palette and select each corresponding game color manually.
py bangbang_draw.py .\path\to\image.png --palette-hex "000000,ffffff,ff0000"

# Re-capture the drawing area and game palette.
py bangbang_draw.py .\path\to\image.png --recalibrate

# Slow clicks down if the game misses inputs.
py bangbang_draw.py .\path\to\image.png --delay 0.05 --click-hold 0.1
```

## Options

| Option | Description |
| --- | --- |
| `image` | Source image path. Omit it to open the GUI. |
| `--grid N` | Cells along the longest edge of the drawing area (default: `60`). |
| `--colors N` | Palette size, from `1` to `256`. If omitted, the CLI prompts; Enter selects `12`. |
| `--dither` | Apply Floyd-Steinberg dithering. |
| `--delay SECONDS` | Wait after each click (default: `0.02`; finite and nonnegative). |
| `--click-hold SECONDS` | Hold the mouse button for each click (default: `0.05`; finite and greater than zero). |
| `--manual` | Select game colors manually. |
| `--palette-hex COLORS` | Comma-separated `RRGGBB` values; enables manual color selection. |
| `--recalibrate` | Capture a new drawing area and game palette. |

If the game misses clicks, increase `--click-hold` or `--delay`. The same
timing limits are enforced in both the CLI and GUI.

## Project files

- `bangbang_draw.py` - GUI, CLI, image processing, and drawing automation.
- `instruc/` - Place the interface screenshot here as `instruc.png`.
- `test_pixel_painting.py` - Focused unit tests.
- `bangbang_config.json` - Local drawing-area and palette calibration.

Calibration and generated previews are machine-specific/runtime data; the
preview is generated as `preview.png` when you create one.
