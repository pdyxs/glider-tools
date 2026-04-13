#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------- Config ----------
GLIDER_PY := "C:\Users\pdyxs\dev\glider\glider.py"
PYTHON    := "pythonw"                  ; pythonw = no console flash on every hotkey
GLIDER_PNP_MATCH := "ZPR0001"           ; stable Glider EDID manufacturer+product code

GAMMA_STEP := 0.1
GAMMA_MIN  := 0.4
GAMMA_MAX  := 2.5

STATE_FILE := A_ScriptDir . "\glider-state.ini"
KNOWN_MODES := [1, 2, 3, 4, 5, 6, 7]

; ---------- State ----------
global gliderDisplay := ""              ; e.g. "\\.\DISPLAY2", filled in by DetectGlider()
global currentGamma  := 1.0
global currentMode   := ""              ; last Glider mode number selected via hotkey
global modeGamma     := Map()           ; per-mode saved gamma: mode number -> gamma value

; ---------- Startup ----------
LoadState()
DetectGlider()
if gliderDisplay = ""
    ShowTip("Glider not detected. Gamma hotkeys won't work until it's plugged in. Press Ctrl+Shift+F12 to retry.")
else
    ShowTip("Glider: " . gliderDisplay)

OnExit(ResetAllGamma)

; ---------- Helpers ----------

; Walk the display chain looking for an ACTIVE adapter whose monitor PnP ID matches the Glider.
; DISPLAY_DEVICE struct: cb(4) + DeviceName[32*2] + DeviceString[128*2] + StateFlags(4) + DeviceID[128*2] + DeviceKey[128*2] = 840 bytes
; Offsets: DeviceName=4, StateFlags=324, DeviceID=328
DetectGlider() {
    global gliderDisplay
    gliderDisplay := ""

    DISPLAY_DEVICE_ACTIVE := 0x1

    idx := 0
    loop {
        adapter := Buffer(840, 0)
        NumPut("UInt", 840, adapter, 0)
        if !DllCall("user32\EnumDisplayDevicesW", "Ptr", 0, "UInt", idx, "Ptr", adapter, "UInt", 0)
            break
        idx++

        stateFlags := NumGet(adapter, 324, "UInt")
        if !(stateFlags & DISPLAY_DEVICE_ACTIVE)
            continue

        deviceName := StrGet(adapter.Ptr + 4, 32, "UTF-16")

        monitor := Buffer(840, 0)
        NumPut("UInt", 840, monitor, 0)
        if DllCall("user32\EnumDisplayDevicesW", "WStr", deviceName, "UInt", 0, "Ptr", monitor, "UInt", 0) {
            monDeviceID := StrGet(monitor.Ptr + 328, 128, "UTF-16")
            if InStr(monDeviceID, GLIDER_PNP_MATCH) {
                gliderDisplay := deviceName
                return
            }
        }
    }
}

RunGlider(args) {
    Run(PYTHON . ' "' . GLIDER_PY . '" ' . args, , "Hide")
}

; ---------- Persistence ----------

LoadState() {
    global modeGamma, KNOWN_MODES, STATE_FILE
    if !FileExist(STATE_FILE)
        return
    for mode in KNOWN_MODES {
        val := IniRead(STATE_FILE, "gamma", "mode" . mode, "")
        if val != ""
            modeGamma[mode] := val + 0.0
    }
}

SaveModeGamma(mode, val) {
    global modeGamma, STATE_FILE
    modeGamma[mode] := val
    IniWrite(val, STATE_FILE, "gamma", "mode" . mode)
}

; Switch Glider mode. Saves the current gamma against the outgoing mode, then
; restores (or defaults) the gamma for the incoming mode and applies it.
SwitchMode(mode, label) {
    global currentMode, currentGamma, modeGamma

    if currentMode != ""
        SaveModeGamma(currentMode, currentGamma)

    if modeGamma.Has(mode)
        currentGamma := modeGamma[mode]
    else
        currentGamma := 1.0

    currentMode := mode
    SetGliderGamma(currentGamma)
    RunGlider("setmode " . mode)
    ShowTip("Mode " . mode . ": " . label . "  gamma=" . Round(currentGamma, 2))
}

