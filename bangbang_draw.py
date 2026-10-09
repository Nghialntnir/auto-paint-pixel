"""Convert images to palette-based pixel art and draw them with mouse clicks.

Run ``python bangbang_draw.py`` for the GUI or pass an image path to use the
command line. See README.md for setup, workflow, options, and safety controls.
"""
import argparse
import ctypes
import json
import math
import os
import queue
import select
import sys
import threading
import time

# Set DPI awareness before importing GUI/automation modules, which may cache
# screen dimensions while importing.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - GUI is optional during import-time checks.
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is needed only for image quantization.
    np = None

try:
    import pyautogui
except ImportError:  # pragma: no cover - automation is optional during import-time checks.
    pyautogui = None

try:
    from PIL import Image, ImageDraw, ImageGrab, ImageTk
except ImportError:  # pragma: no cover - image processing is optional at import time.
    Image = None
    ImageDraw = None
    ImageGrab = None
    ImageTk = None

if pyautogui is not None:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
CONFIG_FILE = "bangbang_config.json"
STOP_EVENT = threading.Event()
DEFAULT_DELAY = 0.02
DEFAULT_CLICK_HOLD = 0.05
LOG_PIXEL_INTERVAL = 100
LOG_LOCK = threading.Lock()


def log_event(category, message):
    timestamp = time.strftime("%H:%M:%S")
    with LOG_LOCK:
        print(f"[{timestamp}] [{category}] {message}", flush=True)


def _require_runtime_deps(*deps):
    missing = []
    if pyautogui is None and "pyautogui" in deps:
        missing.append("pyautogui")
    if np is None and "numpy" in deps:
        missing.append("numpy")
    if Image is None and "Pillow" in deps:
        missing.append("Pillow")
    if tk is None and "tkinter" in deps:
        missing.append("tkinter")
    if missing:
        missing_str = ", ".join(missing)
        raise RuntimeError(
            f"Missing required dependency for this operation: {missing_str}. "
            "Install the project requirements with 'pip install -r requirements.txt'."
        )


# ---------------------------------------------------------------- utilities
def countdown(sec, msg, pause_event=None):
    print(msg)
    for i in range(sec, 0, -1):
        print(f"  {i}...", end="\r", flush=True)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if STOP_EVENT.is_set() or not _wait_until_running(pause_event):
                print("\nEmergency stop (F12).")
                return False
            STOP_EVENT.wait(min(0.05, deadline - time.monotonic()))
    print(" " * 20, end="\r")
    return True


def ask_yes(prompt):
    """Return 'y' to draw, 'a' to draw all, 's' to skip, or 'q' to quit."""
    while True:
        a = _readline_or_stop(prompt)
        if a is None:
            return None
        if a in ("y", "a", "s", "q"):
            return a
        print("  Enter y, a, s, or q.")


def _readline_or_stop(prompt):
    """Read a terminal line while still responding to the global stop hotkey."""
    print(prompt, end="", flush=True)
    if os.name == "nt":
        import msvcrt

        chars = []
        while not STOP_EVENT.is_set():
            if not msvcrt.kbhit():
                STOP_EVENT.wait(0.05)
                continue
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                print()
                return "".join(chars).strip().lower()
            if char == "\003":
                raise KeyboardInterrupt
            if char == "\b":
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if char not in ("\000", "\xe0"):
                chars.append(char)
                sys.stdout.write(char)
                sys.stdout.flush()
        print()
        return None

    while not STOP_EVENT.is_set():
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            return sys.stdin.readline().strip().lower()
    print()
    return None


def _start_emergency_listener(on_pause_toggle=None, on_manual_confirm=None):
    try:
        from pynput import keyboard
    except ImportError as exc:
        raise RuntimeError(
            "Missing required dependency for the emergency stop hotkey: pynput. "
            "Install the project requirements with 'pip install -r requirements.txt'."
        ) from exc

    pressed = set()

    def on_press(key):
        if key == keyboard.Key.f12:
            log_event("HOTKEY", "F12 pressed; emergency stop requested.")
            STOP_EVENT.set()
        elif key == keyboard.Key.f11 and key not in pressed:
            pressed.add(key)
            if on_pause_toggle is not None:
                log_event("HOTKEY", "F11 pressed; pause/resume requested.")
                on_pause_toggle()
        elif key == keyboard.Key.f10 and key not in pressed:
            pressed.add(key)
            if on_manual_confirm is not None:
                log_event(
                    "HOTKEY",
                    "F10 pressed; confirming the manually selected color.")
                on_manual_confirm()

    def on_release(key):
        pressed.discard(key)

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    return listener


def _scale_point(x, y, scale_x, scale_y):
    """Convert a screen point between Tk, screenshot, and automation spaces."""
    return int(x * scale_x), int(y * scale_y)


def _capture_palette_sample(x, y, screenshot, screenshot_scale_x,
                            screenshot_scale_y, automation_scale_x,
                            automation_scale_y):
    sample_x, sample_y = _scale_point(
        x, y, screenshot_scale_x, screenshot_scale_y)
    sample_x = min(screenshot.width - 1, max(0, sample_x))
    sample_y = min(screenshot.height - 1, max(0, sample_y))
    point = _scale_point(x, y, automation_scale_x, automation_scale_y)
    return point, screenshot.getpixel((sample_x, sample_y))[:3]


def _wait_until_running(pause_event):
    while not STOP_EVENT.is_set():
        if pause_event is None or pause_event.wait(0.02):
            return not STOP_EVENT.is_set()
    return False


def _set_window_no_activate(window):
    if os.name != "nt":
        return
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    user32.GetWindowLongW.argtypes = (wintypes.HWND, wintypes.INT)
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = (
        wintypes.HWND, wintypes.INT, wintypes.LONG)
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, wintypes.INT, wintypes.INT,
        wintypes.INT, wintypes.INT, wintypes.UINT)
    user32.SetWindowPos.restype = wintypes.BOOL
    ex_style_index = -20
    no_activate = 0x08000000
    tool_window = 0x00000080
    style = user32.GetWindowLongW(hwnd, ex_style_index)
    user32.SetWindowLongW(
        hwnd, ex_style_index, style | no_activate | tool_window)
    if not user32.SetWindowPos(
        hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
        0x0001 | 0x0002 | 0x0010 | 0x0040):
        raise RuntimeError("Could not display the non-activating countdown.")


