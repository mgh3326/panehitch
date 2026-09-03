from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from panehitch.cli import _inject_events, init_templates
from panehitch.models import Pane, PaneSnapshot


class Backend:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def list(self) -> Sequence[Pane]:
        return [Pane("p-1", label="review")]

    def read(self, pane_id: str) -> PaneSnapshot:
        return PaneSnapshot("queued output", "working")

    def prompt(self, pane_id: str, text: str) -> None:
        self.prompts.append(text)

    def send_return(self, pane_id: str) -> None:
        raise AssertionError("working pane must not receive return")


def test_inbox_seen_advances_only_after_confirmation(tmp_path: Path) -> None:
    inbox, prompt, state = tmp_path / "inbox", tmp_path / "prompt.md", tmp_path / "state.json"
    inbox.mkdir()
    prompt.write_text("hello", encoding="utf-8")
    (inbox / "event.json").write_text(
        json.dumps({"id": "e-1", "target": "review", "prompt_file": str(prompt)}), encoding="utf-8"
    )
    reports = _inject_events(Backend(), inbox, state)
    assert reports == [
        {"target": "p-1", "confirmed": True, "action": "already_working", "id": "e-1"}
    ]
    assert json.loads(state.read_text(encoding="utf-8")) == ["e-1"]


def test_templates_include_expected_material(tmp_path: Path) -> None:
    destination = tmp_path / "starter"
    init_templates(destination)
    assert (destination / "CLAUDE.md").exists()
    assert (destination / "deploy/systemd/panehitch.service.example").exists()
    assert (destination / "launchd/com.example.panehitch.plist.example").exists()
