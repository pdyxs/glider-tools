#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------- Config ----------
GLIDER_PY        := "C:\Users\pdyxs\dev\glider\glider.py"
MIRA_PY          := "C:\Users\pdyxs\dev\glider\mira.py"
DASUNG_PY        := "C:\Users\pdyxs\dev\glider\dasung253.py"
PYTHON           := "pythonw"                ; no console flash on every hotkey
GLIDER_PNP_MATCH := "ZPR0001"               ; stable Glider EDID manufacturer+product code
MIRA_NAME_MATCH  := "MIRA"                  ; substring of Mira monitor DeviceString
DASUNG_NAME_MATCH := "Paperlike"            ; substring of Dasung monitor DeviceString

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
global miraDisplay     := ""
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
DetectMira()
DetectDasung()

if gliderDisplay != ""
    ShowTip("Glider: " . gliderDisplay)
else if miraDisplay != ""
    ShowTip("Mira: " . miraDisplay)
else
    ShowTip("Glider/Mira not detected. Press Ctrl+Shift+F12 to retry.")

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

DetectMira() {
    global miraDisplay, MIRA_NAME_MATCH
    miraDisplay := ""

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
            if InStr(monDeviceString, MIRA_NAME_MATCH) {
                miraDisplay := deviceName
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

; Return the active e-ink display name (Glider preferred over Mira)
EinkDisplay() {
    global gliderDisplay, miraDisplay
    return gliderDisplay != "" ? gliderDisplay : miraDisplay
}

EinkLabel() {
    global gliderDisplay
    return gliderDisplay != "" ? "Glider" : "Mira"
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

ApplyEinkGamma() {
    global currentLevel, gliderInverted
    return SetDisplayLevel(EinkDisplay(), currentLevel, gliderInverted)
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

RunMira(args) {
    Run(PYTHON . ' "' . MIRA_PY . '" ' . args, , "Hide")
}

RunDasung(args) {
    Run(PYTHON . ' "' . DASUNG_PY . '" ' . args, , "Hide")
}

; Mira mode names (1-indexed to match hotkey numbers)
MiraModes := ["speed", "text", "image", "video", "read"]
MiraLabels := ["Speed", "Text", "Image", "Video", "Read"]

; Maps standard slot numbers to Glider firmware mode numbers
GliderFirmwareModes := Map(1, 3, 2, 2, 3, 5, 4, 4, 5, 6, 6, 7, 7, 1)

SwitchMode(mode, gliderLabel) {
    global currentMode, currentLevel, modeLevel, gliderDisplay, MiraModes, MiraLabels, GliderFirmwareModes

    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)

    currentLevel := modeLevel.Has(mode) ? modeLevel[mode] : 0.0
    currentMode  := mode

    ApplyEinkGamma()

    if gliderDisplay != "" {
        fwMode := GliderFirmwareModes.Has(mode) ? GliderFirmwareModes[mode] : mode
        RunGlider("setmode " . fwMode)
        ShowTip(EinkLabel() . "  mode " . mode . ": " . gliderLabel . "  level=" . Round(currentLevel, 2)
            . (gliderInverted ? "  [inv]" : ""))
    } else if miraDisplay != "" {
        if mode <= MiraModes.Length {
            RunMira("setmode " . MiraModes[mode])
            ShowTip("Mira  mode " . mode . ": " . MiraLabels[mode] . "  level=" . Round(currentLevel, 2)
                . (gliderInverted ? "  [inv]" : ""))
        }
    } else {
        ShowTip("No e-ink display detected")
    }
}

ShowTip(msg) {
    ToolTip(msg)
    SetTimer(() => ToolTip(), -1500)
}

; ---------- Hotkeys: Glider / Mira (Ctrl+Shift) ----------
; Keys 1-5: Glider modes 1-5 / Mira presets 1-5 (speed, text, image, video, read)
; Keys 6-7: Glider-only modes (no-op when Mira active)

^+1::SwitchMode(1, "Bayer (Speed)")
^+2::SwitchMode(2, "Binary (Text)")
^+3::SwitchMode(3, "Fast Grey (Graphic)")
^+4::SwitchMode(4, "Blue Noise (Video)")
^+5::SwitchMode(5, "Auto LUT (Read)")
^+6::SwitchMode(6, "Auto LUT + error diffusion")
^+7::SwitchMode(7, "16-level + error diffusion")

^+Space::{
    global gliderDisplay, miraDisplay
    if gliderDisplay != "" {
        RunGlider("redraw")
        ShowTip("Glider  redraw")
    } else if miraDisplay != "" {
        RunMira("refresh")
        ShowTip("Mira  refresh")
    } else {
        ShowTip("No e-ink display detected")
    }
}

^+=::{
    global currentLevel, currentMode, gliderInverted
    currentLevel := Round(Min(currentLevel + LEVEL_STEP, LEVEL_MAX), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if ApplyEinkGamma()
        ShowTip(EinkLabel() . "  level " . currentLevel . "  (" . (gliderInverted ? "darker" : "brighter") . ")")
    else
        ShowTip("No e-ink display detected")
}

^+-::{
    global currentLevel, currentMode, gliderInverted
    currentLevel := Round(Max(currentLevel - LEVEL_STEP, LEVEL_MIN), 3)
    if currentMode != ""
        SaveModeLevel(currentMode, currentLevel)
    if ApplyEinkGamma()
        ShowTip(EinkLabel() . "  level " . currentLevel . "  (" . (gliderInverted ? "brighter" : "darker") . ")")
    else
        ShowTip("No e-ink display detected")
}

^+0::{
    global currentLevel, currentMode, gliderInverted
    currentLevel   := 0.0
    gliderInverted := false
    if currentMode != ""
        SaveModeLevel(currentMode, 0.0)
    SaveGliderInverted()
    ResetAllGamma()
    ShowTip(EinkLabel() . "  level reset")
}

^+\::{
    ; Toggle Windows dark/light mode (e-ink screens look better in dark mode)
    isLight := RegRead("HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 1)
    if isLight {
        Run('C:\Users\pdyxs\Desktop\Force Dark  Mode.lnk', , "Hide")
        ShowTip(EinkLabel() . "  dark mode")
    } else {
        Run('C:\Users\pdyxs\Desktop\Force Light Mode.lnk', , "Hide")
        ShowTip(EinkLabel() . "  light mode")
    }
}

^+F12::{
    DetectGlider()
    DetectMira()
    DetectDasung()
    if gliderDisplay != ""
        ShowTip("Glider: " . gliderDisplay)
    else if miraDisplay != ""
        ShowTip("Mira: " . miraDisplay)
    else
        ShowTip("No e-ink display detected")
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
    DetectMira()
    DetectDasung()
    ShowTip(dasungDisplay != "" ? "Dasung: " . dasungDisplay : "Dasung not detected")
}
