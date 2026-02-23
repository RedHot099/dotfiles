-- bootstrap lazy.nvim, LazyVim and your plugins
require("config.lazy")
require("plugins.python")

vim.g.python3_host_prog = os.getenv("HOME") .. "/.pyenv/versions/nvim/bin/python"

vim.o.completeopt = "menuone,noselect"
