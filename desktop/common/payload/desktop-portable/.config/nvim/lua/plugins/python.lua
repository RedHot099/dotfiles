return {
  -- Enable Pyright and Ruff via LSP
  {
    "neovim/nvim-lspconfig",
    opts = {
      servers = {
        pyright = {
          settings = {
            python = {
              analysis = {
                diagnosticMode = "off",
              },
            },
          },
        },
        ruff = {},
      },
    },
  },

  -- Treesitter support for Python (and optionally others)
  {
    "nvim-treesitter/nvim-treesitter",
    opts = {
      ensure_installed = {
        "python",
        "bash",
        "lua",
        "json",
        "markdown",
        "markdown_inline",
        "vim",
        "yaml",
      },
    },
  },

  -- Mason: install tools automatically
  {
    "mason-org/mason.nvim",
    opts = {
      ensure_installed = {
        "pyright",
        "ruff",
        "black",
        "isort",
        "debugpy",
      },
    },
  },
}