; Build a 256*3 ushort gamma ramp for the given gamma value.
BuildGammaRamp(gamma) {
    ramp := Buffer(256 * 3 * 2, 0)
    loop 256 {
        i := A_Index - 1
        val := i / 255.0
        corrected := val ** (1.0 / gamma)
        v := Round(corrected * 65535)
        if v > 65535
            v := 65535
        if v < 0
            v := 0
        NumPut("UShort", v, ramp, i * 2)          ; R
        NumPut("UShort", v, ramp, i * 2 + 512)    ; G
        NumPut("UShort", v, ramp, i * 2 + 1024)   ; B
    }
    return ramp
}

; Apply a gamma ramp to one specific display (e.g. "\\.\DISPLAY1").
SetDisplayGamma(displayName, gamma) {
    if displayName = ""
        return false
    hdc := DllCall("gdi32\CreateDCW", "WStr", "DISPLAY", "WStr", displayName, "Ptr", 0, "Ptr", 0, "Ptr")
    if !hdc
        return false
    ramp := BuildGammaRamp(gamma)
    ok := DllCall("gdi32\SetDeviceGammaRamp", "Ptr", hdc, "Ptr", ramp)
    DllCall("gdi32\DeleteDC", "Ptr", hdc)
    return ok
}

SetGliderGamma(gamma) {
    global gliderDisplay
    return SetDisplayGamma(gliderDisplay, gamma)
}

; Reset gamma to 1.0 on every currently-active display. Safety net for the case where
; the Glider was disconnected after adjustment, or a ramp leaked to a different output.
ResetAllGamma(*) {
    DISPLAY_DEVICE_ACTIVE := 0x1
    idx := 0
    loop {
        adapter := Buffer(840, 0)
        NumPut("UInt", 840, adapter, 0)
        if !DllCall("user32\EnumDisplayDevicesW", "Ptr", 0, "UInt", idx, "Ptr", adapter, "UInt", 0)
            break
        idx++
        stateFlags := NumGet(adapter, 324, "UInt")
        if !(stateFlags & DISPLAY_DEVICE_ACTIVE)
            continue
        deviceName := StrGet(adapter.Ptr + 4, 32, "UTF-16")
        SetDisplayGamma(deviceName, 1.0)
    }
}

ShowTip(msg) {
    ToolTip(msg)
    SetTimer(() => ToolTip(), -1500)
}

; ---------- Hotkeys ----------

; Modes (see fw/User/caster.h for values)
^+1::SwitchMode(1, "16-level + error diffusion")
^+2::SwitchMode(2, "Binary")
^+3::SwitchMode(3, "Bayer (Browsing)")
^+4::SwitchMode(4, "Blue Noise (Watching)")
^+5::SwitchMode(5, "Fast Grey (Typing)")
^+6::SwitchMode(6, "Auto LUT (Reading)")
^+7::SwitchMode(7, "Auto LUT + error diffusion")

; Redraw
^+Space::(RunGlider("redraw"), ShowTip("Redraw"))

; Gamma: + darker, - lighter, 0 reset
^+=::{
    global currentGamma, currentMode
    currentGamma := Round(Min(currentGamma + GAMMA_STEP, GAMMA_MAX), 2)
    if currentMode != ""
        SaveModeGamma(currentMode, currentGamma)
    if SetGliderGamma(currentGamma)
        ShowTip("Gamma: " . currentGamma . "  (brighter)")
    else
        ShowTip("Gamma failed (Glider not detected?)")
}
^+-::{
    global currentGamma, currentMode
    currentGamma := Round(Max(currentGamma - GAMMA_STEP, GAMMA_MIN), 2)
    if currentMode != ""
        SaveModeGamma(currentMode, currentGamma)
    if SetGliderGamma(currentGamma)
        ShowTip("Gamma: " . currentGamma . "  (darker)")
    else
        ShowTip("Gamma failed (Glider not detected?)")
}
^+0::{
    global currentGamma, currentMode
    currentGamma := 1.0
    if currentMode != ""
        SaveModeGamma(currentMode, 1.0)
    ResetAllGamma()
    if currentMode != ""
        ShowTip("Gamma reset for mode " . currentMode)
    else
        ShowTip("Gamma reset (all displays)")
}

; Re-detect Glider display (use after plugging/unplugging monitors)
^+F12::{
    DetectGlider()
    if gliderDisplay = ""
        ShowTip("Glider not detected")
    else
        ShowTip("Glider: " . gliderDisplay)
}
