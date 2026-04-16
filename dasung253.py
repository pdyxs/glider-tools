"""CLI for controlling a Dasung Paperlike 253 (colour or B&W) over USB serial.

The monitor exposes a CH340 USB-to-serial adapter (VID=0x1A86, PID=0x7523)
running at 115200 baud.  All packets are 24 ASCII bytes:

    5FF5  +  cmd(2)  +  payload(14, right-padded with '0')  +  A0FA

To GET a parameter, send command 0A with the attribute code as the payload.
To SET a parameter, send the attribute code as the command with the value as
the payload.  Responses have the same format; the result sits in bytes 10-11.

Examples:
    python dasung253.py info
    python dasung253.py getmode
    python dasung253.py setmode text
    python dasung253.py getthreshold
    python dasung253.py setthreshold 5
    python dasung253.py refresh
    python dasung253.py serve
"""

import argparse
import glob
import os
import platform
import sys

BAUD = 115200
PACKET_SIZE = 24
PREFIX = b"5FF5"
TAIL = b"A0FA"

VID = 0x1A86  # WCH CH340
PID = 0x7523

# Attribute codes (hex strings sent on the wire)
ATTR = {
    "threshold":   "01",  # 1-9
    "mode":        "02",  # 1-4
    "speed":       "04",  # 1-5
    "rtc":         "05",
    "frontlight":  "07",  # 0-3
    "temperature": "08",  # 0-100 (read-only on B&W)
    "light":       "09",  # 0-100
    "version":     "10",
    "enhancement": "12",  # 0-1
}

DISPLAY_MODES = {
    "auto":    1,
    "text":    2,
    "graphic": 3,
    "video":   4,
}
DISPLAY_MODES_INV = {v: k for k, v in DISPLAY_MODES.items()}

CMD_GET = "0A"
CMD_REFRESH = "03"


# ── serial port discovery ───────────────────────────────────────────────────

def find_port() -> str:
    """Return the first serial port that looks like a CH340."""
    if platform.system() == "Darwin":
        patterns = ["/dev/cu.usbserial-*", "/dev/cu.wchusbserial*"]
    elif platform.system() == "Windows":
        # pyserial can enumerate; fall back to COM* scan
        try:
            import serial.tools.list_ports
            for p in serial.tools.list_ports.comports():
                if p.vid == VID and p.pid == PID:
                    return p.device
        except Exception:
            pass
        patterns = []
    else:
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*"]

    for pat in patterns:
        matches = sorted(glob.glob(pat))
        if matches:
            return matches[0]

    raise SystemExit(
        "Dasung 253 serial port not found. "
        "Make sure the USB cable is connected and the CH340 driver is installed."
    )


def open_port(port: str = None):
    import serial
    p = port or find_port()
    return serial.Serial(p, BAUD, timeout=1)


# ── packet helpers ──────────────────────────────────────────────────────────

def build_packet(cmd: str, payload: str) -> bytes:
    """Build a 24-byte ASCII packet."""
    payload_padded = payload.ljust(14, "0")
    assert len(cmd) == 2 and len(payload_padded) == 14
    packet = PREFIX + cmd.encode() + payload_padded.encode() + TAIL
    assert len(packet) == PACKET_SIZE
    return packet


def parse_response(data: bytes) -> dict:
    """Parse a 24-byte response packet into its fields."""
    if len(data) != PACKET_SIZE:
        raise ValueError(f"Bad response length: {len(data)}")
    if data[:4] != PREFIX:
        raise ValueError(f"Bad prefix: {data[:4]!r}")
    cmd   = data[4:6].decode()
    arg   = data[6:8].decode()
    data1 = data[8:10].decode()
    data2 = data[10:12].decode()
    return {"cmd": cmd, "arg": arg, "data1": data1, "data2": data2}


def transact(cmd: str, payload: str, port: str = None) -> dict:
    """Send a packet and return the parsed response."""
    s = open_port(port)
    try:
        pkt = build_packet(cmd, payload)
        s.write(pkt)
        resp = s.read(PACKET_SIZE)
        if not resp:
            raise SystemExit("No response from monitor (timeout)")
        return parse_response(resp)
    finally:
        s.close()


def get_attr(attr_code: str, port: str = None) -> int:
    """GET a parameter; returns the integer value from data2."""
    attr_int = int(attr_code, 16)
    payload = f"{attr_int:02x}"
    resp = transact(CMD_GET, payload, port)
    return int(resp["data2"], 16)


def set_attr(attr_code: str, value: int, port: str = None) -> dict:
    """SET a parameter using the attribute code as the command."""
    payload = f"{value:02x}"
    return transact(attr_code, payload, port)


# ── commands ────────────────────────────────────────────────────────────────

def cmd_info(args) -> None:
    port = find_port()
    print(f"Port:    {port}")
    version = get_attr(ATTR["version"], port)
    print(f"Version: 0x{version:02x}")
    has_frontlight  = version in (0x30, 0x31)
    has_enhancement = version in (0x11, 0x31)
    print(f"Frontlight:  {'yes' if has_frontlight else 'no'}")
    print(f"Enhancement: {'yes' if has_enhancement else 'no'}")


def cmd_getmode(args) -> None:
    val = get_attr(ATTR["mode"], args.port)
    name = DISPLAY_MODES_INV.get(val, f"unknown({val})")
    print(f"{name} ({val})")


