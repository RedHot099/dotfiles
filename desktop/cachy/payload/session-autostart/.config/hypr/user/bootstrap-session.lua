hl.on("hyprland.start", function()
  hl.exec_cmd("systemctl --user start arch-hypr-session-apps.service")
end)
