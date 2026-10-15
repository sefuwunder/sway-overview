"""Headless GUI test: run the overlay under Xvfb with injected fake Sway
windows (with generated PNG thumbnails), screenshot each state."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TMP = tempfile.mkdtemp()
os.makedirs(os.path.join(TMP, "applications"), exist_ok=True)
for i, (name, kw) in enumerate([
    ("Firefox Web Browser", "web;browser;internet"),
    ("File Manager", "files;folders;thunar"),
    ("Terminal Emulator", "terminal;shell;console"),
]):
    with open(os.path.join(TMP, "applications", f"app{i}.desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=%s\nExec=/bin/true\n"
                "Icon=application-x-executable\nKeywords=%s;\n" % (name, kw))
os.environ["XDG_DATA_DIRS"] = TMP

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib

import overview


def make_png(w, h, r, g, b):
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, w, h)
    pb.fill((r << 24) | (g << 16) | (b << 8) | 0xFF)
    ok, data = pb.save_to_bufferv("png", [], [])
    assert ok
    return bytes(data)


FAKE_WINDOWS = [
    {"con_id": 100, "name": "Firefox", "icon_name": "firefox",
     "workspace": "1", "rect": {}, "scale": 1, "thumb_ok": True,
     "thumb_data": make_png(320, 180, 200, 80, 40)},
    {"con_id": 101, "name": "Terminal", "icon_name": "Alacritty",
     "workspace": "1", "rect": {}, "scale": 1, "thumb_ok": True,
     "thumb_data": make_png(320, 180, 40, 80, 200)},
    {"con_id": 102, "name": "Code", "icon_name": "code",
     "workspace": "2", "rect": {}, "scale": 1, "thumb_ok": False},
]

# bypass Sway: inject fakes
overview.HAVE_SWAY = True
overview.list_windows = lambda: [dict(w) for w in FAKE_WINDOWS]
overview.preload_thumbnails = lambda wins: None  # thumb_data pre-baked


def screenshot(path):
    win = Gdk.get_default_root_window()
    w, h = win.get_width(), win.get_height()
    pb = Gdk.pixbuf_get_from_window(win, 0, 0, w, h)
    if pb:
        pb.savev(path, "png", [], [])


ov = overview.Overview()
assert len(ov.windows) == 3, f"windows={len(ov.windows)}"
# thumbnails landed on the tiles
assert ov._current_wins[0].get("thumb_data"), "no thumb data on win 0"


def stage1():
    screenshot("/tmp/sw-stage1-empty.png")
    # 3 windows + 3 apps visible; keyboard nav across the grid
    assert len(ov.items) == 6, f"items={len(ov.items)}"
    ov.move_selection("Right")
    assert ov.sel == 1, f"sel={ov.sel}"
    ov.entry.set_text("fire")
    return False


def stage2():
    screenshot("/tmp/sw-stage2-search.png")
    # "fire" matches Firefox window + Firefox app
    kinds = [k for k, _o, _e in ov.items]
    assert kinds == ["win", "app"], f"kinds={kinds}"
    Gtk.main_quit()
    return False


GLib.timeout_add(800, stage1)
GLib.timeout_add(1600, stage2)
Gtk.main()
print("GUI test done")
