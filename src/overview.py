"""sway-overview — GNOME Shell-style overview for Sway.

Super-key overlay: window exposé + type-to-search + app grid, running as a
native Wayland client on Sway. No X11, no libwnck.

Sway IPC (`swaymsg -t get_tree`) lists windows; `grim -g <rect>` captures
thumbnails for windows on the focused workspace (Wayland has no hidden-window
capture, so anything off-screen falls back to its app icon). Thumbnails are
captured BEFORE the overlay shows — grim sees the compositor frame, and the
overlay would occlude everything.

Layout: search entry on top, window thumbnails (exposé) in the middle,
application grid below. Type to filter both. Enter activates, Esc closes.
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib

try:
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
    HAVE_LAYER_SHELL = True
except Exception:
    HAVE_LAYER_SHELL = False

from apps import load_apps, search_apps, launch
from search import ranked
from sway_ipc import (
    list_windows, activate, close_window, preload_thumbnails, HAVE_SWAY,
)

CSS = """
#overview { background-color: rgba(18, 18, 22, 0.93); }
#search {
  font-size: 22px; padding: 10px 18px; border-radius: 24px;
  background-color: rgba(255,255,255,0.10); color: #fff;
  border: 1px solid rgba(255,255,255,0.18); caret-color: #fff;
}
#search:focus { border-color: #4a90d9; }
.section-label {
  color: rgba(255,255,255,0.55); font-size: 13px; font-weight: bold;
  letter-spacing: 1px; padding: 14px 8px 6px 8px;
}
.tile { background: transparent; border: 2px solid transparent;
        border-radius: 10px; padding: 6px; }
