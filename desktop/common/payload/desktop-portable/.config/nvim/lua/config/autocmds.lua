-- Autocmds are automatically loaded on the VeryLazy event
-- Default autocmds that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/autocmds.lua
--
-- Add any additional autocmds here
-- with `vim.api.nvim_create_autocmd`
--
-- Or remove existing autocmds by their group name (which is prefixed with `lazyvim_` for the defaults)
-- e.g. vim.api.nvim_del_augroup_by_name("lazyvim_wrap_spell")

-- Save when the editor loses focus, like files.autoSave = "onFocusChange" in VS Code.
vim.api.nvim_create_autocmd({ "FocusLost", "BufLeave", "WinLeave" }, {
  group = vim.api.nvim_create_augroup("autosave_on_focus_change", { clear = true }),
  callback = function(event)
    if vim.bo[event.buf].buftype == "" and vim.api.nvim_buf_get_name(event.buf) ~= "" then
      vim.api.nvim_buf_call(event.buf, function()
        vim.cmd("silent! update")
      end)
    end
  end,
})
