"""CLI for controlling the Modos Glider e-ink monitor over USB HID.

Examples:
    python glider.py info
    python glider.py redraw
    python glider.py setmode 2
    python glider.py powerdown
    python glider.py powerup
"""

import argparse
import platform
import struct
import sys

import hid

VID = 0x1209
PID = 0xAE86
VENDOR_USAGE_PAGE = 0xFF00
REPORT_ID = 0x05
PACKET_SIZE = 64

CMDS = {
    "reset":     0x00,
    "powerdown": 0x01,
    "powerup":   0x02,
    "setinput":  0x03,
    "redraw":    0x04,
    "setmode":   0x05,
    "nuke":      0x06,
    "usbboot":   0x07,
}

RET_CODES = {
    0x00: "GENERAL_FAIL",
    0x01: "CHKSUM_FAIL",
    0x55: "SUCCESS",
}

CRC_TABLE = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7, 0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6, 0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485, 0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4, 0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823, 0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12, 0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41, 0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70, 0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F, 0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E, 0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D, 0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C, 0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB, 0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A, 0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9, 0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8, 0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0,
]


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) ^ CRC_TABLE[(crc >> 8) ^ byte]) & 0xFFFF
    return crc


def find_device_path() -> bytes:
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == VENDOR_USAGE_PAGE:
            return d["path"]
    hint = (
        "If you're using WSL, detach with `usbipd detach --busid 3-1` first."
        if platform.system() == "Windows"
        else "Check that the Glider is plugged in and Input Monitoring is granted to this terminal in System Settings → Privacy."
        if platform.system() == "Darwin"
        else ""
    )
    raise SystemExit(
        f"Glider (VID={VID:#06x} PID={PID:#06x}) not found."
        + (f" {hint}" if hint else "")
    )


def open_device() -> hid.device:
    h = hid.device()
    h.open_path(find_device_path())
    return h


def cmd_info(_args) -> None:
    h = open_device()
    try:
        print(f"Manufacturer: {h.get_manufacturer_string()}")
        print(f"Product:      {h.get_product_string()}")
        print(f"Serial:       {h.get_serial_number_string()}")
    finally:
        h.close()


def send_cmd(cmd: int, param: int, x0: int, y0: int, x1: int, y1: int) -> None:
    byteseq = struct.pack("<bHHHHHH", cmd, param, x0, y0, x1, y1, 0)
    chksum = struct.pack("<H", crc16(byteseq))
    padding = bytes(PACKET_SIZE - 1 - len(byteseq) - len(chksum))
    frame = bytes([REPORT_ID]) + byteseq + chksum + padding

    h = open_device()
    try:
        h.write(frame)
        resp = h.read(PACKET_SIZE, timeout_ms=1000)
        if not resp:
            print("No response (timeout)")
            return
        status_byte = resp[1] if len(resp) > 1 else resp[0]
        status = RET_CODES.get(status_byte, f"UNKNOWN(0x{status_byte:02x})")
        print(f"Response: {status}  raw={list(resp[:8])}")
    finally:
        h.close()


def cmd_simple(name: str):
    def run(args):
        send_cmd(CMDS[name], args.param, args.x0, args.y0, args.x1, args.y1)
    return run


