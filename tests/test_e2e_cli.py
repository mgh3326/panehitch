from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


def test_run_command_with_fake_backend(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "reads": [
                    {"text": "[Pasted text #1 +2 lines]", "status": "idle"},
                    {"text": "accepted", "status": "working"},
                    {"text": "CYCLE_DONE {run_id} ok", "status": "working"},
                ]
            }
        ),
        encoding="utf-8",
    )
    fake = tmp_path / "fake-pane"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys

path = pathlib.Path(os.environ['PANEHITCH_FAKE_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
if args[:2] == ['workspace', 'list']:
    result = {'id': 'cli:workspace:list', 'result': {'workspaces': [{'label': 'w', 'workspace_id': 'w-1'}]}}
elif args[:2] == ['tab', 'create']:
    result = {'id': 'cli:tab:create', 'result': {'root_pane': {'pane_id': 'p-e2e', 'tab_id': 't-e2e'}}}
elif args[:2] == ['agent', 'read']:
    result = state['reads'].pop(0)
    result['text'] = result['text'].replace('{run_id}', state.get('run_id', 'missing'))
    state['current'] = result
    path.write_text(json.dumps(state))
    print(result['text'])
    raise SystemExit(0)
elif args[:2] == ['agent', 'get']:
    current = state.get('current', {'status': 'idle'})
    result = {'id': 'cli:agent:get', 'result': {'agent': {'pane_id': 'p-e2e', 'tab_id': 't-e2e', 'label': 'e2e', 'agent_status': current.get('status')}}}
elif args[:2] == ['agent', 'prompt']:
    state['run_id'] = args[3].split('Run identity: ', 1)[1].split('.', 1)[0]
    result = {'ok': True}
else:
    result = {'id': 'cli:ok', 'result': {'ok': True}}
path.write_text(json.dumps(state))
print(json.dumps(result))
""",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    prompt = tmp_path / "prompt.md"
    prompt.write_text("finish", encoding="utf-8")
    lane = tmp_path / "lane.toml"
    lane.write_text(
        f'''label = "e2e"
cwd = "{tmp_path}"
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
dir = "{tmp_path / "reports"}"
''',
        encoding="utf-8",
    )
    environment = dict(os.environ, PANEHITCH_FAKE_STATE=str(state))
    completed = subprocess.run(
        [
            "uv",
            "run",
            "panehitch",
            "run",
            "--lane",
            str(lane),
            "--herdr",
            str(fake),
            "--poll-s",
            "0",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == "done"
    assert json.loads((Path(str(result["run_dir"])) / "outcome.json").read_text()) == result
