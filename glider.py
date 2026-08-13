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
import time

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
    "settone":   0x09,
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
    matches = hid.enumerate(VID, PID)
    # Prefer the vendor-specific usage page (0xFF00) — required on Windows to
    # select the correct collection out of the four the Glider exposes.
    for d in matches:
        if d.get("usage_page") == VENDOR_USAGE_PAGE:
            return d["path"]
    # On Linux, hidapi's hidraw backend often returns usage_page=0 for all
    # collections. If we got exactly one match, use it directly.
    if len(matches) == 1:
        return matches[0]["path"]
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


def _build_frame(cmd: int, param: int, x0: int = 0, y0: int = 0, x1: int = 0, y1: int = 0,
                  signed: bool = False) -> bytes:
    # settone's lightness/contrast (param/x0) are signed (-3..3, -1..6), unlike
    # every other command's unsigned params, so it needs "h" not "H" there.
    fmt = "<bhhHHHH" if signed else "<bHHHHHH"
    byteseq = struct.pack(fmt, cmd, param, x0, y0, x1, y1, 0)
    chksum = struct.pack("<H", crc16(byteseq))
    padding = bytes(PACKET_SIZE - 1 - len(byteseq) - len(chksum))
    return bytes([REPORT_ID]) + byteseq + chksum + padding


def _send_frame_on(h: "hid.device", frame: bytes) -> str:
    h.write(frame)
    resp = h.read(PACKET_SIZE, timeout_ms=1000)
    if not resp:
        return "TIMEOUT"
    status_byte = resp[1] if len(resp) > 1 else resp[0]
    return RET_CODES.get(status_byte, f"UNKNOWN(0x{status_byte:02x})")


def send_cmd(cmd: int, param: int, x0: int, y0: int, x1: int, y1: int) -> None:
    h = open_device()
    try:
        status = _send_frame_on(h, _build_frame(cmd, param, x0, y0, x1, y1))
        print(f"Response: {status}")
    finally:
        h.close()


def send_settone(lightness: int, contrast: int) -> None:
    h = open_device()
    try:
        status = _send_frame_on(h, _build_frame(CMDS["settone"], lightness, contrast, signed=True))
        print(f"Response: {status}")
    finally:
        h.close()


def send_sequence(frames: list) -> list:
    """Send multiple frames over a single device connection, waiting for each
    ACK before sending the next.

    Sending related commands (e.g. setmode + settone + redraw) as separate
    fire-and-forget processes that each open the device independently is
    racy: the device can drop a command that arrives too soon after another.
    Waiting for a real ACK in between — rather than guessing at a delay —
    avoids that.
    """
    h = open_device()
    try:
        return [_send_frame_on(h, frame) for frame in frames]
    finally:
        h.close()


def cmd_settone(args) -> None:
    send_settone(args.lightness, args.contrast)


# fw/User/caster.c's get_update_frames() is hardcoded to the frame count for a
# ~0.5s waveform ("actually, just always return 0.5s"). SETMODE queues an
# async FPGA redraw of that length; sending another op (our own REDRAW below)
# before it's done appears to get silently dropped rather than queued — the
# firmware even has commented-out is_busy() guards around this exact op-queue
# register. So, unlike settone+redraw (cmd_tone below), this needs a real
# wait, not just waiting for the (immediate, queuing-only) HID ACK.
MODE_SWITCH_SETTLE_S = 0.6


def cmd_modetone(args) -> None:
    region = (args.x0, args.y0, args.x1, args.y1)
    h = open_device()
    try:
        status_mode = _send_frame_on(h, _build_frame(CMDS["setmode"], args.mode, *region))
        time.sleep(MODE_SWITCH_SETTLE_S)
        status_tone = _send_frame_on(h, _build_frame(CMDS["settone"], args.lightness, args.contrast, signed=True))
        status_redraw = _send_frame_on(h, _build_frame(CMDS["redraw"], 0, *region))
    finally:
        h.close()
    print(f"Response: setmode={status_mode} settone={status_tone} redraw={status_redraw}")


def cmd_tone(args) -> None:
    region = (args.x0, args.y0, args.x1, args.y1)
    statuses = send_sequence([
        _build_frame(CMDS["settone"], args.lightness, args.contrast, signed=True),
        _build_frame(CMDS["redraw"], 0, *region),
    ])
    print(f"Response: settone={statuses[0]} redraw={statuses[1]}")