def _focus_window_at(x, y, own_window=None):
    if os.name != "nt":
        return
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.SetForegroundWindow.restype = wintypes.BOOL
    point = wintypes.POINT(int(x), int(y))
    target = user32.WindowFromPoint(point)
    target = user32.GetAncestor(target, 2)
    own_window = (
        user32.GetAncestor(own_window, 2) if own_window else None)
    if not target or target == own_window:
        raise RuntimeError(
            "No game window was found at the selected palette/drawing "
            "position. Bring the game to the front and try again.")
    title_buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(target, title_buffer, len(title_buffer))
    if user32.GetForegroundWindow() != target:
        if not user32.SetForegroundWindow(target):
            raise RuntimeError(
                "Windows could not activate the game window. Bring the game "
                "to the front and ensure it runs with the same permissions "
                "as Pixel Painting.")
        if user32.GetForegroundWindow() != target:
            raise RuntimeError(
                "The game window did not become active. Bring the game to "
                "the front and try again.")
    log_event(
        "FOCUS",
        f"Target window HWND={target:#x}, title={title_buffer.value!r}, "
        f"verified at screen position ({x}, {y}).")


# -------------------------------------------------------------- screen selection
def _overlay(title, parent=None):
    """Open a full-screen selector with a screenshot as its background."""
    _require_runtime_deps("Pillow", "tkinter")
    if parent is not None:
        parent.withdraw()
        parent.update_idletasks()
        parent.update()
        _selection_countdown(parent, 4)
    shot = ImageGrab.grab()
    root = tk.Toplevel(parent) if parent is not None else tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    scale_x, scale_y = shot.width / sw, shot.height / sh
    automation_width, automation_height = (
        pyautogui.size() if pyautogui is not None else (sw, sh))
    automation_scale_x = automation_width / sw
    automation_scale_y = automation_height / sh
    bg = ImageTk.PhotoImage(shot.resize((sw, sh)))
    canvas = tk.Canvas(root, width=sw, height=sh, cursor="crosshair",
                       highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, image=bg, anchor="nw")
    canvas.create_rectangle(10, 10, 900, 50, fill="black")
    canvas.create_text(20, 30, text=title, fill="yellow", anchor="w",
                       font=("Arial", 14, "bold"))
    root.bg = bg
    return (root, canvas, shot, scale_x, scale_y,
            automation_scale_x, automation_scale_y)


def _selection_countdown(parent, seconds, title="GET READY TO SELECT",
                         instruction="Switch to the game; screenshot in",
                         cancel_event=None):
    countdown = tk.Toplevel(parent)
    countdown.withdraw()
    countdown.title("Pixel Painting - Screen capture")
    countdown.attributes("-topmost", True)
    countdown.resizable(False, False)
    countdown.configure(background="#14213d")
    width, height = 440, 132
    x = (countdown.winfo_screenwidth() - width) // 2
    y = 48
    countdown.geometry(f"{width}x{height}+{x}+{y}")
    ttk.Label(
        countdown, text=title,
        style="CountdownTitle.TLabel").pack(pady=(14, 4))
    ttk.Label(
        countdown, text=instruction,
        style="CountdownHint.TLabel").pack()
    counter = ttk.Label(countdown, text=str(seconds),
                        style="CountdownNumber.TLabel")
    counter.pack(pady=(0, 8))
    countdown.update_idletasks()
    _set_window_no_activate(countdown)
    countdown.deiconify()
    countdown.attributes("-topmost", True)
    completed = True
    try:
        countdown.update()
        deadline = time.monotonic() + seconds
        remaining = seconds
        while remaining > 0:
            countdown.update()
            if cancel_event is not None and cancel_event.is_set():
                completed = False
                break
            next_remaining = max(
                0, int(deadline - time.monotonic() + 0.999))
            if next_remaining != remaining:
                remaining = next_remaining
                counter.configure(text=str(remaining))
            time.sleep(0.03)
        if completed:
            countdown.update_idletasks()
    finally:
        if countdown.winfo_exists():
            countdown.attributes("-topmost", False)
            countdown.withdraw()
            countdown.update_idletasks()
            countdown.destroy()
        parent.update_idletasks()
    return completed


def select_region(parent=None):
    try:
        root, canvas, _shot, _sx, _sy, ax, ay = _overlay(
            "Drag from the TOP-LEFT to the BOTTOM-RIGHT "
            "of the drawing area (ESC = cancel)",
            parent)
        state = {"start": None, "rect": None, "box": None}

        def down(e):
            state["start"] = (e.x, e.y)
            state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                    outline="red", width=2)

        def move(e):
            if state["start"]:
                x0, y0 = state["start"]
                canvas.coords(state["rect"], x0, y0, e.x, e.y)

        def up(e):
            x0, y0 = state["start"]
            x1, y1 = e.x, e.y
            left, top = _scale_point(min(x0, x1), min(y0, y1), ax, ay)
            right, bottom = _scale_point(max(x0, x1), max(y0, y1), ax, ay)
            state["box"] = (left, top, right, bottom)
            root.destroy()

        canvas.bind("<ButtonPress-1>", down)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", up)
        root.bind("<Escape>", lambda e: root.destroy())
        if parent is None:
            root.mainloop()
        else:
            parent.wait_window(root)
        if state["box"] is None:
            raise RuntimeError("Drawing-area selection was cancelled.")
        return state["box"]
    finally:
        _restore_parent_behind(parent)


def pick_palette(n, parent=None):
    try:
        root, canvas, shot, sx, sy, ax, ay = _overlay(
            f"Click {n} game palette swatches in order (ESC = cancel)",
            parent)
        points, colors = [], []

        def click(e):
            point, rgb = _capture_palette_sample(
                e.x, e.y, shot, sx, sy, ax, ay)
            points.append(point)
            colors.append(rgb)
            log_event(
                "PALETTE",
                f"Captured color {len(points)}/{n} RGB={rgb} "
                f"at ({point[0]}, {point[1]}).")
            canvas.create_oval(e.x - 6, e.y - 6, e.x + 6, e.y + 6,
                               outline="red", width=2)
            canvas.create_text(e.x + 12, e.y - 12, text=str(len(points)),
                               fill="red", font=("Arial", 12, "bold"))
            if len(points) >= n:
                root.after(400, root.destroy)

        canvas.bind("<Button-1>", click)
        root.bind("<Escape>", lambda e: root.destroy())
        if parent is None:
            root.mainloop()
        else:
            parent.wait_window(root)
        if len(points) < n:
            raise RuntimeError("Palette selection was cancelled.")
        return points, colors
    finally:
        _restore_parent_behind(parent)


def _restore_parent_behind(parent):
    if parent is None:
        return
    try:
        parent.deiconify()
        parent.attributes("-topmost", False)
        parent.lower()
    except tk.TclError:
        pass


