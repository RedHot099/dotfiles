local launch = "uwsm app -- "
local home = os.getenv("HOME")

local binds = {
  { "SUPER + RETURN", launch .. TERMINAL },
  { "SUPER + SHIFT + F", launch .. FILE_MANAGER },
  { "SUPER + B", launch .. BROWSER },
  { "SUPER + N", launch .. "code" },
  { "SUPER + SHIFT + N", launch .. "t3code" },
  { "SUPER + SHIFT + M", launch .. "spotify" },
  { "SUPER + SHIFT + O", launch .. "obsidian" },
  { "SUPER + SHIFT + S", "noctalia msg screenshot-region" },
  { "SUPER + M", "noctalia msg mic-mute" },
  { "SUPER + ALT + A", home .. "/.local/bin/arch-hypr-agent" },
  { "SUPER + A", launch .. "google-chrome-stable --app=https://t3.chat" },
  { "SUPER + SHIFT + A", launch .. "google-chrome-stable --app=https://chatgpt.com" },
  { "SUPER + SHIFT + C", launch .. "google-chrome-stable --app=https://calendar.google.com" },
  { "SUPER + E", launch .. "google-chrome-stable --app=https://mail.google.com" },
  { "SUPER + Y", launch .. "google-chrome-stable --app=https://youtube.com" },
}

for _, bind in ipairs(binds) do
  hl.unbind(bind[1])
  hl.bind(bind[1], hl.dsp.exec_cmd(bind[2]))
end