def cmd_simple(name: str):
    def run(args):
        send_cmd(CMDS[name], args.param, args.x0, args.y0, args.x1, args.y1)
    return run


def cmd_reinput(args) -> None:
    """Force the firmware to re-run its input bring-up.

    SETINPUT only writes config.input_sel; the firmware's UI loop calls
    apply_input_selection() *only when the value changes*. Sending the value the
    device already holds is therefore a no-op that still reports SUCCESS. Bounce
    through another value so the selection genuinely transitions.

    The device is LEFT ON `input`, and SETINPUT calls config_save(), so the
    choice persists across reconnects. Default 2 (DP); passing 0 leaves the
    device on Auto, which is unreliable on firmware 1.0.
    """
    import time
    target = args.input
    via = 0 if target != 0 else 2
    send_cmd(CMDS["setinput"], via, 0, 0, 0, 0)
    time.sleep(args.delay)
    send_cmd(CMDS["setinput"], target, 0, 0, 0, 0)
    time.sleep(args.delay)
    send_cmd(CMDS["redraw"], 0, args.x0, args.y0, args.x1, args.y1)


def cmd_serve(_args) -> None:
    """Listen on ~/.glider-cmd (a named pipe) for commands and execute them.

    Run this once from a terminal that has HID access (Input Monitoring permission).
    Hammerspoon (or any other client) can then send bare commands by writing to the pipe:

        echo "setmode 6" > ~/.glider-cmd
        echo "redraw" > ~/.glider-cmd
    """
    from common import serve_loop
    serve_loop("glider-cmd", "Glider", build_parser())



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

    p = sub.add_parser("reinput", help="Force the input bring-up to re-run (setinput <other> then <target>, then redraw) - use this, not a bare setinput, since setting the value the device already holds is a no-op. NOTE: leaves the device on <target>, saved to flash")
    p.add_argument("input", type=int, nargs="?", default=2, help="Target input the device is LEFT ON, persisted to flash: 0=Auto, 1=TMDS, 2=DP (default 2). Auto is unreliable on fw 1.0 - stick to 2 unless you mean it")
    p.add_argument("--delay", type=float, default=3.0, help="Seconds to wait between transitions (default 3)")
    p.add_argument("--x0", type=int, default=0)
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--x1", type=int, default=1599)
    p.add_argument("--y1", type=int, default=1199)
    p.set_defaults(func=cmd_reinput)

    p = sub.add_parser("usbboot", help="Enter USB DFU boot mode for firmware flashing")
    p.add_argument("param", type=int, nargs="?", default=0)
    p.add_argument("--x0", type=int, default=0)
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--x1", type=int, default=1599)
    p.add_argument("--y1", type=int, default=1199)
    p.set_defaults(func=cmd_simple("usbboot"))

    p = sub.add_parser("settone", help="Live-preview lightness/contrast without persisting to flash (see also: setcfg set lightness/contrast + save)")
    p.add_argument("lightness", type=int, help="-3..3")
    p.add_argument("contrast", type=int, help="-1..6")
    p.set_defaults(func=cmd_settone)

    p = sub.add_parser("tone", help="settone + redraw, sent over one device connection so the redraw can't race the tone change")
    p.add_argument("lightness", type=int, help="-3..3")
    p.add_argument("contrast", type=int, help="-1..6")
    p.add_argument("--x0", type=int, default=0)
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--x1", type=int, default=1599, help="Right edge (13.3\" panel: 1599, 6\" panel: 1447)")
    p.add_argument("--y1", type=int, default=1199, help="Bottom edge (13.3\" panel: 1199, 6\" panel: 1071)")
    p.set_defaults(func=cmd_tone)

    p = sub.add_parser("modetone", help="setmode + settone + redraw, sent over one device connection so they can't race each other")
    p.add_argument("mode", type=int, help="Firmware mode index")
    p.add_argument("lightness", type=int, help="-3..3")
    p.add_argument("contrast", type=int, help="-1..6")
    p.add_argument("--x0", type=int, default=0)
    p.add_argument("--y0", type=int, default=0)
    p.add_argument("--x1", type=int, default=1599, help="Right edge (13.3\" panel: 1599, 6\" panel: 1447)")
    p.add_argument("--y1", type=int, default=1199, help="Bottom edge (13.3\" panel: 1199, 6\" panel: 1071)")
    p.set_defaults(func=cmd_modetone)

    sub.add_parser("serve", help="Listen on ~/.glider-cmd for commands (run from a terminal with HID access)").set_defaults(func=cmd_serve)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