# -------------------------------------------------------------- image processing
def grid_for_box(box, max_cells):
    """Return rectangular grid dimensions proportional to the selected box."""
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        raise ValueError("The drawing area must have a positive width and height.")
    longest = max(width, height)
    grid_w = max(1, round(max_cells * width / longest))
    grid_h = max(1, round(max_cells * height / longest))
    return grid_w, grid_h


def quantize(img_path, grid_size, palette_rgb, dither):
    """Resize the full image to the selected box's grid, then map to its palette."""
    _require_runtime_deps("numpy", "Pillow")
    if not palette_rgb:
        raise ValueError("The palette cannot be empty.")
    palette = np.asarray(palette_rgb, dtype=np.float32)
    if palette.ndim != 2 or palette.shape[1] != 3:
        raise ValueError("Each palette color must contain three RGB values.")

    grid_w, grid_h = grid_size
    if grid_w <= 0 or grid_h <= 0:
        raise ValueError("The drawing grid must have a positive width and height.")
    img = Image.open(img_path).convert("RGB")
    img = img.resize((grid_w, grid_h), Image.LANCZOS)

    pixels = np.asarray(img, dtype=np.float32)
    if dither:
        work = pixels.copy()
        q = np.empty((grid_h, grid_w), dtype=int)
        for y in range(grid_h):
            for x in range(grid_w):
                old = work[y, x].copy()
                ci = int(np.argmin(np.sum((palette - old) ** 2, axis=1)))
                q[y, x] = ci
                error = old - palette[ci]
                if x + 1 < grid_w:
                    work[y, x + 1] += error * (7 / 16)
                if y + 1 < grid_h:
                    if x > 0:
                        work[y + 1, x - 1] += error * (3 / 16)
                    work[y + 1, x] += error * (5 / 16)
                    if x + 1 < grid_w:
                        work[y + 1, x + 1] += error * (1 / 16)
    else:
        q = np.empty((grid_h, grid_w), dtype=int)
        for y in range(grid_h):
            distances = np.sum(
                (pixels[y, :, None, :] - palette[None, :, :]) ** 2,
                axis=2)
            q[y] = np.argmin(distances, axis=1)
    return q


