local assignments = {
  { class = "(google-chrome|Google-chrome)", workspace = "1" },
  { class = "(code|Code|dev.zed.Zed|cursor)", workspace = "2" },
  { class = "(t3code|T3Code)", workspace = "2" },
  { class = "(YouTube|youtube)", workspace = "3" },
  { class = "(Caprine|vesktop|signal)", workspace = "4" },
  { class = "(Spotify|spotify)", workspace = "5" },
  { class = "(chromium|Chromium)", workspace = "6" },
}

for _, assignment in ipairs(assignments) do
  hl.window_rule({
    match = { class = assignment.class },
    workspace = assignment.workspace,
  })
end
