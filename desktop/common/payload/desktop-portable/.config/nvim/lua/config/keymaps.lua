-- Keymaps are automatically loaded on the VeryLazy event
-- Default keymaps that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/keymaps.lua
-- Add any additional keymaps here
local map = vim.keymap.set
local opts = { noremap = true, silent = true }

-- Shared by VS Code and Neovim
map("v", "<", "<gv", opts)
map("v", ">", ">gv", opts)
map("v", "J", ":m '>+1<CR>gv=gv", opts)
map("v", "K", ":m '<-2<CR>gv=gv", opts)
map("x", "<leader>c", "gc", { remap = true, desc = "Toggle Comment" })
-- Do not open output when reverting
map("n", "U", "<C-r>", opts)

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
  return
end

-- Neovim: the VS Code keybindings and leader keys, where LazyVim leaves them
-- free. <leader>g, <leader>s, and <leader>l stay LazyVim's git, search, and
-- Lazy groups.

-- Editors and windows
map("n", "<leader>h", "<Cmd>bprevious<CR>", { desc = "Previous Buffer" })
map("n", "<leader>j", "<C-w>j", { desc = "Window Below" })
map("n", "<leader>k", "<C-w>k", { desc = "Window Above" })
map("n", "<leader>;", "<C-w>l", { desc = "Window Right" })
map("n", "<leader>v", "<C-w>v", { desc = "Split Right" })
-- ctrl+w closes the editor below, so window commands stay under <leader>w.
map("n", "<leader>w", "<C-w>", { desc = "Windows" })
map("n", "<C-w>", function() Snacks.bufdelete() end, { desc = "Close Buffer" })

-- Code
map("n", "<leader>p", function() LazyVim.format({ force = true }) end, { desc = "Format Document" })
map("n", "gh", vim.lsp.buf.hover, { desc = "Hover" })
map("n", "<C-/>", "gcc", { remap = true, desc = "Toggle Comment" })
map("n", "<C-_>", "gcc", { remap = true, desc = "which_key_ignore" })
map("x", "<C-/>", "gc", { remap = true, desc = "Toggle Comment" })
map("x", "<C-_>", "gc", { remap = true, desc = "which_key_ignore" })

-- Quick Open and the Command Palette
map("n", "<C-p>", LazyVim.pick("files"), { desc = "Quick Open" })
map("n", "<C-S-p>", function() Snacks.picker.commands() end, { desc = "Command Palette" })

-- Find and replace in the current file
map("n", "<C-f>", function() Snacks.picker.lines() end, { desc = "Find" })
map("n", "<C-h>", function()
  require("grug-far").open({ prefills = { paths = vim.fn.expand("%") } })
end, { desc = "Replace" })

-- Navigation history
map("n", "<M-h>", "<C-o>", { desc = "Navigate Back" })
map("n", "<M-l>", "<C-i>", { desc = "Navigate Forward" })

-- Explorer, terminal, and zen mode
map("n", "<C-b>", "<Cmd>Neotree toggle<CR>", { desc = "Toggle Explorer" })
map("n", "<C-e>", function()
  vim.cmd(vim.bo.filetype == "neo-tree" and "Neotree close" or "Neotree focus")
end, { desc = "Focus Explorer" })
map({ "n", "t" }, "<C-S-j>", function() Snacks.terminal.toggle(nil, { cwd = LazyVim.root() }) end, { desc = "Toggle Terminal" })
map("t", "<C-S-w>", "<C-\\><C-n><Cmd>bdelete!<CR>", { desc = "Kill Terminal" })
map("n", "<C-'>", function() Snacks.zen() end, { desc = "Zen Mode" })

-- Git
map("n", "<C-S-g>", function() Snacks.lazygit({ cwd = LazyVim.root.git() }) end, { desc = "Source Control" })
map("n", "<C-M-g>", function() Snacks.picker.git_branches() end, { desc = "Git Checkout" })
