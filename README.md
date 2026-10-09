# Pixel Painting

Pixel Painting converts a local image into a grid of colored pixels and paints
that grid in a game or drawing application. It samples a game's palette,
matches the source image to those colors, saves a preview, then uses mouse
clicks to draw the result.

![Pixel Painting interface](instruc/instruc.png)

> To add the screenshot, save it as `instruc/instruc.png`.

## Features

- Graphical interface and command-line workflows.
- Supports PNG, JPEG, BMP, and GIF source images.
- Resizes artwork to a configurable grid and maps it to a captured or custom
  color palette.
- Optional Floyd-Steinberg dithering to improve the appearance of gradients
  with a limited palette.
- Captures the game's palette colors and exact screen coordinates for
  automatic color selection during drawing.
- Saves a labeled `preview.png` and reports how many pixels use each color.
- Lets you skip selected colors so those pixels are left untouched.
- Manual color selection, including an option to confirm the first color and
  automatically select all remaining captured colors.
- Optional duplicate pass that redraws each color's pixels once before
  switching to the next palette color, helping cover missed clicks.
- Configurable click delay and mouse-button hold duration.
- Pause, resume, and emergency-stop controls; GUI drawing also verifies the
  target application is active before clicking.
- Remembers drawing-area and captured-palette calibration in
  `pixel_config.json`.

## Requirements and installation

Python 3.10 or newer is recommended. From the project folder, install the
dependencies:

```powershell
py -m pip install -r requirements.txt
```

## Graphical interface

Launch the GUI without an image argument:

```powershell
py pixel_draw.py
```

Work through the numbered sections in the window:

1. **Source image:** Browse to a PNG, JPEG, BMP, or GIF. The source image is
   read from its original location and is not modified.
2. **Drawing settings:** Set **Grid longest edge (cells)**, **Palette size
   (colors)**, **Wait after click (s)**, and **Mouse press duration (s)**.
   The grid value controls cells along the longer canvas edge; the shorter
   edge is calculated proportionally. If you change the palette size, capture
   a matching set of swatches before previewing or drawing. Enable dithering
   if desired. Longer grids create more detail and require more clicks and
   drawing time.
   Optionally enable **Draw every color twice** to revisit every pixel in the
   current color immediately after its first pass, before selecting the next
   color. This doubles drawing clicks and is useful when the game occasionally
   misses inputs. It is disabled by default because it approximately doubles
   drawing time.
3. **Drawing area and palette:** Select the target canvas by dragging from its
   top-left to bottom-right after the countdown. Capture palette colors by
   clicking the center of each game swatch, in order. Captured swatch positions
   are used to select the corresponding game color while drawing. Recapturing
   a palette preserves in-range skipped color numbers; review them against the
   new palette, as they remain attached to palette positions.
4. **Preview and skipped colors:** Generate and inspect the preview before
   drawing. The color list reports pixel counts. Click a color to exclude it;
   use Ctrl+click to select or deselect multiple colors. Excluded colors are
   not drawn. If all colors containing pixels are excluded, drawing will not
   start.
5. **Drawing controls:** Start drawing, pause or resume, stop, and confirm a
   manually selected color. The app displays its current status and progress.

### Grid resolution and preview

Select a rectangular drawing area first. **Grid longest edge (cells)** sets
the number of cells along the longer side of that rectangle; it is not the
total number of cells. Pixel Painting scales the shorter side proportionally
and rounds it to the nearest whole cell, with a minimum of one cell. For
example, a 60-cell setting in a 3:2 landscape area produces a grid of about
60 x 40 cells. The GUI shows the final width, height, and total cell count
beside the setting.

