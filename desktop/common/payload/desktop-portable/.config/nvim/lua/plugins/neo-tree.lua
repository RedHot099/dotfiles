-- Explorer on the right with the VS Code explorer keys.
return {
  "nvim-neo-tree/neo-tree.nvim",
  opts = {
    window = {
      position = "right",
      mappings = {
        ["n"] = "add",
        ["N"] = "add_directory",
        ["r"] = "rename",
        ["d"] = "delete",
        ["c"] = "close_all_nodes",
      },
    },
    filesystem = {
      filtered_items = {
        hide_dotfiles = false,
        hide_gitignored = false,
      },
    },
  },
}
