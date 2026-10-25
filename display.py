"""Cross-platform OS-level display operations.

Handles operations that are independent of which e-ink device is plugged in:
theme switching (dark/light mode) and display-level inversion.

Platform support:
    theme:       macOS, Linux (GNOME), Windows
    setlevel:    macOS only (CGSetDisplayTransferByTable)
    invertloop:  macOS only (~60fps gamma daemon)
    invert:      Linux stub (TODO: mutter D-Bus or colord ICC profile)
    detect:      Linux (EDID scan), macOS (CoreGraphics), Windows (EnumDisplayDevices)
    reconnect:   Linux (GNOME, via gdctl)
    laptop:      Linux (GNOME, via gdctl)

Examples:
    python display.py theme toggle
    python display.py theme dark
    python display.py detect
    python display.py setlevel 12345 0.1          # macOS
    python display.py invertloop 12345 --level 0  # macOS
    python display.py invert toggle               # Linux (stub)
    python display.py reconnect                   # Linux/GNOME: recover a black Glider
    python display.py laptop toggle               # Linux/GNOME: built-in display on/off
"""

import argparse
import os
import platform
import sys


# ── Known e-ink display identifiers ─────────────────────────────────────────

EINK_IDS = [
    {"pnp": "ZPR0001",    "name": "Glider"},
    {"edid_name": "MIRA", "name": "Mira"},
    {"edid_name": "Paperlike", "name": "Dasung"},
]


# ── Theme toggle ─────────────────────────────────────────────────────────────

def _get_theme_macos() -> str:
    """Return 'dark' or 'light'."""
    import subprocess
    result = subprocess.run(
        ["defaults", "read", "-g", "AppleInterfaceStyle"],
        capture_output=True, text=True,
    )
    return "dark" if result.returncode == 0 and "Dark" in result.stdout else "light"


def _set_theme_macos(mode: str) -> None:
    import subprocess
    if mode == "dark":
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to tell appearance preferences to set dark mode to true',
        ], check=True)
    else:
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to tell appearance preferences to set dark mode to false',
        ], check=True)


def _get_theme_linux() -> str:
    import subprocess
    result = subprocess.run(
        ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        capture_output=True, text=True,
    )
    return "dark" if "dark" in result.stdout.lower() else "light"


def _set_theme_linux(mode: str) -> None:
    import subprocess
    value = "prefer-dark" if mode == "dark" else "default"
    subprocess.run(
        ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", value],
        check=True,
    )


def _get_theme_windows() -> str:
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "light" if value == 1 else "dark"
    except OSError:
        return "light"


def _set_theme_windows(mode: str) -> None:
    import winreg
    value = 1 if mode == "light" else 0
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        access=winreg.KEY_SET_VALUE,
    )
    winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
    winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)
    winreg.CloseKey(key)


def cmd_theme(args) -> None:
    """Toggle or set dark/light mode."""
    system = platform.system()

    if system == "Darwin":
        get_fn, set_fn = _get_theme_macos, _set_theme_macos
    elif system == "Linux":
        get_fn, set_fn = _get_theme_linux, _set_theme_linux
    elif system == "Windows":
        get_fn, set_fn = _get_theme_windows, _set_theme_windows
    else:
        raise SystemExit(f"theme: unsupported platform {system!r}")

    mode = args.mode
    if mode == "toggle":
        current = get_fn()
        mode = "dark" if current == "light" else "light"

    set_fn(mode)
    print(f"theme -> {mode}")


# ── Display detection ────────────────────────────────────────────────────────

def _detect_linux() -> list[dict]:
    """Scan DRM connectors for known e-ink displays via EDID."""
    import glob
    import os

    results = []
    for connector_path in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        connector_dir = os.path.dirname(connector_path)
        connector_name = os.path.basename(connector_dir)
        try:
            status = open(connector_path).read().strip()
        except OSError:
            continue
        if status != "connected":
            continue
        edid_path = os.path.join(connector_dir, "edid")
        try:
            edid = open(edid_path, "rb").read()
        except OSError:
            continue
        if len(edid) < 128:
            continue
        # PNP ID: three 5-bit letters (bytes 8-9, big-endian) + product code
        # (bytes 10-11, little-endian), e.g. Glider = "ZPR0001"
        mfg = int.from_bytes(edid[8:10], "big")
        pnp = "".join(chr(ord("A") - 1 + ((mfg >> shift) & 0x1F)) for shift in (10, 5, 0))
        pnp += f"{int.from_bytes(edid[10:12], 'little'):04X}"
        # Extract monitor name from EDID descriptor blocks (bytes 54–125)
        edid_text = ""
        for block_start in range(54, 126, 18):
            block = edid[block_start:block_start + 18]
            if len(block) < 18:
                continue
            # Tag 0xFC = monitor name descriptor
            if block[0] == 0 and block[1] == 0 and block[2] == 0 and block[3] == 0xFC:
                edid_text += block[5:].decode("ascii", errors="ignore").strip().strip("\n")
        for eid in EINK_IDS:
            if ("pnp" in eid and eid["pnp"] == pnp) or \
                    ("edid_name" in eid and eid["edid_name"] in edid_text):
                results.append({"connector": connector_name, "display": eid["name"], "edid_name": edid_text})
                break
    return results