.tile:hover { background-color: rgba(255,255,255,0.08); }
.tile.selected { border-color: #4a90d9; background-color: rgba(74,144,217,0.18); }
.tile-label { color: #eee; font-size: 12px; }
"""

APP_ICON_SIZE = 64
THUMB_WIDTH = 300

class Overview(Gtk.Window):
    def __init__(self):
        super().__init__(title="Overview")
        self.set_name("overview")
        self.set_decorated(False)
        self.set_app_paintable(True)

        if HAVE_LAYER_SHELL:
            # proper Wayland overlay: above everything, exclusive keyboard
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(
                self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
            for edge in (GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT,
                         GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM):
                GtkLayerShell.set_anchor(self, edge, True)
        else:
            # fallback: plain fullscreen window
            self.fullscreen()
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.stick()
            self.set_keep_above(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        css = Gtk.CssProvider()
        css.load_from_data(CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.apps = load_apps()
        self.windows = list_windows() if HAVE_SWAY else []
        # capture BEFORE the window shows: grim sees the compositor frame
        if self.windows:
            preload_thumbnails(self.windows)
        self.icon_theme = Gtk.IconTheme.get_default()

        # navigable items in visual order: [(kind, obj, eventbox)]
        self.items = []
        self.sel = -1
        self._current_wins = []
        self._current_apps = []

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.set_margin_top(48)
        vbox.set_margin_bottom(24)
        vbox.set_margin_start(64)
        vbox.set_margin_end(64)
        self.add(vbox)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        search_row.set_halign(Gtk.Align.CENTER)
        self.entry = Gtk.Entry()
        self.entry.set_name("search")
        self.entry.set_placeholder_text("Type to search windows and applications…")
        self.entry.set_width_chars(42)
        self.entry.connect("changed", self.on_search)
        search_row.pack_start(self.entry, False, False, 0)
        vbox.pack_start(search_row, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        vbox.pack_start(scroller, True, True, 0)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scroller.add(content)

        self.win_label = Gtk.Label(label="WINDOWS")
        self.win_label.set_halign(Gtk.Align.START)
        self.win_label.get_style_context().add_class("section-label")
        content.pack_start(self.win_label, False, False, 0)

        self.win_flow = Gtk.FlowBox()
        self.win_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.win_flow.set_max_children_per_line(4)
        self.win_flow.set_halign(Gtk.Align.CENTER)
        content.pack_start(self.win_flow, False, False, 0)

        self.app_label = Gtk.Label(label="APPLICATIONS")
        self.app_label.set_halign(Gtk.Align.START)
        self.app_label.get_style_context().add_class("section-label")
        content.pack_start(self.app_label, False, False, 0)

        self.app_flow = Gtk.FlowBox()
        self.app_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.app_flow.set_max_children_per_line(7)
        self.app_flow.set_halign(Gtk.Align.CENTER)
        content.pack_start(self.app_flow, False, False, 0)

        self.connect("key-press-event", self.on_key)

        self.show_all()
        self.refresh("")  # after show_all: refresh hides empty sections
        self.entry.grab_focus()

    # ---------- data ----------

    def refresh(self, query):
        q = query.strip()
        if q:
            self._current_wins = ranked(q, self.windows,
                                       lambda w: (w["name"], w["icon_name"]))
            self._current_apps = search_apps(self.apps, q)
        else:
            self._current_wins = list(self.windows)
            self._current_apps = list(self.apps)
        self._populate(self.win_flow, self.win_label, "WINDOWS",
                       self._current_wins, self.make_win_tile, q)
        self._populate(self.app_flow, self.app_label, "APPLICATIONS",
                       self._current_apps, self.make_app_tile, q)
        self.items = (
            [("win", w, c) for w, c in
             zip(self._current_wins, self.win_flow.get_children())] +
            [("app", a, c) for a, c in
             zip(self._current_apps, self.app_flow.get_children())]
        )
        self.sel = 0 if self.items else -1
        self.update_selection()

    def _populate(self, flow, label, title, objs, maker, query):
        for child in flow.get_children():
            flow.remove(child)
        for obj in objs:
            flow.add(maker(obj))
        label.set_text("%s (%d)" % (title, len(objs)) if query else title)
        label.set_visible(bool(objs))
        flow.set_visible(bool(objs))
        flow.show_all()

    def on_search(self, entry):
        self.refresh(entry.get_text())

    # ---------- tiles ----------

    def icon_pixbuf(self, icon_name, size):
        if not icon_name:
            icon_name = "application-x-executable"
        try:
            return self.icon_theme.load_icon(icon_name, size, 0)
        except Exception:
            pass
        if os.path.isabs(icon_name) and os.path.exists(icon_name):
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_size(icon_name, size, size)
            except Exception:
                pass
        try:
            return self.icon_theme.load_icon("application-x-executable", size, 0)
        except Exception:
            return None

    def pixbuf_from_png(self, data, width):
        try:
            loader = GdkPixbuf.PixbufLoader.new_with_type("png")
            loader.write(data)
            loader.close()
            pb = loader.get_pixbuf()
            if pb:
                h = int(pb.get_height() * width / max(pb.get_width(), 1))
                return pb.scale_simple(width, h, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            pass
        return None

    def make_win_tile(self, win):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("tile")
        img = Gtk.Image()
        pb = None
        if win.get("thumb_data"):
            pb = self.pixbuf_from_png(win["thumb_data"], THUMB_WIDTH)
        if pb is None:
            pb = self.icon_pixbuf(win["icon_name"], 96)
        if pb:
            img.set_from_pixbuf(pb)
        img.set_size_request(THUMB_WIDTH, int(THUMB_WIDTH * 9 / 16))
        box.pack_start(img, False, False, 0)
        lab = Gtk.Label(label=win["name"])
        lab.get_style_context().add_class("tile-label")
        lab.set_ellipsize(True)
        lab.set_max_width_chars(32)
        box.pack_start(lab, False, False, 0)
        ev = Gtk.EventBox()
        ev.add(box)
        ev.connect("button-press-event", self.on_win_click, win)
        return ev

    def make_app_tile(self, app):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class("tile")
        img = Gtk.Image()
        pb = self.icon_pixbuf(app.icon, APP_ICON_SIZE)
        if pb:
            img.set_from_pixbuf(pb)
        img.set_size_request(APP_ICON_SIZE, APP_ICON_SIZE)
        box.pack_start(img, False, False, 0)
        lab = Gtk.Label(label=app.name)
        lab.get_style_context().add_class("tile-label")
        lab.set_ellipsize(True)
        lab.set_max_width_chars(18)
        lab.set_lines(2)
        box.pack_start(lab, False, False, 0)
        ev = Gtk.EventBox()
        ev.add(box)
        ev.connect("button-press-event", self.on_app_click, app)
        return ev

    # ---------- input ----------

    def on_key(self, _w, ev):
        key = Gdk.keyval_name(ev.keyval)
        if key == "Escape":
            Gtk.main_quit()
            return True
        if key in ("Up", "Down", "Left", "Right"):
            self.move_selection(key)
            return True
        if key in ("Return", "KP_Enter"):
            self.activate_selected()
            return True
        return False

    def move_selection(self, key):
        if not self.items:
            return
        kind = self.items[self.sel][0] if 0 <= self.sel < len(self.items) else "app"
        cols = 4 if kind == "win" else 7
        if key == "Right":
            self.sel = min(len(self.items) - 1, self.sel + 1)
        elif key == "Left":
            self.sel = max(0, self.sel - 1)
        elif key == "Down":
            self.sel = min(len(self.items) - 1, self.sel + cols)
        elif key == "Up":
            self.sel = max(0, self.sel - cols)
        self.update_selection()

    def update_selection(self):
        for i, (_k, _o, ev) in enumerate(self.items):
            ctx = ev.get_child().get_style_context()
            if i == self.sel:
                ctx.add_class("selected")
            else:
                ctx.remove_class("selected")

    def activate_selected(self):
        if 0 <= self.sel < len(self.items):
            kind, obj, _ev = self.items[self.sel]
            if kind == "win":
                activate(obj)
            else:
                launch(obj)
            Gtk.main_quit()

    def on_win_click(self, _ev, event, win):
        if event.button == 3:  # right-click closes the window
            close_window(win)
            self.windows = [w for w in self.windows
                            if w["con_id"] != win["con_id"]]
            self.refresh(self.entry.get_text())
            return True
        activate(win)
        Gtk.main_quit()
        return True

    def on_app_click(self, _ev, _event, app):
        launch(app)
        Gtk.main_quit()
        return True


def main():
    win = Overview()
    win.connect("destroy", Gtk.main_quit)
    Gtk.main()


if __name__ == "__main__":
    main()
