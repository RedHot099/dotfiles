local session_apps = os.getenv("HOME") .. "/.config/hypr/autostart.d/session-apps.lua"
local file = io.open(session_apps, "r")
if file then
  file:close()
  dofile(session_apps)
end