def cmd_detect(args) -> None:
    system = platform.system()
    if system == "Linux":
        found = _detect_linux()
        if not found:
            print("No known e-ink display detected.")
            return
        for entry in found:
            print(f"{entry['connector']}  {entry['display']}  ({entry['edid_name']})")
    else:
        raise SystemExit(f"detect: not yet implemented on {system!r}")


# ── Output reconnect (Linux/GNOME) ───────────────────────────────────────────

RECONNECT_OFF_SECONDS = 3


def _gdctl_layout() -> list[dict]:
    """Parse `gdctl show` into logical monitors, each with its monitors' current modes."""
    import re
    import subprocess

    out = subprocess.run(["gdctl", "show"], capture_output=True, text=True, check=True).stdout
    modes, logical = {}, []
    section, connector, expect = None, None, None
    for raw in out.splitlines():
        line = re.sub(r"^[\s│├└─]+", "", raw).strip()
        if line in ("Monitors:", "Logical monitors:"):
            section = line
        elif section == "Monitors:" and (m := re.match(r"Monitor (\S+) \(", line)):
            connector = m.group(1)
        elif section == "Monitors:" and line == "Current mode":
            expect = "mode"
        elif expect == "mode":
            modes[connector], expect = line, None
        elif line.startswith("Logical monitor #"):
            logical.append({"x": "0", "y": "0", "scale": "1", "transform": "normal",
                            "primary": False, "monitors": []})
        elif logical and (m := re.match(r"Position: \((-?\d+), (-?\d+)\)", line)):
            logical[-1]["x"], logical[-1]["y"] = m.groups()
        elif logical and line.startswith("Scale: "):
            logical[-1]["scale"] = line.split(": ", 1)[1]
        elif logical and line.startswith("Transform: "):
            logical[-1]["transform"] = line.split(": ", 1)[1]
        elif logical and line.startswith("Primary: "):
            logical[-1]["primary"] = line.endswith("yes")
        elif logical and (m := re.match(r"(\S+) \(", line)) and m.group(1) in modes:
            logical[-1]["monitors"].append(m.group(1))
    for lm in logical:
        lm["modes"] = {c: modes[c] for c in lm["monitors"]}
    return logical


def _gdctl_set(logical: list[dict]) -> None:
    import subprocess

    args = ["gdctl", "set"]
    for lm in logical:
        args.append("-L")
        for c in lm["monitors"]:
            args += ["-M", c]
            if lm["modes"].get(c):
                args += ["--mode", lm["modes"][c]]
        if lm["primary"]:
            args.append("--primary")
        if lm.get("scale"):
            args += ["--scale", lm["scale"]]
        args += ["--transform", lm["transform"]]
        if lm.get("right_of"):
            args += ["--right-of", lm["right_of"]]
        else:
            args += ["-x", lm["x"], "-y", lm["y"]]
    subprocess.run(args, check=True)


def cmd_reconnect(args) -> None:
    """Disable the Glider's output for a few seconds, then restore the exact layout.

    Workaround for the black-screen-on-plug-in bug: the host modeset/retrain plus the
    Glider's own live-loss -> suspend -> wake pipeline restart brings the panel up,
    where setmode/redraw/reinput don't. Not persisted (no `gdctl set -P`).
    """
    import copy
    import re
    import shutil
    import time

    if platform.system() != "Linux":
        raise SystemExit("reconnect: Linux (GNOME) only")
    if not shutil.which("gdctl"):
        raise SystemExit("reconnect: gdctl not found (needs GNOME 48+)")
    gliders = [re.sub(r"^card\d+-", "", e["connector"])
               for e in _detect_linux() if e["display"] == "Glider"]
    if not gliders:
        raise SystemExit("reconnect: no Glider output connected")
    glider = gliders[0]

    layout = _gdctl_layout()
    if not any(glider in lm["monitors"] for lm in layout):
        raise SystemExit(f"reconnect: {glider} is not enabled in the current layout")

    off = copy.deepcopy(layout)
    for lm in off:
        lm["monitors"] = [c for c in lm["monitors"] if c != glider]
    off = [lm for lm in off if lm["monitors"]]
    if not off:
        raise SystemExit("reconnect: the Glider is the only active output; can't turn it off")
    if not any(lm["primary"] for lm in off):
        off[0]["primary"] = True

    _gdctl_set(off)
    time.sleep(RECONNECT_OFF_SECONDS)
    _gdctl_set(layout)
    print(f"reconnect: {glider} off for {RECONNECT_OFF_SECONDS}s and restored")


