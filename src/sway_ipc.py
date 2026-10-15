"""Sway IPC backend for sway-overview: window listing, activation, thumbnails.

Uses `swaymsg` JSON IPC — no X11, no libwnck. Tree parsing is pure
functions over JSON, so the whole backend is unit-testable without Sway.

Wayland note: unlike X11's `import -window`, there is no per-window
capture on Wayland. Thumbnails are grabbed with `grim -g <rect>` for
windows on the *focused* workspace only, and they must be captured
BEFORE the overlay shows (otherwise grim captures the overlay itself).
Windows on other workspaces fall back to their app icon.
"""

import json
import os
import shutil
import subprocess
import threading

THUMB_WIDTH = 600  # captured pixels; the UI scales down


def _run(*args, timeout=5):
    p = subprocess.run(
        ["swaymsg", "-t", args[0], *args[1:]],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError("swaymsg failed: %s" % (args,))
    return json.loads(p.stdout.decode("utf-8", "replace"))


def _have_sway():
    if not shutil.which("swaymsg"):
        return False
    try:
        _run("get_version", timeout=3)
        return True
    except Exception:
        return False


HAVE_SWAY = _have_sway()


# ---------- tree parsing (pure) ----------

def _icon_name(node):
    app_id = node.get("app_id")
    if app_id:
        return app_id
    props = node.get("window_properties") or {}
    return props.get("class") or props.get("instance") or ""


def _is_window(node):
    return bool(node.get("app_id") or node.get("window_properties"))


def _walk(node, workspace, out):
    """Depth-first walk collecting leaf window nodes."""
    if node.get("type") == "workspace":
        if node.get("name") == "__i3_scratch":
            return  # scratchpad is not part of the exposé
        workspace = node.get("name")
    if _is_window(node):
        out.append((node, workspace))
        return  # leaf — don't descend into its decorations
    for child in node.get("nodes") or []:
        _walk(child, workspace, out)
    for child in node.get("floating_nodes") or []:
        _walk(child, workspace, out)


def _output_scale(outputs, rect):
    """Physical-pixel scale of the output containing the rect's center."""
    cx = rect.get("x", 0) + rect.get("width", 0) / 2
    cy = rect.get("y", 0) + rect.get("height", 0) / 2
    for o in outputs or []:
        r = o.get("rect") or {}
        if (r.get("x", 0) <= cx < r.get("x", 0) + r.get("width", 0) and
                r.get("y", 0) <= cy < r.get("y", 0) + r.get("height", 0)):
            return o.get("scale", 1) or 1
    return 1


def parse_windows(tree, workspaces, outputs, exclude_pid=None):
    """Build window dicts from swaymsg JSON. Focused workspace first."""
    focused_ws = None
    for ws in workspaces or []:
        if ws.get("focused"):
            focused_ws = ws.get("name")
            break
    found = []
    _walk(tree or {}, None, found)
    wins = []
    for node, workspace in found:
        if exclude_pid is not None and node.get("pid") == exclude_pid:
            continue
        name = node.get("name") or ""
        if not name:
            continue
        rect = node.get("rect") or {}
        scale = _output_scale(outputs, rect)
        wins.append({
            "con_id": node.get("id"),
            "name": name,
            "icon_name": _icon_name(node),
            "workspace": workspace,
            "rect": rect,
            "scale": scale,
            "focused": bool(node.get("focused")),
            "urgent": bool(node.get("urgent")),
            "pid": node.get("pid"),
            # grim can only capture what's actually on screen
            "thumb_ok": workspace == focused_ws,
        })
    wins.sort(key=lambda w: (w["workspace"] != focused_ws, w["workspace"] or ""))
    return wins


def grim_geometry(win):
    """grim -g argument for a window, in physical pixels. None if degenerate."""
    rect = win.get("rect") or {}
    s = win.get("scale", 1) or 1
    x = int(rect.get("x", 0) * s)
    y = int(rect.get("y", 0) * s)
    w = int(rect.get("width", 0) * s)
    h = int(rect.get("height", 0) * s)
    if w < 10 or h < 10:
        return None
    return "%d,%d %dx%d" % (x, y, w, h)


# ---------- live IPC ----------

def list_windows():
    """All windows, focused workspace first. Dicts match the xfce-overview
    shape (name, icon_name, workspace) plus con_id/rect/scale/thumb_ok."""
    if not HAVE_SWAY:
        return []
    try:
        tree = _run("get_tree")
        workspaces = _run("get_workspaces")
        outputs = _run("get_outputs")
    except Exception:
        return []
    return parse_windows(tree, workspaces, outputs, exclude_pid=os.getpid())


def activate(win):
    """Focus a window; Sway switches to its workspace automatically."""
    try:
        subprocess.run(
            ["swaymsg", "[con_id=%s] focus" % win["con_id"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        return True
    except Exception:
        return False


def close_window(win):
    try:
        subprocess.run(
            ["swaymsg", "[con_id=%s] kill" % win["con_id"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        return True
    except Exception:
        return False


def thumbnail(win, width=THUMB_WIDTH):
    """Capture a window's on-screen rect with grim. PNG bytes or None."""
    if not win.get("thumb_ok"):
        return None
    geom = grim_geometry(win)
    if not geom:
        return None
    try:
        p = subprocess.run(
            ["grim", "-g", geom, "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
        )
        if p.returncode == 0 and p.stdout[:8].startswith(b"\x89PNG"):
            return p.stdout
    except Exception:
        pass
    return None


def preload_thumbnails(windows, width=THUMB_WIDTH):
    """Capture thumbnails for all capturable windows in parallel.

    Must run BEFORE the overlay window is shown — grim captures the
    compositor frame, and the overlay would occlude everything.
    Stores PNG bytes in win["thumb_data"]; missing on failure.
    """
    targets = [w for w in windows if w.get("thumb_ok")]

    def work(win):
        data = thumbnail(win, width)
        if data:
            win["thumb_data"] = data

    threads = [threading.Thread(target=work, args=(w,), daemon=True)
               for w in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
