"""
BangBang - Auto ve tranh pixel bang click
Cai dat:  pip install -r requirements.txt
Chay:     python bangbang_draw.py anh.png --grid 60 --dither
Giao dien: python bangbang_draw.py

Quy trinh:
  Chay khong co tep anh de mo giao dien chon anh, vung ve, mau va dieu khien.
  1. Keo tha chuot de chon khung ve (goc tren-trai -> goc duoi-phai)
  2. Click lan luot len cac o mau trong bang mau cua game (tool tu lay ma mau RGB)
  3. Tool gan pixel vao cac mau da lay, luu preview.png kem chu giai mau
  4. Xac nhan tung mau hoac chon ve tat ca; giu chuot moi click de Paint nhan on dinh
  5. Bam F12 bat ky luc nao trong khi ve de dung khan cap

Dung khan cap: day chuot vao GOC TREN-TRAI man hinh (pyautogui failsafe).
"""
import argparse
import ctypes
import json
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
except ImportError:  # pragma: no cover - GUI dependency is optional for import-time checks.
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy is required only when actually quantizing images.
    np = None

try:
    import pyautogui
except ImportError:  # pragma: no cover - GUI automation dependency is optional at import time.
    pyautogui = None

try:
    from PIL import Image, ImageDraw, ImageGrab, ImageTk
except ImportError:  # pragma: no cover - image processing dependency is optional at import time.
    Image = None
    ImageDraw = None
    ImageGrab = None
    ImageTk = None

if pyautogui is not None:
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.0
CONFIG_FILE = "bangbang_config.json"
STOP_EVENT = threading.Event()


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


# ---------------------------------------------------------------- tien ich
def countdown(sec, msg, pause_event=None):
    print(msg)
    for i in range(sec, 0, -1):
        print(f"  {i}...", end="\r", flush=True)
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            if STOP_EVENT.is_set() or not _wait_until_running(pause_event):
                print("\nDa dung khan cap (F12).")
                return False
            STOP_EVENT.wait(min(0.05, deadline - time.monotonic()))
    print(" " * 20, end="\r")
    return True


def ask_yes(prompt):
    """Tra ve 'y' (ve), 'a' (ve tat ca), 's' (bo qua) hoac 'q' (thoat)."""
    while True:
        a = _readline_or_stop(prompt)
        if a is None:
            return None
        if a in ("y", "a", "s", "q"):
            return a
        print("  Chi nhap y / a / s / q.")


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


def _start_emergency_listener():
    try:
        from pynput import keyboard
    except ImportError as exc:
        raise RuntimeError(
            "Missing required dependency for the emergency stop hotkey: pynput. "
            "Install the project requirements with 'pip install -r requirements.txt'."
        ) from exc

    def on_press(key):
        if key == keyboard.Key.f12:
            STOP_EVENT.set()

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    return listener


def _wait_until_running(pause_event):
    while not STOP_EVENT.is_set():
        if pause_event is None or pause_event.wait(0.02):
            return not STOP_EVENT.is_set()
    return False


# ---------------------------------------------------------------- UI chon vung
def _overlay(title, parent=None):
    """Mo cua so toan man hinh co anh chup man hinh lam nen."""
    _require_runtime_deps("Pillow", "tkinter")
    if parent is not None:
        parent.withdraw()
        parent.update_idletasks()
        parent.update()
        _selection_countdown(parent, title, 4)
    shot = ImageGrab.grab()
    root = tk.Toplevel(parent) if parent is not None else tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    scale_x, scale_y = shot.width / sw, shot.height / sh
    bg = ImageTk.PhotoImage(shot.resize((sw, sh)))
    canvas = tk.Canvas(root, width=sw, height=sh, cursor="crosshair",
                       highlightthickness=0)
    canvas.pack()
    canvas.create_image(0, 0, image=bg, anchor="nw")
    canvas.create_rectangle(10, 10, 900, 50, fill="black")
    canvas.create_text(20, 30, text=title, fill="yellow", anchor="w",
                       font=("Arial", 14, "bold"))
    root.bg = bg  # giu tham chieu
    return root, canvas, shot, scale_x, scale_y


