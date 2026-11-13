-- Workspaces that differ between machines. On a laptop T3 Code keeps
-- workspace 2 to itself, VS Code and Neovim take 3 and YouTube 5. On a
-- desktop VS Code and Neovim share 2 with T3 Code and YouTube takes 3.
-- start-session-code and start-session-youtube make the same choice.
local battery = io.popen("ls -d /sys/class/power_supply/BAT* 2>/dev/null")
local laptop = false
if battery then
  laptop = battery:read("*l") ~= nil
  battery:close()
end

if laptop then
  return { code = "3", youtube = "5" }
end
return { code = "2", youtube = "3" }
