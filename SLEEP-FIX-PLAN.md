# Glider Sleep/Wake Fix Plan

## Root cause

The Glider screen goes black during Windows sleep and requires physical unplug/replug to
recover. This is a confirmed firmware bug — USB suspend/resume callbacks (`tud_suspend_cb`,
`tud_resume_cb`) are not implemented in the latest upstream firmware, and `USBCMD_POWERUP`
/ `USBCMD_POWERDOWN` are unimplemented TODOs.

When the system sleeps, the Glider's MCU clears the e-ink panel but has no resume callback
to re-initialize it. Software resets (pnputil, PnP disable/enable) don't help because the
Caster FPGA ends up in a bad state that only a full hardware power cycle clears.

## Phase 1: Verify the flash process (do this first — it's the gate)

1. Run `python glider.py usbboot` from Windows to put the STM32 into DFU bootloader mode
2. Route USB to WSL: `usbipd attach --wsl --busid <busid>` (device re-enumerates as DFU)
3. Flash the current firmware in WSL:
   ```bash
   sudo apt install dfu-util
   dfu-util -a 0 -i 0 -s 0x08000000:leave -D glider_ec_rtos.bin
   ```
4. Upload FPGA bitstream + resources via `utils/flash_tool/flash.py` (needs investigation —
   may require the full GUI flash_tool for this step)
5. Verify the device comes back and works normally

## Phase 2: Build environment

1. Install STM32CubeIDE (Windows GUI or WSL headless build mode)
2. Clone upstream with submodules: `git clone --recursive https://github.com/modos-labs/glider`
3. Build the firmware — produces `fw/Debug/glider_ec_rtos.bin`
4. Flash that binary via Phase 1 and confirm it works (proves our build matches the device)

## Phase 3: Implement USB suspend/resume

Changes to two files in the upstream firmware:

### `fw/User/usbapp.c` — add TinyUSB callbacks

```c
volatile bool glider_suspended = false;
volatile bool glider_resumed   = false;

void tud_suspend_cb(bool remote_wakeup_en) {
    (void)remote_wakeup_en;
    glider_suspended = true;
}

void tud_resume_cb(void) {
    glider_resumed = true;
}
```

### `fw/User/ui.c` — handle the flags in the main event loop

```c
if (glider_resumed) {
    glider_resumed   = false;
    glider_suspended = false;
    // Re-check FPGA health; restart if needed
    if (fpga_write_reg8(CSR_ID0, 0x00) != 0x35) {
        restart_fpga();
    }
    power_on_epd();
    caster_init();
    // trigger full redraw
}
```

Then: build → flash via Phase 1 → test sleep/wake.

## Key technical notes

- MCU: STM32H750, USB stack: TinyUSB
- Firmware built with STM32CubeIDE (Eclipse-based, not a plain Makefile)
- Flash: `dfu-util` for MCU firmware + custom HID protocol for FPGA bitstream/font/config
- `power_on_epd()` and `power_off_epd()` are already implemented — resume just needs to
  call them in the right order with an FPGA health check first
- The resume sequence may need more than `power_on_epd()` + `caster_init()` — test and
  iterate if the display doesn't come back cleanly
- Local WSL clone of upstream: `~/glider` (Ubuntu)
- Upstream repo: https://github.com/modos-labs/glider
