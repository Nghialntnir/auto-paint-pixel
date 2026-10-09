# Pixel Painting

Pixel Painting turns an image into a limited-color pixel grid and draws it in a
game or drawing app with mouse clicks. The existing `bangbang_draw.py` filename
is retained so current commands and shortcuts continue to work; the app itself
is named **Pixel Painting**.

## Install

From the project directory, install the dependencies:

```powershell
py -m pip install -r requirements.txt
```

## GUI workflow

Open Pixel Painting without an image argument:

```powershell
py bangbang_draw.py
```

1. Choose the source image with **Browse...**.
2. Set the longest grid edge and the number of palette colors. The default
   grid edge is 60 cells.
3. Click **Select drawing area**, switch to the game during the countdown, and
   drag from the top-left to the bottom-right of the canvas area.
4. Click **Capture game palette** and click the center of each game color
   swatch, in the order to use them. Pixel Painting samples each color and
   records that swatch's screen position. It clicks the recorded position to
   select that color before drawing its pixels.
5. Click **Generate preview** and inspect the image and color counts. Select
   any background colors in **Colors to skip** if they should not be painted.
6. Set the click timing if needed, then click **Start** and switch to the game
   during the countdown. Press **F10** after selecting each swatch when manual
   color mode is enabled. Use **F11** or the Pause/Resume buttons to pause, and
   **F12** or Stop to end drawing.

The application also verifies that the game window is active before drawing.
If it cannot focus the game, bring the game to the foreground and retry.
PyAutoGUI's emergency failsafe is enabled; moving the pointer to the top-left
screen corner stops the automation.

## Command-line workflow

Run the CLI with a source image:

```powershell
py bangbang_draw.py .\joker.jpg --grid 60 --dither
```

The first run guides you through selecting the drawing area and palette. Review
`preview.png`, enter any palette color number to skip (or leave blank to draw
all), and confirm each color with `y`. Enter `s` to skip a color, `q` to quit,
or `a` to draw all remaining colors without further confirmation. Switch back
to the game during the countdown before drawing begins. The `F12` and
top-left-corner emergency stops are available while drawing.

Examples:

```powershell
# Choose the palette size, increase detail, and enable dithering.
py bangbang_draw.py .\joker.jpg --grid 80 --colors 12 --dither

# Use a custom RGB palette and select each corresponding game color manually.
py bangbang_draw.py .\joker.jpg --grid 60 --palette-hex "000000,ffffff,ff0000"

# Re-select the game canvas and palette after moving or resizing the game.
py bangbang_draw.py .\joker.jpg --recalibrate

# Slow the clicks down if the game misses inputs.
py bangbang_draw.py .\joker.jpg --delay 0.05 --click-hold 0.1
```

## Click timing

The default mouse hold is **0.05 seconds**, followed by a **0.02-second delay**
after each click. These timings give games time to register both color-selection
and pixel-drawing clicks. `--click-hold` must be finite and greater than zero;
`--delay` must be finite and nonnegative. The GUI validates the same rules
before starting. For example, increase the hold to 0.1 seconds and the delay to
0.05 seconds if a game still misses clicks.

## Command options

| Option | Description |
| --- | --- |
| `image` | Source image path. Omit it to open the GUI. |
| `--grid N` | Cells along the longest edge of the drawing area (default: `60`). |
| `--colors N` | Palette size from `1` to `256`. If omitted, the CLI prompts; Enter selects `12`. |
| `--dither` | Enable Floyd-Steinberg dithering. |
| `--delay SECONDS` | Wait after each click (default: `0.02`; finite and `>= 0`). |
| `--click-hold SECONDS` | Hold the mouse button for each click (default: `0.05`; finite and `> 0`). |
| `--manual` | Select each game color manually; use F10 in the GUI or confirm in the CLI. |
| `--palette-hex COLORS` | Comma-separated `RRGGBB` colors; enables manual color selection. |
| `--recalibrate` | Select the drawing area and game palette again. |

The saved drawing area, palette, and skipped-color settings remain in
`bangbang_config.json` for compatibility with existing installations.
