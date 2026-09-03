from __future__ import annotations

from pathlib import Path

import pytest

from panehitch.lane import LaneError, load_lane


def _write_lane(tmp_path: Path, replacement: str = "") -> Path:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("work", encoding="utf-8")
    text = f'''label = "sample"
cwd = "."
timeout_s = 1
[agent]
kind = "claude"
args = []
[tools]
allow = ["example__read"]
[prompt]
file = "{prompt}"
header = "again means stop"
[completion]
marker = "^CYCLE_DONE (?P<run_id>\\\\S+) (?P<status>ok|blocked)$"
[artifacts]
globs = []
[backend]
kind = "herdr"
[herdr]
session = "s"
workspace = "w"
[report]
dir = "reports"
'''
    path = tmp_path / "lane.toml"
    path.write_text(replacement or text, encoding="utf-8")
    return path


def test_lane_loads_required_contract(tmp_path: Path) -> None:
    lane = load_lane(_write_lane(tmp_path))
    assert lane.backend_kind == "herdr"
    assert lane.tools == ["example__read"]


@pytest.mark.parametrize(
    ("marker", "message"),
    [
        ("([unclosed", "invalid"),
        ("^CYCLE_DONE (\\\\S+) (\\\\w+)$", "named run_id and status"),
    ],
)
def test_marker_is_validated_before_spawn(tmp_path: Path, marker: str, message: str) -> None:
    path = _write_lane(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "^CYCLE_DONE (?P<run_id>\\\\S+) (?P<status>ok|blocked)$", marker
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LaneError, match=message):
        load_lane(path)


def test_backend_kind_is_validated(tmp_path: Path) -> None:
    path = _write_lane(tmp_path)
    path.write_text(
        path.read_text(encoding="utf-8").replace('kind = "herdr"', 'kind = "other"'),
        encoding="utf-8",
    )
    with pytest.raises(LaneError, match="backend.kind"):
        load_lane(path)
