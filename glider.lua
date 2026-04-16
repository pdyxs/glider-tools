-- glider.lua — Hammerspoon port of glider.ahk
-- Drop in ~/.hammerspoon/ and add `require("glider")` to ~/.hammerspoon/init.lua

-- ---------- Config ----------

-- Path to glider.py on this machine (edit if yours differs)
local GLIDER_PY = os.getenv("HOME") .. "/dev/glider/glider.py"

-- Python path: tries Homebrew (Apple Silicon, then Intel), falls back to system
local function findPython()
    for _, p in ipairs({
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    }) do
        if hs.fs.attributes(p) then return p end
    end
    return "/usr/bin/python3"
end
local PYTHON = findPython()

-- Glider reports a blank name on macOS (unlike Windows where it shows "Paper Monitor")
local GLIDER_NAME = ""

-- Levels curve: y = x + k * sin(π * x).
-- k=0 is identity; k>0 lifts midtones (lighter); k<0 drops them (darker).
-- Endpoints are always anchored because sin(0)=sin(π)=0.
-- Keep |k| <= ~0.3 for monotonic output.
local LEVEL_STEP = 0.03
local LEVEL_MIN  = -0.30
local LEVEL_MAX  =  0.30

local STATE_FILE = os.getenv("HOME") .. "/.glider-state.json"

-- ---------- State ----------

local gliderScreen = nil   -- hs.screen object for the Glider, or nil
local currentLevel = 0.0   -- sine-curve midtone lift: 0 = neutral
local currentMode  = nil   -- last mode number selected via hotkey (integer or nil)
local modeLevel    = {}    -- per-mode saved level: tostring(mode) -> number

-- ---------- Persistence ----------

local function loadState()
    local f = io.open(STATE_FILE, "r")
    if not f then return end
    local content = f:read("*all")
    f:close()
    local ok, data = pcall(hs.json.decode, content)
    if ok and data and type(data.modeLevel) == "table" then
        modeLevel = data.modeLevel
    end
end

local function saveState()
    local f = io.open(STATE_FILE, "w")
    if f then
        f:write(hs.json.encode({ modeLevel = modeLevel }, true))
        f:close()
    end
end

-- ---------- Helpers ----------

local function findGlider()
    gliderScreen = nil
    for _, s in ipairs(hs.screen.allScreens()) do
        if s:name() == GLIDER_NAME then
            gliderScreen = s
            break
        end
    end
    return gliderScreen ~= nil
end

local function runGlider(args)
    -- Fire-and-forget: no output needed for mode/redraw commands
    local t = hs.task.new(PYTHON, nil, function() end, args)
    t:start()
end

-- Build a 256-entry gamma ramp from the sine-based midtone lift.
-- Returns a 1-indexed table of floats [0.0, 1.0], same format hs.screen:setGamma() expects.
local function buildLevelsRamp(k)
    local ramp = {}
    for i = 0, 255 do
        local val = i / 255.0
        local corrected = val + k * math.sin(math.pi * val)
        ramp[i + 1] = math.max(0.0, math.min(1.0, corrected))
    end
    return ramp
end

local function setGliderLevel(k)
    if not gliderScreen then return false end
    local ramp = buildLevelsRamp(k)
    gliderScreen:setGamma(ramp, ramp, ramp)
    return true
end

-- Reset gamma to system default on every display.
-- Safety net: handles the case where the Glider is unplugged after adjustment
-- and a ramp "leaks" onto whatever display inherits its slot.
local function resetAllGamma()
    hs.screen.restoreGamma()
end

-- ---------- Mode switching ----------

local MODE_LABELS = {
    [1] = "16-level + error diffusion",
    [2] = "Binary",
    [3] = "Bayer (Browsing)",
    [4] = "Blue Noise (Watching)",
    [5] = "Fast Grey (Typing)",
    [6] = "Auto LUT (Reading)",
    [7] = "Auto LUT + error diffusion",
}

local function switchMode(mode)
    -- Save outgoing mode's level before switching
    if currentMode then
        modeLevel[tostring(currentMode)] = currentLevel
    end

    -- Restore incoming mode's saved level (default: 0)
    currentLevel = modeLevel[tostring(mode)] or 0.0
    currentMode = mode

    setGliderLevel(currentLevel)
    runGlider({ GLIDER_PY, "setmode", tostring(mode) })
    saveState()

    hs.alert.show(string.format("Mode %d: %s  level=%.2f", mode, MODE_LABELS[mode], currentLevel))
end

-- ---------- Startup ----------

loadState()

if findGlider() then
    hs.alert.show("Glider: " .. gliderScreen:name())
else
    hs.alert.show("Glider not detected. Level hotkeys won't work until plugged in.")
end

-- Reset gamma cleanly when Hammerspoon quits
hs.shutdownCallback = function()
    if currentMode then
        modeLevel[tostring(currentMode)] = currentLevel
        saveState()
    end
    resetAllGamma()
end

-- Re-detect automatically when display configuration changes (plug/unplug)
local screenWatcher = hs.screen.watcher.new(findGlider)
screenWatcher:start()

-- ---------- Hotkeys (Ctrl+Shift — matches Windows bindings) ----------

local M = { "ctrl", "shift" }

-- Mode switching
for mode = 1, 7 do
    hs.hotkey.bind(M, tostring(mode), function() switchMode(mode) end)
end

-- Redraw
hs.hotkey.bind(M, "space", function()
    runGlider({ GLIDER_PY, "redraw" })
    hs.alert.show("Redraw")
end)

-- Level: brighter (lift midtones)
hs.hotkey.bind(M, "=", function()
    currentLevel = math.min(currentLevel + LEVEL_STEP, LEVEL_MAX)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000  -- round to 3dp
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if setGliderLevel(currentLevel) then
        hs.alert.show(string.format("Level: %.2f  (brighter)", currentLevel))
    else
        hs.alert.show("Level failed (Glider not detected?)")
    end
end)

-- Level: darker (drop midtones)
hs.hotkey.bind(M, "-", function()
    currentLevel = math.max(currentLevel - LEVEL_STEP, LEVEL_MIN)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if setGliderLevel(currentLevel) then
        hs.alert.show(string.format("Level: %.2f  (darker)", currentLevel))
    else
        hs.alert.show("Level failed (Glider not detected?)")
    end
end)

-- Level: reset to neutral
hs.hotkey.bind(M, "0", function()
    currentLevel = 0.0
    if currentMode then modeLevel[tostring(currentMode)] = 0.0; saveState() end
    resetAllGamma()
    if currentMode then
        hs.alert.show("Level reset for mode " .. currentMode)
    else
        hs.alert.show("Level reset (all displays)")
    end
end)

-- Re-detect Glider manually (after plugging/unplugging monitors)
hs.hotkey.bind(M, "f12", function()
    if findGlider() then
        hs.alert.show("Glider: " .. gliderScreen:name())
    else
        hs.alert.show("Glider not detected")
    end
end)