Press Enter or leave the grid field to validate the value and refresh the
preview when the image, area, and palette are ready. Invalid or incomplete
values invalidate the old preview and prevent drawing until corrected. Other
changes that affect image preparation, such as choosing another image,
changing the drawing area or palette, or toggling dithering, also require an
updated preview. Changing the palette-count setting also requires recapturing
the palette. Start refreshes a stale preview before drawing. The preview and
drawing use the same quantized cell indices, palette, and grid; the enlarged
pixel-art preview uses nearest-neighbor scaling.

The selected screen rectangle is treated as half-open: its left and top edges
are included, while its right and bottom edges are the exclusive boundaries.
Every grid cell is mapped to an integer screen coordinate at its center using
the final grid width and height. This keeps clicks inside the selected
rectangle for portrait, landscape, and non-divisible dimensions. The reported
grid and selected screen area are also written to the run log.

### Selecting game colors

By default, the app automatically clicks each captured palette swatch before
drawing that color. Enable **Select each game color manually (confirm with
F10)** to select swatches yourself. In that mode, select the requested color in
the game and confirm it using **F10** or **Confirm selected color (F10)**.

You can also enable **After first manual color, auto-select the rest**. Select
and confirm the first game color; Pixel Painting then uses the captured
positions to choose all remaining colors without further confirmation. This
option requires a captured game palette. A custom hex palette has no screen
positions, so its colors must be selected manually.

### Retry pixels with a duplicate pass

Enable **Draw every color twice** in Drawing settings when the target app
occasionally misses a click. For each color, Pixel Painting completes one pass
over that color's pixels, returns to the beginning of the same pixel list, and
clicks every pixel a second time. Only after both passes finish does it select
the next palette color. For example, it completes both passes for black before
selecting white.

The retry uses the same pixel coordinates and color; it does not recolor,
re-quantize, or make a separate pass over the whole image. Skipped colors
remain skipped. In manual-color mode, select and confirm a color once; both
passes for that color then run before the app asks for the next color. Drawing
progress includes both passes. Stop or pause controls remain available while
either pass is running.

The option is off by default because it approximately doubles the number of
pixel clicks and drawing time. You can also enable it from the command line:

```powershell
py pixel_draw.py .\path\to\image.png --duplicate-pass
```

### Keyboard controls and safety

| Key | GUI behavior | CLI behavior |
| --- | --- | --- |
| **F9** | Pause or resume drawing. | No pause action. |
| **F10** | Confirm the currently selected game color in manual mode. | Manual color choice is made at the terminal prompt. |
| **F12** | Stop drawing immediately. | Emergency stop while prompts or drawing are active. |

The GUI also has Pause, Resume, Stop, and color-confirmation buttons. The
PyAutoGUI failsafe is enabled: moving the pointer to the top-left corner of the
screen stops automation. Use F12 or Stop when possible; avoid moving the cursor
to that corner accidentally during drawing.

## Command line

Pass an image path to run the command-line workflow:

```powershell
py pixel_draw.py .\path\to\image.png --grid 60 --dither
```

On first use, follow the prompts to select the drawing area and capture the
palette. Pixel Painting reuses the saved calibration on later runs unless
`--recalibrate` is specified. The generated `preview.png` lists each palette
color and the number of pixels assigned to it. Review the preview, then enter
comma-separated 1-based palette numbers to skip (for example, `1,3`), or press
Enter to draw all colors.

Before each color, the CLI offers:

| Input | Behavior |
| --- | --- |
| `y` | Draw this color. |
| `s` | Skip this color. |
| `q` | Stop the drawing run. |
| `a` | Draw this and all remaining colors without more prompts. |

In manual mode, the CLI instead asks you to select each requested game color
and confirm at the terminal prompt.

### Examples

```powershell
# More detail, 12 game colors, and dithering.
py pixel_draw.py .\path\to\image.png --grid 80 --colors 12 --dither

# A custom palette; select each corresponding game color manually.
py pixel_draw.py .\path\to\image.png --palette-hex "000000,ffffff,ff0000"

# Re-capture the drawing area and palette.
py pixel_draw.py .\path\to\image.png --recalibrate

# Slow down clicks if the target application misses inputs.
py pixel_draw.py .\path\to\image.png --delay 0.05 --click-hold 0.1

# Draw each color's pixels twice before switching to the next color.
py pixel_draw.py .\path\to\image.png --duplicate-pass
```

