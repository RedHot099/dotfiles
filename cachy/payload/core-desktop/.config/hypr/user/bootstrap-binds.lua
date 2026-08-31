local launch = "uwsm app -- "
local noctalia = "noctalia msg "
local home = os.getenv("HOME")

local function bind(keys, dispatcher, options)
  hl.unbind(keys)
  hl.bind(keys, dispatcher, options)
end

local function command(keys, value, options)
  bind(keys, hl.dsp.exec_cmd(value), options)
end

local function open_on(workspace, value)
  return function()
    hl.dispatch(hl.dsp.focus({ workspace = workspace }))
    hl.exec_cmd(value)
  end
end

local function send_shortcut_once(mods, key)
  return function()
    hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "down" }))
    hl.timer(function()
      hl.dispatch(hl.dsp.send_key_state({ mods = mods, key = key, state = "up" }))
    end, { timeout = 50, type = "oneshot" })
  end
end

local function active_window_is_terminal()
  local window = hl.get_active_window()
  local class = window and (window.class or ""):lower() or ""
  return class:match("terminal") or class:match("alacritty") or class:match("kitty") or class:match("foot")
end

local function clipboard_shortcut(default_mods, default_key, terminal_mods, terminal_key)
  return function()
    if active_window_is_terminal() then
      send_shortcut_once(terminal_mods, terminal_key)()
    else
      send_shortcut_once(default_mods, default_key)()
    end
  end
end

bind("SUPER + W", hl.dsp.window.close())
bind("SUPER + J", hl.dsp.layout("togglesplit"))
bind("SUPER + P", hl.dsp.window.pseudo())
bind("SUPER + T", hl.dsp.window.float({ action = "toggle" }))
bind("SUPER + F", hl.dsp.window.fullscreen({ mode = "fullscreen" }))
bind("SUPER + ALT + F", hl.dsp.window.fullscreen({ mode = "maximized" }))
command("SUPER + O", "hyprctl dispatch togglefloating && hyprctl dispatch pin && hyprctl dispatch resizeactive exact 2200 1100 && hyprctl dispatch centerwindow")

for _, direction in ipairs({ "LEFT", "RIGHT", "UP", "DOWN" }) do
  local short = direction:sub(1, 1):lower()
  bind("SUPER + " .. direction, hl.dsp.focus({ direction = short }))
  bind("SUPER + SHIFT + " .. direction, hl.dsp.window.swap({ direction = short }))
end

for workspace = 1, 6 do
  local key = tostring(workspace)
  bind("SUPER + " .. key, hl.dsp.focus({ workspace = key }))
  bind("SUPER + SHIFT + " .. key, hl.dsp.window.move({ workspace = key }))
  bind("SUPER + SHIFT + ALT + " .. key, hl.dsp.window.move({ workspace = key, follow = false }))
end

