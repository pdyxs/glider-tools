#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------- Config ----------
GLIDER_PY      := "C:\Users\pdyxs\dev\glider\glider.py"
DASUNG_PY      := "C:\Users\pdyxs\dev\glider\dasung253.py"
PYTHON         := "pythonw"                ; no console flash on every hotkey
GLIDER_PNP_MATCH := "ZPR0001"             ; stable Glider EDID manufacturer+product code
DASUNG_NAME_MATCH := "Paperlike"          ; substring of Dasung monitor DeviceString

LEVEL_STEP := 0.03
LEVEL_MIN  := -0.30
LEVEL_MAX  :=  0.30

THRESHOLD_MIN     := 1
THRESHOLD_MAX     := 9
THRESHOLD_DEFAULT := 5

STATE_FILE := A_ScriptDir . "\glider-state.ini"
KNOWN_MODES := [1, 2, 3, 4, 5, 6, 7]

; ---------- State ----------
global gliderDisplay   := ""
global dasungDisplay   := ""
global currentLevel    := 0.0
global currentMode     := ""
global modeLevel       := Map()
global gliderInverted  := false
global dasungThreshold := 5
global dasungInverted  := false

; ---------- Startup ----------
LoadState()
DetectGlider()
DetectDasung()

if gliderDisplay = ""
    ShowTip("Glider not detected. Hotkeys won't work until plugged in. Press Ctrl+Shift+F12 to retry.")
else
    ShowTip("Glider: " . gliderDisplay)

if dasungDisplay = ""
    ShowTip("Dasung not detected. Press Alt+Shift+F12 to retry.")
else
    ShowTip("Dasung: " . dasungDisplay)

OnExit(ResetAllGamma)

; ---------- Display detection ----------

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

DetectDasung() {
    global dasungDisplay, DASUNG_NAME_MATCH
    dasungDisplay := ""

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
            monDeviceString := StrGet(monitor.Ptr + 68, 128, "UTF-16")
            if InStr(monDeviceString, DASUNG_NAME_MATCH) {
                dasungDisplay := deviceName
                return
            }
        }
    }
}

; ---------- Persistence ----------

LoadState() {
    global modeLevel, KNOWN_MODES, STATE_FILE
    global dasungThreshold, gliderInverted, dasungInverted, THRESHOLD_DEFAULT
    if !FileExist(STATE_FILE)
        return
    for mode in KNOWN_MODES {
        val := IniRead(STATE_FILE, "levels", "mode" . mode, "")
        if val != ""
            modeLevel[mode] := val + 0.0
    }
    dasungThreshold := IniRead(STATE_FILE, "dasung", "threshold", THRESHOLD_DEFAULT) + 0
    gliderInverted  := IniRead(STATE_FILE, "glider",  "inverted",  0) = "1"
    dasungInverted  := IniRead(STATE_FILE, "dasung",  "inverted",  0) = "1"
}

SaveModeLevel(mode, val) {
    global modeLevel, STATE_FILE
    modeLevel[mode] := val
    IniWrite(val, STATE_FILE, "levels", "mode" . mode)
}

SaveDasungState() {
    global STATE_FILE, dasungThreshold, dasungInverted
    IniWrite(dasungThreshold, STATE_FILE, "dasung", "threshold")
    IniWrite(dasungInverted ? 1 : 0, STATE_FILE, "dasung", "inverted")
}

SaveGliderInverted() {
    global STATE_FILE, gliderInverted
    IniWrite(gliderInverted ? 1 : 0, STATE_FILE, "glider", "inverted")
}

; ---------- Gamma ----------

; Build a 256*3 ushort ramp from a sine-based midtone lift: y = x + k*sin(pi*x).
; Pass invert:=true to flip the ramp (display inversion).
BuildLevelsRamp(k, invert := false) {
    static PI := 3.14159265358979
    ramp := Buffer(256 * 3 * 2, 0)
    loop 256 {
        i := A_Index - 1
        val := i / 255.0
        corrected := val + k * Sin(PI * val)
        if invert
            corrected := 1.0 - corrected
        if corrected > 1.0
            corrected := 1.0
        if corrected < 0.0
            corrected := 0.0
        v := Round(corrected * 65535)
        NumPut("UShort", v, ramp, i * 2)        ; R
        NumPut("UShort", v, ramp, i * 2 + 512)  ; G
        NumPut("UShort", v, ramp, i * 2 + 1024) ; B
    }
    return ramp
}

SetDisplayLevel(displayName, k, invert := false) {
    if displayName = ""
        return false
    hdc := DllCall("gdi32\CreateDCW", "WStr", "DISPLAY", "WStr", displayName, "Ptr", 0, "Ptr", 0, "Ptr")
    if !hdc
        return false
    ramp := BuildLevelsRamp(k, invert)
    ok := DllCall("gdi32\SetDeviceGammaRamp", "Ptr", hdc, "Ptr", ramp)
    DllCall("gdi32\DeleteDC", "Ptr", hdc)
    return ok
}

