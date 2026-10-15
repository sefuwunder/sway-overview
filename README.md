# sway-overview

GNOME Shell-style overview for Sway — without GNOME Shell.

Press **Super** and get the three things that make GNOME's overview great,
running as a native Wayland client on Sway:

- **Window exposé** — live thumbnails of windows on the focused workspace,
  captured with `grim`
- **Type-to-search** — filters windows *and* applications as you type
- **App grid** — every installed application, icon grid, searchable

No X11. No window manager replacement. Just an overlay.

## How it works

`bin/sway-overview` toggles a GTK overlay. Windows come from Sway's JSON IPC
(`swaymsg -t get_tree`) — no libwnck, no X11 calls. Thumbnails are captured
with `grim -g <window-rect>` in parallel *before* the overlay shows (grim
sees the compositor frame, so capturing after would just photograph the
overlay). Enter focuses the window (`[con_id=…] focus` — Sway jumps to its
workspace), arrows move, Esc (or Super again) closes. Right-click a thumbnail
to kill that window.

If `gtk-layer-shell` is available the overlay uses it (proper overlay layer,
exclusive keyboard); otherwise it falls back to a plain fullscreen window.

## Wayland caveats (honest)

- **Only the focused workspace gets thumbnails.** Wayland has no
  hidden-window capture (`import -window` was an X11 privilege) — windows on
  other workspaces show their app icon instead.
- **HiDPI** is handled: window rects are scaled by the output's scale factor
  before passing to grim.

## Install

```sh
./bin/setup.sh
```

Installs `grim`, `python3-gi`, `gir1.2-gtk-3.0`, `gir1.2-gtk-layer-shell-0.1`,
then appends `bindsym Mod4 exec …/bin/sway-overview` to
`~/.config/sway/config` and reloads Sway.

If Super is already your `$mod`, pressing it alone opens the overview;
`$mod`+key combos still work as before.

## Layout

- `src/overview.py` — the GTK overlay (search + exposé + app grid)
- `src/sway_ipc.py` — Sway IPC backend: tree parsing, focus/kill,
  grim thumbnails (pure-JSON parsing, fully testable without Sway)
- `src/apps.py` — `.desktop` parsing, app search, launching (no GTK,
  shared with xfce-overview)
- `src/search.py` — fuzzy scoring shared by both (no GTK, shared)
- `bin/sway-overview` — toggle launcher (kills the running overlay on 2nd press)
- `bin/setup.sh` — deps + Super keybinding
- `tests/` — `test_sway.py` (mock-tree IPC tests), `test_core.py`
  (search + desktop parsing), `test_gui.py` (Xvfb overlay test)

## Notes

- The overlay excludes its own PID from the window list, so it never
  shows itself.
- XWayland windows are supported via `window_properties.class`
  for icon lookup.
- The overlay re-scans windows and apps every time it opens, so it's
  always fresh.
