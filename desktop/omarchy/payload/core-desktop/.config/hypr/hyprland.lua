dofile((os.getenv("OMARCHY_PATH") or "/usr/share/omarchy") .. "/default/hypr/bootstrap.lua")
require("default.hypr.omarchy")
require("hypr.monitors")
require("hypr.input")
require("hypr.bindings")
require("hypr.looknfeel")
require("hypr.autostart")
require("default.hypr.toggles")

o.window("^google-chrome$", { workspace = "1 silent" })
o.window("^com\\.t3tools\\.T3Code$", { workspace = "2 silent" })
o.window("^(Code|code)$", { workspace = "2 silent" })
o.window("^chrome-(www\\.)?youtube\\.com__.*$", { workspace = "3 silent" })
o.window("^(caprine|Caprine)$", { workspace = "4 silent" })
o.window("^chrome-web\\.whatsapp\\.com__.*$", { workspace = "4 silent" })
o.window("^(vesktop|Vesktop)$", { workspace = "4 silent" })
o.window("^steam$", { workspace = "5 silent" })
o.window("^chromium$", { workspace = "6 silent" })
-- Omarchy floats every Steam window; tile the main one, keep dialogs floating.
o.window({ class = "steam", title = "Steam" }, { float = false })
-- Big Picture opens as an oversized float (e.g. 2560x1600 on a 1080p panel).
o.window({ class = "^steam$", title = "^Steam Big Picture Mode$" }, { fullscreen = true })
-- Same share of the screen as 2200x1100 on the 3440x1440 ultrawide.
o.window("^org.omarchy.btop$", { size = { "(monitor_w*0.64)", "(monitor_h*0.76)" }, center = true })

-- GPU variables come from Omarchy's default/hypr/nvidia.lua, which detects the card.
hl.env("HYPRCURSOR_THEME", "Maverick Pointy Dark")
hl.env("XCURSOR_THEME", "Maverick Pointy Dark")
