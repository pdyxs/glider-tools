"""Linux hotkey daemon for e-ink display control.

Equivalent of glider.lua (Hammerspoon) and glider.ahk (AutoHotkey) for Linux/GNOME/Wayland.
Uses evdev to read keyboard events directly — works on both Wayland and X11.

Hotkeys
-------
Ctrl+Shift+1–7    Glider/Mira mode switch (1–5 for Mira; 1–7 for Glider)
Ctrl+Shift+Space  Glider redraw / Mira refresh
Ctrl+Shift+=      Brightness up (not supported on Linux; shows notification)
Ctrl+Shift+-      Brightness down (not supported on Linux; shows notification)
Ctrl+Shift+0      Reset (inversion off, Dasung threshold reset)
Ctrl+Shift+\\     Theme toggle (dark/light)
Ctrl+Shift+I      Glider/Mira inversion toggle
Ctrl+Shift+F12    Re-detect displays

Alt+Shift+1–4     Dasung mode (auto, text, graphic, video)
Alt+Shift+Space   Dasung refresh
Alt+Shift+=       Dasung threshold up
Alt+Shift+-       Dasung threshold down
Alt+Shift+0       Dasung reset (threshold + inversion)
Alt+Shift+\\      Theme toggle (dark/light)
Alt+Shift+I       Dasung inversion toggle
Alt+Shift+F12     Re-detect displays

Requirements
------------
    sudo dnf install python3-evdev          # evdev
    sudo usermod -aG input $USER            # then log out/in
    # or install as a systemd user service — see eink-daemon.service
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys

try:
    import evdev
    from evdev import ecodes
except ImportError:
    sys.exit("evdev not found. Install with: sudo dnf install python3-evdev")

# ── Config ────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
GLIDER_PY    = os.path.join(SCRIPT_DIR, "glider.py")
MIRA_PY      = os.path.join(SCRIPT_DIR, "mira.py")
DASUNG_PY    = os.path.join(SCRIPT_DIR, "dasung253.py")
DISPLAY_PY   = os.path.join(SCRIPT_DIR, "display.py")

PYTHON       = sys.executable
STATE_FILE   = os.path.expanduser("~/.eink-state.json")

THRESHOLD_MIN     = 1
THRESHOLD_MAX     = 9
THRESHOLD_DEFAULT = 5

GLIDER_FIRMWARE_MODES = {1: 3, 2: 2, 3: 5, 4: 4, 5: 6, 6: 7, 7: 1}
MIRA_MODES            = {1: "speed", 2: "text", 3: "image", 4: "video", 5: "read"}
GLIDER_MODE_LABELS    = {
    1: "Bayer (Speed)", 2: "Binary (Text)", 3: "Fast Grey (Graphic)",
    4: "Blue Noise (Video)", 5: "Auto LUT (Read)",
    6: "Auto LUT + error diffusion", 7: "16-level + error diffusion",
}
DASUNG_MODES  = {1: "auto", 2: "text", 3: "graphic", 4: "video"}
DASUNG_LABELS = {1: "Auto", 2: "Text", 3: "Graphic", 4: "Video"}

# ── State ─────────────────────────────────────────────────────────────────────

state = {
    "modeLevel":       {},     # not used on Linux (no gamma API), kept for JSON compat with macOS
    "dasungThreshold": THRESHOLD_DEFAULT,
    "gliderInverted":  False,
    "dasungInverted":  False,
}
current_mode = None

# Detected devices (populated by detect_displays)
glider_connected = False
mira_connected   = False
dasung_port      = None   # e.g. "/dev/ttyUSB0"


def load_state() -> None:
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        state.update({k: v for k, v in data.items() if k in state})
    except (OSError, json.JSONDecodeError):
        pass


def save_state() -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        print(f"save_state error: {e}", flush=True)


# ── Display detection ─────────────────────────────────────────────────────────

def detect_displays() -> None:
    global glider_connected, mira_connected, dasung_port

    # Glider / Mira via USB HID
    glider_connected = False
    mira_connected   = False
    try:
        import hid
        for d in hid.enumerate():
            if d.get("vendor_id") == 0x1209 and d.get("product_id") == 0xAE86:
                glider_connected = True
            if d.get("vendor_id") == 0x0416 and d.get("product_id") == 0x5020:
                mira_connected = True
    except Exception as e:
        print(f"HID detection error: {e}", flush=True)

    # Dasung via USB serial (CH340)
    dasung_port = None
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            if p.vid == 0x1A86 and p.pid == 0x7523:
                dasung_port = p.device
                break
    except Exception as e:
        print(f"Serial detection error: {e}", flush=True)

    parts = []
    if glider_connected:
        parts.append("Glider")
    if mira_connected:
        parts.append("Mira")
    if dasung_port:
        parts.append(f"Dasung ({dasung_port})")
    notify("E-ink displays: " + (", ".join(parts) if parts else "none detected"))


def eink_label() -> str:
    if glider_connected:
        return "Glider"
    if mira_connected:
        return "Mira"
    return "E-ink"


def eink_connected() -> bool:
    return glider_connected or mira_connected


# ── Subprocess helpers ────────────────────────────────────────────────────────

def run(*args: str) -> None:
    """Fire-and-forget subprocess."""
    subprocess.Popen([PYTHON] + list(args),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notify(msg: str) -> None:
    """Show a desktop notification (requires notify-send)."""
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-t", "2000", "--urgency=low", "E-ink", msg],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[notify] {msg}", flush=True)


# ── Actions ───────────────────────────────────────────────────────────────────

def action_switch_mode(mode: int) -> None:
    global current_mode
    current_mode = mode

    if glider_connected:
        fw = GLIDER_FIRMWARE_MODES.get(mode, mode)
        run(GLIDER_PY, "setmode", str(fw))
        label = GLIDER_MODE_LABELS.get(mode, str(mode))
        inv = "  [inv]" if state["gliderInverted"] else ""
        notify(f"Glider  mode {mode}: {label}{inv}")

    elif mira_connected:
        name = MIRA_MODES.get(mode)
        if name:
            run(MIRA_PY, "setmode", name)
            notify(f"Mira  mode {mode}: {name.capitalize()}")
        else:
            notify(f"Mira: no mode {mode}")

    else:
        notify("No e-ink display detected")

    save_state()


def action_redraw() -> None:
    if glider_connected:
        run(GLIDER_PY, "redraw")
        notify("Glider  redraw")
    elif mira_connected:
        run(MIRA_PY, "refresh")
        notify("Mira  refresh")
    else:
        notify("No e-ink display detected")


def action_brightness_up() -> None:
    notify(f"{eink_label()}: brightness adjustment not supported on Linux")


def action_brightness_down() -> None:
    notify(f"{eink_label()}: brightness adjustment not supported on Linux")


def action_reset() -> None:
    state["gliderInverted"] = False
    state["dasungThreshold"] = THRESHOLD_DEFAULT
    state["dasungInverted"] = False
    save_state()
    if dasung_port:
        run(DASUNG_PY, "setthreshold", str(THRESHOLD_DEFAULT))
    notify("E-ink  reset")


def action_theme_toggle() -> None:
    run(DISPLAY_PY, "theme", "toggle")
    notify("Theme toggled")


def action_eink_invert() -> None:
    if not eink_connected():
        notify("No e-ink display detected")
        return
    state["gliderInverted"] = not state["gliderInverted"]
    save_state()
    # TODO: call display.py invert once Linux inversion is implemented
    run(DISPLAY_PY, "invert", "toggle")
    label = eink_label()
    notify(f"{label}  {'inverted' if state['gliderInverted'] else 'normal'}")


def action_redetect() -> None:
    detect_displays()


# ── Dasung-specific actions ───────────────────────────────────────────────────

def action_dasung_mode(mode: int) -> None:
    name = DASUNG_MODES.get(mode)
    if not name:
        return
    if not dasung_port:
        notify("Dasung not detected")
        return
    run(DASUNG_PY, "setmode", name)
    notify(f"Dasung  {DASUNG_LABELS[mode]} mode")


def action_dasung_refresh() -> None:
    if not dasung_port:
        notify("Dasung not detected")
        return
    run(DASUNG_PY, "refresh")
    notify("Dasung  refresh")


def action_dasung_threshold(delta: int) -> None:
    if not dasung_port:
        notify("Dasung not detected")
        return
    t = max(THRESHOLD_MIN, min(THRESHOLD_MAX, state["dasungThreshold"] + delta))
    state["dasungThreshold"] = t
    save_state()
    run(DASUNG_PY, "setthreshold", str(t))
    direction = "up" if delta > 0 else "down"
    notify(f"Dasung  threshold {t}  ({direction})")


def action_dasung_reset() -> None:
    if not dasung_port:
        notify("Dasung not detected")
        return
    state["dasungThreshold"] = THRESHOLD_DEFAULT
    state["dasungInverted"] = False
    save_state()
    run(DASUNG_PY, "setthreshold", str(THRESHOLD_DEFAULT))
    notify("Dasung  reset")


def action_dasung_invert() -> None:
    if not dasung_port:
        notify("Dasung not detected")
        return
    state["dasungInverted"] = not state["dasungInverted"]
    save_state()
    # TODO: call display.py invert once Linux inversion is implemented
    run(DISPLAY_PY, "invert", "toggle")
    notify(f"Dasung  {'inverted' if state['dasungInverted'] else 'normal'}")


# ── Keyboard state ────────────────────────────────────────────────────────────

pressed = set()   # currently-held evdev keycodes

CTRL_KEYS  = frozenset({ecodes.KEY_LEFTCTRL,  ecodes.KEY_RIGHTCTRL})
SHIFT_KEYS = frozenset({ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT})
ALT_KEYS   = frozenset({ecodes.KEY_LEFTALT,   ecodes.KEY_RIGHTALT})


def has_ctrl()  -> bool: return bool(pressed & CTRL_KEYS)
def has_shift() -> bool: return bool(pressed & SHIFT_KEYS)
def has_alt()   -> bool: return bool(pressed & ALT_KEYS)


# ── Key → action maps ─────────────────────────────────────────────────────────

# Built after all action_* functions are defined (see register_bindings below)
CTRL_SHIFT_BINDINGS: dict = {}
ALT_SHIFT_BINDINGS:  dict = {}


def register_bindings() -> None:
    CTRL_SHIFT_BINDINGS.update({
        ecodes.KEY_1:         lambda: action_switch_mode(1),
        ecodes.KEY_2:         lambda: action_switch_mode(2),
        ecodes.KEY_3:         lambda: action_switch_mode(3),
        ecodes.KEY_4:         lambda: action_switch_mode(4),
        ecodes.KEY_5:         lambda: action_switch_mode(5),
        ecodes.KEY_6:         lambda: action_switch_mode(6),
        ecodes.KEY_7:         lambda: action_switch_mode(7),
        ecodes.KEY_SPACE:     action_redraw,
        ecodes.KEY_EQUAL:     action_brightness_up,
        ecodes.KEY_MINUS:     action_brightness_down,
        ecodes.KEY_0:         action_reset,
        ecodes.KEY_BACKSLASH: action_theme_toggle,
        ecodes.KEY_I:         action_eink_invert,
        ecodes.KEY_F12:       action_redetect,
    })
    ALT_SHIFT_BINDINGS.update({
        ecodes.KEY_1:         lambda: action_dasung_mode(1),
        ecodes.KEY_2:         lambda: action_dasung_mode(2),
        ecodes.KEY_3:         lambda: action_dasung_mode(3),
        ecodes.KEY_4:         lambda: action_dasung_mode(4),
        ecodes.KEY_SPACE:     action_dasung_refresh,
        ecodes.KEY_EQUAL:     lambda: action_dasung_threshold(+1),
        ecodes.KEY_MINUS:     lambda: action_dasung_threshold(-1),
        ecodes.KEY_0:         action_dasung_reset,
        ecodes.KEY_BACKSLASH: action_theme_toggle,
        ecodes.KEY_I:         action_dasung_invert,
        ecodes.KEY_F12:       action_redetect,
    })


def dispatch(keycode: int) -> None:
    """Fire the action for the current modifier+key combination, if any."""
    ctrl  = has_ctrl()
    shift = has_shift()
    alt   = has_alt()

    if ctrl and shift and not alt:
        action = CTRL_SHIFT_BINDINGS.get(keycode)
    elif alt and shift and not ctrl:
        action = ALT_SHIFT_BINDINGS.get(keycode)
    else:
        return

    if action:
        try:
            action()
        except Exception as e:
            print(f"action error: {e}", flush=True)


# ── Device management ─────────────────────────────────────────────────────────

def find_keyboards() -> list:
    """Return all evdev devices that look like real keyboards."""
    result = []
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if ecodes.KEY_A in keys and ecodes.KEY_LEFTCTRL in keys:
                    result.append(dev)
        except OSError:
            pass
    return result


async def handle_device(device: evdev.InputDevice) -> None:
    """Read key events from one device until it's removed or errors."""
    print(f"Listening on {device.path}  {device.name}", flush=True)
    try:
        async for event in device.async_read_loop():
            if event.type != ecodes.EV_KEY:
                continue
            if event.value == 1:    # key down
                pressed.add(event.code)
                dispatch(event.code)
            elif event.value == 0:  # key up
                pressed.discard(event.code)
    except OSError:
        print(f"Device removed: {device.path}", flush=True)
    finally:
        # Clear any modifier state this device was holding
        pressed.difference_update(CTRL_KEYS | SHIFT_KEYS | ALT_KEYS)


async def run_listener() -> None:
    """Start listeners on all keyboards; re-scan when a device is removed."""
    while True:
        keyboards = find_keyboards()
        if not keyboards:
            print("No keyboard devices found — retrying in 5s…", flush=True)
            await asyncio.sleep(5)
            continue

        tasks = [asyncio.create_task(handle_device(dev)) for dev in keyboards]
        # Wait for any one device to disconnect, then re-scan
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in tasks:
            t.cancel()
        await asyncio.sleep(1)   # brief pause for udev to settle


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    load_state()
    detect_displays()
    register_bindings()
    print("E-ink hotkey daemon started. Press Ctrl+C to stop.", flush=True)
    try:
        asyncio.run(run_listener())
    except KeyboardInterrupt:
        pass
    print("E-ink hotkey daemon stopped.", flush=True)


if __name__ == "__main__":
    main()
