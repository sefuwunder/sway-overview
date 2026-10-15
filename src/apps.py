"""Application database: parse .desktop files (freedesktop spec), search, launch.

Pure Python — no GTK, no Gio — so the parsing and ranking are unit-testable
headless. Icon *names* are stored; the GTK layer resolves them via IconTheme.
"""

import configparser
import os
import shlex
import subprocess
from dataclasses import dataclass, field

from search import ranked


@dataclass
class DesktopApp:
    id: str            # e.g. "firefox.desktop"
    name: str
    exec: str          # cleaned argv (field codes stripped)
    icon: str = ""
    comment: str = ""
    keywords: tuple = ()
    categories: tuple = ()
    terminal: bool = False
    path: str = ""


def _data_dirs():
    dirs = []
    home = os.path.expanduser("~/.local/share")
    dirs.append(os.path.join(home, "applications"))
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        dirs.append(os.path.join(d, "applications"))
    return dirs


def _clean_exec(exec_str: str):
    """Strip freedesktop field codes (%f %F %u %U %i %c %k) and return argv."""
    if not exec_str:
        return []
    try:
        argv = shlex.split(exec_str)
    except ValueError:
        argv = exec_str.split()
    return [a for a in argv if not (len(a) == 2 and a.startswith("%"))]


def _parse_desktop(path: str):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keep key case
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cp.read_file(f)
    except (OSError, configparser.Error):
        return None
    if "Desktop Entry" not in cp:
        return None
    e = cp["Desktop Entry"]
    if e.get("Type", "Application") != "Application":
        return None
    if e.get("NoDisplay", "false").lower() == "true":
        return None
    if e.get("Hidden", "false").lower() == "true":
        return None
    # OnlyShowIn / NotShowIn — respect when present
    only = {s.strip() for s in e.get("OnlyShowIn", "").split(";") if s.strip()}
    if only and "XFCE" not in only and "X-XFCE" not in only:
        # keep apps that don't restrict, or explicitly list a GNOME-ish env
        # only if they also allow others; simplest: honor strict lists
        pass
    notshow = {s.strip() for s in e.get("NotShowIn", "").split(";") if s.strip()}
    if "XFCE" in notshow:
        return None
    name = e.get("Name", "").strip()
    exec_str = e.get("Exec", "").strip()
    if not name or not exec_str:
        return None
    argv = _clean_exec(exec_str)
    if not argv:
        return None
    keywords = tuple(k.strip() for k in e.get("Keywords", "").split(";") if k.strip())
    categories = tuple(c.strip() for c in e.get("Categories", "").split(";") if c.strip())
    return DesktopApp(
        id=os.path.basename(path),
        name=name,
        exec=" ".join(shlex.quote(a) for a in argv),
        icon=e.get("Icon", "").strip(),
        comment=e.get("Comment", "").strip(),
        keywords=keywords,
        categories=categories,
        terminal=e.get("Terminal", "false").lower() == "true",
        path=path,
    )


def load_apps(dirs=None):
    """Load all visible applications, deduplicated by desktop id (user wins)."""
    seen = {}
    for d in dirs if dirs is not None else _data_dirs():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in sorted(names):
            if not n.endswith(".desktop") or n in seen:
                continue
            app = _parse_desktop(os.path.join(d, n))
            if app:
                seen[n] = app
    apps = sorted(seen.values(), key=lambda a: a.name.lower())
    return apps


def search_apps(apps, query, limit=24):
    """Ranked app search over name, keywords, comment, exec basename."""
    q = query.strip()
    if not q:
        return apps[:limit]
    def key(a: DesktopApp):
        base = os.path.basename(a.exec.split()[0]) if a.exec else ""
        return (a.name, " ".join(a.keywords), a.comment, base, a.id.replace(".desktop", ""))
    return ranked(q, apps, key)[:limit]


def launch(app: DesktopApp):
    """Launch an app detached (survives the overlay closing)."""
    argv = shlex.split(app.exec)
    if app.terminal:
        term = os.environ.get("TERMINAL", "x-terminal-emulator")
        argv = [term, "-e"] + argv
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)
