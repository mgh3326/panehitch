from __future__ import annotations

import json
import stat
from pathlib import Path

from panehitch.backend import HerdrBackend
from panehitch.lane import load_lane
from panehitch.runner import run_lane


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_backend(tmp_path: Path, reads: list[dict[str, str]]) -> tuple[HerdrBackend, Path]:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"reads": reads, "log": []}), encoding="utf-8")
    executable = tmp_path / "fake-pane"
    _executable(
        executable,
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state_path = pathlib.Path(os.environ['PANEHITCH_FAKE_STATE'])
state = json.loads(state_path.read_text())
command = sys.argv[1:]
state['log'].append(command)
if command[:2] == ['agent', 'start']:
    result = {'pane_id': 'p-1', 'tab_id': 't-1'}
elif command[:2] == ['agent', 'read']:
    result = state['reads'].pop(0) if state['reads'] else {'text': '', 'status': 'working'}
elif command[:2] == ['agent', 'list']:
    result = {'agents': [{'pane_id': 'p-1', 'label': 'review'}]}
else:
    result = {'ok': True}
state_path.write_text(json.dumps(state))
print(json.dumps(result))
""",
    )
    return HerdrBackend(str(executable)), state


def _lane(tmp_path: Path, timeout: float = 1.0) -> Path:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("do work", encoding="utf-8")
    lane = tmp_path / "lane.toml"
    lane.write_text(
        f'''label = "sample"
cwd = "{tmp_path}"
timeout_s = {timeout}
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
globs = ["artifact.txt"]
[backend]
kind = "herdr"
[herdr]
session = "s"
workspace = "w"
[report]
dir = "{tmp_path / "reports"}"
''',
        encoding="utf-8",
    )
    return lane


def _fixed_run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "reports" / "run-001"
    path.mkdir(parents=True)
    return path


def test_lifecycle_marker_artifacts_and_schema(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PANEHITCH_FAKE_STATE", str(tmp_path / "state.json"))
    backend, state = _fake_backend(
        tmp_path,
        [
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
            {"text": "accepted", "status": "working"},
            {
                "text": "prompt echo\nCYCLE_DONE old ok\nprogress\nCYCLE_DONE run-001 ok\nshell",
                "status": "working",
            },
        ],
    )
    (tmp_path / "artifact.txt").write_text("evidence", encoding="utf-8")
    run_dir = _fixed_run_dir(tmp_path)
    monkeypatch.setattr("panehitch.runner._run_dir", lambda parent: run_dir)
    result = run_lane(load_lane(_lane(tmp_path)), backend, poll_s=0)
    assert result["status"] == "done"
    assert result["schema_version"] == "panehitch-cycle/v1"
    assert result["run_id"] == "run-001"
    assert result["pane_id"] == "p-1"
    assert result["tab_id"] == "t-1"
    assert {"started_at", "finished_at", "cleaned_at", "prompt_confirmed_at"} <= set(
        result["timestamps"]
    )
    assert len(result["artifacts"]) == 1
    state_data = json.loads(state.read_text(encoding="utf-8"))
    assert any(item[1:3] == ["send-keys", "p-1"] for item in state_data["log"])
    assert any(item[1:3] == ["close", "p-1"] for item in state_data["log"])
    start = next(item for item in state_data["log"] if item[:2] == ["agent", "start"])
    assert start[start.index("--tools") + 1] == "example__read"
    prompted = next(item for item in state_data["log"] if item[:2] == ["agent", "prompt"])
    assert "again means stop" in prompted[3]
    outcome_path = Path(str(result["run_dir"])) / "outcome.json"
    assert json.loads(outcome_path.read_text(encoding="utf-8"))["status"] == "done"


def test_timeout_is_not_done(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PANEHITCH_FAKE_STATE", str(tmp_path / "state.json"))
    backend, _ = _fake_backend(
        tmp_path,
        [
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
            {"text": "accepted", "status": "working"},
        ],
    )
    run_dir = _fixed_run_dir(tmp_path)
    monkeypatch.setattr("panehitch.runner._run_dir", lambda parent: run_dir)
    ticks = iter((0.0, 0.0, 1.0))
    result = run_lane(
        load_lane(_lane(tmp_path, timeout=0.5)),
        backend,
        poll_s=0,
        clock=lambda: next(ticks),
        sleep=lambda _: None,
    )
    assert result["status"] == "timeout"


def test_unconfirmed_prompt_is_recorded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PANEHITCH_FAKE_STATE", str(tmp_path / "state.json"))
    backend, _ = _fake_backend(
        tmp_path,
        [
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
        ],
    )
    run_dir = _fixed_run_dir(tmp_path)
    monkeypatch.setattr("panehitch.runner._run_dir", lambda parent: run_dir)
    result = run_lane(load_lane(_lane(tmp_path)), backend, poll_s=0)
    assert result["status"] == "error"
    assert result["failure"] == "prompt_unconfirmed"


def test_blocked_marker_is_terminal_blocked(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PANEHITCH_FAKE_STATE", str(tmp_path / "state.json"))
    backend, _ = _fake_backend(
        tmp_path,
        [
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
            {"text": "accepted", "status": "working"},
            {"text": "CYCLE_DONE run-001 blocked", "status": "working"},
        ],
    )
    run_dir = _fixed_run_dir(tmp_path)
    monkeypatch.setattr("panehitch.runner._run_dir", lambda parent: run_dir)
    assert run_lane(load_lane(_lane(tmp_path)), backend, poll_s=0)["status"] == "blocked"


def test_wrong_run_marker_in_prompt_echo_cannot_complete(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PANEHITCH_FAKE_STATE", str(tmp_path / "state.json"))
    backend, _ = _fake_backend(
        tmp_path,
        [
            {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
            {"text": "accepted", "status": "working"},
            {"text": "prompt echo\nCYCLE_DONE stale ok\nmore output", "status": "working"},
        ],
    )
    run_dir = _fixed_run_dir(tmp_path)
    monkeypatch.setattr("panehitch.runner._run_dir", lambda parent: run_dir)
    ticks = iter((0.0, 0.0, 1.0))
    result = run_lane(
        load_lane(_lane(tmp_path, timeout=0.5)),
        backend,
        poll_s=0,
        clock=lambda: next(ticks),
        sleep=lambda _: None,
    )
    assert result["status"] == "timeout"
