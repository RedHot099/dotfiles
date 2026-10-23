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
        -- Match ruff.lineLength in VS Code.
        ruff = {
          init_options = {
            settings = {
              lineLength = 120,
            },
          },
        },
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

  -- <leader>p in Python: apply Ruff's lint fixes, sort imports, then format
  -- through the Ruff server, which knows the line length above.
  {
    "stevearc/conform.nvim",
    opts = {
      formatters_by_ft = {
        python = { "ruff_fix", "ruff_organize_imports", lsp_format = "last" },
      },
      formatters = {
        ruff_fix = { append_args = { "--line-length", "120" } },
        ruff_organize_imports = { append_args = { "--line-length", "120" } },
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
