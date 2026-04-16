-- glider.lua — Hammerspoon bindings for Modos Glider and Dasung Paperlike 253
-- Drop in ~/.hammerspoon/ and add `require("glider")` to ~/.hammerspoon/init.lua

-- ---------- Config ----------

local GLIDER_PY = os.getenv("HOME") .. "/dev/glider/glider.py"
local DASUNG_PY = os.getenv("HOME") .. "/dev/glider/dasung253.py"

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

local THRESHOLD_MIN     = 1
local THRESHOLD_MAX     = 9
local THRESHOLD_DEFAULT = 5

local STATE_FILE = os.getenv("HOME") .. "/.glider-state.json"

-- ---------- State ----------

local gliderScreen    = nil   -- hs.screen for the Glider, or nil
local dasungScreen    = nil   -- hs.screen for the Dasung 253, or nil

local currentLevel    = 0.0   -- Glider sine-curve midtone lift
local currentMode     = nil   -- last Glider mode number selected (integer or nil)
local modeLevel       = {}    -- per-mode saved level: tostring(mode) -> number
local gliderInverted  = false

local dasungThreshold = THRESHOLD_DEFAULT
local dasungInverted  = false

-- Inversion loop tasks: persistent python processes that re-apply inverted gamma
-- at ~60 fps (macOS resets the gamma table periodically, so a single call doesn't hold)
local gliderInvTask = nil
local dasungInvTask = nil

-- ---------- Persistence ----------

local function loadState()
    local f = io.open(STATE_FILE, "r")
    if not f then return end
    local content = f:read("*all")
    f:close()
    local ok, data = pcall(hs.json.decode, content)
    if not (ok and data) then return end
    if type(data.modeLevel) == "table" then
        modeLevel = data.modeLevel
    end
    if type(data.dasungThreshold) == "number" then
        dasungThreshold = data.dasungThreshold
    end
    if type(data.gliderInverted) == "boolean" then
        gliderInverted = data.gliderInverted
    end
    if type(data.dasungInverted) == "boolean" then
        dasungInverted = data.dasungInverted
    end
end

local function saveState()
    local f = io.open(STATE_FILE, "w")
    if f then
        f:write(hs.json.encode({
            modeLevel       = modeLevel,
            dasungThreshold = dasungThreshold,
            gliderInverted  = gliderInverted,
            dasungInverted  = dasungInverted,
        }, true))
        f:close()
    end
end

-- ---------- Screen detection ----------

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

local function findDasung()
    dasungScreen = nil
    for _, s in ipairs(hs.screen.allScreens()) do
        if s:name():find("Paperlike") then
            dasungScreen = s
            break
        end
    end
    return dasungScreen ~= nil
end

local function findScreens()
    findGlider()
    findDasung()
end

-- ---------- Helpers ----------

local function run(args)
    hs.task.new(PYTHON, nil, args):start()
end

local function runDasung(cmdargs)
    local args = { DASUNG_PY }
    for _, v in ipairs(cmdargs) do table.insert(args, v) end
    run(args)
end

local function resetAllGamma()
    hs.screen.restoreGamma()
end

-- ---------- Gamma / inversion ----------

-- Start a persistent invertloop process for one display.
-- The loop re-applies the inverted ramp at ~60 fps to fight macOS periodically resetting it.
local function startInvertLoop(screen, level)
    if not screen then return nil end
    local t = hs.task.new(PYTHON, nil,
        { GLIDER_PY, "invertloop", tostring(screen:id()), "--level", tostring(level or 0) })
    t:start()
    return t
end

local function stopInvertLoop(task)
    if task then task:terminate() end
end

-- Apply the Glider's current level + inversion state. If inverted, restarts the loop
-- so a level change mid-inversion picks up the new level value.
local function applyGliderGamma()
    if not gliderScreen then return false end
    stopInvertLoop(gliderInvTask)
    gliderInvTask = nil
    if gliderInverted then
        gliderInvTask = startInvertLoop(gliderScreen, currentLevel)
    else
        run({ GLIDER_PY, "setlevel", tostring(gliderScreen:id()), tostring(currentLevel) })
    end
    return true
end

-- Apply the Dasung's inversion state (no level adjustment on the Dasung).
local function applyDasungGamma()
    if not dasungScreen then return false end
    stopInvertLoop(dasungInvTask)
    dasungInvTask = nil
    if dasungInverted then
        dasungInvTask = startInvertLoop(dasungScreen, 0)
    end
    return true
end

-- ---------- Glider mode switching ----------

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
    if currentMode then
        modeLevel[tostring(currentMode)] = currentLevel
    end
    currentLevel = modeLevel[tostring(mode)] or 0.0
    currentMode = mode
    applyGliderGamma()
    run({ GLIDER_PY, "setmode", tostring(mode) })
    saveState()
    hs.alert.show(string.format("Glider  mode %d: %s  level=%.2f%s",
        mode, MODE_LABELS[mode], currentLevel, gliderInverted and "  [inv]" or ""))
end

-- ---------- Startup ----------

loadState()
findScreens()

if gliderScreen then
    hs.alert.show("Glider detected")
    applyGliderGamma()
else
    hs.alert.show("Glider not detected. Hotkeys won't work until plugged in.")
end

if dasungScreen then
    hs.alert.show("Dasung detected: " .. dasungScreen:name())
    applyDasungGamma()
    -- Sync threshold from the monitor so our state matches reality
    hs.task.new(PYTHON, function(code, out, _)
        if code == 0 then
            local val = tonumber(out:match("^%s*(%d+)"))
            if val then dasungThreshold = val end
        end
    end, { DASUNG_PY, "getthreshold" }):start()
end

hs.shutdownCallback = function()
    if currentMode then
        modeLevel[tostring(currentMode)] = currentLevel
    end
    saveState()
    stopInvertLoop(gliderInvTask)
    stopInvertLoop(dasungInvTask)
    resetAllGamma()
end

-- Restart invert loops with fresh display IDs when display config changes
local screenWatcher = hs.screen.watcher.new(function()
    findScreens()
    applyGliderGamma()
    applyDasungGamma()
end)
screenWatcher:start()

-- ---------- Hotkeys ----------

local G = { "ctrl", "shift" }   -- Glider
local D = { "alt",  "shift" }   -- Dasung 253

-- Glider: mode switching (1–7)
for mode = 1, 7 do
    hs.hotkey.bind(G, tostring(mode), function() switchMode(mode) end)
end

-- Glider: redraw
hs.hotkey.bind(G, "space", function()
    run({ GLIDER_PY, "redraw" })
    hs.alert.show("Glider  redraw")
end)

-- Glider: gamma brighter
hs.hotkey.bind(G, "=", function()
    currentLevel = math.min(currentLevel + LEVEL_STEP, LEVEL_MAX)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if applyGliderGamma() then
        hs.alert.show(string.format("Glider  level %.2f  (brighter)", currentLevel))
    else
        hs.alert.show("Glider not detected")
    end
end)

-- Glider: gamma darker
hs.hotkey.bind(G, "-", function()
    currentLevel = math.max(currentLevel - LEVEL_STEP, LEVEL_MIN)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if applyGliderGamma() then
        hs.alert.show(string.format("Glider  level %.2f  (darker)", currentLevel))
    else
        hs.alert.show("Glider not detected")
    end
end)

-- Glider: reset gamma and inversion
hs.hotkey.bind(G, "0", function()
    currentLevel   = 0.0
    gliderInverted = false
    stopInvertLoop(gliderInvTask)
    gliderInvTask = nil
    if currentMode then modeLevel[tostring(currentMode)] = 0.0; saveState() end
    resetAllGamma()
    hs.alert.show("Glider  level reset")
end)

-- Glider: toggle inversion
hs.hotkey.bind(G, "\\", function()
    gliderInverted = not gliderInverted
    saveState()
    if applyGliderGamma() then
        hs.alert.show("Glider  " .. (gliderInverted and "inverted" or "normal"))
    else
        hs.alert.show("Glider not detected")
    end
end)

-- Glider: re-detect
hs.hotkey.bind(G, "f12", function()
    findScreens()
    hs.alert.show(gliderScreen and ("Glider detected: " .. gliderScreen:name()) or "Glider not detected")
end)

-- Dasung: mode switching (1=auto, 2=text, 3=graphic, 4=video)
local DASUNG_MODES  = { "auto", "text", "graphic", "video" }
local DASUNG_LABELS = { "Auto", "Text", "Graphic", "Video" }
for i, mode in ipairs(DASUNG_MODES) do
    hs.hotkey.bind(D, tostring(i), function()
        runDasung({ "setmode", mode })
        hs.alert.show("Dasung  " .. DASUNG_LABELS[i] .. " mode")
    end)
end

-- Dasung: threshold up
hs.hotkey.bind(D, "=", function()
    dasungThreshold = math.min(dasungThreshold + 1, THRESHOLD_MAX)
    saveState()
    runDasung({ "setthreshold", tostring(dasungThreshold) })
    hs.alert.show(string.format("Dasung  threshold %d  (up)", dasungThreshold))
end)

-- Dasung: threshold down
hs.hotkey.bind(D, "-", function()
    dasungThreshold = math.max(dasungThreshold - 1, THRESHOLD_MIN)
    saveState()
    runDasung({ "setthreshold", tostring(dasungThreshold) })
    hs.alert.show(string.format("Dasung  threshold %d  (down)", dasungThreshold))
end)

-- Dasung: reset threshold and inversion
hs.hotkey.bind(D, "0", function()
    dasungThreshold = THRESHOLD_DEFAULT
    dasungInverted  = false
    stopInvertLoop(dasungInvTask)
    dasungInvTask = nil
    saveState()
    runDasung({ "setthreshold", tostring(dasungThreshold) })
    resetAllGamma()
    hs.alert.show("Dasung  reset")
end)

-- Dasung: refresh (clear ghosting)
hs.hotkey.bind(D, "space", function()
    runDasung({ "refresh" })
    hs.alert.show("Dasung  refresh")
end)

-- Dasung: toggle inversion
hs.hotkey.bind(D, "\\", function()
    dasungInverted = not dasungInverted
    saveState()
    if applyDasungGamma() then
        hs.alert.show("Dasung  " .. (dasungInverted and "inverted" or "normal"))
    else
        hs.alert.show("Dasung not detected")
    end
end)

-- Dasung: re-detect serial port
hs.hotkey.bind(D, "f12", function()
    findScreens()
    hs.alert.show(dasungScreen and ("Dasung detected: " .. dasungScreen:name()) or "Dasung not detected")
end)