# ── Built-in display on/off (Linux/GNOME) ────────────────────────────────────

LAPTOP_STATE_FILE = os.path.expanduser("~/.eink-laptop-display.json")


def _builtin_connector() -> str:
    """The laptop panel's connector (eDP/LVDS/DSI), whether or not it's enabled."""
    import re
    import subprocess

    out = subprocess.run(["gdctl", "show"], capture_output=True, text=True, check=True).stdout
    for m in re.finditer(r"Monitor (\S+) \(", out):
        if m.group(1).split("-")[0] in ("eDP", "LVDS", "DSI"):
            return m.group(1)
    raise SystemExit("laptop: no built-in display found")


def cmd_laptop(args) -> None:
    """Enable/disable the built-in display, remembering where it was.

    Turning it off saves the full layout; turning it back on restores that layout if the
    other outputs haven't changed, else places the panel right of the rightmost output.
    Not persisted (no `gdctl set -P`), like reconnect.
    """
    import copy
    import json
    import shutil

    if platform.system() != "Linux":
        raise SystemExit("laptop: Linux (GNOME) only")
    if not shutil.which("gdctl"):
        raise SystemExit("laptop: gdctl not found (needs GNOME 48+)")
    panel = _builtin_connector()
    layout = _gdctl_layout()
    enabled = any(panel in lm["monitors"] for lm in layout)
    state = args.state if args.state != "toggle" else ("off" if enabled else "on")

    if state == "off":
        if not enabled:
            print(f"laptop: {panel} already off")
            return
        off = copy.deepcopy(layout)
        for lm in off:
            lm["monitors"] = [c for c in lm["monitors"] if c != panel]
        off = [lm for lm in off if lm["monitors"]]
        if not off:
            raise SystemExit("laptop: the built-in display is the only active output; can't turn it off")
        if not any(lm["primary"] for lm in off):
            off[0]["primary"] = True
        with open(LAPTOP_STATE_FILE, "w") as f:
            json.dump(layout, f)
        _gdctl_set(off)
        print(f"laptop: {panel} off")
        return

    if enabled:
        print(f"laptop: {panel} already on")
        return
    try:
        with open(LAPTOP_STATE_FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = []
    others = lambda lay: sorted(c for lm in lay for c in lm["monitors"] if c != panel)
    if saved and others(saved) == others(layout):
        _gdctl_set(saved)
    else:
        prev = next((lm for lm in saved if panel in lm["monitors"]), None)
        rightmost = max(layout, key=lambda lm: int(lm["x"]))
        _gdctl_set(layout + [{
            "monitors": [panel], "modes": {}, "primary": False, "transform": "normal",
            "scale": prev["scale"] if prev else None,   # None: gdctl uses the preferred scale
            "right_of": rightmost["monitors"][0],
        }])
    print(f"laptop: {panel} on")


# ── macOS gamma / inversion (moved from glider.py) ──────────────────────────

def _load_coregraphics():
    import ctypes
    CG = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    CG.CGSetDisplayTransferByTable.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
    ]
    CG.CGSetDisplayTransferByTable.restype = ctypes.c_int32
    return CG


def _build_ramp(n: int, k: float, invert: bool = False):
    import ctypes
    import math
    TableType = ctypes.c_float * n
    ramp = TableType()
    for i in range(n):
        x = i / 255.0
        y = x + k * math.sin(math.pi * x)
        if invert:
            y = 1.0 - y
        ramp[i] = max(0.0, min(1.0, y))
    return ramp


def cmd_setlevel(args) -> None:
    """Apply sine-curve midtone lift to one display via CGSetDisplayTransferByTable (macOS only).

    Level k=0 is identity; k>0 lifts midtones (brighter); k<0 drops them (darker).
    Endpoints are anchored because sin(0)=sin(pi)=0. Keep |k|<=0.3 for monotonic output.
    """
    if platform.system() != "Darwin":
        raise SystemExit("setlevel is macOS-only")
    import ctypes
    CG = _load_coregraphics()
    n = 256
    ramp = _build_ramp(n, args.level)
    result = CG.CGSetDisplayTransferByTable(
        ctypes.c_uint32(args.display_id), ctypes.c_uint32(n), ramp, ramp, ramp,
    )
    if result != 0:
        print(f"CGSetDisplayTransferByTable failed with code {result}")


