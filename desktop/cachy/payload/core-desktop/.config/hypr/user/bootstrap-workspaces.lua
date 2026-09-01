for workspace = 1, 6 do
  hl.workspace_rule({
    workspace = tostring(workspace),
    monitor = PRIMARY_MONITOR,
    default = true,
    persistent = true,
  })
end
