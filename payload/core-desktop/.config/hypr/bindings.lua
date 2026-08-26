hl.unbind("SUPER + SHIFT + CTRL + A")

local home = os.getenv("HOME")

local function open_session_app(workspace, command)
  return function()
    hl.dispatch(hl.dsp.focus({ workspace = workspace }))
    hl.exec_cmd(command)
  end
end

local bindings = {
  { "SUPER + RETURN", "Terminal", "uwsm-app -- xdg-terminal-exec --dir=\"$(omarchy-cmd-terminal-cwd)\"" },
  { "SUPER + SHIFT + F", "File manager", "uwsm-app -- nautilus --new-window" },
  { "SUPER + B", "Browser", open_session_app("1", home .. "/.local/bin/start-session-chrome") },
  { "SUPER + SHIFT + RETURN", "Browser", open_session_app("1", home .. "/.local/bin/start-session-chrome") },
  { "SUPER + SHIFT + B", "Chromium", open_session_app("6", home .. "/.local/bin/start-session-chromium") },
  { "SUPER + ALT + B", "Browser (private)", "omarchy-launch-browser --private" },
  { "SUPER + SHIFT + M", "Music", "omarchy-launch-or-focus spotify" },
  { "SUPER + N", "VS Code", open_session_app("2", home .. "/.local/bin/start-session-code") },
  { "SUPER + SHIFT + N", "T3 Code", open_session_app("2", home .. "/.local/bin/start-session-t3") },
  { "SUPER + ALT + N", "Neovim", "omarchy-launch-tui nvim" },
  { "SUPER + SHIFT + T", "Activity", "omarchy-launch-tui btop" },
  { "SUPER + SHIFT + O", "Obsidian", "omarchy-launch-or-focus ^obsidian$ \"uwsm-app -- obsidian -disable-gpu --enable-wayland-ime\"" },
  { "SUPER + SHIFT + W", "Typora", "uwsm-app -- typora --enable-wayland-ime" },
  { "SUPER + SHIFT + S", "Screenshot", "omarchy capture screenshot" },
  { "SUPER + M", "Mute microphone", "omarchy-audio-input-mute" },
  { "SUPER + ALT + A", "Agent", "omarchy agent --pick" },
  { "SUPER + SHIFT + CTRL + A", "Switch audio output", "omarchy-audio-output-switch" },
  { "SUPER + A", "T3 Chat", "omarchy-launch-webapp \"https://t3.chat\"" },
  { "SUPER + SHIFT + A", "ChatGPT", "omarchy-launch-webapp \"https://chatgpt.com\"" },
  { "SUPER + SHIFT + C", "Calendar", "omarchy-launch-webapp \"https://calendar.google.com\"" },
  { "SUPER + E", "Email", "omarchy-launch-webapp \"https://mail.google.com\"" },
  { "SUPER + Y", "YouTube", open_session_app("3", home .. "/.local/bin/start-session-youtube") },
  { "SUPER + SHIFT + Y", "YouTube", open_session_app("3", home .. "/.local/bin/start-session-youtube") },
  { "SUPER + ALT + T", "Twitch Following Live", "omarchy-launch-webapp \"https://pl.twitch.tv/directory/following/live\"" },
  { "SUPER + SHIFT + ALT + G", "WhatsApp", open_session_app("4", "omarchy-launch-or-focus-webapp WhatsApp \"https://web.whatsapp.com/\"") },
  { "SUPER + SHIFT + CTRL + G", "WhatsApp", open_session_app("4", "omarchy-launch-or-focus-webapp WhatsApp \"https://web.whatsapp.com/\"") },
  { "SUPER + SHIFT + G", "Caprine", open_session_app("4", home .. "/.local/bin/start-session-caprine") },
  { "SUPER + SHIFT + P", "Google Photos", "omarchy-launch-or-focus-webapp \"Google Photos\" \"https://photos.google.com/\"" },
  { "SUPER + SHIFT + X", "X", "omarchy-launch-webapp \"https://x.com/\"" },
  { "SUPER + SHIFT + ALT + X", "X Post", "omarchy-launch-webapp \"https://x.com/compose/post\"" },
  { "SUPER + O", "Pop window out", "omarchy-hyprland-window-pop 2200 1100" },
  { "SUPER + PERIOD", "Snooze Google Calendar notification", "omarchy-shell notifications snoozeGoogleCalendar" },
}

for _, binding in ipairs(bindings) do
  hl.unbind(binding[1])
  o.bind(binding[1], binding[2], binding[3])
end

hl.unbind("SUPER + mouse:274")
o.bind("SUPER + mouse:274", "Snooze Google Calendar notification", "omarchy-shell notifications snoozeGoogleCalendar")