def cmd_invertloop(args) -> None:
    """Inversion daemon: loops at ~60 fps re-applying an inverted gamma ramp (macOS only).

    macOS periodically resets the gamma table, so a single call doesn't hold — this
    matches the CVDisplayLink approach used by tools like Black Light.

    Level updates are picked up in-place by watching a level file
    (~/.glider-invert-{display_id}), so Hammerspoon can adjust brightness without
    restarting the process (which would cause a flash).
    """
    if platform.system() != "Darwin":
        raise SystemExit("invertloop is macOS-only")
    import ctypes
    import os
    import time
    CG = _load_coregraphics()
    n = 256
    display = ctypes.c_uint32(args.display_id)
    level_file = os.path.expanduser(f"~/.glider-invert-{args.display_id}")

    current_k = args.level
    ramp = _build_ramp(n, current_k, invert=True)
    last_mtime = 0.0

    try:
        while True:
            # Check for level update by watching the file mtime (cheap, no re-read unless changed)
            try:
                mtime = os.stat(level_file).st_mtime
                if mtime != last_mtime:
                    last_mtime = mtime
                    new_k = float(open(level_file).read().strip())
                    if new_k != current_k:
                        current_k = new_k
                        ramp = _build_ramp(n, current_k, invert=True)
            except (OSError, ValueError):
                pass
            CG.CGSetDisplayTransferByTable(display, ctypes.c_uint32(n), ramp, ramp, ramp)
            time.sleep(1 / 60)
    except KeyboardInterrupt:
        pass


# ── Linux inversion (stub) ───────────────────────────────────────────────────

def cmd_invert(args) -> None:
    """Toggle per-display colour inversion.

    macOS: not implemented here — use invertloop for macOS inversion.
    Linux: TODO — requires mutter D-Bus colour management or colord ICC profile.
    Windows: handled in AutoHotkey via SetDeviceGammaRamp.
    """
    system = platform.system()
    if system == "Linux":
        # TODO: implement via mutter org.gnome.Mutter.DisplayConfig or colord
        raise SystemExit(
            "Linux display inversion is not yet implemented.\n"
            "Planned approach: colord ICC profile or mutter D-Bus colour management API."
        )
    else:
        raise SystemExit(f"invert: not supported on {system!r} via this script")


# ── Argument parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # theme
    p = sub.add_parser("theme", help="Set or toggle dark/light mode (all platforms)")
    p.add_argument("mode", choices=["dark", "light", "toggle"])
    p.set_defaults(func=cmd_theme)

    # detect
    sub.add_parser("detect", help="List connected e-ink displays and their DRM connectors").set_defaults(func=cmd_detect)

    # reconnect (Linux/GNOME)
    sub.add_parser("reconnect", help="Turn the Glider's output off and back on to recover a black panel (Linux/GNOME)").set_defaults(func=cmd_reconnect)

    # laptop (Linux/GNOME)
    p = sub.add_parser("laptop", help="Turn the built-in display on/off (Linux/GNOME)")
    p.add_argument("state", nargs="?", default="toggle", choices=["on", "off", "toggle"])
    p.set_defaults(func=cmd_laptop)

    # setlevel (macOS)
    p = sub.add_parser("setlevel", help="Set display gamma ramp via sine-curve midtone lift (macOS only)")
    p.add_argument("display_id", type=int, help="CGDirectDisplayID — use screen:id() in Hammerspoon")
    p.add_argument("level", type=float, help="Midtone lift k: 0=neutral, >0=brighter, <0=darker. Keep |k|<=0.3.")
    p.set_defaults(func=cmd_setlevel)

    # invertloop (macOS)
    p = sub.add_parser("invertloop", help="Continuously apply inverted gamma until killed (macOS only)")
    p.add_argument("display_id", type=int, help="CGDirectDisplayID — use screen:id() in Hammerspoon")
    p.add_argument("--level", type=float, default=0.0, help="Midtone lift to combine with inversion (default 0)")
    p.set_defaults(func=cmd_invertloop)

    # invert (Linux stub)
    p = sub.add_parser("invert", help="Toggle per-display colour inversion (Linux stub — not yet implemented)")
    p.add_argument("state", choices=["on", "off", "toggle"])
    p.add_argument("--output", default=None, help="DRM connector name, e.g. card1-DP-3 (auto-detected if omitted)")
    p.set_defaults(func=cmd_invert)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