def save_preview(idx, palette_rgb, path="preview.png", zoom=8):
    _require_runtime_deps("numpy", "Pillow")
    arr = np.full(idx.shape + (3,), 128, dtype=np.uint8)
    for i, c in enumerate(palette_rgb):
        arr[idx == i] = c
    image = Image.fromarray(arr).resize(
        (idx.shape[1] * zoom, idx.shape[0] * zoom), Image.NEAREST)

    columns = min(6, len(palette_rgb))
    rows = (len(palette_rgb) + columns - 1) // columns
    cell_w, cell_h = 104, 28
    legend_h = 12 + rows * cell_h
    preview = Image.new(
        "RGB", (max(image.width, columns * cell_w), image.height + legend_h),
        "white")
    preview.paste(image, (0, 0))
    draw = ImageDraw.Draw(preview)
    counts = np.bincount(idx[idx >= 0].astype(int),
                         minlength=len(palette_rgb))
    for i, color in enumerate(palette_rgb):
        x = (i % columns) * cell_w + 6
        y = image.height + 6 + (i // columns) * cell_h
        swatch = tuple(int(channel) for channel in color)
        draw.rectangle((x, y, x + 22, y + 19), fill=swatch, outline="black")
        label = f"#{i + 1} {int(counts[i])}"
        draw.text((x + 27, y + 3), label, fill="black")
    preview.save(path)


# ---------------------------------------------------------------- drawing
def draw(idx, box, palette_pts, skip, delay, n_colors, manual=False,
         click_hold=DEFAULT_CLICK_HOLD, pause_event=None, on_pixel=None,
         automatic=False, on_manual_color=None):
    _require_runtime_deps("numpy", "pyautogui")
    x1, y1, x2, y2 = box
    grid_h, grid_w = idx.shape
    cw, ch = (x2 - x1) / grid_w, (y2 - y1) / grid_h
    todo = [c for c in range(n_colors)
            if c not in skip and np.any(idx == c)]
    skipped_pixels = int(sum(np.count_nonzero(idx == c) for c in skip))
    total_pixels = int(sum(np.count_nonzero(idx == c) for c in todo))
    log_event(
        "DRAW",
        f"Starting grid {grid_w}x{grid_h}; {total_pixels} pixels across "
        f"{len(todo)} colors; skipping {skipped_pixels} pixels.")
    draw_all = False
    draw_all_from = None
    for k, ci in enumerate(todo, 1):
        if STOP_EVENT.is_set():
            log_event("STOP", "Emergency stop received before color drawing.")
            return
        ys, xs = np.where(idx == ci)
        log_event(
            "COLOR",
            f"Starting color #{ci + 1}: {len(xs)} pixels "
            f"({k}/{len(todo)} used colors).")
        msg = (f"\n[{k}/{len(todo)} colors with pixels; palette "
               f"#{ci + 1}/{n_colors}]: {len(xs)} pixels.")
        if manual:
            msg += "\n  >> Select this color in the game first."
            if automatic and on_manual_color is not None:
                manual_color_action = on_manual_color(ci)
                if not manual_color_action:
                    return
                if manual_color_action == "auto_remaining":
                    manual = False
                    palette_already_selected = True
                else:
                    palette_already_selected = False
        else:
            palette_already_selected = False
        if automatic:
            log_event(
                "DRAW",
                f"Drawing color #{ci + 1} automatically; F12 = stop.")
        elif draw_all:
            log_event(
                "DRAW",
                f"Drawing color #{ci + 1} automatically; F12 = stop.")
        else:
            options = "y = draw | s = skip this color | q = quit"
            if not manual:
                options += " | a = draw all remaining colors"
            ans = ask_yes(msg + "\n  Enter " + options + ": ")
            if ans in (None, "q"):
                if STOP_EVENT.is_set():
                    log_event("STOP", "Emergency stop received at prompt.")
                    return
                log_event("STOP", "Drawing cancelled at color prompt.")
                return
            if ans == "s":
                continue
            if ans == "a":
                draw_all = True
                draw_all_from = k
        if not automatic and (not draw_all or k == draw_all_from):
            if not countdown(3, "  Return to the game window..."):
                return
        if not manual and not palette_already_selected:
            px, py = palette_pts[ci]
            log_event(
                "PALETTE",
                f"Selecting game color #{ci + 1} at ({px}, {py}).")
            if not _click(px, py, click_hold, delay, pause_event):
                log_event("STOP", "Stopped while selecting a palette color.")
                return
            if not automatic and STOP_EVENT.wait(0.05):
                log_event(
                    "STOP",
                    f"Stopped while selecting palette color #{ci + 1}.")
                return
        for pixel_number, (cy, cx) in enumerate(sorted(zip(ys, xs)), 1):
            px = int(x1 + (cx + 0.5) * cw)
            py = int(y1 + (cy + 0.5) * ch)
            def pixel_done():
                if on_pixel is not None:
                    on_pixel(ci, pixel_number, len(xs), px, py)

            if not _click(px, py, click_hold, delay, pause_event, pixel_done):
                log_event(
                    "STOP",
                    f"Stopped before completing color #{ci + 1}, "
                    f"pixel {pixel_number}/{len(xs)} at ({px}, {py}).")
                return
            if (len(xs) <= LOG_PIXEL_INTERVAL
                    or pixel_number == 1
                    or pixel_number % LOG_PIXEL_INTERVAL == 0
                    or pixel_number == len(xs)):
                log_event(
                    "CLICK",
                    f"Color #{ci + 1}, pixel {pixel_number}/{len(xs)} "
                    f"clicked at ({px}, {py}); hold={click_hold * 1000:.0f}ms.")
        log_event("COLOR", f"Finished color #{ci + 1}.")
    log_event("DRAW", "All selected pixels completed.")


def _click(x, y, click_hold, delay, pause_event=None, on_click=None):
    """Send a deliberate press/release and let the app process the click."""
    if not _wait_until_running(pause_event):
        return False
    if STOP_EVENT.is_set():
        return False
    pyautogui.moveTo(x, y)
    pressed = False
    try:
        pyautogui.mouseDown()
        pressed = True
        deadline = time.monotonic() + click_hold
        while not STOP_EVENT.is_set():
            if pause_event is not None and not pause_event.is_set():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            STOP_EVENT.wait(min(remaining, 0.01))
    finally:
        if pressed:
            pyautogui.mouseUp()
    if STOP_EVENT.is_set():
        return False
    if on_click is not None:
        on_click()
    if not _wait_until_running(pause_event):
        return False
    return not STOP_EVENT.wait(delay)


def _validate_timing(delay, click_hold):
    if not math.isfinite(delay) or delay < 0:
        raise ValueError(
            "Delay must be a finite number greater than or equal to zero.")
    if not math.isfinite(click_hold) or click_hold <= 0:
        raise ValueError(
            "Click hold must be a finite number greater than zero.")


def _parse_skip_colors(response, n_colors):
    """Parse a comma-separated list of 1-based palette colors to skip."""
    response = response.strip()
    if not response:
        return set()

    try:
        color_numbers = [int(value.strip()) for value in response.split(",")]
    except ValueError as exc:
        raise ValueError(
            f"Enter comma-separated color numbers from 1 to {n_colors}.") from exc
    if any(not 1 <= number <= n_colors for number in color_numbers):
        raise ValueError(
            f"Enter comma-separated color numbers from 1 to {n_colors}.")
    return {number - 1 for number in color_numbers}


class DrawingApp:
    def __init__(self, root, args):
        _require_runtime_deps("Pillow", "tkinter", "numpy", "pyautogui")
        self.root = root
        self.events = queue.Queue()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.worker = None
        self.manual_color_event = None
        self.auto_select_remaining = False
        try:
            with open(CONFIG_FILE, encoding="utf-8") as config_file:
                self.config = json.load(config_file)
        except FileNotFoundError:
            self.config = {}

        saved_palette = self.config.get("palette_rgb", [])
        color_count = args.colors or len(saved_palette) or 12
        self.image_path = tk.StringVar(value=args.image or "")
        self.grid_count = tk.StringVar(value=str(args.grid))
        self.color_count = tk.StringVar(value=str(color_count))
        self.delay = tk.StringVar(value=str(args.delay))
        self.click_hold = tk.StringVar(value=str(args.click_hold))
        self.use_dither = tk.BooleanVar(value=args.dither)
        self.manual = tk.BooleanVar(value=args.manual)
        self.auto_select_remaining_enabled = tk.BooleanVar(value=False)
        self.status = tk.StringVar(
            value="Choose an image, drawing area, and palette to get started.")
        self.progress = tk.StringVar(value="Not started")

        self._configure_style()
        root.title("Pixel Painting")
        root.geometry("900x780")
        root.minsize(720, 560)
        self.preview_source = None
        self.preview_image = None
        self._build_widgets()
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)
        self.root.bind_all("<Button-4>", self._on_mousewheel)
        self.root.bind_all("<Button-5>", self._on_mousewheel)
        self.root.after(80, self._process_events)

    def _configure_style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        self.root.configure(background="#edf2f7")
        style.configure("App.TFrame", background="#edf2f7")
        style.configure("Header.TFrame", background="#14213d")
        style.configure(
            "Title.TLabel", background="#14213d", foreground="#ffffff",
            font=("Segoe UI", 18, "bold"))
        style.configure(
            "Subtitle.TLabel", background="#14213d", foreground="#dbeafe",
            font=("Segoe UI", 9))
        style.configure(
            "Section.TLabelframe", background="#ffffff", borderwidth=1,
            relief="solid")
        style.configure(
            "Section.TLabelframe.Label", background="#ffffff",
            foreground="#14213d", font=("Segoe UI", 10, "bold"))
        style.configure(
            "TLabel", background="#ffffff", foreground="#263449",
            font=("Segoe UI", 9))
        style.configure("TCheckbutton", background="#ffffff")
        style.configure("TEntry", padding=5)
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 9))
        style.configure(
            "Primary.TButton", background="#2563eb", foreground="#ffffff",
            font=("Segoe UI", 10, "bold"))
        style.map(
            "Primary.TButton",
            background=[("disabled", "#aebbd0"), ("active", "#1d4ed8")],
            foreground=[("disabled", "#eef2f7"), ("!disabled", "#ffffff")])
        style.configure(
            "Pause.TButton", background="#fbbf24", foreground="#422006")
        style.configure(
            "Stop.TButton", background="#ef4444", foreground="#ffffff")
        style.configure(
            "Status.TLabel", background="#e0f2fe", foreground="#0c4a6e",
            padding=8, font=("Segoe UI", 9, "bold"))
        style.configure(
            "Progress.TLabel", background="#ffffff", foreground="#475569",
            padding=4, font=("Consolas", 9))
        style.configure(
            "Preview.TLabel", background="#f8fafc", foreground="#64748b")
        style.configure(
            "CountdownTitle.TLabel", background="#14213d", foreground="#ffffff",
            font=("Segoe UI", 11, "bold"))
        style.configure(
            "CountdownHint.TLabel", background="#14213d", foreground="#dbeafe",
            font=("Segoe UI", 9))
        style.configure(
            "CountdownNumber.TLabel", background="#14213d", foreground="#fbbf24",
            font=("Segoe UI", 24, "bold"))

    def _build_widgets(self):
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        self.scroll_canvas = tk.Canvas(
            shell, background="#edf2f7", highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            shell, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.scroll_canvas.pack(side="left", fill="both", expand=True)

        panel = ttk.Frame(
            self.scroll_canvas, style="App.TFrame", padding=(14, 14, 14, 20))
        self.panel_window = self.scroll_canvas.create_window(
            (0, 0), window=panel, anchor="nw")
        panel.bind("<Configure>", self._update_scroll_region)
        self.scroll_canvas.bind("<Configure>", self._resize_panel)

        header = ttk.Frame(panel, style="Header.TFrame", padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="PIXEL PAINTING", style="Title.TLabel").pack(
            anchor="w")
        ttk.Label(
            header,
            text="Turn an image into pixel art using your game's color palette.",
            style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(
            header,
            text="Select an image  /  Capture colors  /  Preview  /  Draw",
            style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

        image_section = ttk.LabelFrame(
            panel, text="  1. Source image  ", style="Section.TLabelframe",
            padding=10)
        image_section.grid(row=1, column=0, sticky="ew", pady=5)
        ttk.Entry(image_section, textvariable=self.image_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(image_section, text="Browse...", command=self._choose_image).grid(
            row=0, column=1)
        image_section.grid_columnconfigure(0, weight=1)

        settings = ttk.LabelFrame(
            panel, text="  2. Drawing settings  ", style="Section.TLabelframe",
            padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=5)
        self._add_setting(settings, "Longest edge (cells)", self.grid_count, 0)
        self._add_setting(settings, "Palette colors", self.color_count, 2)
        self._add_setting(settings, "Delay (s)", self.delay, 4)
        self._add_setting(settings, "Click hold (s)", self.click_hold, 6)
        ttk.Checkbutton(
            settings, text="Use dithering", variable=self.use_dither).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            settings, text="Select each game color manually (confirm with F10)",
            variable=self.manual,
            command=self._update_manual_options).grid(
                row=1, column=2, columnspan=4, sticky="w", pady=(8, 0))
        self.auto_select_remaining_check = ttk.Checkbutton(
                settings, text="After first manual color, auto-select the rest",
            variable=self.auto_select_remaining_enabled)
        self.auto_select_remaining_check.grid(
            row=2, column=2, columnspan=4, sticky="w", pady=(5, 0))

        setup = ttk.LabelFrame(
            panel, text="  3. Drawing area and palette  ",
            style="Section.TLabelframe", padding=10)
        setup.grid(row=3, column=0, sticky="ew", pady=5)
        ttk.Button(
            setup, text="Select drawing area",
            command=self._select_region).grid(
                row=0, column=0, padx=(0, 6))
        ttk.Button(
            setup, text="Capture game palette",
            command=self._select_palette).grid(
                row=0, column=1, padx=6)
        ttk.Button(
            setup, text="Generate preview",
            command=self._make_preview).grid(
                row=0, column=2, padx=6)
        self.region_label = ttk.Label(
            setup, text=self._region_description(), anchor="w")
        self.region_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        controls = ttk.LabelFrame(
            panel, text="  4. Drawing controls  ", style="Section.TLabelframe",
            padding=10)
        controls.grid(row=4, column=0, sticky="ew", pady=5)
        button_row = ttk.Frame(controls)
        button_row.pack(fill="x")
        self.start_button = ttk.Button(
            button_row, text="Start", command=self.start,
            style="Primary.TButton")
        self.start_button.pack(side="left", padx=(0, 6))
        self.pause_button = ttk.Button(
            button_row, text="Pause", command=self.pause,
            style="Pause.TButton", state="disabled")
        self.pause_button.pack(side="left", padx=6)
        self.resume_button = ttk.Button(
            button_row, text="Resume", command=self.resume,
            style="Primary.TButton", state="disabled")
        self.resume_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            button_row, text="Stop", command=self.stop,
            style="Stop.TButton", state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.manual_selected_button = ttk.Button(
            button_row, text="Confirm selected color (F10)",
            command=self._confirm_manual_color, state="disabled")
        self.manual_selected_button.pack(side="left", padx=6)
        ttk.Label(
            controls, text="F10: confirm color  |  F11: pause/resume  |  F12: stop",
            style="Progress.TLabel").pack(anchor="w", pady=(7, 0))

        ttk.Label(
            panel, textvariable=self.status, style="Status.TLabel",
            anchor="w").grid(row=5, column=0, sticky="ew", pady=(5, 2))
        ttk.Label(
            panel, textvariable=self.progress, style="Progress.TLabel",
            anchor="w").grid(row=6, column=0, sticky="ew")
        palette_section = ttk.LabelFrame(
            panel, text="  5. Colors to skip (optional)  ",
            style="Section.TLabelframe", padding=8)
        palette_section.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(
            palette_section,
            text=("Click colors to exclude them from drawing. "
                  "Use Ctrl+click to select multiple colors."),
            style="Preview.TLabel", anchor="w").pack(fill="x", pady=(0, 6))
        list_frame = ttk.Frame(palette_section)
        list_frame.pack(fill="x")
        self.palette_list = tk.Listbox(
            list_frame, selectmode=tk.EXTENDED, exportselection=False,
            height=8, font=("Consolas", 10), borderwidth=1,
            relief="solid", activestyle="none")
        palette_scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.palette_list.yview)
        self.palette_list.configure(yscrollcommand=palette_scrollbar.set)
        self.palette_list.pack(side="left", fill="x", expand=True)
        palette_scrollbar.pack(side="right", fill="y")
        self.palette_list.bind("<<ListboxSelect>>", self._save_skipped_colors)
        self._refresh_palette_list()

        preview_section = ttk.LabelFrame(
            panel, text="  6. Full preview  ", style="Section.TLabelframe",
            padding=8)
        preview_section.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        self.preview_label = ttk.Label(
            preview_section, text="Your complete preview will appear here.",
            style="Preview.TLabel", anchor="center", relief="sunken")
        self.preview_label.pack(fill="x", expand=True)
        panel.grid_columnconfigure(0, weight=1)

    def _update_scroll_region(self, _event=None):
        self.scroll_canvas.configure(
            scrollregion=self.scroll_canvas.bbox("all"))

    def _resize_panel(self, event):
        self.scroll_canvas.itemconfigure(self.panel_window, width=event.width)
        self._render_preview()

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            direction = -1 if event.delta > 0 else 1
        self.scroll_canvas.yview_scroll(direction, "units")
        return "break"

    def _render_preview(self):
        if self.preview_source is None:
            return
        available_width = max(200, self.scroll_canvas.winfo_width() - 48)
        preview = self.preview_source
        if preview.width > available_width:
            height = round(preview.height * available_width / preview.width)
            preview = preview.resize(
                (available_width, height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_image, text="")

    @staticmethod
    def _add_setting(parent, label, variable, column):
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w")
        ttk.Entry(parent, textvariable=variable, width=7).grid(
            row=0, column=column + 1, padx=(3, 12))

    def _region_description(self):
        box = self.config.get("box")
        if not box:
            return "No drawing area selected."
        return f"Selected area: {box[2] - box[0]} x {box[3] - box[1]} px"

    def _refresh_palette_list(self, counts=None, reset_selection=False):
        if not hasattr(self, "palette_list"):
            return
        palette = self.config.get("palette_rgb", [])
        selected = set() if reset_selection else self._skipped_color_indices()
        self.palette_list.delete(0, tk.END)
        for index, color in enumerate(palette):
            rgb = tuple(int(channel) for channel in color)
            hex_color = "#{:02X}{:02X}{:02X}".format(*rgb)
            suffix = (f" - {int(counts[index])} pixels"
                      if counts is not None else "")
            self.palette_list.insert(
                tk.END, f"  #{index + 1:02d}  {hex_color}{suffix}")
            luminance = sum(
                channel * weight for channel, weight in zip(
                    rgb, (0.299, 0.587, 0.114)))
            foreground = "#111827" if luminance > 145 else "#FFFFFF"
            self.palette_list.itemconfigure(
                index, background=hex_color, foreground=foreground)
            if index in selected:
                self.palette_list.selection_set(index)
        self.palette_list.configure(height=min(max(len(palette), 3), 8))
        if hasattr(self, "auto_select_remaining_check"):
            self._update_manual_options()

    def _update_manual_options(self):
        palette_points = self.config.get("palette_pts")
        palette = self.config.get("palette_rgb", [])
        has_captured_palette = (
            bool(palette_points) and len(palette_points) == len(palette))
        manual_enabled = self.manual.get()
        self.auto_select_remaining_check.configure(
            state=("normal" if manual_enabled and has_captured_palette
                   else "disabled"))
        if not manual_enabled or not has_captured_palette:
            self.auto_select_remaining_enabled.set(False)

    def _skipped_color_indices(self):
        palette = self.config.get("palette_rgb", [])
        saved = self.config.get("skip_colors", [])
        if not isinstance(saved, list):
            return set()
        return {
            index for index in saved
            if type(index) is int and 0 <= index < len(palette)
        }

    def _save_skipped_colors(self, _event=None):
        if not hasattr(self, "palette_list"):
            return
        self.config["skip_colors"] = list(
            map(int, self.palette_list.curselection()))
        self._save_config()

    def _save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump(self.config, config_file)

    def _choose_image(self):
        path = filedialog.askopenfilename(
            title="Choose an image to draw",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                       ("All files", "*.*")])
        if path:
            self.image_path.set(path)
            self.preview_source = None
            self.preview_image = None
            self.preview_label.configure(
                image="", text="Generate a preview for the selected image.")
            self._refresh_palette_list()

    def _select_region(self):
        try:
            self.config["box"] = select_region(self.root)
            self._save_config()
            self.region_label.config(text=self._region_description())
            if self.image_path.get().strip() and self.config.get("palette_rgb"):
                self._make_preview()
            else:
                self._set_status("Drawing area selected.")
        except Exception as exc:
            messagebox.showerror("Drawing area selection failed", str(exc))

    def _select_palette(self):
        try:
            count = int(self.color_count.get())
            if not 1 <= count <= 256:
                raise ValueError("Palette size must be between 1 and 256.")
            points, colors = pick_palette(count, self.root)
            self.config["palette_pts"] = points
            self.config["palette_rgb"] = colors
            self.config["skip_colors"] = []
            self._refresh_palette_list(reset_selection=True)
            self._save_config()
            if self.image_path.get().strip() and self.config.get("box"):
                self._make_preview()
            else:
                self._set_status(
                    f"Captured {len(colors)} colors from the game.")
        except Exception as exc:
            messagebox.showerror("Palette capture failed", str(exc))

    def _get_image_data(self):
        path = self.image_path.get().strip()
        box = self.config.get("box")
        palette = self.config.get("palette_rgb")
        if not path or not os.path.isfile(path):
            raise ValueError("Choose a valid image file.")
        if not box:
            raise ValueError("Select a drawing area first.")
        if not palette:
            raise ValueError("Capture the game palette first.")
        max_cells = int(self.grid_count.get())
        if max_cells <= 0:
            raise ValueError("The longest grid edge must be greater than zero.")
        grid_size = grid_for_box(box, max_cells)
        idx = quantize(path, grid_size, palette, self.use_dither.get())
        return idx, box, palette

    def _make_preview(self):
        try:
            idx, _, palette = self._get_image_data()
            save_preview(idx, palette, path="preview.png")
            with Image.open("preview.png") as preview_file:
                self.preview_source = preview_file.copy()
            self._render_preview()
            counts = np.bincount(idx.ravel(), minlength=len(palette))
            self._refresh_palette_list(counts)
            used = int(np.count_nonzero(counts))
            self._set_status(
                f"Preview: {idx.shape[1]} x {idx.shape[0]} cells, "
                f"{len(palette)} palette colors, {used} colors used.")
        except Exception as exc:
            messagebox.showerror("Preview generation failed", str(exc))

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            idx, box, palette = self._get_image_data()
            delay = float(self.delay.get())
            click_hold = float(self.click_hold.get())
            _validate_timing(delay, click_hold)
        except Exception as exc:
            messagebox.showerror("Cannot start drawing", str(exc))
            return

        STOP_EVENT.clear()
        self.pause_event.set()
        self.manual_color_event = None
        self.auto_select_remaining = False
        self.manual_selected_button.config(state="disabled")
        palette_points = self.config.get("palette_pts")
        manual = self.manual.get() or palette_points is None
        active_colors = [
            color for color in range(len(palette))
            if color not in self._skipped_color_indices()
            and np.any(idx == color)
        ]
        if not active_colors:
            message = (
                "No pixels remain to draw. Clear one or more colors from "
                "'Colors to skip' and generate the preview again.")
            log_event("ERROR", message)
            messagebox.showerror("Nothing to draw", message)
            return
        if not manual and len(palette_points) != len(palette):
            messagebox.showerror(
                "Invalid palette",
                "The number of palette positions does not match the palette. "
                "Capture the palette again or enable manual color selection.")
            return
        self.progress.set("Starting from the first pixel")
        self._set_running_controls(True)
        self._set_status(
            "Switch to the drawing app. Confirm manual colors with F10, or "
            "auto-select remaining captured colors; F11 pauses; F12 stops.")
        log_event(
            "START",
            f"Prepared grid {idx.shape[1]}x{idx.shape[0]} in area {box}; "
            f"palette={len(palette)}, click hold={click_hold * 1000:.0f}ms, "
            f"delay={delay * 1000:.1f}ms, manual-color-mode={manual}.")
        if manual:
            log_event(
                "MANUAL",
                "Choose the first game swatch, then press F10 to confirm or "
                "auto-select the remaining captured palette colors.")
        self.root.lower()
        log_event(
            "COUNTDOWN",
            "Four-second start countdown; switch to the drawing app now.")
        if not _selection_countdown(
                self.root, 4, title="SWITCH TO THE DRAWING APP",
                instruction="Drawing starts in", cancel_event=STOP_EVENT):
            self._set_running_controls(False)
            self._set_status("Drawing stopped before it started.")
            log_event("STOP", "Drawing cancelled during the start countdown.")
            return
        if STOP_EVENT.is_set():
            self._set_running_controls(False)
            self._set_status("Drawing stopped before it started.")
            log_event("STOP", "Emergency stop before the first pixel.")
            return
        target_point = (
            palette_points[0] if palette_points
            else ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        )
        try:
            _focus_window_at(*target_point, own_window=self.root.winfo_id())
        except RuntimeError as exc:
            self._set_running_controls(False)
            self._set_status("Could not activate the game window.")
            log_event("ERROR", f"Could not activate drawing target: {exc}")
            messagebox.showerror("Cannot focus game window", str(exc))
            return
        time.sleep(0.15)
        skip_colors = self._skipped_color_indices()
        log_event(
            "START",
            f"Drawing begins; excluded colors: "
            f"{', '.join(f'#{i + 1}' for i in sorted(skip_colors)) or 'none'}.")
        self.worker = threading.Thread(
            target=self._draw_worker,
            args=(idx, box, palette, palette_points, skip_colors, manual,
                  delay, click_hold),
            daemon=True)
        self.worker.start()

    def _draw_worker(self, idx, box, palette, palette_points, skip_colors,
                     manual, delay, click_hold):
        try:
            draw(
                idx, box, palette_points, skip_colors, delay, len(palette),
                manual,
                click_hold, self.pause_event, self._pixel_completed,
                automatic=True, on_manual_color=self._wait_for_manual_color)
            state = "Stopped." if STOP_EVENT.is_set() else "Drawing complete."
            self.events.put(("finished", state))
        except Exception as exc:
            log_event("ERROR", f"Drawing worker failed: {exc}")
            self.events.put(("error", str(exc)))

    def _wait_for_manual_color(self, color_index):
        event = threading.Event()
        self.manual_color_event = event
        self.events.put(("manual_color", color_index + 1))
        log_event(
            "MANUAL",
            f"Waiting for game color #{color_index + 1}; select its swatch "
            "and press F10.")
        while not STOP_EVENT.is_set():
            if not _wait_until_running(self.pause_event):
                return False
            if event.wait(0.05):
                self.manual_color_event = None
                return ("auto_remaining" if self.auto_select_remaining
                        else True)
        return False

    def _confirm_manual_color(self):
        if self.manual_color_event is not None:
            self.auto_select_remaining = (
                self.auto_select_remaining_enabled.get())
            self.manual_color_event.set()
            self.manual_selected_button.config(state="disabled")
            if self.auto_select_remaining:
                self._set_status(
                    "Color confirmed. Remaining colors will be selected "
                    "automatically.")
                log_event(
                    "MANUAL",
                    "Current color confirmed; automatically selecting all "
                    "remaining captured palette colors.")
            else:
                self._set_status("Color confirmed; drawing will continue.")
                log_event("COLOR", "Manual game color selection confirmed.")

    def request_manual_confirm(self):
        if self.manual_color_event is None:
            log_event("MANUAL", "F10 ignored; no color is awaiting confirmation.")
            return
        self.events.put(("manual_confirm", None))
        log_event("HOTKEY", "Queued manual color confirmation on the GUI thread.")

    def _pixel_completed(self, color, number, total, x, y):
        self.events.put(
            ("progress", (color + 1, number, total, x, y,
                          not self.pause_event.is_set())))

    def _process_events(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "progress":
                    color, number, total, x, y, paused = value
                    self.progress.set(
                        f"Color #{color}: pixel {number}/{total}; "
                        f"last position ({x}, {y})")
                    if paused:
                        self.status.set(
                            "Paused after the current click completed.")
                elif event == "finished":
                    self._set_status(value)
                    self._set_running_controls(False)
                    self.manual_selected_button.config(state="disabled")
                elif event == "error":
                    self._set_status("Drawing failed.")
                    self._set_running_controls(False)
                    self.manual_selected_button.config(state="disabled")
                    messagebox.showerror("Drawing error", value)
                elif event == "manual_color":
                    self._set_status(
                        f"Select color #{value} in the game, then click "
                        "'Confirm selected color (F10)'.")
                    self.manual_selected_button.config(state="normal")
                elif event == "manual_confirm":
                    self._confirm_manual_color()
                elif event == "pause_toggle":
                    if self.worker is not None and self.worker.is_alive():
                        if self.pause_event.is_set():
                            self.pause()
                        else:
                            self.resume()
        except queue.Empty:
            pass
        self.root.after(80, self._process_events)

    def pause(self):
        if self.worker is not None and self.worker.is_alive():
            self.pause_event.clear()
            self.pause_button.config(state="disabled")
            self.resume_button.config(state="normal")
            self._set_status("Pausing after the current click...")
            log_event("PAUSE", "Pause requested; current click will be released.")

    def resume(self):
        if self.worker is not None and self.worker.is_alive():
            self.pause_event.set()
            self.pause_button.config(state="normal")
            self.resume_button.config(state="disabled")
            self._set_status("Resuming from the next pixel...")
            log_event("RESUME", "Drawing resumed from the next pixel.")

    def stop(self):
        log_event("STOP", "Stop requested from the GUI.")
        STOP_EVENT.set()
        self.pause_event.set()
        if self.manual_color_event is not None:
            self.manual_color_event.set()
        self._set_status("Stopping...")
        self.resume_button.config(state="disabled")
        self.stop_button.config(state="disabled")
        self.manual_selected_button.config(state="disabled")

    def request_pause_toggle(self):
        self.events.put(("pause_toggle", None))

    def _set_running_controls(self, running):
        self.start_button.config(state="disabled" if running else "normal")
        self.pause_button.config(state="normal" if running else "disabled")
        self.resume_button.config(state="disabled")
        self.stop_button.config(state="normal" if running else "disabled")

    def _set_status(self, text):
        self.status.set(text)

    def close(self, listener):
        STOP_EVENT.set()
        self.pause_event.set()
        listener.stop()
        self.root.destroy()


def run_gui(args):
    _require_runtime_deps("tkinter", "Pillow", "numpy", "pyautogui")
    root = tk.Tk()
    app = DrawingApp(root, args)
    listener = _start_emergency_listener(
        app.request_pause_toggle, app.request_manual_confirm)
    root.protocol("WM_DELETE_WINDOW", lambda: app.close(listener))
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(
        description="Convert an image to pixel art and draw it by clicking.")
    ap.add_argument(
        "image", nargs="?", help="source image (omit to open the GUI)")
    ap.add_argument(
        "--grid", type=int, default=60,
        help="cells along the longer edge of the drawing area (default: 60)")
    ap.add_argument(
        "--colors", type=int, default=None,
        help="palette size, 1..256 (default: prompt, or 12 on Enter)")
    ap.add_argument("--dither", action="store_true", help="enable dithering")
    ap.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help="seconds after each click (default: 0.02; must be finite and >= 0)")
    ap.add_argument(
        "--click-hold", type=float, default=DEFAULT_CLICK_HOLD,
        help="mouse press duration in seconds (default: 0.05; must be finite and > 0)")
    ap.add_argument(
        "--manual", action="store_true",
        help="select each game color manually; the tool only clicks pixels")
    ap.add_argument(
        "--palette-hex", default=None,
        help='comma-separated RRGGBB colors, e.g. "ffffff,000000,ff0000" '
             "(automatically enables --manual)")
    ap.add_argument(
        "--recalibrate", action="store_true",
        help="select the drawing area and palette again")
    a = ap.parse_args()
    if a.grid <= 0:
        ap.error("--grid must be greater than zero")
    try:
        _validate_timing(a.delay, a.click_hold)
    except ValueError as exc:
        ap.error(str(exc))
    if a.colors is not None and not 1 <= a.colors <= 256:
        ap.error("--colors must be between 1 and 256")

    if a.image is None:
        run_gui(a)
        return

    cfg = {}
    if os.path.exists(CONFIG_FILE) and not a.recalibrate:
        with open(CONFIG_FILE, encoding="utf-8") as config_file:
            cfg = json.load(config_file)
        saved_colors = len(cfg.get("palette_rgb", []))
        print(f"Reusing the saved configuration with {saved_colors} colors "
              "(use --colors N to change the palette size).")
    if "box" not in cfg:
        countdown(
            5, "Step 1: Select the drawing area. Switch to the game; "
               "the screen will be captured in 5 seconds...")
        cfg["box"] = select_region()

    manual = a.manual
    if a.palette_hex is not None:
        hexes = [h.strip().lstrip("#") for h in a.palette_hex.split(",")]
        if not hexes or len(hexes) > 256 or any(
                len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h)
                for h in hexes):
            ap.error(
                "--palette-hex must be a comma-separated list of valid "
                "RRGGBB colors")
        if a.colors is not None and a.colors != len(hexes):
            ap.error("--colors must match the number of colors in --palette-hex")
        cfg["palette_rgb"] = [
            tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in hexes
        ]
        cfg["palette_pts"] = None
        manual = True
    elif ("palette_rgb" not in cfg
          or (cfg.get("palette_pts") is None and not manual)
          or (a.colors is not None
              and len(cfg.get("palette_rgb") or []) != a.colors)):
        n = a.colors
        while not n:
            t = input(
                "How many colors are in the game palette? (Enter = 12): "
            ).strip()
            n = (int(t) if t.isdigit() and int(t) > 0
                 else (12 if t == "" else None))
            if n is not None and not 1 <= n <= 256:
                print("  Enter a number from 1 to 256.")
                n = None
        countdown(
            5, f"Step 2: Select {n} palette colors. Switch to the game; "
               "the screen will be captured in 5 seconds...")
        pts, cols = pick_palette(n)
        cfg["palette_pts"], cfg["palette_rgb"] = pts, cols
    with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
        json.dump(cfg, config_file)

    box, pts, cols = cfg["box"], cfg["palette_pts"], cfg["palette_rgb"]
    print(
        "Drawing area:", box, "| width x height =",
        box[2] - box[0], "x", box[3] - box[1])
    if pts is None:
        manual = True

    grid_size = grid_for_box(box, a.grid)
    print(
        f"Drawing grid: {grid_size[0]} x {grid_size[1]} "
        "(width x height).")
    idx = quantize(a.image, grid_size, cols, a.dither)
    save_preview(idx, cols)
    counts = np.bincount(idx[idx >= 0].astype(int), minlength=len(cols))
    used_colors = int(np.count_nonzero(counts))
    print(f"Palette contains {len(cols)} colors; image uses {used_colors}.")
    for i, (rgb, count) in enumerate(zip(cols, counts), 1):
        hex_color = "#{:02X}{:02X}{:02X}".format(*rgb)
        print(f"  Color #{i}: {hex_color} - {int(count)} pixels")
    print("Saved preview.png with the captured RGB colors and legend.")

    listener = _start_emergency_listener()
    try:
        print("Press F12 at any time for an emergency stop.")
        while True:
            response = _readline_or_stop(
                "Enter color numbers to skip (e.g. 1,3; leave blank to draw all): "
            )
            if response is None:
                print("Emergency stop (F12).")
                return
            try:
                skip = _parse_skip_colors(response, len(cols))
                break
            except ValueError as exc:
                print(f"  {exc}")

        total = int(np.sum(idx >= 0))
        print(f"Approximately {total} clicks.")
        if manual:
            print("Select each color manually; enter y to draw or s to skip.")
        else:
            print(
                "Each color prompts for confirmation; enter a to draw all "
                "remaining colors.")
        draw(idx, box, pts, skip, a.delay, len(cols), manual, a.click_hold)
        if not STOP_EVENT.is_set():
            print("Drawing complete.")
    finally:
        listener.stop()
        listener.join()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
