-- ctrl+] and gd go to the definition, and list the references when the cursor
-- is already on it, as Go to Definition does in VS Code.
local function definition_or_references()
  local win = vim.api.nvim_get_current_win()
  local buf = vim.api.nvim_get_current_buf()
  vim.lsp.buf_request_all(buf, "textDocument/definition", function(client)
    return vim.lsp.util.make_position_params(win, client.offset_encoding)
  end, function(results)
    local found = false
    for client_id, response in pairs(results) do
      local client = vim.lsp.get_client_by_id(client_id)
      local cursor = client and vim.lsp.util.make_position_params(win, client.offset_encoding).position
      local locations = client and response.result or {}
      if locations.uri or locations.targetUri then
        locations = { locations }
      end
      for _, location in ipairs(locations) do
        found = true
        local range = location.targetSelectionRange or location.range
        if
          (location.targetUri or location.uri) ~= vim.uri_from_bufnr(buf)
          or range.start.line ~= cursor.line
          or cursor.character < range.start.character
          or cursor.character > range["end"].character
        then
          vim.lsp.buf.definition()
          return
        end
      end
    end
    if found then
      -- Show the list even for a single reference instead of jumping to it.
      Snacks.picker.lsp_references({ auto_confirm = false })
    else
      vim.notify("No definition found", vim.log.levels.WARN)
    end
  end)
end

return {
  "neovim/nvim-lspconfig",
  opts = {
    servers = {
      ["*"] = {
        keys = {
          { "gd", definition_or_references, desc = "Goto Definition or References", has = "definition" },
          { "<C-]>", definition_or_references, desc = "Goto Definition or References", has = "definition" },
        },
      },
    },
  },
}