ApplyGliderGamma() {
    global gliderDisplay, currentLevel, gliderInverted
    return SetDisplayLevel(gliderDisplay, currentLevel, gliderInverted)
}

ApplyDasungGamma() {
    global dasungDisplay, dasungInverted
    return SetDisplayLevel(dasungDisplay, 0.0, dasungInverted)
}

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

; ---------- Helpers ----------

RunGlider(args) {
    Run(PYTHON . ' "' . GLIDER_PY . '" ' . args, , "Hide")
}

RunDasung(args) {
    Run(PYTHON . ' "' . DASUNG_PY . '" ' . args, , "Hide")
}

SwitchMode(mode, label) {
    global currentMode, currentLevel, modeLevel

    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)

    currentLevel := modeLevel.Has(mode) ? modeLevel[mode] : 0.0
    currentMode  := mode

    ApplyGliderGamma()
    RunGlider("setmode " . mode)
    ShowTip("Glider  mode " . mode . ": " . label . "  level=" . Round(currentLevel, 2)
        . (gliderInverted ? "  [inv]" : ""))
}

ShowTip(msg) {
    ToolTip(msg)
    SetTimer(() => ToolTip(), -1500)
}

; ---------- Hotkeys: Glider (Ctrl+Shift) ----------

^+1::SwitchMode(1, "16-level + error diffusion")
^+2::SwitchMode(2, "Binary")
^+3::SwitchMode(3, "Bayer (Browsing)")
^+4::SwitchMode(4, "Blue Noise (Watching)")
^+5::SwitchMode(5, "Fast Grey (Typing)")
^+6::SwitchMode(6, "Auto LUT (Reading)")
^+7::SwitchMode(7, "Auto LUT + error diffusion")

^+Space::(RunGlider("redraw"), ShowTip("Glider  redraw"))

^+=::{
    global currentLevel, currentMode
    currentLevel := Round(Min(currentLevel + LEVEL_STEP, LEVEL_MAX), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if ApplyGliderGamma()
        ShowTip("Glider  level " . currentLevel . "  (brighter)")
    else
        ShowTip("Glider not detected")
}

^+-::{
    global currentLevel, currentMode
    currentLevel := Round(Max(currentLevel - LEVEL_STEP, LEVEL_MIN), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if ApplyGliderGamma()
        ShowTip("Glider  level " . currentLevel . "  (darker)")
    else
        ShowTip("Glider not detected")
}

^+0::{
    global currentLevel, currentMode, gliderInverted
    currentLevel   := 0.0
    gliderInverted := false
    if currentMode != ""
        SaveModeLevel(currentMode, 0.0)
    SaveGliderInverted()
    ResetAllGamma()
    ShowTip("Glider  level reset")
}

^+\::{
    global gliderInverted
    gliderInverted := !gliderInverted
    SaveGliderInverted()
    if ApplyGliderGamma()
        ShowTip("Glider  " . (gliderInverted ? "inverted" : "normal"))
    else
        ShowTip("Glider not detected")
}

^+F12::{
    DetectGlider()
    DetectDasung()
    ShowTip(gliderDisplay != "" ? "Glider: " . gliderDisplay : "Glider not detected")
}

; ---------- Hotkeys: Dasung 253 (Alt+Shift) ----------

!+1::(RunDasung("setmode auto"),    ShowTip("Dasung  Auto mode"))
!+2::(RunDasung("setmode text"),    ShowTip("Dasung  Text mode"))
!+3::(RunDasung("setmode graphic"), ShowTip("Dasung  Graphic mode"))
!+4::(RunDasung("setmode video"),   ShowTip("Dasung  Video mode"))

!+Space::(RunDasung("refresh"), ShowTip("Dasung  refresh"))

!+=::{
    global dasungThreshold
    dasungThreshold := Min(dasungThreshold + 1, THRESHOLD_MAX)
    SaveDasungState()
    RunDasung("setthreshold " . dasungThreshold)
    ShowTip("Dasung  threshold " . dasungThreshold . "  (up)")
}

!+-::{
    global dasungThreshold
    dasungThreshold := Max(dasungThreshold - 1, THRESHOLD_MIN)
    SaveDasungState()
    RunDasung("setthreshold " . dasungThreshold)
    ShowTip("Dasung  threshold " . dasungThreshold . "  (down)")
}

!+0::{
    global dasungThreshold, dasungInverted
    dasungThreshold := THRESHOLD_DEFAULT
    dasungInverted  := false
    SaveDasungState()
    RunDasung("setthreshold " . dasungThreshold)
    ResetAllGamma()
    ShowTip("Dasung  reset")
}

!+\::{
    global dasungInverted
    dasungInverted := !dasungInverted
    SaveDasungState()
    if ApplyDasungGamma()
        ShowTip("Dasung  " . (dasungInverted ? "inverted" : "normal"))
    else
        ShowTip("Dasung not detected")
}

!+F12::{
    DetectGlider()
    DetectDasung()
    ShowTip(dasungDisplay != "" ? "Dasung: " . dasungDisplay : "Dasung not detected")
}