def cmd_setmode(args) -> None:
    mode = args.mode.lower()
    if mode not in DISPLAY_MODES:
        raise SystemExit(f"Unknown mode '{mode}'. Choose from: {', '.join(DISPLAY_MODES)}")
    val = DISPLAY_MODES[mode]
    resp = set_attr(ATTR["mode"], val, args.port)
    print(f"mode -> {mode} ({val})  resp={resp}")


def cmd_getthreshold(args) -> None:
    val = get_attr(ATTR["threshold"], args.port)
    print(val)


def cmd_setthreshold(args) -> None:
    if not 1 <= args.value <= 9:
        raise SystemExit("Threshold must be 1-9")
    resp = set_attr(ATTR["threshold"], args.value, args.port)
    print(f"threshold -> {args.value}  resp={resp}")


def cmd_getlight(args) -> None:
    val = get_attr(ATTR["light"], args.port)
    print(val)


def cmd_setlight(args) -> None:
    if not 0 <= args.value <= 100:
        raise SystemExit("Light must be 0-100")
    resp = set_attr(ATTR["light"], args.value, args.port)
    print(f"light -> {args.value}  resp={resp}")


def cmd_getspeed(args) -> None:
    val = get_attr(ATTR["speed"], args.port)
    print(val)


def cmd_setspeed(args) -> None:
    if not 1 <= args.value <= 5:
        raise SystemExit("Speed must be 1-5")
    resp = set_attr(ATTR["speed"], args.value, args.port)
    print(f"speed -> {args.value}  resp={resp}")


def cmd_getfrontlight(args) -> None:
    val = get_attr(ATTR["frontlight"], args.port)
    print(val)


def cmd_setfrontlight(args) -> None:
    if not 0 <= args.value <= 3:
        raise SystemExit("Frontlight must be 0-3")
    resp = set_attr(ATTR["frontlight"], args.value, args.port)
    print(f"frontlight -> {args.value}  resp={resp}")


def cmd_getenhancement(args) -> None:
    val = get_attr(ATTR["enhancement"], args.port)
    print(val)


def cmd_setenhancement(args) -> None:
    if args.value not in (0, 1):
        raise SystemExit("Enhancement must be 0 or 1")
    resp = set_attr(ATTR["enhancement"], args.value, args.port)
    print(f"enhancement -> {args.value}  resp={resp}")


def cmd_refresh(args) -> None:
    resp = transact(CMD_REFRESH, "00", args.port)
    print(f"refresh  resp={resp}")


def cmd_serve(args) -> None:
    """Listen on ~/.dasung253-cmd for commands and execute them.

    Hammerspoon (or any other client) can send commands by writing to the pipe:

        echo "setmode text" > ~/.dasung253-cmd
        echo "setthreshold 5" > ~/.dasung253-cmd
    """
    pipe_path = os.path.expanduser("~/.dasung253-cmd")
    if not os.path.exists(pipe_path):
        os.mkfifo(pipe_path)
    parser = build_parser()
    print(f"Dasung 253 daemon listening on {pipe_path}  (Ctrl+C to stop)", flush=True)
    while True:
        try:
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
    print("Dasung 253 daemon stopped.", flush=True)


# ── argument parser ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port", default=None, help="Serial port (auto-detected if omitted)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info",           help="Show port, firmware version, and capabilities").set_defaults(func=cmd_info)
    sub.add_parser("getmode",        help="Get current display mode").set_defaults(func=cmd_getmode)
    sub.add_parser("getthreshold",   help="Get threshold (contrast), 1-9").set_defaults(func=cmd_getthreshold)
    sub.add_parser("getlight",       help="Get light level, 0-100").set_defaults(func=cmd_getlight)
    sub.add_parser("getspeed",       help="Get refresh speed, 1-5").set_defaults(func=cmd_getspeed)
    sub.add_parser("getfrontlight",  help="Get frontlight level, 0-3").set_defaults(func=cmd_getfrontlight)
    sub.add_parser("getenhancement", help="Get enhancement (0 or 1)").set_defaults(func=cmd_getenhancement)
    sub.add_parser("refresh",        help="Clear ghosting / full refresh").set_defaults(func=cmd_refresh)
    sub.add_parser("serve",          help="Listen on ~/.dasung253-cmd for commands").set_defaults(func=cmd_serve)

    p = sub.add_parser("setmode", help="Set display mode: auto, text, graphic, video")
    p.add_argument("mode", help="auto | text | graphic | video")
    p.set_defaults(func=cmd_setmode)

    p = sub.add_parser("setthreshold", help="Set threshold (contrast), 1-9")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setthreshold)

    p = sub.add_parser("setlight", help="Set light level, 0-100")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setlight)

    p = sub.add_parser("setspeed", help="Set refresh speed, 1-5")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setspeed)

    p = sub.add_parser("setfrontlight", help="Set frontlight level, 0-3")
    p.add_argument("value", type=int)
    p.set_defaults(func=cmd_setfrontlight)

    p = sub.add_parser("setenhancement", help="Set enhancement on (1) or off (0)")
    p.add_argument("value", type=int, choices=[0, 1])
    p.set_defaults(func=cmd_setenhancement)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
