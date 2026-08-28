hl.config({
  input = {
    kb_layout = "pl",
    kb_model = "",
    kb_options = "ctrl:nocaps",
    repeat_rate = 40,
    repeat_delay = 600,
    numlock_by_default = true,
    accel_profile = "flat",
    sensitivity = 0,
    follow_mouse = 1,
    touchpad = {
      natural_scroll = true,
      scroll_factor = 0.4,
    },
  },
})

o.window("(Alacritty|kitty|foot)", { scroll_touchpad = 1.5 })
o.window("com.mitchellh.ghostty", { scroll_touchpad = 1.2 })
