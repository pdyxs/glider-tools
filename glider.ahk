#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------- Config ----------
GLIDER_PY := "C:\Users\pdyxs\dev\glider\glider.py"
PYTHON    := "pythonw"                  ; pythonw = no console flash on every hotkey
GLIDER_PNP_MATCH := "ZPR0001"           ; stable Glider EDID manufacturer+product code

; Levels curve: y = x + k * sin(pi * x). k=0 is identity, k>0 lifts midtones
; (lighter), k<0 drops them (darker). Endpoints (black/white) are always
; anchored because sin(0)=sin(pi)=0. Keep |k| <= ~0.3 for monotonic output.
LEVEL_STEP := 0.03
LEVEL_MIN  := -0.30
LEVEL_MAX  := 0.30

STATE_FILE := A_ScriptDir . "\glider-state.ini"
KNOWN_MODES := [1, 2, 3, 4, 5, 6, 7]

; ---------- State ----------
global gliderDisplay := ""              ; e.g. "\\.\DISPLAY2", filled in by DetectGlider()
global currentLevel  := 0.0             ; sine-curve midtone lift: 0 = neutral
global currentMode   := ""              ; last Glider mode number selected via hotkey
global modeLevel     := Map()           ; per-mode saved level: mode number -> level value

; ---------- Startup ----------
LoadState()
DetectGlider()
if gliderDisplay = ""
    ShowTip("Glider not detected. Level hotkeys won't work until it's plugged in. Press Ctrl+Shift+F12 to retry.")
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
    global modeLevel, KNOWN_MODES, STATE_FILE
    if !FileExist(STATE_FILE)
        return
    for mode in KNOWN_MODES {
        val := IniRead(STATE_FILE, "levels", "mode" . mode, "")
        if val != ""
            modeLevel[mode] := val + 0.0
    }
}

SaveModeLevel(mode, val) {
    global modeLevel, STATE_FILE
    modeLevel[mode] := val
    IniWrite(val, STATE_FILE, "levels", "mode" . mode)
}

; Switch Glider mode. Saves the current level against the outgoing mode, then
; restores (or defaults) the level for the incoming mode and applies it.
SwitchMode(mode, label) {
    global currentMode, currentLevel, modeLevel

    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)

    if modeLevel.Has(mode)
        currentLevel := modeLevel[mode]
    else
        currentLevel := 0.0

    currentMode := mode
    SetGliderLevel(currentLevel)
    RunGlider("setmode " . mode)
    ShowTip("Mode " . mode . ": " . label . "  level=" . Round(currentLevel, 2))
}

; Build a 256*3 ushort ramp from a sine-based midtone lift: y = x + k*sin(pi*x).
; Endpoints are anchored (sin(0)=sin(pi)=0), the bulge is centred at x=0.5.
BuildLevelsRamp(k) {
    static PI := 3.14159265358979
    ramp := Buffer(256 * 3 * 2, 0)
    loop 256 {
        i := A_Index - 1
        val := i / 255.0
        corrected := val + k * Sin(PI * val)
        if corrected > 1.0
            corrected := 1.0
        if corrected < 0.0
            corrected := 0.0
        v := Round(corrected * 65535)
        NumPut("UShort", v, ramp, i * 2)          ; R
        NumPut("UShort", v, ramp, i * 2 + 512)    ; G
        NumPut("UShort", v, ramp, i * 2 + 1024)   ; B
    }
    return ramp
}

; Apply a levels ramp to one specific display (e.g. "\\.\DISPLAY1").
SetDisplayLevel(displayName, k) {
    if displayName = ""
        return false
    hdc := DllCall("gdi32\CreateDCW", "WStr", "DISPLAY", "WStr", displayName, "Ptr", 0, "Ptr", 0, "Ptr")
    if !hdc
        return false
    ramp := BuildLevelsRamp(k)
    ok := DllCall("gdi32\SetDeviceGammaRamp", "Ptr", hdc, "Ptr", ramp)
    DllCall("gdi32\DeleteDC", "Ptr", hdc)
    return ok
}

SetGliderLevel(k) {
    global gliderDisplay
    return SetDisplayLevel(gliderDisplay, k)
}

; Reset levels to identity (k=0) on every currently-active display. Safety net for the
; case where the Glider was disconnected after adjustment, or a ramp leaked to another output.
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
        SetDisplayLevel(deviceName, 0.0)
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

; Levels: + lighter (lift midtones), - darker (drop midtones), 0 reset
^+=::{
    global currentLevel, currentMode
    currentLevel := Round(Min(currentLevel + LEVEL_STEP, LEVEL_MAX), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if SetGliderLevel(currentLevel)
        ShowTip("Level: " . currentLevel . "  (brighter)")
    else
        ShowTip("Level failed (Glider not detected?)")
}
^+-::{
    global currentLevel, currentMode
    currentLevel := Round(Max(currentLevel - LEVEL_STEP, LEVEL_MIN), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if SetGliderLevel(currentLevel)
        ShowTip("Level: " . currentLevel . "  (darker)")
    else
        ShowTip("Level failed (Glider not detected?)")
}
^+0::{
    global currentLevel, currentMode
    currentLevel := 0.0
    if currentMode != ""
        SaveModeLevel(currentMode, 0.0)
    ResetAllGamma()
    if currentMode != ""
        ShowTip("Level reset for mode " . currentMode)
    else
        ShowTip("Level reset (all displays)")
}

; Re-detect Glider display (use after plugging/unplugging monitors)
^+F12::{
    DetectGlider()
    if gliderDisplay = ""
        ShowTip("Glider not detected")
    else
        ShowTip("Glider: " . gliderDisplay)
}
