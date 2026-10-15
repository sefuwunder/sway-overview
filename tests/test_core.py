"""Tests for search scoring and .desktop parsing — run headless: python3 -m pytest tests/"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from search import score, ranked
from apps import _parse_desktop, _clean_exec, search_apps, DesktopApp


def test_score_exact_prefix_wins():
    assert score("fire", "Firefox", "web browser") > score("fire", "Web Browser", "fire tools")


def test_score_substring():
    assert score("fox", "Firefox") > 0
    assert score("zzz", "Firefox") == 0


def test_score_fuzzy():
    assert score("ffx", "Firefox") > 0
    assert score("xyz", "Firefox") == 0


def test_score_empty_query():
    assert score("", "Firefox") == 0


def test_score_case_insensitive():
    assert score("FIREFOX", "firefox") == score("firefox", "Firefox")


def test_ranked_orders_by_score():
    items = ["Firefox", "File Manager", "Terminal"]
    out = ranked("fi", items, lambda s: (s,))
    assert out[0] in ("Firefox", "File Manager")
    assert len(out) == 2  # Terminal doesn't match


def test_clean_exec_strips_field_codes():
    assert _clean_exec("firefox %u --new-tab") == ["firefox", "--new-tab"]
    assert _clean_exec("exo-open --launch TerminalEmulator") == ["exo-open", "--launch", "TerminalEmulator"]


def _write_desktop(tmp, name, body):
    p = os.path.join(tmp, name)
    with open(p, "w") as f:
        f.write(body)
    return p


def test_parse_desktop_basic():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_desktop(tmp, "t.desktop",
            "[Desktop Entry]\nName=Test App\nExec=test-app --flag\nIcon=test\nComment=A test\n")
        app = _parse_desktop(p)
        assert app is not None
        assert app.name == "Test App"
        assert app.exec == "test-app --flag"
        assert app.icon == "test"


def test_parse_desktop_skips_nodisplay():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_desktop(tmp, "t.desktop",
            "[Desktop Entry]\nName=Hidden\nExec=hidden\nNoDisplay=true\n")
        assert _parse_desktop(p) is None


def test_parse_desktop_skips_xfce_excluded():
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_desktop(tmp, "t.desktop",
            "[Desktop Entry]\nName=NotForXfce\nExec=nfx\nNotShowIn=XFCE;\n")
        assert _parse_desktop(p) is None


def test_search_apps_ranks_name_first():
    apps = [
        DesktopApp(id="a.desktop", name="File Manager", exec="thunar", comment="browse files"),
        DesktopApp(id="b.desktop", name="Firefox", exec="firefox", comment="manage files online"),
    ]
    out = search_apps(apps, "file")
    assert out[0].name == "File Manager"


def test_search_apps_empty_query_returns_all():
    apps = [DesktopApp(id="a.desktop", name="B", exec="b"),
            DesktopApp(id="b.desktop", name="A", exec="a")]
    out = search_apps(apps, "")
    assert len(out) == 2
