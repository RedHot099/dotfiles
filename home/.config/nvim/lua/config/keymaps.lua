-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
local map = vim.keymap.set
local opts = { noremap = true, silent = true }

if vim.g.vscode then
  -- VSCode Tab Navigation
  map("n", "<leader>h", "<Cmd>call VSCodeNotify('workbench.action.previousEditor')<CR>", opts)
  map("n", "<leader>l", "<Cmd>call VSCodeNotify('workbench.action.nextEditor')<CR>", opts)

  -- VSCode Pane Navigation
  map("n", "<leader>j", "<Cmd>call VSCodeNotify('workbench.action.focusBelowGroup')<CR>", opts)
  map("n", "<leader>k", "<Cmd>call VSCodeNotify('workbench.action.focusAboveGroup')<CR>", opts)
  map("n", "<leader>g", "<Cmd>call VSCodeNotify('workbench.action.focusLeftGroup')<CR>", opts)
  map("n", "<leader>;", "<Cmd>call VSCodeNotify('workbench.action.focusRightGroup')<CR>", opts)

  -- Open new editor splits
  map("n", "<leader>v", "<Cmd>call VSCodeNotify('workbench.action.splitEditorRight')<CR>", opts)
  map("n", "<leader>s", "<Cmd>call VSCodeNotify('workbench.action.splitEditorDown')<CR>", opts)

  -- Diagnostics Navigation
  map("n", "[d", "<Cmd>call VSCodeNotify('editor.action.marker.prev')<CR>", opts)
  map("n", "]d", "<Cmd>call VSCodeNotify('editor.action.marker.next')<CR>", opts)

  -- Code Action / Quick Fix
  map("n", "<leader>ca", "<Cmd>call VSCodeNotify('editor.action.quickFix')<CR>", opts)

  -- Format Document
  map("n", "<leader>p", "<Cmd>call VSCodeNotify('editor.action.formatDocument')<CR>", opts)

  -- Hover
  map("n", "gh", "<Cmd>call VSCodeNotify('editor.action.showDefinitionPreviewHover')<CR>", opts)

  -- Visual Mode
  map("v", "<", "<gv", opts)
  map("v", ">", ">gv", opts)
  map("v", "J", ":m '>+1<CR>gv=gv", opts)
  map("v", "K", ":m '<-2<CR>gv=gv", opts)
  map("v", "<leader>c", "<Cmd>call VSCodeNotifyVisual('editor.action.commentLine', 1)<CR>", opts)

  -- Do not open output when reverting
  map("n", "U", "<C-r>", opts)
end
