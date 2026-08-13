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
- **Firmware 1.0 input auto-detect is unreliable** — after flashing the upstream `1.0` firmware release (`ed94ef7f`), `input_sel: 0` (Auto) intermittently fails to lock onto the DisplayPort Alt Mode signal from a USB-C host (no signal, or garbled output at an off-spec refresh rate) — independent of cable, port, or USB-C orientation. Fix: force the input to DP via the panel's on-screen menu (Auto/TMDS/DP), or `python glider.py setinput 2` (`0` = Auto, `1` = TMDS, `2` = DP). This is saved to the device's flash config (`setcfg get` → `input_sel`) and survives reconnects.
- **`setinput` to the current value is a no-op** — use `glider.py reinput` instead; see below.
- **Boot-time display mode is never applied to the FPGA** — see below. Unconfirmed, but the code path is clear.

## Boot mode is tracked but never applied (unconfirmed lead)

Noted 2026-08-13, **not yet verified or fixed.** Symptom: on every connect the Glider comes up in a mode that is hard to read and doesn't look like any of the four named modes. Changing to any mode makes it usable.

This looks like the same class of bug as the AUX polarity issue below — state tracked in the MCU but never pushed to the hardware.

At boot, `ui.c:854` does:

```c
mode = mode_index_for((update_mode_t)config.update_mode);

bool tmds_mode = false;
start_display_pipeline(&tmds_mode, &fonts, &signal_osd_state, &no_signal_deadline);
```

That first line only updates the MCU's local `mode` index variable. `start_display_pipeline()` then runs `restart_fpga()` → `power_on_epd()` → `caster_init()` → `apply_input_selection()`, and **never calls `apply_display_mode()`**. So the Caster runs whatever mode `caster_init()` leaves it in, while the MCU believes it is in `config.update_mode`. Pressing a mode key calls `apply_display_mode()`, which does write it — hence the manual fix.

The resume path has the same omission (~`ui.c:889`): `mode = mode_index_for(...)` with no apply.

Consistent with the symptoms:

- The `modes[]` table in `ui.c:51` contains only `UM_FAST_MONO_BAYER` (Browsing), `UM_FAST_MONO_BLUE_NOISE` (Watching), `UM_FAST_GREY` (Typing) and `UM_AUTO_LUT_NO_DITHER` (Reading). The Caster's reset default isn't in that table, so the mode you land in has no UI name.
- The OSD reports the *tracked* mode rather than the actual one, which is why it's hard to tell what you're looking at.
- `update_mode` doesn't appear in `setcfg get` output, unlike `input_sel` / `lightness` / `contrast`.

Likely fix: apply the mode after `caster_init()` inside `start_display_pipeline()`, covering cold boot and resume in one place. **Confirm what `caster_init()` actually leaves the mode as before writing the patch** — that step hasn't been done.

## Stale AUX polarity on DP re-selection (fixed in firmware)

Diagnosed 2026-08-13. Symptom: on plugging in — to a different machine, or after a long sleep — the panel shows a black screen or "No signal", and it takes two to four replug attempts before it comes up. Once it connects it is completely stable.

Root cause is in the firmware, not the cable or the host. The PTN3460 DP bridge's AUX polarity is only ever written by `usb_mux_set()` during PD negotiation on a **connect event**. Otherwise `ptn3460_init()` re-applies `ptn_state.reverse_polarity`, which `ptn3460_powerdown()` never clears — so a DP re-selection without a fresh connect keeps whatever orientation the previous session left behind. When that cached value disagrees with the current connector orientation, AUX lands on the wrong SBU pins, the host can't read DPCD, and the link never acquires.

Diagnostic signature, all observed together:

| Where | What it shows |
|---|---|
| `/sys/class/drm/card1-DP-4/status` | `connected`, `enabled`, `dpms=On` — host side is fine |
| Mutter current mode | `1600x1200@74.996`, matching `pclk_hz 156618000 / (1680 × 1243)` |
| Panel | Black, or the firmware's own "No signal" OSD |
| `dmesg` | sometimes `retrieve_link_cap: Read receiver caps dpcd data failed` |
| `glider.py redraw` / `setmode` | returns SUCCESS; panel flashes and returns to black |
| `glider.py setinput 0` then `2` | returns SUCCESS; **does not** fix it (re-applies the same stale cache) |
| Replugging the cable | fixes it, but only sometimes — typically two to four attempts, with or without flipping |

