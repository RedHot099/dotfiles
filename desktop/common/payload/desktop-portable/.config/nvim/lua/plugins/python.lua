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

  -- Supermaven AI-powered code completion plugin
  {
    "supermaven-inc/supermaven-nvim",
    config = function()
      require("supermaven-nvim").setup({
        keymaps = {
          accept_suggestion = "<Tab>",
          clear_suggestion = "<C-]>",
          accept_word = "<C-j>",
        },
        disable_inline_completion = false,
        disable_keymaps = false,
        use_virtual_text = true,
      })
    end,
  },

  -- Add supermaven as a source to nvim-cmp (LazyVim uses 'cmp' plugin)
  {
    "hrsh7th/nvim-cmp",
    opts = function(_, opts)
      -- add supermaven source at the end of sources list
      table.insert(opts.sources, { name = "supermaven" })
    end,
  },
}