def _selection_countdown(parent, title, seconds):
    countdown = tk.Toplevel(parent)
    countdown.title("Chuan bi chon")
    countdown.attributes("-topmost", True)
    countdown.resizable(False, False)
    countdown.configure(background="#14213d")
    width, height = 440, 132
    x = (countdown.winfo_screenwidth() - width) // 2
    y = 48
    countdown.geometry(f"{width}x{height}+{x}+{y}")
    ttk.Label(
        countdown, text="CHUAN BI CHUP MAN HINH",
        style="CountdownTitle.TLabel").pack(pady=(14, 4))
    instruction = "Chuyen sang game; man hinh se duoc chup sau"
    ttk.Label(
        countdown, text=instruction,
        style="CountdownHint.TLabel").pack()
    counter = ttk.Label(countdown, text=str(seconds),
                        style="CountdownNumber.TLabel")
    counter.pack(pady=(0, 8))
    countdown.update()

    deadline = time.monotonic() + seconds
    remaining = seconds
    while remaining > 0:
        countdown.update()
        next_remaining = max(
            0, int(deadline - time.monotonic() + 0.999))
        if next_remaining != remaining:
            remaining = next_remaining
            counter.configure(text=str(remaining))
        time.sleep(0.03)
    countdown.destroy()
    parent.update_idletasks()