The tell is that the panel *flashes* on a mode change: the e-ink pipeline is alive and painting, and what it's painting is an empty framebuffer. The video never arrived.

### `setinput <same value>` is a no-op — this matters for testing

`USBCMD_SETINPUT` only writes `config.input_sel` and saves it (`usbapp.c:167`). The bring-up is driven from the UI loop, which acts on a **change**:

```c
if (previous_config.input_sel != config.input_sel) {
    apply_input_selection(&tmds_mode);
```

On a device already at `input_sel: 2`, `glider.py setinput 2` therefore returns SUCCESS while doing nothing at all — `apply_input_selection()` never runs.

`glider.py reinput` exists to avoid this trap: it bounces via Auto (`setinput 0` → `setinput 2` → `redraw`) so the selection genuinely transitions. Use it instead of a bare `setinput` whenever the goal is to make the firmware *do* something.

### Status: candidate fix, NOT confirmed

`glider-fw-build` branch `fix-dp-aux-polarity` (`19648c7`) reads the live CC polarity from the FUSB302 on every DP input selection instead of trusting the cache. Flashed 2026-08-13.

It has **not been shown to work.** The theory rests on a code path that can clearly go stale, but the behavioural evidence is weak: the "flipping the connector fixes it" observation that motivated it is equally explained by "any replug fixes it sometimes", and a same-orientation replug has since recovered it too. Treat the AUX polarity story as a plausible hypothesis, not an established root cause.

To actually test it, next time the panel is blank:

```bash
# 1. Start the log FIRST - it drains on read (see below)
#    In one terminal, on /dev/ttyACM0 at 115200: run `syslog`
# 2. In another terminal, force the DP path to re-run:
python glider.py reinput
```

Then read the log for `Syncing AUX polarity to CC polarity N`:

- **Line absent** → the DP branch never ran; check `setcfg get` → `input_sel` and confirm the new firmware is flashed (`ver` should not say `Jul 25 2026`).
- **Line present and the panel recovers** → hypothesis supported, and this is a scriptable recovery.
- **Line present and the panel stays blank** → AUX polarity is not the cause. Look elsewhere; the FPGA's DP receiver state is the next suspect, since only a true power cycle has ever reliably cleared it.

The same commit bounds two unbounded waits that could wedge the display pipeline task: the PTN3460 HPD wait (whose "timeout" only logged and never broke out) and the FPGA CSR poll in `restart_fpga()`.

### Reading the device's own log

The firmware logs the whole bring-up (`Requesting DP input`, `PTN3460 up after N ms`, `Setting orientation to flipped`), but `shell_syslog` **drains** the ring buffer as it prints — `syslog_next()` advances `tail_idx`, so the log is consumed on first read and the boot sequence can't be recovered after the fact. Run `syslog` over `/dev/ttyACM0` *before* triggering the path you want to observe, or it will show only `[0.000] System starting`.

### Flashing MCU firmware (Linux)

The udev rule for the STM32 DFU interface (`0483:df11`) is at `/etc/udev/rules.d/99-glider-dfu.rules`.

```bash
# 1. Hold the button closer to the USB-C port while plugging in USB.
# 2. Confirm DFU mode — must show alt=0 "@Internal Flash /0x08000000":
dfu-util -l | grep -i 0483:df11
# 3. Flash (":leave" exits DFU and boots the new firmware):
dfu-util -a 0 -i 0 -s 0x08000000:leave -D path/to/glider_ec_rtos.bin
# 4. Unplug and replug normally.
```

Build first with `make -f Makefile.standalone` in `fw/` — this avoids needing STM32CubeIDE.

**Do not use `flash.py` for an MCU-only change.** It prompts to write a display config and that prompt defaults to yes, which overwrites `input_sel`, `lightness`, `contrast`, panel timing and VCOM. `dfu-util` alone leaves SPI flash untouched. `glider-config-backup.txt` holds a `setcfg get` dump for restoring those by hand if needed.

The BOOT0 button runs the STM32's mask-ROM bootloader, which no flash operation can overwrite — a bad MCU image is always recoverable by re-entering DFU and reflashing.

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
