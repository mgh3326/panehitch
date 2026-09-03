from __future__ import annotations

import json
import stat
from pathlib import Path

from panehitch.backend import HerdrBackend


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
if args[:2] == ['workspace', 'list']:
    output = {'id': 'cli:workspace:list', 'result': {'workspaces': [{'label': 'work', 'workspace_id': 'w1'}]}}
elif args[:2] == ['tab', 'create']:
    output = {'id': 'cli:tab:create', 'result': {'root_pane': {'pane_id': 'w1:p1', 'tab_id': 'w1:t1'}}}
elif args[:2] == ['agent', 'list']:
    output = state['agent_list']
elif args[:2] == ['agent', 'get']:
    output = {'id': 'cli:agent:get', 'result': {'agent': {'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'label': 'sample', 'agent_status': state['status']}}}
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
    backend = HerdrBackend(str(executable))
    pane = backend.start(
        session="unused",
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
    assert start == [
        "agent",
        "start",
        "sample",
        "--kind",
        "claude",
        "--pane",
        "w1:p1",
        "--timeout",
        "3001",
        "--",
        "--allowedTools",
        "Read",
    ]
    assert ["agent", "read", "w1:p1", "--source", "recent-unwrapped", "--lines", "120"] in calls
    assert ["agent", "prompt", "w1:p1", "hello"] in calls
    assert ["tab", "close", "w1:t1"] in calls
