-- glider.lua — Hammerspoon bindings for Modos Glider, ONYX Mira, and Dasung Paperlike 253
-- Drop in ~/.hammerspoon/ and add `require("glider")` to ~/.hammerspoon/init.lua

-- ---------- Config ----------

local GLIDER_PY = os.getenv("HOME") .. "/dev/glider/glider.py"
local MIRA_PY   = os.getenv("HOME") .. "/dev/glider/mira.py"
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
local MIRA_NAME   = "Mira133"

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
local miraScreen      = nil   -- hs.screen for the Mira, or nil
local dasungScreen    = nil   -- hs.screen for the Dasung 253, or nil

local currentLevel    = 0.0   -- Glider/Mira sine-curve midtone lift
local currentMode     = nil   -- last Glider/Mira mode number selected (integer or nil)
local modeLevel       = {}    -- per-mode saved level: tostring(mode) -> number
local gliderInverted  = false -- shared: applies to whichever e-ink screen is active

local dasungThreshold = THRESHOLD_DEFAULT
local dasungInverted  = false

-- Inversion loop tasks: persistent python processes that re-apply inverted gamma
-- at ~60 fps (macOS resets the gamma table periodically, so a single call doesn't hold)
local einkInvTask   = nil   -- inversion task for glider or mira (whichever is active)
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

local function findMira()
    miraScreen = nil
    for _, s in ipairs(hs.screen.allScreens()) do
        if s:name():find(MIRA_NAME) then
            miraScreen = s
            break
        end
    end
    return miraScreen ~= nil
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
    findMira()
    findDasung()
end

-- Returns the active e-ink screen (Glider preferred over Mira)
local function einkScreen()
    return gliderScreen or miraScreen
end

-- ---------- Helpers ----------

local function run(args)
    hs.task.new(PYTHON, nil, args):start()
end

-- Like hs.alert.show but replaces the previous "nudge" alert (level/threshold
-- adjustments) rather than stacking a new one on top.
local lastNudgeAlert = nil
local function nudgeAlert(msg)
    if lastNudgeAlert then hs.alert.closeSpecific(lastNudgeAlert) end
    lastNudgeAlert = hs.alert.show(msg)
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

local function invertLevelFile(screen)
    return os.getenv("HOME") .. "/.glider-invert-" .. tostring(screen:id())
end

local function writeInvertLevel(screen, level)
    local f = io.open(invertLevelFile(screen), "w")
    if f then f:write(tostring(level)); f:close() end
end

-- Start the inversion daemon for a screen. The daemon loops at ~60 fps re-applying
-- the inverted ramp; level updates are delivered by writing the level file.
local function startInvertLoop(screen, level)
    if not screen then return nil end
    writeInvertLevel(screen, level)
    local t = hs.task.new(PYTHON, nil,
        { GLIDER_PY, "invertloop", tostring(screen:id()), "--level", tostring(level) })
    t:start()
    return t
end

local function stopInvertLoop(task)
    if task then task:terminate() end
end

-- Apply e-ink (Glider or Mira) gamma. If inverted and daemon already running, just
-- update the level file — no process restart, no flash.
local function applyEinkGamma()
    local screen = einkScreen()
    if not screen then return false end
    if gliderInverted then
        if einkInvTask then
            writeInvertLevel(screen, currentLevel)
        else
            einkInvTask = startInvertLoop(screen, currentLevel)
        end
    else
        stopInvertLoop(einkInvTask)
        einkInvTask = nil
        run({ GLIDER_PY, "setlevel", tostring(screen:id()), tostring(currentLevel) })
    end
    return true
end

-- Apply Dasung inversion state (no level adjustment on the Dasung).
local function applyDasungGamma()
    if not dasungScreen then return false end
    if dasungInverted then
        if not dasungInvTask then
            dasungInvTask = startInvertLoop(dasungScreen, 0)
        end
    else
        stopInvertLoop(dasungInvTask)
        dasungInvTask = nil
    end
    return true
end

-- ---------- Glider mode switching ----------

local GLIDER_MODE_LABELS = {
    [1] = "Bayer (Speed)",
    [2] = "Binary (Text)",
    [3] = "Fast Grey (Graphic)",
    [4] = "Blue Noise (Video)",
    [5] = "Auto LUT (Read)",
    [6] = "Auto LUT + error diffusion",
    [7] = "16-level + error diffusion",
}

-- Maps standard slot numbers to Glider firmware mode numbers
local GLIDER_FIRMWARE_MODES = {
    [1] = 3,  -- Bayer
    [2] = 2,  -- Binary
    [3] = 5,  -- Fast Grey
    [4] = 4,  -- Blue Noise
    [5] = 6,  -- Auto LUT
    [6] = 7,  -- Auto LUT + error diffusion
    [7] = 1,  -- 16-level + error diffusion (broken)
}

-- Mira modes: 1=speed, 2=text, 3=image, 4=video, 5=read
local MIRA_MODES = { "speed", "text", "image", "video", "read" }
local MIRA_MODE_LABELS = {
    [1] = "Speed",
    [2] = "Text",
    [3] = "Image",
    [4] = "Video",
    [5] = "Read",
}

local function switchMode(mode)
    if currentMode then
        modeLevel[tostring(currentMode)] = currentLevel
    end
    currentLevel = modeLevel[tostring(mode)] or 0.0
    currentMode = mode
    applyEinkGamma()

    if gliderScreen then
        local fwMode = GLIDER_FIRMWARE_MODES[mode] or mode
        run({ GLIDER_PY, "setmode", tostring(fwMode) })
        hs.alert.show(string.format("Glider  mode %d: %s  level=%.2f%s",
            mode, GLIDER_MODE_LABELS[mode] or "?", currentLevel, gliderInverted and "  [inv]" or ""))
    elseif miraScreen then
        local modeName = MIRA_MODES[mode]
        if modeName then
            run({ MIRA_PY, "setmode", modeName })
            hs.alert.show(string.format("Mira  mode %d: %s  level=%.2f%s",
                mode, MIRA_MODE_LABELS[mode], currentLevel, gliderInverted and "  [inv]" or ""))
        end
    end
    saveState()
end

-- ---------- Startup ----------

loadState()
findScreens()

if gliderScreen then
    hs.alert.show("Glider detected")
    applyEinkGamma()
elseif miraScreen then
    hs.alert.show("Mira detected: " .. miraScreen:name())
    applyEinkGamma()
else
    hs.alert.show("Glider/Mira not detected. Hotkeys won't work until plugged in.")
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
    stopInvertLoop(einkInvTask)
    stopInvertLoop(dasungInvTask)
    resetAllGamma()
end

-- Restart invert loops with fresh display IDs when display config changes
local screenWatcher = hs.screen.watcher.new(function()
    findScreens()
    applyEinkGamma()
    applyDasungGamma()
end)
screenWatcher:start()

-- ---------- Hotkeys ----------

local G = { "ctrl", "shift" }   -- Glider / Mira (same keys, not used simultaneously)
local D = { "alt",  "shift" }   -- Dasung 253

-- Glider/Mira: mode switching
-- Glider has 7 modes; Mira has 5. Keys 1-5 work for both; 6-7 only apply to Glider.
for mode = 1, 7 do
    hs.hotkey.bind(G, tostring(mode), function()
        if gliderScreen then
            switchMode(mode)
        elseif miraScreen then
            if MIRA_MODES[mode] then switchMode(mode) end
        else
            hs.alert.show("No e-ink display detected")
        end
    end)
end

-- Glider/Mira: redraw / refresh
hs.hotkey.bind(G, "space", function()
    if gliderScreen then
        run({ GLIDER_PY, "redraw" })
        hs.alert.show("Glider  redraw")
    elseif miraScreen then
        run({ MIRA_PY, "refresh" })
        hs.alert.show("Mira  refresh")
    else
        hs.alert.show("No e-ink display detected")
    end
end)

-- Glider/Mira: gamma brighter
hs.hotkey.bind(G, "=", function()
    currentLevel = math.min(currentLevel + LEVEL_STEP, LEVEL_MAX)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if applyEinkGamma() then
        nudgeAlert(string.format("%s  level %.2f  (%s)",
            gliderScreen and "Glider" or "Mira", currentLevel,
            gliderInverted and "darker" or "brighter"))
    else
        hs.alert.show("No e-ink display detected")
    end
end)

-- Glider/Mira: gamma darker
hs.hotkey.bind(G, "-", function()
    currentLevel = math.max(currentLevel - LEVEL_STEP, LEVEL_MIN)
    currentLevel = math.floor(currentLevel * 1000 + 0.5) / 1000
    if currentMode then modeLevel[tostring(currentMode)] = currentLevel; saveState() end
    if applyEinkGamma() then
        nudgeAlert(string.format("%s  level %.2f  (%s)",
            gliderScreen and "Glider" or "Mira", currentLevel,
            gliderInverted and "brighter" or "darker"))
    else
        hs.alert.show("No e-ink display detected")
    end
end)

-- Glider/Mira: reset gamma and inversion
hs.hotkey.bind(G, "0", function()
    currentLevel   = 0.0
    gliderInverted = false
    stopInvertLoop(einkInvTask)
    einkInvTask = nil
    if currentMode then modeLevel[tostring(currentMode)] = 0.0; saveState() end
    resetAllGamma()
    hs.alert.show((gliderScreen and "Glider" or "Mira") .. "  level reset")
end)

-- Glider/Mira: toggle inversion
hs.hotkey.bind(G, "\\", function()
    gliderInverted = not gliderInverted
    saveState()
    if applyEinkGamma() then
        hs.alert.show((gliderScreen and "Glider" or "Mira") .. "  " .. (gliderInverted and "inverted" or "normal"))
    else
        hs.alert.show("No e-ink display detected")
    end
end)

-- Glider/Mira: re-detect
hs.hotkey.bind(G, "f12", function()
    findScreens()
    if gliderScreen then
        hs.alert.show("Glider detected: " .. gliderScreen:name())
    elseif miraScreen then
        hs.alert.show("Mira detected: " .. miraScreen:name())
    else
        hs.alert.show("No e-ink display detected")
    end
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
    nudgeAlert(string.format("Dasung  threshold %d  (up)", dasungThreshold))
end)

-- Dasung: threshold down
hs.hotkey.bind(D, "-", function()
    dasungThreshold = math.max(dasungThreshold - 1, THRESHOLD_MIN)
    saveState()
    runDasung({ "setthreshold", tostring(dasungThreshold) })
    nudgeAlert(string.format("Dasung  threshold %d  (down)", dasungThreshold))
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
