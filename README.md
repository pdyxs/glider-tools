# Glider Monitor Control Tooling

Windows-side control tooling for the Modos Glider e-ink monitor. The upstream Modos repo's tooling is Linux-only, so this is a minimal alternative for driving the device from Windows.

## What this is

- **`glider.py`** — Python CLI that talks to the Glider over USB HID (modes, redraw, power, input switching)
- **`glider.ahk`** — AutoHotkey v2 script binding keyboard shortcuts to Glider commands plus per-mode gamma adjustment
- **`glider-state.ini`** — auto-generated per-mode gamma persistence (gitignored)

## Hardware context

- **Device**: Modos Glider 13.3" (1600×1200 e-ink)
- **USB**: VID `0x1209`, PID `0xae86`, Manufacturer "Modos", Product "Control"
- **EDID**: PnP ID `ZPR0001`, friendly name "Paper Monitor"
- **HID**: 4 collections; the command channel is the one with `usage_page == 0xFF00`

## Why a custom tool

The upstream repo at <https://github.com/modos-labs/glider> ships two Python tools in `utils/`:

- **`flash_tool/main.py`** — full factory workstation GUI. Hardcoded Linux-only (`xrandr`, `xinput`, `/dev/ttyUSB0`, `/sys/class/drm/`). Won't run on Windows.
- **`usb_example.py`** — minimal HID example, but it's **outdated and wrong**: old VID/PID (`0x0483/0x5750`), wrong struct format (`<hhhhhhh` — 7 signed shorts), missing report ID and packet padding. Do not copy from it.

The *actual correct* protocol lives inside `flash_tool/main.py`'s `send_cmd` method. This project extracts that protocol into a Windows-friendly CLI.

## USB HID protocol

Reference: `flash_tool/main.py:260` (`send_cmd`) in the upstream repo.

```python
byteseq = struct.pack('<bHHHHHH', cmd, param, x0, y0, x1, y1, pid)
chksum  = struct.pack('<H', crc16(byteseq))
packet  = b'\x05' + byteseq + chksum + bytearray(48)   # total = 64 bytes
```

Key details:

| Aspect | Value |
|---|---|
| Struct format | `<bHHHHHH` (1 signed byte + 6 unsigned shorts = 13 bytes) |
| Report ID | `0x05` (prepended; required on Windows HID) |
| Packet size | 64 bytes total (1 + 13 + 2 + 48 padding) |
| CRC | CRC-16 CCITT with precomputed lookup table, over the 13 command bytes only |
| Response | 64 bytes, status byte at `resp[1]` (index 0 is echoed report ID) |
| Status codes | `0x55` success, `0x00` general fail, `0x01` checksum fail |

### Device selection on Windows

The Glider exposes 4 HID collections with different usage pages. Only the vendor-specific one (`usage_page == 0xFF00`) is the command channel. Iterate `hid.enumerate(VID, PID)` and open by `path` for that specific collection — not just `h.open(vid, pid)` which grabs the first match and may pick the wrong collection on Windows.

## Command list

From `fw/User/usbapp.h` in the upstream repo:

| Value | Name | Description |
|---|---|---|
| 0x00 | RESET | Reset |
| 0x01 | POWERDOWN | Panel power down |
| 0x02 | POWERUP | Panel power up |
| 0x03 | SETINPUT | Switch input source |
| 0x04 | REDRAW | Force full refresh of bounding box |
| 0x05 | SETMODE | Switch display/dither mode |
| 0x06 | NUKE | **Destructive** — don't use casually |
| 0x07 | USBBOOT | Enter USB boot mode |
| 0x08 | RECV | Firmware transfer |

Mode values for SETMODE (from `fw/User/caster.h`):

| Mode | Enum name | Firmware UI label | What it does |
|---|---|---|---|
| 0 | `MANUAL_LUT_NO_DITHER` | — | 16-level grayscale, no dither |
| 1 | `MANUAL_LUT_ERROR_DIFFUSION` | — | 16-level + error diffusion |
| 2 | `FAST_MONO_NO_DITHER` | — | Binary, no dither |
| 3 | `FAST_MONO_BAYER` | Browsing | Binary + Bayer dither |
| 4 | `FAST_MONO_BLUE_NOISE` | Watching | Binary + blue noise dither |
| 5 | `FAST_GREY` | Typing | Fast grayscale |
| 6 | `AUTO_LUT_NO_DITHER` | Reading | Auto waveform, no dither |
| 7 | `AUTO_LUT_ERROR_DIFFUSION` | — | Auto waveform + error diffusion |

The firmware's own mode picker UI in `fw/User/ui.c` labels a subset of these with their intended use cases (Browsing/Watching/Typing/Reading) — a good hint at what Modos recommends for each.

### Bounding box

