hl.env("GDK_SCALE", "2")
hl.monitor({ output = "HDMI-A-1", mode = "3440x1440@174.96", position = "0x0", scale = 1 })

hl.config({
  general = {
    gaps_in = 2,
    gaps_out = 2,
    border_size = 1,
    layout = "dwindle",
  },
  dwindle = {
    preserve_split = true,
    force_split = 2,
  },
})

hl.workspace_rule({
  workspace = "w[t1]",
  gaps_out = { top = 2, right = 343, bottom = 2, left = 343 },
})
