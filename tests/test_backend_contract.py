from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from panehitch.backend import BackendError, HerdrBackend, HerdrErrorCode


def _executable(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

state_path = pathlib.Path(os.environ['PANEHITCH_BACKEND_STATE'])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state['calls'].append(args)
before_agent_args = args[:args.index('--')] if '--' in args else args
allowed_flags = {
    '--workspace', '--cwd', '--label', '--no-focus', '--kind', '--pane',
    '--timeout', '--source', '--lines',
}
if (
    (args[:2] in (['agent', 'list'], ['workspace', 'list']) and len(args) != 2)
    or any(arg.startswith('--') and arg not in allowed_flags for arg in before_agent_args)
):
    print('usage: fake-herdr', file=sys.stderr)
    state_path.write_text(json.dumps(state))
    raise SystemExit(2)
if args[:2] == ['agent', 'start'] and state.get('fail_start'):
    print(json.dumps({'error': {'code': 'startup_failed'}}), file=sys.stderr)
    state_path.write_text(json.dumps(state))
    raise SystemExit(1)
if args[:2] == ['workspace', 'list']:
    output = {'id': 'cli:workspace:list', 'result': {'workspaces': [{'label': 'work', 'workspace_id': 'w1'}]}}
elif args[:2] == ['tab', 'create']:
    output = {'id': 'cli:tab:create', 'result': {'root_pane': {'pane_id': 'w1:p1', 'tab_id': 'w1:t1'}}}
elif args[:2] == ['agent', 'list']:
    output = state['agent_list']
elif args[:2] == ['agent', 'get']:
    output = {'id': 'cli:agent:get', 'result': {'agent': {'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'name': 'sample', 'agent_status': state['status']}}}
elif args[:2] == ['agent', 'read']:
    state_path.write_text(json.dumps(state))
    print('visible output')
    raise SystemExit(0)
else:
    output = {'id': 'cli:ok', 'result': {'ok': True}}
state_path.write_text(json.dumps(state))
print(json.dumps(output))
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def test_adapter_uses_current_cli_shapes(tmp_path: Path, monkeypatch) -> None:
    fixture = Path(__file__).parent / "fixtures" / "herdr-agent-list.json"
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {"calls": [], "status": "working", "agent_list": json.loads(fixture.read_text())}
        ),
        encoding="utf-8",
    )
    executable = tmp_path / "fake-herdr"
    _executable(executable)
    monkeypatch.setenv("PANEHITCH_BACKEND_STATE", str(state))
    waits: list[float] = []
    backend = HerdrBackend(str(executable), sleep=waits.append)
    pane = backend.start(
        workspace="work",
        cwd=tmp_path,
        kind="claude",
        args=[],
        tools=["Read"],
        label="sample",
    )
    assert pane.pane_id == "w1:p1"
    assert backend.list()[0].tab_id == "w1:t1"
    assert backend.read(pane.pane_id).status == "working"
    backend.prompt(pane.pane_id, "hello")
    backend.send_return(pane.pane_id)
    backend.close(pane.pane_id)
    calls = json.loads(state.read_text())["calls"]
    start = next(call for call in calls if call[:2] == ["agent", "start"])
    tab_create = next(call for call in calls if call[:2] == ["tab", "create"])
    assert tab_create == [
        "tab",
        "create",
        "--workspace",
        "w1",
        "--cwd",
        str(tmp_path),
        "--label",
        "sample",
        "--no-focus",
    ]
    assert start == [
        "agent",
        "start",
        "sample",
        "--kind",
        "claude",
        "--pane",
        "w1:p1",
        "--timeout",
        "120000",
        "--",
        "--allowedTools",
        "Read",
    ]
    assert ["agent", "read", "w1:p1", "--source", "recent-unwrapped", "--lines", "120"] in calls
    assert ["agent", "prompt", "w1:p1", "hello"] in calls
    assert ["tab", "close", "w1:t1"] in calls
    assert waits == []


def test_fake_rejects_unknown_flags_like_cli(tmp_path: Path, monkeypatch) -> None:
    fixture = Path(__file__).parent / "fixtures" / "herdr-agent-list.json"
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"calls": [], "status": "idle", "agent_list": json.loads(fixture.read_text())}),
        encoding="utf-8",
    )
    executable = tmp_path / "fake-herdr"
    _executable(executable)
    monkeypatch.setenv("PANEHITCH_BACKEND_STATE", str(state))
    for args in (
        ["agent", "list", "--json"],
        ["agent", "send-keys", "w1:p1", "return", "--json"],
        ["tab", "create", "--json"],
        ["agent", "get", "w1:p1", "--quiet"],
    ):
        completed = subprocess.run(
            [str(executable), *args], text=True, capture_output=True, check=False
        )
        assert completed.returncode == 2
        assert "usage:" in completed.stderr


