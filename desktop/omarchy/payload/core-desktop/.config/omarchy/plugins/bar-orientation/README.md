# bar-orientation

An Omarchy shell service that keeps one bar widget layout for the horizontal
bar and another for the vertical bar. When you move the bar between a
horizontal edge (top, bottom) and a vertical edge (left, right), the layout
saved for the new orientation replaces `bar.layout`. Rearranging widgets on
either edge updates that orientation's saved layout.

It comes with `bar-orientation-tray`, a copy of Omarchy's system tray that can
open its drawer downward on a vertical bar. It works with Omarchy 4 and needs
`bash` and `jq`.

## Install

Copy both directories, then load and enable the plugins:

```bash
cp -r bar-orientation bar-orientation-tray ~/.config/omarchy/plugins/
omarchy-shell shell rescanPlugins
omarchy plugin enable bar-orientation
omarchy plugin enable bar-orientation-tray
```

The two are separate plugins because Omarchy keeps a service's settings in
`plugins[]` and a bar widget's settings in its `bar.layout` entry. The tray is
a clone of `omarchy.tray`, so enabling it replaces the built-in tray.

Enabling adds `{ "id": "bar-orientation" }` to `plugins[]` in
`~/.config/omarchy/shell.json`. The first sync saves the current layout for
the current orientation. Move the bar to a side edge, arrange the widgets, and
move it back: each orientation now keeps its own layout.

You can also seed the other orientation's layout by hand:

```json
{
  "id": "bar-orientation",
  "layouts": {
    "vertical": { "left": [], "center": [], "right": [] }
  }
}
```

On a vertical bar, `left` is the top section and `right` is the bottom section.

## Tray

`bar-orientation-tray` behaves like the built-in tray. On a vertical bar the
built-in tray puts its chevron above the pinned icons and slides the drawer
upward. Set `revealDown` on the tray's layout entry to mirror it: pinned icons
first, then a downward chevron, then the drawer. Use it when the tray ends the
top section of a vertical bar:

```json
{ "id": "bar-orientation-tray", "revealDown": true }
```

Pinning or hiding an icon keeps `revealDown` and any other setting on the
entry. The tray code is Omarchy's `omarchy.tray` (MIT) with these two changes.

## Behaviour

- The plugin stores `orientation` and `layouts.{horizontal,vertical}` on its
  own `plugins[]` entry.
- It writes `shell.json` atomically and then runs
  `omarchy-shell shell reloadConfig`.
- It never writes when its entry is missing or the file is not valid JSON, so
  a half-written file cannot be replaced with the packaged defaults.

Third-party services cannot rewrite the bar through the shell API, so the
service watches `shell.json` and leaves the edit to the `sync-layout` script.

## Optional Hyprland bindings

Omarchy counts `SUPER + CTRL + 1..9` panels in the bar's right section. On a
vertical bar that is the bottom section. To count in the top section while the
bar is vertical, add this to `~/.config/hypr/bindings.lua`:

```lua
local panel_section = [[$(jq -r 'if ((.bar.position // "top") | IN("left","right")) then "left" else "right" end' "$HOME/.config/omarchy/shell.json")]]
for panel = 1, 9 do
  local keys = "SUPER + CTRL + code:" .. tostring(panel + 9)
  hl.unbind(keys)
  o.bind(keys, "Bar panel " .. panel, "omarchy-shell -q shell togglePanelAt " .. panel_section .. " " .. tostring(panel))
end
```

## License

MIT
