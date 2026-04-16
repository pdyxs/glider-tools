"""CLI for controlling the ONYX BOOX Mira 13" e-ink monitor over USB HID.

Examples:
    python mira.py info
    python mira.py getstatus
    python mira.py refresh
    python mira.py reset
    python mira.py setmode text
    python mira.py setcontrast 7
    python mira.py setspeed 5
    python mira.py setcoldlight 100
    python mira.py setwarmlight 50
"""

import argparse
import sys
import time

import hid

VID = 0x0416
PID = 0x5020

# Opcodes
OP_REFRESH          = 0x01
OP_SET_REFRESH_MODE = 0x02
OP_SET_SPEED        = 0x04
OP_SET_CONTRAST     = 0x05
OP_SET_COLD_LIGHT   = 0x06
OP_SET_WARM_LIGHT   = 0x07
OP_SET_DITHER       = 0x09
OP_SET_COLOUR       = 0x11
OP_SET_AUTO_DITHER  = 0x12
OP_RESET            = 0x1F
OP_GET_STATUS       = 0x8F

# Refresh mode values
REFRESH_DIRECT = 0x01  # DirectUpdate — grayscale, slower
REFRESH_A2     = 0x03  # A2 — fast binary update

# Mode presets: (refresh_mode, contrast, user_speed, dither_mode, white_filter, black_filter)
MODES = {
    "speed": (REFRESH_A2,     8, 7, 0,  0,  0),
    "text":  (REFRESH_A2,     7, 6, 1,  0,  0),
    "image": (REFRESH_DIRECT, 7, 5, 0,  0,  0),
    "video": (REFRESH_A2,     7, 6, 2, 10,  0),
    "read":  (REFRESH_DIRECT, 7, 5, 3, 12, 10),
}

MODE_NAMES = list(MODES)  # insertion order: speed, text, image, video, read

# Auto-dither presets per dither_mode
AUTO_DITHER_PRESETS = {
    0: [0, 0, 0, 0],   # off
    1: [1, 0, 30, 10],  # low
    2: [1, 0, 40, 10],  # middle
    3: [1, 0, 50, 30],  # high
}


def open_device() -> hid.device:
    h = hid.device()
    try:
        h.open(VID, PID)
    except OSError:
        raise SystemExit(
            f"Mira (VID={VID:#06x} PID={PID:#06x}) not found. "
            "Check it is plugged in and Input Monitoring is granted in "
            "System Settings → Privacy (macOS)."
        )
    return h


def send(h: hid.device, opcode: int, *params: int) -> None:
    """Send a single HID report: [0x00, opcode, param...]."""
    pkt = [0x00, opcode] + list(params)
    h.write(pkt)
    time.sleep(0.05)  # brief settle; long ops (mode set) use multiple sends


def user_speed_to_wire(user_speed: int) -> int:
    """Convert user speed 1–7 to wire value (wire = 11 - user_speed)."""
    return 11 - user_speed


def set_mode_raw(h: hid.device, refresh_mode: int, contrast: int, user_speed: int,
                 dither_mode: int, white_filter: int, black_filter: int) -> None:
    send(h, OP_SET_REFRESH_MODE, refresh_mode)
    send(h, OP_SET_CONTRAST, contrast)
    send(h, OP_SET_SPEED, user_speed_to_wire(user_speed))
    send(h, OP_SET_DITHER, dither_mode)
    auto = AUTO_DITHER_PRESETS.get(dither_mode, [0, 0, 0, 0])
    send(h, OP_SET_AUTO_DITHER, *auto)
    send(h, OP_SET_COLOUR, 255 - white_filter, black_filter)


def cmd_info(_args) -> None:
    h = open_device()
    try:
        print(f"Manufacturer: {h.get_manufacturer_string()}")
        print(f"Product:      {h.get_product_string()}")
        print(f"Serial:       {h.get_serial_number_string()}")
    finally:
        h.close()


def cmd_getstatus(_args) -> None:
    h = open_device()
    try:
        send(h, OP_GET_STATUS)
        resp = h.read(64, timeout_ms=1000)
        if not resp:
            print("No response (timeout)")
            return
        speed    = resp[4] if len(resp) > 4 else "?"
        contrast = resp[5] if len(resp) > 5 else "?"
        cold     = resp[6] if len(resp) > 6 else "?"
        warm     = resp[7] if len(resp) > 7 else "?"
        mode     = resp[9] if len(resp) > 9 else "?"
        print(f"speed={speed}  contrast={contrast}  cold_light={cold}  warm_light={warm}  refresh_mode={mode}")
        print(f"raw={list(resp[:16])}")
    finally:
        h.close()


def cmd_refresh(_args) -> None:
    h = open_device()
    try:
        send(h, OP_REFRESH)
        print("refresh sent")
    finally:
        h.close()


def cmd_reset(_args) -> None:
    h = open_device()
    try:
        send(h, OP_RESET)
        print("reset sent")
    finally:
        h.close()


def cmd_setmode(args) -> None:
    name = args.mode.lower()
    if name not in MODES:
        raise SystemExit(f"Unknown mode '{name}'. Choose from: {', '.join(MODES)}")
    h = open_device()
    try:
        set_mode_raw(h, *MODES[name])
        print(f"mode -> {name}")
    finally:
        h.close()


def cmd_setcontrast(args) -> None:
    if not 0 <= args.value <= 15:
        raise SystemExit("Contrast must be 0–15")
    h = open_device()
    try:
        send(h, OP_SET_CONTRAST, args.value)
        print(f"contrast -> {args.value}")
    finally:
        h.close()


def cmd_setspeed(args) -> None:
    if not 1 <= args.value <= 7:
        raise SystemExit("Speed must be 1–7")
    h = open_device()
    try:
        send(h, OP_SET_SPEED, user_speed_to_wire(args.value))
        print(f"speed -> {args.value} (wire {user_speed_to_wire(args.value)})")
    finally:
        h.close()


def cmd_setcoldlight(args) -> None:
    if not 0 <= args.value <= 254:
        raise SystemExit("Cold light must be 0–254")
    h = open_device()
    try:
        send(h, OP_SET_COLD_LIGHT, args.value)
        print(f"cold_light -> {args.value}")
    finally:
        h.close()


def cmd_setwarmlight(args) -> None:
    if not 0 <= args.value <= 254:
        raise SystemExit("Warm light must be 0–254")
    h = open_device()
    try:
        send(h, OP_SET_WARM_LIGHT, args.value)
        print(f"warm_light -> {args.value}")
    finally:
        h.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info",      help="Print device manufacturer/product/serial").set_defaults(func=cmd_info)
    sub.add_parser("getstatus", help="Read current status from device").set_defaults(func=cmd_getstatus)
    sub.add_parser("refresh",   help="Full screen refresh (clear ghosting)").set_defaults(func=cmd_refresh)
    sub.add_parser("reset",     help="Reset device to defaults").set_defaults(func=cmd_reset)

    p = sub.add_parser("setmode", help=f"Apply a display preset: {', '.join(MODES)}")
    p.add_argument("mode", help=" | ".join(MODES))
    p.set_defaults(func=cmd_setmode)

    p = sub.add_parser("setcontrast", help="Set contrast, 0–15")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setcontrast)

    p = sub.add_parser("setspeed", help="Set refresh speed, 1–7 (7=fastest)")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setspeed)

    p = sub.add_parser("setcoldlight", help="Set cool frontlight, 0–254")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setcoldlight)

    p = sub.add_parser("setwarmlight", help="Set warm frontlight, 0–254")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setwarmlight)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