bind("SUPER + S", hl.dsp.workspace.toggle_special("scratchpad"))
bind("SUPER + ALT + S", hl.dsp.window.move({ workspace = "special:scratchpad", follow = false }))
bind("SUPER + TAB", hl.dsp.focus({ workspace = "e+1" }))
bind("SUPER + SHIFT + TAB", hl.dsp.focus({ workspace = "e-1" }))
bind("SUPER + CTRL + TAB", hl.dsp.focus({ workspace = "previous" }))
bind("ALT + TAB", hl.dsp.window.cycle_next())
bind("ALT + SHIFT + TAB", hl.dsp.window.cycle_next({ next = false }))
bind("SUPER + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
bind("SUPER + mouse_up", hl.dsp.focus({ workspace = "e-1" }))
bind("SUPER + mouse:272", hl.dsp.window.drag(), { mouse = true })
bind("SUPER + mouse:273", hl.dsp.window.resize(), { mouse = true })

command("SUPER + RETURN", launch .. TERMINAL)
command("SUPER + SHIFT + F", launch .. FILE_MANAGER)
bind("SUPER + B", open_on("1", launch .. "google-chrome-stable"))
bind("SUPER + SHIFT + RETURN", open_on("1", launch .. "google-chrome-stable"))
bind("SUPER + SHIFT + B", open_on("6", launch .. "chromium"))
command("SUPER + ALT + B", launch .. "google-chrome-stable --incognito")
bind("SUPER + N", open_on("2", launch .. "code"))
bind("SUPER + SHIFT + N", open_on("2", launch .. "t3code"))
command("SUPER + ALT + N", launch .. TERMINAL .. " -e nvim")
command("SUPER + SHIFT + T", launch .. TERMINAL .. " -e btop")
command("SUPER + SHIFT + M", launch .. "spotify")
command("SUPER + SHIFT + O", launch .. "obsidian --disable-gpu --enable-wayland-ime")
bind("SUPER + SHIFT + G", open_on("4", launch .. "caprine"))
command("SUPER + ALT + A", home .. "/.local/bin/arch-hypr-agent")

local webapps = {
  { "SUPER + A", "https://t3.chat" },
  { "SUPER + SHIFT + A", "https://chatgpt.com" },
  { "SUPER + SHIFT + C", "https://calendar.google.com" },
  { "SUPER + E", "https://mail.google.com" },
  { "SUPER + Y", "https://youtube.com" },
  { "SUPER + SHIFT + Y", "https://youtube.com" },
  { "SUPER + ALT + T", "http://pl.twitch.tv/directory/following/live" },
  { "SUPER + SHIFT + ALT + G", "https://web.whatsapp.com/" },
  { "SUPER + SHIFT + CTRL + G", "https://web.whatsapp.com/" },
  { "SUPER + SHIFT + P", "https://photos.google.com/" },
  { "SUPER + SHIFT + X", "https://x.com/" },
  { "SUPER + SHIFT + ALT + X", "https://x.com/compose/post" },
}
for _, item in ipairs(webapps) do
  command(item[1], launch .. "google-chrome-stable --app=" .. item[2])
end

command("SUPER + SPACE", noctalia .. "panel-toggle launcher")
command("SUPER + ALT + SPACE", noctalia .. "panel-toggle launcher")
command("SUPER + CTRL + E", noctalia .. "panel-toggle launcher /emo")
command("SUPER + CTRL + V", noctalia .. "panel-toggle clipboard")
command("SUPER + ESCAPE", noctalia .. "panel-toggle session")
command("SUPER + K", noctalia .. "settings-toggle")
command("SUPER + CTRL + A", noctalia .. "panel-toggle control-center")
command("SUPER + CTRL + B", noctalia .. "panel-toggle control-center")
command("SUPER + CTRL + D", noctalia .. "panel-toggle control-center")
command("SUPER + CTRL + W", noctalia .. "panel-toggle control-center")
command("SUPER + CTRL + P", noctalia .. "panel-toggle session")
command("SUPER + CTRL + T", launch .. TERMINAL .. " -e btop")
command("SUPER + CTRL + L", noctalia .. "session lock")
bind("SUPER + C", clipboard_shortcut("CTRL", "C", "CTRL", "Insert"))
bind("SUPER + V", clipboard_shortcut("CTRL", "V", "SHIFT", "Insert"))
bind("SUPER + X", send_shortcut_once("CTRL", "X"))

local bar_panels = {
  "control-center media",
  "control-center notifications",
  "control-center bluetooth",
  "control-center network",
  "control-center audio",
  "control-center brightness",
  "control-center battery",
  "session",
}
for panel, target in ipairs(bar_panels) do
  hl.unbind("SUPER + CONTROL + " .. tostring(panel))
  command("SUPER + CTRL + code:" .. tostring(panel + 9), noctalia .. "panel-toggle " .. target)
end

command("PRINT", noctalia .. "screenshot-region")
command("SUPER + SHIFT + S", noctalia .. "screenshot-region")
command("SUPER + PRINT", "pkill hyprpicker || hyprpicker -a")
command("SUPER + M", noctalia .. "mic-mute")
command("XF86AudioRaiseVolume", noctalia .. "volume-up", { locked = true, repeating = true })
command("XF86AudioLowerVolume", noctalia .. "volume-down", { locked = true, repeating = true })
command("XF86AudioMute", noctalia .. "volume-mute", { locked = true })
command("XF86AudioMicMute", noctalia .. "mic-mute", { locked = true })
command("XF86AudioPlay", noctalia .. "media toggle", { locked = true })
command("XF86AudioPause", noctalia .. "media toggle", { locked = true })
command("XF86AudioNext", noctalia .. "media next", { locked = true })
command("XF86AudioPrev", noctalia .. "media previous", { locked = true })
command("XF86MonBrightnessUp", noctalia .. "brightness-up", { locked = true, repeating = true })
command("XF86MonBrightnessDown", noctalia .. "brightness-down", { locked = true, repeating = true })