def select_region(parent=None):
    try:
        root, canvas, shot, sx, sy = _overlay(
            "KEO CHUOT tu goc TREN-TRAI den goc DUOI-PHAI khung ve (ESC = thoat)",
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
            state["box"] = (int(min(x0, x1) * sx), int(min(y0, y1) * sy),
                            int(max(x0, x1) * sx), int(max(y0, y1) * sy))
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
            raise RuntimeError("Da huy chon vung ve.")
        return state["box"]
    finally:
        _restore_parent_behind(parent)


def pick_palette(n, parent=None):
    try:
        root, canvas, shot, sx, sy = _overlay(
            f"CLICK lan luot {n} o mau trong bang mau cua game (ESC = thoat)",
            parent)
        points, colors = [], []

        def click(e):
            px = min(shot.width - 1, max(0, int(e.x * sx)))
            py = min(shot.height - 1, max(0, int(e.y * sy)))
            rgb = shot.getpixel((px, py))[:3]
            points.append((px, py))
            colors.append(rgb)
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
            raise RuntimeError("Da huy chon bang mau.")
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


# ------------------------------------------------------------- xu ly anh
def grid_for_box(box, max_cells):
    """Return rectangular grid dimensions proportional to the selected box."""
    x1, y1, x2, y2 = box
    width, height = x2 - x1, y2 - y1
    if width <= 0 or height <= 0:
        raise ValueError("Vung ve phai co chieu rong va chieu cao lon hon 0.")
    longest = max(width, height)
    grid_w = max(1, round(max_cells * width / longest))
    grid_h = max(1, round(max_cells * height / longest))
    return grid_w, grid_h


def quantize(img_path, grid_size, palette_rgb, dither):
    """Resize the full image to the selected box's grid, then map to its palette."""
    _require_runtime_deps("numpy", "Pillow")
    if not palette_rgb:
        raise ValueError("Bang mau khong duoc de trong.")
    palette = np.asarray(palette_rgb, dtype=np.float32)
    if palette.ndim != 2 or palette.shape[1] != 3:
        raise ValueError("Moi mau trong bang mau phai co 3 gia tri RGB.")

    grid_w, grid_h = grid_size
    if grid_w <= 0 or grid_h <= 0:
        raise ValueError("Luoi ve phai co chieu rong va chieu cao lon hon 0.")
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


# ---------------------------------------------------------------- ve
def draw(idx, box, palette_pts, skip, delay, n_colors, manual=False,
         click_hold=0.04, pause_event=None, on_pixel=None,
         automatic=False, on_manual_color=None):
    _require_runtime_deps("numpy", "pyautogui")
    x1, y1, x2, y2 = box
    grid_h, grid_w = idx.shape
    cw, ch = (x2 - x1) / grid_w, (y2 - y1) / grid_h
    todo = [c for c in range(n_colors)
            if c not in skip and np.any(idx == c)]
    draw_all = False
    draw_all_from = None
    for k, ci in enumerate(todo, 1):
        if STOP_EVENT.is_set():
            print("\nDa dung khan cap (F12).")
            return
        ys, xs = np.where(idx == ci)
        msg = (f"\n[{k}/{len(todo)} mau co pixel; bang mau #{ci + 1}/"
               f"{n_colors}]: {len(xs)} diem.")
        if manual:
            msg += "\n  >> Hay TU CHON mau nay trong game truoc."
            if automatic and on_manual_color is not None:
                if not on_manual_color(ci):
                    return
        if automatic:
            print(msg + "\n  Dang ve (F12 = dung).")
        elif draw_all:
            print(msg + "\n  Tu dong ve (F12 = dung).")
        else:
            options = "y = ve | s = bo qua mau nay | q = thoat"
            if not manual:
                options += " | a = ve tat ca mau con lai"
            ans = ask_yes(msg + "\n  Bam " + options + ": ")
            if ans in (None, "q"):
                if STOP_EVENT.is_set():
                    print("Da dung khan cap (F12).")
                    return
                print("Da dung.")
                return
            if ans == "s":
                continue
            if ans == "a":
                draw_all = True
                draw_all_from = k
        if not automatic and (not draw_all or k == draw_all_from):
            if not countdown(3, "  Quay lai cua so game..."):
                return
        if not manual:
            px, py = palette_pts[ci]
            if not _click(px, py, click_hold, delay, pause_event):
                print("\nDa dung khan cap (F12).")
                return
            if not automatic and STOP_EVENT.wait(0.05):
                print("\nDa dung khan cap (F12).")
                return
        for pixel_number, (cy, cx) in enumerate(sorted(zip(ys, xs)), 1):
            px = int(x1 + (cx + 0.5) * cw)
            py = int(y1 + (cy + 0.5) * ch)
            def pixel_done():
                if on_pixel is not None:
                    on_pixel(ci, pixel_number, len(xs), px, py)

            if not _click(px, py, click_hold, delay, pause_event, pixel_done):
                print("\nDa dung khan cap (F12).")
                return
        print(f"  Xong mau #{ci + 1}.")


def _click(x, y, click_hold, delay, pause_event=None, on_click=None):
    """Send a deliberate press/release and leave time for the app to process it."""
    if not _wait_until_running(pause_event):
        return False
    if STOP_EVENT.is_set():
        return False
    pyautogui.moveTo(x, y)
    pyautogui.mouseDown()
    try:
        deadline = time.monotonic() + click_hold
        while not STOP_EVENT.is_set():
            if pause_event is not None and not pause_event.is_set():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            STOP_EVENT.wait(min(remaining, 0.01))
    finally:
        pyautogui.mouseUp()
    if STOP_EVENT.is_set():
        return False
    if on_click is not None:
        on_click()
    if not _wait_until_running(pause_event):
        return False
    return not STOP_EVENT.wait(delay)


class DrawingApp:
    def __init__(self, root, args):
        _require_runtime_deps("Pillow", "tkinter", "numpy", "pyautogui")
        self.root = root
        self.args = args
        self.events = queue.Queue()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.worker = None
        self.last_pixel = None
        self.manual_color_event = None
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
        self.status = tk.StringVar(value="Chon anh, vung ve va bang mau de bat dau.")
        self.progress = tk.StringVar(value="Chua bat dau")

        self._configure_style()
        root.title("BangBang - Ve pixel")
        root.geometry("860x760")
        root.minsize(720, 620)
        self._build_widgets()
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
        panel = ttk.Frame(self.root, style="App.TFrame", padding=14)
        panel.pack(fill="both", expand=True)

        header = ttk.Frame(panel, style="Header.TFrame", padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="BANGBANG PIXEL", style="Title.TLabel").pack(
            anchor="w")
        ttk.Label(
            header, text="Chon anh, lay bang mau va dieu khien qua trinh ve.",
            style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

        image_section = ttk.LabelFrame(
            panel, text="  1. Anh nguon  ", style="Section.TLabelframe",
            padding=10)
        image_section.grid(row=1, column=0, sticky="ew", pady=5)
        ttk.Entry(image_section, textvariable=self.image_path).grid(
            row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(image_section, text="Chon anh...", command=self._choose_image).grid(
            row=0, column=1)
        image_section.grid_columnconfigure(0, weight=1)

        settings = ttk.LabelFrame(
            panel, text="  2. Thiet lap  ", style="Section.TLabelframe",
            padding=10)
        settings.grid(row=2, column=0, sticky="ew", pady=5)
        self._add_setting(settings, "Luoi canh dai", self.grid_count, 0)
        self._add_setting(settings, "So mau", self.color_count, 2)
        self._add_setting(settings, "Delay (s)", self.delay, 4)
        self._add_setting(settings, "Giu click (s)", self.click_hold, 6)
        ttk.Checkbutton(
            settings, text="Dithering", variable=self.use_dither).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            settings, text="Tu chon mau thu cong", variable=self.manual).grid(
                row=1, column=2, columnspan=3, sticky="w", pady=(8, 0))

        setup = ttk.LabelFrame(
            panel, text="  3. Vung ve va bang mau  ",
            style="Section.TLabelframe", padding=10)
        setup.grid(row=3, column=0, sticky="ew", pady=5)
        ttk.Button(
            setup, text="Chon vung ve", command=self._select_region).grid(
                row=0, column=0, padx=(0, 6))
        ttk.Button(
            setup, text="Lay mau tu game", command=self._select_palette).grid(
                row=0, column=1, padx=6)
        ttk.Button(
            setup, text="Tao preview", command=self._make_preview).grid(
                row=0, column=2, padx=6)
        self.region_label = ttk.Label(
            setup, text=self._region_description(), anchor="w")
        self.region_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        controls = ttk.LabelFrame(
            panel, text="  4. Dieu khien  ", style="Section.TLabelframe",
            padding=10)
        controls.grid(row=4, column=0, sticky="ew", pady=5)
        self.start_button = ttk.Button(
            controls, text="Bat dau", command=self.start,
            style="Primary.TButton")
        self.start_button.pack(side="left", padx=(0, 6))
        self.pause_button = ttk.Button(
            controls, text="Tam dung", command=self.pause,
            style="Pause.TButton", state="disabled")
        self.pause_button.pack(side="left", padx=6)
        self.resume_button = ttk.Button(
            controls, text="Tiep tuc", command=self.resume,
            style="Primary.TButton", state="disabled")
        self.resume_button.pack(side="left", padx=6)
        self.stop_button = ttk.Button(
            controls, text="Dung", command=self.stop,
            style="Stop.TButton", state="disabled")
        self.stop_button.pack(side="left", padx=6)
        self.manual_selected_button = ttk.Button(
            controls, text="Da chon mau trong game",
            command=self._confirm_manual_color, state="disabled")
        self.manual_selected_button.pack(side="left", padx=6)

        ttk.Label(
            panel, textvariable=self.status, style="Status.TLabel",
            anchor="w").grid(row=5, column=0, sticky="ew", pady=(5, 2))
        ttk.Label(
            panel, textvariable=self.progress, style="Progress.TLabel",
            anchor="w").grid(row=6, column=0, sticky="ew")
        self.preview_label = ttk.Label(
            panel, text="Preview se hien thi tai day", style="Preview.TLabel",
            anchor="center", relief="sunken")
        self.preview_label.grid(row=7, column=0, sticky="nsew", pady=(8, 0))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(7, weight=1)

    @staticmethod
    def _add_setting(parent, label, variable, column):
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w")
        ttk.Entry(parent, textvariable=variable, width=7).grid(
            row=0, column=column + 1, padx=(3, 12))

    def _region_description(self):
        box = self.config.get("box")
        if not box:
            return "Chua chon vung"
        return f"Vung: {box[2] - box[0]} x {box[3] - box[1]}"

    def _save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump(self.config, config_file)

    def _choose_image(self):
        path = filedialog.askopenfilename(
            title="Chon anh de ve",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"),
                       ("All files", "*.*")])
        if path:
            self.image_path.set(path)

    def _select_region(self):
        try:
            self.config["box"] = select_region(self.root)
            self._save_config()
            self.region_label.config(text=self._region_description())
            if self.image_path.get().strip() and self.config.get("palette_rgb"):
                self._make_preview()
            else:
                self._set_status("Da chon vung ve.")
        except Exception as exc:
            messagebox.showerror("Khong chon duoc vung ve", str(exc))

    def _select_palette(self):
        try:
            count = int(self.color_count.get())
            if not 1 <= count <= 256:
                raise ValueError("So mau phai nam trong khoang 1..256.")
            points, colors = pick_palette(count, self.root)
            self.config["palette_pts"] = points
            self.config["palette_rgb"] = colors
            self._save_config()
            if self.image_path.get().strip() and self.config.get("box"):
                self._make_preview()
            else:
                self._set_status(f"Da lay {len(colors)} mau tu giao dien game.")
        except Exception as exc:
            messagebox.showerror("Khong lay duoc bang mau", str(exc))

    def _get_image_data(self):
        path = self.image_path.get().strip()
        box = self.config.get("box")
        palette = self.config.get("palette_rgb")
        if not path or not os.path.isfile(path):
            raise ValueError("Hay chon tep anh hop le.")
        if not box:
            raise ValueError("Hay chon vung ve truoc.")
        if not palette:
            raise ValueError("Hay lay bang mau tu giao dien game truoc.")
        max_cells = int(self.grid_count.get())
        if max_cells <= 0:
            raise ValueError("Luoi canh dai phai lon hon 0.")
        grid_size = grid_for_box(box, max_cells)
        idx = quantize(path, grid_size, palette, self.use_dither.get())
        return idx, box, palette

    def _make_preview(self):
        try:
            idx, _, palette = self._get_image_data()
            save_preview(idx, palette, path="preview.png")
            with Image.open("preview.png") as preview_file:
                preview = preview_file.copy()
            preview.thumbnail((700, 460), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(preview)
            self.preview_label.config(image=self.preview_image, text="")
            counts = np.bincount(idx.ravel(), minlength=len(palette))
            used = int(np.count_nonzero(counts))
            self._set_status(
                f"Preview: {idx.shape[1]} x {idx.shape[0]} o, "
                f"{len(palette)} mau trong bang, {used} mau co pixel.")
        except Exception as exc:
            messagebox.showerror("Khong tao duoc preview", str(exc))

    def start(self):
        if self.worker is not None and self.worker.is_alive():
            return
        try:
            idx, box, palette = self._get_image_data()
            delay = float(self.delay.get())
            click_hold = float(self.click_hold.get())
            if delay < 0 or click_hold <= 0:
                raise ValueError("Delay phai >= 0 va giu click phai > 0.")
        except Exception as exc:
            messagebox.showerror("Khong the bat dau", str(exc))
            return

        STOP_EVENT.clear()
        self.pause_event.set()
        self.last_pixel = None
        self.manual_color_event = None
        palette_points = self.config.get("palette_pts")
        manual = self.manual.get() or palette_points is None
        if not manual and len(palette_points) != len(palette):
            messagebox.showerror(
                "Bang mau khong hop le",
                "So vi tri mau khong khop bang mau. Hay lay lai bang mau "
                "hoac bat tu chon mau thu cong.")
            return
        self.progress.set("Bat dau tu pixel dau tien")
        self._set_running_controls(True)
        self._set_status("Dang bat dau. Bam F12 hoac nut Dung de dung khan cap.")
        self.worker = threading.Thread(
            target=self._draw_worker,
            args=(idx, box, palette, palette_points, manual, delay, click_hold),
            daemon=True)
        self.worker.start()

    def _draw_worker(self, idx, box, palette, palette_points, manual,
                     delay, click_hold):
        try:
            if not countdown(3, "Chuyen sang cua so game...", self.pause_event):
                self.events.put(("finished", "Da dung."))
                return
            draw(
                idx, box, palette_points, set(), delay, len(palette), manual,
                click_hold, self.pause_event, self._pixel_completed,
                automatic=True, on_manual_color=self._wait_for_manual_color)
            state = "Da dung." if STOP_EVENT.is_set() else "Ve hoan tat."
            self.events.put(("finished", state))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _wait_for_manual_color(self, color_index):
        event = threading.Event()
        self.manual_color_event = event
        self.events.put(("manual_color", color_index + 1))
        while not STOP_EVENT.is_set():
            if not _wait_until_running(self.pause_event):
                return False
            if event.wait(0.05):
                self.manual_color_event = None
                return True
        return False

    def _confirm_manual_color(self):
        if self.manual_color_event is not None:
            self.manual_color_event.set()
            self.manual_selected_button.config(state="disabled")
            self._set_status("Da xac nhan mau; tiep tuc ve.")

    def _pixel_completed(self, color, number, total, x, y):
        self.last_pixel = (color, number, x, y)
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
                        f"Mau #{color}: pixel {number}/{total}; "
                        f"toa do cuoi ({x}, {y})")
                    if paused:
                        self.status.set("Da tam dung sau khi hoan tat click hien tai.")
                elif event == "finished":
                    self._set_status(value)
                    self._set_running_controls(False)
                    self.manual_selected_button.config(state="disabled")
                elif event == "error":
                    self._set_status("Gap loi khi ve.")
                    self._set_running_controls(False)
                    self.manual_selected_button.config(state="disabled")
                    messagebox.showerror("Loi khi ve", value)
                elif event == "manual_color":
                    self._set_status(
                        f"Hay chon mau #{value} trong game, roi bam "
                        "'Da chon mau trong game'.")
                    self.manual_selected_button.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(80, self._process_events)

    def pause(self):
        if self.worker is not None and self.worker.is_alive():
            self.pause_event.clear()
            self.pause_button.config(state="disabled")
            self.resume_button.config(state="normal")
            self._set_status("Dang tam dung sau click hien tai...")

    def resume(self):
        if self.worker is not None and self.worker.is_alive():
            self.pause_event.set()
            self.pause_button.config(state="normal")
            self.resume_button.config(state="disabled")
            self._set_status("Dang tiep tuc tu pixel ke tiep...")

    def stop(self):
        STOP_EVENT.set()
        self.pause_event.set()
        if self.manual_color_event is not None:
            self.manual_color_event.set()
        self._set_status("Dang dung...")
        self.resume_button.config(state="disabled")
        self.stop_button.config(state="disabled")
        self.manual_selected_button.config(state="disabled")

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
    listener = _start_emergency_listener()
    root.protocol("WM_DELETE_WINDOW", lambda: app.close(listener))
    root.mainloop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--grid", type=int, default=60,
                    help="so o tren canh dai nhat cua khung ve (mac dinh 60)")
    ap.add_argument("--colors", type=int, default=None,
                    help="so mau trong bang mau (1..256; mac dinh hoi, Enter = 12)")
    ap.add_argument("--dither", action="store_true", help="khu rang cua")
    ap.add_argument("--delay", type=float, default=0.001,
                    help="giay nghi giua 2 click (tang neu game bi sot)")
    ap.add_argument("--click-hold", type=float, default=0.005,
                    help="thoi gian giu chuot moi click (mac dinh 0.005 giay)")
    ap.add_argument("--manual", action="store_true",
                    help="tu chon mau trong game, tool chi click diem")
    ap.add_argument("--palette-hex", default=None,
                    help='nhap tay bang mau, vd "ffffff,000000,ff0000,..." (tu bat --manual)')
    ap.add_argument("--recalibrate", action="store_true",
                    help="chon lai khung + bang mau")
    a = ap.parse_args()
    if a.grid <= 0:
        ap.error("--grid phai lon hon 0")
    if a.delay < 0:
        ap.error("--delay khong duoc am")
    if a.click_hold <= 0:
        ap.error("--click-hold phai lon hon 0")
    if a.colors is not None and not 1 <= a.colors <= 256:
        ap.error("--colors phai nam trong khoang 1..256")

    if a.image is None:
        run_gui(a)
        return

    cfg = {}
    if os.path.exists(CONFIG_FILE) and not a.recalibrate:
        cfg = json.load(open(CONFIG_FILE))
        saved_colors = len(cfg.get("palette_rgb", []))
        print(f"Dung lai cau hinh cu voi {saved_colors} mau "
              "(them --colors N de doi so mau bang mau).")
    if "box" not in cfg:
        countdown(5, "B1: chon khung ve. Chuyen sang cua so game, "
                     "man hinh se duoc chup sau 5 giay...")
        cfg["box"] = select_region()

    manual = a.manual
    if a.palette_hex is not None:
        hexes = [h.strip().lstrip("#") for h in a.palette_hex.split(",")]
        if not hexes or len(hexes) > 256 or any(
                len(h) != 6 or any(c not in "0123456789abcdefABCDEF" for c in h)
                for h in hexes):
            ap.error("--palette-hex phai la danh sach ma mau RRGGBB hop le")
        if a.colors is not None and a.colors != len(hexes):
            ap.error("--colors phai trung voi so mau trong --palette-hex")
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
            t = input("Game co bao nhieu mau? (Enter = 12): ").strip()
            n = int(t) if t.isdigit() and int(t) > 0 else (12 if t == "" else None)
            if n is not None and not 1 <= n <= 256:
                print("  Nhap so mau tu 1 den 256.")
                n = None
        countdown(5, f"B2: chon {n} mau. Chuyen sang cua so game, "
                     "man hinh se duoc chup sau 5 giay...")
        pts, cols = pick_palette(n)
        cfg["palette_pts"], cfg["palette_rgb"] = pts, cols
    json.dump(cfg, open(CONFIG_FILE, "w"))

    box, pts, cols = cfg["box"], cfg["palette_pts"], cfg["palette_rgb"]
    print("Khung ve:", box, "| rong x cao =", box[2] - box[0], "x", box[3] - box[1])
    if pts is None:
        manual = True

    grid_size = grid_for_box(box, a.grid)
    print(f"Luoi ve: {grid_size[0]} x {grid_size[1]} o (rong x cao).")
    idx = quantize(a.image, grid_size, cols, a.dither)
    save_preview(idx, cols)
    counts = np.bincount(idx[idx >= 0].astype(int), minlength=len(cols))
    used_colors = int(np.count_nonzero(counts))
    print(f"Bang mau co {len(cols)} mau; anh su dung {used_colors} mau.")
    for i, (rgb, count) in enumerate(zip(cols, counts), 1):
        hex_color = "#{:02X}{:02X}{:02X}".format(*rgb)
        print(f"  Mau #{i}: {hex_color} - {int(count)} diem")
    print("Da luu preview.png voi mau RGB da lay va chu giai; mo xem truoc khi ve.")

    listener = _start_emergency_listener()
    try:
        print("Bam F12 bat ky luc nao de dung khan cap.")
        s = _readline_or_stop(
            "Nhap so thu tu mau NEN can bo qua (vd 1, de trong = ve het): ")
        if s is None:
            print("Da dung khan cap (F12).")
            return
        skip = {int(s) - 1} if s.isdigit() else set()

        total = int(np.sum(idx >= 0))
        print(f"Tong ~{total} click.")
        if manual:
            print("Moi mau can chon thu cong; nhap y de ve, s de bo qua.")
        else:
            print("Moi mau se hoi y; nhap a de tu dong ve tat ca mau con lai.")
        draw(idx, box, pts, skip, a.delay, len(cols), manual, a.click_hold)
        if not STOP_EVENT.is_set():
            print("Hoan thanh.")
    finally:
        listener.stop()
        listener.join()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1)
