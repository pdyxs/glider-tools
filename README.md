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
| `Ctrl+Shift+F11` | Linux/GNOME: turn the Glider's output off for 3 s and restore it (recovers a black panel; see below) |
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

## Stale AUX polarity on DP re-selection (RULED OUT 2026-08-16)

> **This hypothesis is dead.** On 2026-08-16 a black-screen boot was captured with
> the fix's own log line present (`Syncing AUX polarity to CC polarity 0`) and the
> panel still blank — the pre-agreed disproof condition. The section is kept for the
> ruled-out evidence and for the `setinput` no-op trap, which is still true and still
> matters. For where the investigation actually stands, see
> [What the 2026-08-16 capture showed](#what-the-2026-08-16-capture-showed).

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

The tell is that the panel *flashes* on a mode change: the e-ink pipeline is alive and painting, and what it's painting is an empty framebuffer.

> **Correction (2026-08-16):** the conclusion originally drawn from that — "the video never arrived" — is **wrong**. A black-screen boot log shows the DP receiver locking at the correct timing (`Input status 3c, measured 1600 x 1200, total 1680 x 1242`). The video *does* arrive. The fault is downstream of the DP receiver, in the Caster/EPD render path.
>
> Also note the `redraw`/`setmode` row above proves less than it appears to: `caster_redraw()` and `caster_setmode()` just write FPGA registers and unconditionally `return 0` (`caster.c:95`, `caster.c:106`). Their SUCCESS says nothing about whether the panel updated.

### `setinput <same value>` is a no-op — this matters for testing

`USBCMD_SETINPUT` only writes `config.input_sel` and saves it (`usbapp.c:167`). The bring-up is driven from the UI loop, which acts on a **change**:

```c
if (previous_config.input_sel != config.input_sel) {
    apply_input_selection(&tmds_mode);
```

On a device already at `input_sel: 2`, `glider.py setinput 2` therefore returns SUCCESS while doing nothing at all — `apply_input_selection()` never runs.

`glider.py reinput` exists to avoid this trap: it bounces through another value (`setinput 0` → `setinput 2` → `redraw`) so the selection genuinely transitions. Use it instead of a bare `setinput` whenever the goal is to make the firmware *do* something.

**`reinput` leaves the device on its target input, saved to flash.** `SETINPUT` calls `config_save()`, so `reinput 0` persists `input_sel: 0` (Auto) — the setting the auto-detect problem above is about. Default is `2` (DP); pass another value only if you mean to change the device's resting state. To undo it, `setinput 2` on its own is enough, since `0` → `2` is a real change.

### Status: RULED OUT

`glider-fw-build` branch `fix-dp-aux-polarity` (`19648c7`) reads the live CC polarity from the FUSB302 on every DP input selection instead of trusting the cache. Flashed 2026-08-13.

The agreed test was: capture a black-screen boot and look for `Syncing AUX polarity to CC polarity N`. Line present + panel still blank → AUX polarity is not the cause. **On 2026-08-16 that is exactly what happened.** The fix is running and correct on its own terms; it simply does not fix this bug.

**Beware `ver` when checking what is flashed.** The device reports:

```
Version: 0.1 (Jul 25 2026 14:13:29)
Git: ed94ef7fd95a42cfdcdaf5e5da1dcdd709122763
```

`ed94ef7` is three commits *before* the AUX fix, so this looks like the old firmware — but it isn't. `setcfg get` exposes `lightness`/`contrast`, which only exist as of `ca6d766`, *after* that hash. **The version string is stale and does not track the build.** Confirm what's running from behaviour (a feature or log line the commit introduced), never from `ver`. The old advice here — "`ver` should not say `Jul 25 2026`" — was wrong and would have sent you to reflash working firmware.

`19648c7` also bounds two unbounded waits that could wedge the display pipeline task: the PTN3460 HPD wait (whose "timeout" only logged and never broke out) and the FPGA CSR poll in `restart_fpga()`. Those are worth keeping regardless.

## What the 2026-08-16 capture showed

First clean capture of a black-screen boot alongside a working boot from the same session (full logs: `logs/boot-black-2026-08-16.log`, `logs/boot-working-2026-08-16.log`).

**The headline result is negative, and it is the useful part: the failing boot log looks healthy.** Both boots reach the same final state — `Input status 3c` (`DP | STABLE | SUPPORTED | LIVE`), 1600x1200, total 1680x1242, all EPD rails in spec (VN -15.0, VGL -20.4, VP 14.7, VGH 25.2, VCOM -2.3), bitstream loaded, `FPGA started with status 21`. Nothing in the MCU's view of the world distinguishes the black boot from the working one.

That rules out a large class of theories at once. The MCU thinks everything worked, and by everything it can observe, it did. Whatever is wrong is in the FPGA's framebuffer or the Caster render path — state the MCU never inspects and never logs.

### The one structural difference: an HPD/pipeline ordering race (RULED OUT 2026-10-22)

Diffing the two, one ordering flips around `FPGA started with status 21` (`ui.c:701`, the last line of `start_display_pipeline()`):

| | Working boot | Black boot |
|---|---|---|
| `Syncing AUX polarity` | 1.748 | 1.748 |
| `DP enabled` (HPD high) | **1.750 — before** | 1.771 — **after**, +20 ms |
| `FPGA started with status 21` | 1.751 | 1.751 |
| First `Input status` | `3c` at 2.762 | `1c` at 2.752, then `3c` at 2.952 |

`DP enabled` (`usbpd.c:116`) is where the PD task sends HPD **high**, telling the host to start driving video. It runs in a *different FreeRTOS task* from `start_display_pipeline()`, so its position relative to `caster_init()` is genuinely racy — nothing sequences them.

In the working boot HPD goes high just *before* the pipeline finishes starting; in the black boot it lands 20 ms *after*. The black boot also passes through `1c` (no `INPUT_STATUS_LIVE`) for 200 ms before reaching `3c`, where the working boot goes straight to `3c`.

**Treat this as a lead, not a cause — it is one sample against one sample**, and a 20 ms shift could easily be noise. But it is the only structural difference in an otherwise identical pair, it is a real unsequenced cross-task race in the code, and a race explains the defining symptom (intermittent, cleared by replugging, never by software) better than any stale-state theory has.

Next step is to weight it: capture several boots of each kind and check whether the ordering correlates. `logs/` is the place to accumulate them.

### Still open, still unconfirmed

`start_display_pipeline()` never calls `apply_display_mode()` — see [Boot mode is tracked but never applied](#boot-mode-is-tracked-but-never-applied-unconfirmed-lead). That remains true and unfixed, but it is **not** the black-screen cause: on 2026-08-16, `setmode 2` followed by `redraw` did not recover a black panel. Only a physical replug did.

## HPD sequencing fix, and the first software recovery (2026-10-22)

### HPD-before-bridge-setup: RULED OUT

Both August logs contain **two** `DP enabled` lines. The first (~1.5 s) raised HPD as soon as DP alt mode was entered, because `displayport_suspended` started `false` (`usbpd.c:34`). About 200 ms later `apply_input_selection()` re-ran `ptn3460_init()`, reloading EDID emulation and rewriting the PTN3460's registers underneath a host that could be mid EDID read or link training. The second `DP enabled` was a high→high no-op.

`glider-fw-build` branch `fix-hpd-sequencing` fixes the ordering:

- `5d577aa` started DP suspended **and** dropped HPD around every `ptn3460_init()`. The second half caused a ~5 s loop: HPD low → host drops video → `Live video lost` → suspend → wake on input → pipeline restart → HPD low again (`logs/patched-hpd-loop-2026-10-22.log`). **Don't drop HPD on the wake/re-init path.**
- `1563040` keeps only the boot-time hold. Flashed 2026-10-22. The log confirms it works as designed: a single `DP enabled`, after the PTN3460 is configured.

**It doesn't fix the bug.** The second cold plug on `1563040` came up black (`logs/boot-1563040-black-2026-10-22.log`), with HPD correctly sequenced and `DP enabled` landing *before* `FPGA started`, the ordering that the August race lead associated with working boots. That rules out both the HPD-sequencing theory and the August ordering lead. `1563040` is harmless and stays flashed.

### A host-side output toggle recovers a black panel

On that black boot, disabling the Glider's output on the host for 3 s and re-enabling it (`gdctl set`, not persisted) brought the panel up. `python display.py reconnect` (hotkey `Ctrl+Shift+F11` in `eink-linux.py`) does this, saving and restoring the exact layout. **This is the first recovery that hasn't needed a physical replug.** `setmode`, `redraw` and `reinput` have never worked.

The toggle exercises both ends, so it doesn't yet say which one matters (`logs/host-toggle-after-black-2026-10-22.log`): the host does a full modeset and link retrain, and the Glider sees the video stop, runs `Live video lost`, reloads the FPGA, suspends, wakes on input and restarts the whole pipeline. One difference from every cold boot: on wake the video is **already present** when the pipeline comes up (first status `19`, then `3c`), whereas at plug-in the pipeline starts with no video (`01`) and the host's stream arrives about 1.2 s later.

Failures also split about 50/50 between a black panel and the firmware's "No Signal" popup. No "No Signal" boot log has been captured yet.

### Upgraded to upstream 1.1.1 (2026-10-22)

None of the investigation above ran on upstream's 1.1 (2026-07-31) or 1.1.1 (2026-08-05) releases, though both predate it. 1.1.1 fixes the EDID, which is also loaded into the PTN3460 (video input byte `0x85` → `0x81`, valid unused standard timings, a range-limits descriptor). The Caster timing monitor now also checks the porches, and a new `CSR_INPUT_DEBUG` register is logged as `Input status XX debug YY`.

Now flashed: MCU `glider-fw-build` branch `glider-1.1.1-patched` (`5d826b9`: 1.1.1 plus lightness/contrast, the AUX sync, the standalone build and the boot-time HPD hold), and the release's `fpga-8bit-mono.bit`. The bitstream went over HID with the release's `flash.py --skip-mcu --no-config --no-fonts --bitstream fpga-8bit-mono.bit`; that's safe because `--no-config` skips the config prompt. `setcfg get` was identical before and after. The first boot came up with a picture (`logs/boot-1.1.1-ok-2026-10-22.log`). One good boot proves nothing on its own, so keep counting, and on a black screen save the log first: the `debug` byte is the new evidence.

### Reading the device's own log

The firmware logs the whole bring-up (`Requesting DP input`, `PTN3460 up after N ms`, `Syncing AUX polarity to CC polarity N`) over the USB serial shell on `/dev/ttyACM0` at 115200.

> **Correction (2026-10-22): `syslog` DOES drain on read.** `syslog_next()` (`syslog.c:171`)
> advances a global `tail_idx`, so each entry is returned exactly once. A second read
> straight after a full one returns nothing. **Save the first read to `logs/`; it's the
> only copy.** The 2026-08-16 correction below, which said the opposite, was wrong. Its
> point about the trailing `\n` still stands.

`shell_syslog` (`shell/shell_cmds.c:115`) is a **follow** loop — `tail -f`, not `cat`:

```c
do {
    line = syslog_next(ts, MAX_TS_LINE, lbuf, MAX_LOG_LINE);
    if (line) printf("%s %s\n", ts, line);
    c = term_getch(&ctx->t, TERM_INPUT_DONT_WAIT);
} while (c < 0);          // exits as soon as ANY byte arrives
```

It streams entries as they are produced and exits the moment a keypress arrives. The failure mode that created the myth: sending `syslog\r\n` writes a **trailing `\n` that is immediately consumed as that keypress**, so the loop prints roughly one entry and quits. Poll it in a loop and you get one line per invocation, which looks exactly like a buffer draining away.

**Send a bare `\r` and then keep the port quiet**, and the whole unread log is there, but only once:

```python
p = serial.Serial('/dev/ttyACM0', 115200, timeout=0.2)
p.write(b'syslog\r')      # bare CR - no trailing byte to end the follow loop
while ...:                # just read; do NOT write anything else
    buf += p.read(4096)
```

Because it follows, the useful workflow is the reverse of what was documented: attach *first* and leave it running, then trigger the path you want to watch from a second channel (HID commands via `glider.py` don't drop the USB connection; `reset` does). If you didn't, the boot sequence is still in the ring buffer until something reads it.

Other useful shell commands: `setcfg get`, `power status`, `ver` (but see the warning above — `ver`'s git hash is stale and misreports what's flashed).

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
