"""
BangBang - Auto ve tranh pixel bang click
Cai dat:  pip install -r requirements.txt
Chay:     python bangbang_draw.py joker.jpg --grid 60 --dither

Quy trinh:
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
import select
import sys
import threading

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
except ImportError:  # pragma: no cover - GUI dependency is optional for import-time checks.
    tk = None

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
def countdown(sec, msg):
    print(msg)
    for i in range(sec, 0, -1):
        print(f"  {i}...", end="\r", flush=True)
        if STOP_EVENT.wait(1):
            print("\nDa dung khan cap (F12).")
            return False
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
            return False

    listener = keyboard.Listener(on_press=on_press)
    listener.start()
    return listener


# ---------------------------------------------------------------- UI chon vung
def _overlay(title):
    """Mo cua so toan man hinh co anh chup man hinh lam nen."""
    _require_runtime_deps("Pillow", "tkinter")
    shot = ImageGrab.grab()
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
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


def select_region():
    root, canvas, shot, sx, sy = _overlay(
        "KEO CHUOT tu goc TREN-TRAI den goc DUOI-PHAI khung ve (ESC = thoat)")
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
    root.bind("<Escape>", lambda e: sys.exit("Da huy."))
    root.mainloop()
    return state["box"]


def pick_palette(n):
    root, canvas, shot, sx, sy = _overlay(
        f"CLICK lan luot {n} o mau trong bang mau cua game (ESC = thoat)")
    points, colors = [], []

    def click(e):
        px, py = int(e.x * sx), int(e.y * sy)
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
    root.bind("<Escape>", lambda e: sys.exit("Da huy."))
    root.mainloop()
    return points, colors


# ------------------------------------------------------------- xu ly anh
def quantize(img_path, grid, palette_rgb, dither):
    """Map pixels only to the supplied palette; -1 marks letterbox cells."""
    _require_runtime_deps("numpy", "Pillow")
    if not palette_rgb:
        raise ValueError("Bang mau khong duoc de trong.")
    palette = np.asarray(palette_rgb, dtype=np.float32)
    if palette.ndim != 2 or palette.shape[1] != 3:
        raise ValueError("Moi mau trong bang mau phai co 3 gia tri RGB.")

    img = Image.open(img_path).convert("RGB")
    img.thumbnail((grid, grid), Image.LANCZOS)  # giu ti le
    w, h = img.size

    pixels = np.asarray(img, dtype=np.float32)
    if dither:
        work = pixels.copy()
        q = np.empty((h, w), dtype=int)
        for y in range(h):
            for x in range(w):
                old = work[y, x].copy()
                ci = int(np.argmin(np.sum((palette - old) ** 2, axis=1)))
                q[y, x] = ci
                error = old - palette[ci]
                if x + 1 < w:
                    work[y, x + 1] += error * (7 / 16)
                if y + 1 < h:
                    if x > 0:
                        work[y + 1, x - 1] += error * (3 / 16)
                    work[y + 1, x] += error * (5 / 16)
                    if x + 1 < w:
                        work[y + 1, x + 1] += error * (1 / 16)
    else:
        q = np.empty((h, w), dtype=int)
        for y in range(h):
            distances = np.sum(
                (pixels[y, :, None, :] - palette[None, :, :]) ** 2,
                axis=2)
            q[y] = np.argmin(distances, axis=1)

    out = -np.ones((grid, grid), dtype=int)
    ox, oy = (grid - w) // 2, (grid - h) // 2
    out[oy:oy + h, ox:ox + w] = q
    return out


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
         click_hold=0.04):
    _require_runtime_deps("numpy", "pyautogui")
    x1, y1, x2, y2 = box
    grid = idx.shape[0]
    cw, ch = (x2 - x1) / grid, (y2 - y1) / grid
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
        if draw_all:
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
        if not draw_all or k == draw_all_from:
            if not countdown(3, "  Quay lai cua so game..."):
                return
        if not manual:
            px, py = palette_pts[ci]
            if not _click(px, py, click_hold, delay):
                print("\nDa dung khan cap (F12).")
                return
            if STOP_EVENT.wait(0.05):
                print("\nDa dung khan cap (F12).")
                return
        for cy, cx in sorted(zip(ys, xs)):
            px = int(x1 + (cx + 0.5) * cw)
            py = int(y1 + (cy + 0.5) * ch)
            if not _click(px, py, click_hold, delay):
                print("\nDa dung khan cap (F12).")
                return
        print(f"  Xong mau #{ci + 1}.")


def _click(x, y, click_hold, delay):
    """Send a deliberate press/release and leave time for the app to process it."""
    if STOP_EVENT.is_set():
        return False
    pyautogui.moveTo(x, y)
    pyautogui.mouseDown()
    try:
        stopped = STOP_EVENT.wait(click_hold)
    finally:
        pyautogui.mouseUp()
    if stopped or STOP_EVENT.wait(delay):
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--grid", type=int, default=60,
                    help="so o moi canh (60 => moi o ~10px voi khung 600)")
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

    idx = quantize(a.image, a.grid, cols, a.dither)
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
