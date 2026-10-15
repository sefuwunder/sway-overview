"""Tests for the Sway IPC backend — pure JSON parsing, no Sway needed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sway_ipc import parse_windows, grim_geometry, _output_scale


def mock_tree():
    return {
        "id": 1, "type": "root", "nodes": [
            {"id": 2, "type": "output", "name": "HDMI-1", "nodes": [
                {"id": 10, "type": "workspace", "name": "1", "nodes": [
                    {"id": 100, "type": "con", "name": "Firefox",
                     "app_id": "firefox", "pid": 1111,
                     "rect": {"x": 0, "y": 0, "width": 960, "height": 1040},
                     "focused": False, "urgent": False},
                    {"id": 101, "type": "con", "name": "Terminal",
                     "app_id": "Alacritty", "pid": 2222,
                     "rect": {"x": 960, "y": 0, "width": 960, "height": 1040},
                     "focused": True, "urgent": False},
                ], "floating_nodes": [
                    {"id": 102, "type": "floating_con", "name": "xterm",
                     "app_id": None, "pid": 3333,
                     "window_properties": {"class": "XTerm", "instance": "xterm"},
                     "rect": {"x": 100, "y": 100, "width": 800, "height": 600},
                     "focused": False, "urgent": True},
                ]},
                {"id": 11, "type": "workspace", "name": "2", "nodes": [
                    {"id": 103, "type": "con", "name": "Code",
                     "app_id": "code", "pid": 4444,
                     "rect": {"x": 0, "y": 0, "width": 1920, "height": 1040},
                     "focused": False, "urgent": False},
                ], "floating_nodes": []},
                {"id": 12, "type": "workspace", "name": "__i3_scratch",
                 "nodes": [
                    {"id": 104, "type": "con", "name": "Hidden",
                     "app_id": "hidden", "pid": 5555,
                     "rect": {"x": 0, "y": 0, "width": 100, "height": 100},
                     "focused": False, "urgent": False},
                 ], "floating_nodes": []},
                # container node (not a window) — must not appear
                {"id": 13, "type": "workspace", "name": "3", "nodes": [
                    {"id": 105, "type": "con", "name": "split",
                     "app_id": None, "pid": None,
                     "rect": {"x": 0, "y": 0, "width": 1920, "height": 1040},
                     "nodes": [
                        {"id": 106, "type": "con", "name": "Editor",
                         "app_id": "emacs", "pid": 6666,
                         "rect": {"x": 0, "y": 0, "width": 960, "height": 1040},
                         "focused": False, "urgent": False},
                     ], "floating_nodes": []},
                ], "floating_nodes": []},
            ]},
        ],
    }


def mock_workspaces():
    return [
        {"name": "1", "focused": True},
        {"name": "2", "focused": False},
        {"name": "3", "focused": False},
    ]


def mock_outputs():
    return [{"name": "HDMI-1", "scale": 1,
             "rect": {"x": 0, "y": 0, "width": 1920, "height": 1080}}]


def windows():
    return parse_windows(mock_tree(), mock_workspaces(), mock_outputs())


def test_finds_all_windows():
    names = {w["name"] for w in windows()}
    assert names == {"Firefox", "Terminal", "xterm", "Code", "Editor"}, names


def test_scratchpad_excluded():
    assert "Hidden" not in {w["name"] for w in windows()}


def test_container_not_a_window():
    assert "split" not in {w["name"] for w in windows()}


def test_focused_workspace_first():
    wins = windows()
    assert wins[0]["workspace"] == "1"
    assert wins[1]["workspace"] == "1"
    assert wins[2]["workspace"] == "1"
    assert {w["workspace"] for w in wins[3:]} == {"2", "3"}


def test_thumb_ok_only_on_focused_workspace():
    by_name = {w["name"]: w for w in windows()}
    assert by_name["Firefox"]["thumb_ok"] is True
    assert by_name["Terminal"]["thumb_ok"] is True
    assert by_name["xterm"]["thumb_ok"] is True
    assert by_name["Code"]["thumb_ok"] is False
    assert by_name["Editor"]["thumb_ok"] is False


def test_icon_names():
    by_name = {w["name"]: w for w in windows()}
    assert by_name["Firefox"]["icon_name"] == "firefox"
    assert by_name["Terminal"]["icon_name"] == "Alacritty"
    assert by_name["xterm"]["icon_name"] == "XTerm"  # XWayland class
    assert by_name["Editor"]["icon_name"] == "emacs"


def test_con_ids_and_rects():
    by_name = {w["name"]: w for w in windows()}
    assert by_name["Firefox"]["con_id"] == 100
    assert by_name["Firefox"]["rect"]["width"] == 960


def test_exclude_pid():
    wins = parse_windows(mock_tree(), mock_workspaces(), mock_outputs(),
                         exclude_pid=1111)
    assert "Firefox" not in {w["name"] for w in wins}


def test_grim_geometry():
    wins = windows()
    ff = next(w for w in wins if w["name"] == "Firefox")
    assert grim_geometry(ff) == "0,0 960x1040"


def test_grim_geometry_hidpi():
    outputs = [{"name": "eDP-1", "scale": 2,
                "rect": {"x": 0, "y": 0, "width": 1920, "height": 1080}}]
    wins = parse_windows(mock_tree(), mock_workspaces(), outputs)
    ff = next(w for w in wins if w["name"] == "Firefox")
    assert grim_geometry(ff) == "0,0 1920x2080"


def test_grim_geometry_degenerate():
    assert grim_geometry({"rect": {"x": 0, "y": 0, "width": 5, "height": 5},
                         "scale": 1}) is None
    assert grim_geometry({"rect": {}, "scale": 1}) is None


def test_output_scale_outside():
    # rect center outside all outputs -> scale 1 fallback
    s = _output_scale(mock_outputs(),
                      {"x": 5000, "y": 5000, "width": 100, "height": 100})
    assert s == 1