### Options

| Option | Description |
| --- | --- |
| `image` | Source image path. Omit it to open the GUI. |
| `--grid N` | Cells along the grid's longest edge; must be greater than zero (default: `60`). |
| `--colors N` | Palette size from `1` to `256`. If omitted, prompts; press Enter to use `12`. |
| `--dither` | Apply Floyd-Steinberg dithering when mapping image colors. |
| `--delay SECONDS` | Wait after each click; finite and nonnegative (default: `0.02`). |
| `--click-hold SECONDS` | Hold the mouse button for each click; finite and greater than zero (default: `0.05`). |
| `--manual` | Select each game color manually; the tool only clicks pixels. |
| `--palette-hex COLORS` | Comma-separated `RRGGBB` colors; automatically enables manual selection. |
| `--recalibrate` | Capture a new drawing area and game palette instead of reusing calibration. |
| `--duplicate-pass` | Draw each color's pixels twice before selecting the next color. |

The GUI and CLI both validate timing values. If the game misses clicks, try
increasing `--click-hold` or `--delay`.

## Troubleshooting

- **Wrong colors are selected:** Capture the palette again and click near the
  center of each swatch, keeping the same order as the game's palette.
- **Clicks land outside the canvas:** Select the drawing area again and ensure
  the game window is at the expected size and position.
- **Regular white gaps remain:** A preview confirms the intended quantized
  pixels, but cannot establish how the target app processes screen clicks.
  Check the run log's selected rectangle, grid dimensions, and cell size;
  verify that the selection excludes unwanted borders and matches the target
  canvas. Pixel Painting warns when the requested grid has more cells along
  either axis than there are screen-coordinate positions in the selected
  rectangle, because those cells must share click coordinates. This is a
  screen-coordinate limit, not a measurement of the game's internal grid.
  DPI/display scaling, window scaling, a target canvas grid that differs from
  the chosen resolution, asynchronous input handling, and missed clicks are
  also possible causes. The app does not infer the target's internal grid or
  automatically repair gaps. The optional duplicate pass can help with
  occasional missed clicks, but it does not fix a coordinate or grid mismatch.
- **Drawing is too slow:** Reduce the longest grid edge or lower the delay.
  A smaller grid means fewer clicks and less detail.
- **The target misses clicks:** Increase the click hold or delay.
- **Need a fresh setup:** Run with `--recalibrate` or use the GUI's area and
  palette capture controls.

## Tests

Run the project's unittest suite from the repository directory:

```powershell
py -m unittest -v
```

Grid tests check proportional landscape and portrait dimensions, very wide or
tall and small canvases, invalid inputs, and that the resulting dimensions are
passed to the image quantizer. They also check when a grid exceeds the selected
area's available screen-coordinate positions. Coordinate tests check integer
cell centers, including the first and last cells, non-divisible rectangles,
and that clicks stay inside the selected half-open drawing area. The tests use
mocks for screen input and image-preparation boundaries, so they do not
establish how a particular game handles clicks or renders its canvas.

## Project files and generated data

- `pixel_draw.py` - GUI, CLI, image processing, calibration, and drawing.
- `test_pixel_painting.py` - Unit tests for grid geometry, coordinate mapping,
  calibration validation, palette handling, timing, skip colors, manual
  selection, duplicate passes, and hotkeys.
- `instruc/instruc.png` - Optional interface screenshot referenced above.
- `pixel_config.json` - Local drawing-area, palette, and skipped-color
  calibration.
- `preview.png` - Generated preview of the most recently processed image.

Calibration and previews are local runtime data and can vary between
computers. Example artwork is intentionally not bundled in this repository.