def test_start_failure_closes_created_tab(tmp_path: Path, monkeypatch) -> None:
    fixture = Path(__file__).parent / "fixtures" / "herdr-agent-list.json"
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "calls": [],
                "status": "idle",
                "agent_list": json.loads(fixture.read_text()),
                "fail_start": True,
            }
        ),
        encoding="utf-8",
    )
    executable = tmp_path / "fake-herdr"
    _executable(executable)
    monkeypatch.setenv("PANEHITCH_BACKEND_STATE", str(state))
    with pytest.raises(BackendError):
        HerdrBackend(str(executable)).start(
            workspace="work", cwd=tmp_path, kind="claude", args=[], tools=["Read"], label="sample"
        )
    assert ["tab", "close", "w1:t1"] in json.loads(state.read_text())["calls"]


def _start_with_responses(
    monkeypatch, responses: list[object]
) -> tuple[HerdrBackend, list[list[str]]]:
    backend = HerdrBackend("fake-herdr", sleep=lambda _: None)
    calls: list[list[str]] = []

    monkeypatch.setattr(backend, "_workspace_id", lambda workspace: "w1")
    monkeypatch.setattr(
        backend,
        "_json",
        lambda args: {"root_pane": {"pane_id": "w1:p1", "tab_id": "w1:t1"}},
    )
    monkeypatch.setattr(
        backend,
        "_agent",
        lambda pane_id: {
            "pane_id": pane_id,
            "tab_id": "w1:t1",
            "name": "sample",
            "agent_status": "idle",
        },
    )
    pending = iter(responses)

    def run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[:2] == ["agent", "start"]:
            outcome = next(pending)
            if isinstance(outcome, BackendError):
                raise outcome
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backend, "_run", run)
    return backend, calls


def _backend_error(code: str) -> BackendError:
    return BackendError(json.dumps({"error": {"code": code}}))


def test_start_retries_busy_agent_response(monkeypatch, tmp_path: Path) -> None:
    backend, calls = _start_with_responses(monkeypatch, [BackendError("opaque"), object()])
    monkeypatch.setattr(backend, "_error_code", lambda error: HerdrErrorCode.PANE_BUSY)
    pane = backend.start(
        workspace="work", cwd=tmp_path, kind="claude", args=[], tools=["Read"], label="sample"
    )
    assert pane.pane_id == "w1:p1"
    assert sum(call[:2] == ["agent", "start"] for call in calls) == 2


def test_start_waits_for_not_ready_agent_response(monkeypatch, tmp_path: Path) -> None:
    backend, calls = _start_with_responses(monkeypatch, [BackendError("opaque")])
    monkeypatch.setattr(backend, "_error_code", lambda error: HerdrErrorCode.NOT_READY)
    waited: list[str] = []
    monkeypatch.setattr(backend, "_wait_for_settled_start", waited.append)
    backend.start(
        workspace="work", cwd=tmp_path, kind="claude", args=[], tools=["Read"], label="sample"
    )
    assert waited == ["w1:p1"]
    assert sum(call[:2] == ["agent", "start"] for call in calls) == 1


def test_start_fails_for_unrecognized_agent_response(monkeypatch, tmp_path: Path) -> None:
    backend, calls = _start_with_responses(monkeypatch, [BackendError("opaque")])
    monkeypatch.setattr(backend, "_error_code", lambda error: None)
    with pytest.raises(BackendError, match="opaque"):
        backend.start(
            workspace="work",
            cwd=tmp_path,
            kind="claude",
            args=[],
            tools=["Read"],
            label="sample",
        )
    assert ["tab", "close", "w1:t1"] in calls


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("agent_not_ready", HerdrErrorCode.NOT_READY),
        ("agent_pane_busy", HerdrErrorCode.PANE_BUSY),
        ("timeout", HerdrErrorCode.TIMEOUT),
        ("other", None),
    ],
)
def test_structured_start_error_codes_are_enums(code: str, expected: HerdrErrorCode | None) -> None:
    assert HerdrBackend._error_code(_backend_error(code)) is expected


def test_settled_start_fails_immediately_when_blocked(monkeypatch) -> None:
    backend = HerdrBackend("fake-herdr", sleep=lambda _: None)
    calls: list[str] = []

    def agent(pane_id: str) -> dict[str, str]:
        calls.append(pane_id)
        return {"agent_status": "blocked"}

    monkeypatch.setattr(backend, "_agent", agent)
    with pytest.raises(BackendError, match="trust the working directory"):
        backend._wait_for_settled_start("w1:p1")
    assert calls == ["w1:p1"]


def test_settled_start_bounds_unknown_status(monkeypatch) -> None:
    backend = HerdrBackend("fake-herdr", sleep=lambda _: None)
    calls = 0

    def agent(pane_id: str) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"agent_status": "unknown"}

    monkeypatch.setattr(backend, "_agent", agent)
    with pytest.raises(BackendError, match="remained unknown"):
        backend._wait_for_settled_start("w1:p1")
    assert calls == 20