def cmd_serve(_args) -> None:
    """Listen on ~/.glider-cmd (a named pipe) for commands and execute them.

    Run this once from a terminal that has HID access (Input Monitoring permission).
    Hammerspoon (or any other client) can then send bare commands by writing to the pipe:

        echo "setmode 6" > ~/.glider-cmd
        echo "setlevel 12345 0.1" > ~/.glider-cmd
    """
    import os
    pipe_path = os.path.expanduser("~/.glider-cmd")
    if not os.path.exists(pipe_path):
        os.mkfifo(pipe_path)
    parser = build_parser()
    print(f"Glider daemon listening on {pipe_path}  (Ctrl+C to stop)", flush=True)
    while True:
        try:
            # Reopen each iteration: a writer closing the pipe sends EOF, which ends the for-loop.
            with open(pipe_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    print(f"< {line}", flush=True)
                    try:
                        cmd_args = parser.parse_args(line.split())
                        cmd_args.func(cmd_args)
                    except SystemExit as e:
                        print(f"  error: {e}", flush=True)
                    except Exception as e:
                        print(f"  error: {e}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"pipe error: {e}", flush=True)
    print("Glider daemon stopped.", flush=True)


def cmd_setlevel(args) -> None:
    """Apply sine-curve midtone lift to one display via CGSetDisplayTransferByTable (macOS only).

    Level k=0 is identity; k>0 lifts midtones (brighter); k<0 drops them (darker).
    Endpoints are anchored because sin(0)=sin(pi)=0. Keep |k|<=0.3 for monotonic output.
    """
    if platform.system() != "Darwin":
        raise SystemExit("setlevel is macOS-only")
    import ctypes
    import math
    CG = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    CG.CGSetDisplayTransferByTable.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
    ]
    CG.CGSetDisplayTransferByTable.restype = ctypes.c_int32
    n = 256
    TableType = ctypes.c_float * n
    ramp = TableType()
    k = args.level
    for i in range(n):
        x = i / 255.0
        y = x + k * math.sin(math.pi * x)
        ramp[i] = max(0.0, min(1.0, y))
    result = CG.CGSetDisplayTransferByTable(ctypes.c_uint32(args.display_id), ctypes.c_uint32(n), ramp, ramp, ramp)
    if result != 0:
        print(f"CGSetDisplayTransferByTable failed with code {result}")


def cmd_invertloop(args) -> None:
    """Continuously apply an inverted gamma ramp until killed (macOS only).

    macOS periodically resets the gamma table (Night Shift, True Tone, colour profiles),
    so a single CGSetDisplayTransferByTable call doesn't persist. This command loops at
    ~60 fps, re-applying the ramp on every iteration, matching what Black Light does via
    CVDisplayLink. Hammerspoon starts this as a background task and terminates it when
    inversion is toggled off.

    An optional --level applies the sine-curve midtone lift on top of the inversion
    (used for the Glider, which also has a brightness adjustment).
    """
    if platform.system() != "Darwin":
        raise SystemExit("invertloop is macOS-only")
    import ctypes
    import math
    import time
    CG = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    CG.CGSetDisplayTransferByTable.argtypes = [
        ctypes.c_uint32, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
        ctypes.POINTER(ctypes.c_float),
    ]
    CG.CGSetDisplayTransferByTable.restype = ctypes.c_int32
    n = 256
    TableType = ctypes.c_float * n
    k = args.level
    ramp = TableType()
    for i in range(n):
        x = i / 255.0
        y = x + k * math.sin(math.pi * x)
        ramp[i] = max(0.0, min(1.0, 1.0 - y))
    display = ctypes.c_uint32(args.display_id)
    interval = 1 / 60
    try:
        while True:
            CG.CGSetDisplayTransferByTable(display, ctypes.c_uint32(n), ramp, ramp, ramp)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Print device manufacturer/product/serial").set_defaults(func=cmd_info)

    for name in ["reset", "powerdown", "powerup", "redraw", "setmode", "setinput"]:
        p = sub.add_parser(name, help=f"Send {name.upper()} command")
        p.add_argument("param", type=int, nargs="?", default=0, help="Command parameter (e.g. mode index for setmode)")
        p.add_argument("--x0", type=int, default=0)
        p.add_argument("--y0", type=int, default=0)
        p.add_argument("--x1", type=int, default=1599, help="Right edge (13.3\" panel: 1599, 6\" panel: 1447)")
        p.add_argument("--y1", type=int, default=1199, help="Bottom edge (13.3\" panel: 1199, 6\" panel: 1071)")
        p.set_defaults(func=cmd_simple(name))

    sub.add_parser("serve", help="Listen on ~/.glider-cmd for commands (run from a terminal with HID access)").set_defaults(func=cmd_serve)

    p = sub.add_parser("setlevel", help="Set display gamma ramp via sine-curve midtone lift (macOS only)")
    p.add_argument("display_id", type=int, help="CGDirectDisplayID — use screen:id() in Hammerspoon")
    p.add_argument("level", type=float, help="Midtone lift k: 0=neutral, >0=brighter, <0=darker. Keep |k|<=0.3.")
    p.add_argument("--invert", action="store_true", help="Invert the display (flip the ramp)")
    p.set_defaults(func=cmd_setlevel)

    p = sub.add_parser("invertloop", help="Continuously apply inverted gamma until killed (macOS only)")
    p.add_argument("display_id", type=int, help="CGDirectDisplayID — use screen:id() in Hammerspoon")
    p.add_argument("--level", type=float, default=0.0, help="Midtone lift to combine with inversion (default 0)")
    p.set_defaults(func=cmd_invertloop)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