The `REDRAW` and `SETMODE` commands take `(x0, y0, x1, y1)`. For full-screen operation on the 13.3" panel use `(0, 0, 1599, 1199)`. The 6" panel is `1448 × 1072` instead (defaults in `glider.py` target the 13.3").

### No threshold / brightness / gamma command

The full USB command set is the 9 commands above — there's no `SET_THRESHOLD`, `SET_BRIGHTNESS`, or `SET_GAMMA`. Binary quantization and grayscale mapping live in the Caster FPGA pipeline as fixed logic. Changing them would require rebuilding the FPGA bitstream (Xilinx ISE 14.7). For "adjust the blacks/whites" use cases, we apply a gamma ramp on the Windows side instead (see below).

## Gamma adjustment (Windows-side)

`glider.ahk` uses `gdi32!SetDeviceGammaRamp` to apply a per-display gamma ramp to the Glider's HDC. This is purely a preprocessing trick on the video signal — the Glider panel itself operates unchanged.

### Display detection

The script enumerates display adapters via `user32!EnumDisplayDevicesW`, filters to **active** adapters (StateFlags bit `0x1`), and for each one queries the attached monitor and matches its DeviceID against `ZPR0001` (the Glider's stable EDID PnP ID). This means the script survives monitor renumbering — you can add/remove other displays without breaking detection.

**PowerShell PInvoke gotcha**: when calling `EnumDisplayDevicesW` from PowerShell, passing `$null` as the first argument doesn't marshal to a NULL `LPCWSTR`. Use `IntPtr.Zero` with a matching `IntPtr` signature (the AHK v2 `DllCall("...", "Ptr", 0, ...)` form works correctly without this workaround).

### Gamma ramp construction

For gamma value `g`, each channel entry at index `i`:

```
out[i] = clamp(((i / 255) ** (1 / g)) * 65535, 0, 65535)
```

- `g == 1.0` → identity (no change)
- `g > 1.0`  → brighter midtones
- `g < 1.0`  → darker midtones

Per-mode gamma is persisted to `glider-state.ini` and reloaded on startup. A separate entry per mode means each mode can have its own preferred gamma (e.g. high gamma for text reading, neutral for image viewing).

### Safety net

`Ctrl+Shift+0` resets gamma on **all active displays** (not just the Glider). This handles the case where the Glider gets disconnected after an adjustment and a ramp "leaks" onto whatever display inherits its slot. The script also calls the same reset on exit (via `OnExit`).

## Display requirements

Gamma hotkeys require the Glider in **extended mode** or as the sole display. In Windows "duplicate/mirror" mode, both outputs share a single logical framebuffer and gamma ramp — there's no API to target one output independently in that configuration.

## Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+1` | Mode 1 — 16-level + error diffusion |
| `Ctrl+Shift+2` | Mode 2 — Binary |
| `Ctrl+Shift+3` | Mode 3 — Bayer (Browsing) |
| `Ctrl+Shift+4` | Mode 4 — Blue Noise (Watching) |
| `Ctrl+Shift+5` | Mode 5 — Fast Grey (Typing) |
| `Ctrl+Shift+6` | Mode 6 — Auto LUT (Reading) |
| `Ctrl+Shift+7` | Mode 7 — Auto LUT + error diffusion |
| `Ctrl+Shift+Space` | Redraw |
| `Ctrl+Shift++` | Gamma brighter |
| `Ctrl+Shift+-` | Gamma darker |
| `Ctrl+Shift+0` | Reset gamma on all active displays |
| `Ctrl+Shift+F12` | Re-detect Glider (after monitor hotplug) |

## Setup

### Prerequisites

- **Python 3** with the `hidapi` package (`pip install hidapi`). Note: this is **not** the `hid` package on PyPI, which needs a separately-installed `hidapi.dll`. `hidapi` ships its own.
- **AutoHotkey v2** (`scoop install autohotkey` — needs the `extras` bucket: `scoop bucket add extras`)
- The Glider plugged directly into a Windows USB port (not routed through WSL)

### Running

```powershell
# Manual test of the Python CLI:
python C:\Users\pdyxs\dev\glider\glider.py info
python C:\Users\pdyxs\dev\glider\glider.py redraw
python C:\Users\pdyxs\dev\glider\glider.py setmode 6

# Launch the hotkey script:
& 'C:\Users\pdyxs\scoop\apps\autohotkey\current\v2\AutoHotkey64.exe' 'C:\Users\pdyxs\dev\glider\glider.ahk'
```

To close the AHK script: right-click the tray icon → Exit, or `Stop-Process -Name AutoHotkey64`.

### Auto-start on login

Create a shortcut to `glider.ahk` in `shell:startup` (Win+R → `shell:startup`).

## Known limitations & future work

- **No runtime threshold/level adjustment on the Glider itself** — requires FPGA bitstream rebuild (Xilinx ISE 14.7). Gamma workaround is Windows-side only.
- **No `GETMODE` query** — the firmware doesn't expose a way to read back the current mode, so the script assumes a fresh state on startup. A user could press any mode hotkey once to sync.
- **Mirror mode unsupported** — per-display gamma doesn't work when displays are duplicated; switch to Extend mode.
- **Upstream flashing still requires Linux/WSL** — if you ever need to flash firmware or regenerate display config, bounce the USB to WSL via `usbipd-win` and use `utils/flash_tool/` from a local clone of the upstream repo. That path is out of scope for this project.

## Upstream repo reference

The Modos source tree is at <https://github.com/modos-labs/glider>. A local clone is kept in WSL at `~/glider` (Ubuntu distro) for easy reference.

Key upstream files for this project:

| Path | Purpose |
|---|---|
| `fw/User/usbapp.h`, `fw/User/usbapp.c` | USB command list and handler |
| `fw/User/caster.h` | Mode enum definitions |
| `fw/User/ui.c` | Firmware UI mode labels (Browsing/Watching/etc.) |
| `utils/flash_tool/main.py` | Canonical protocol reference (Linux-only tool, but the protocol code is correct) |
| `utils/usb_example.py` | **Do not trust** — outdated VID/PID and wrong struct format |

## Files in this repo

| File | Purpose |
|---|---|
| `glider.py` | Python HID CLI |
| `glider.ahk` | AutoHotkey v2 hotkey script |
| `glider-state.ini` | Runtime state (per-mode gamma) — gitignored |
| `README.md` | This file |
| `.gitignore` | Ignores state file and build artifacts |
