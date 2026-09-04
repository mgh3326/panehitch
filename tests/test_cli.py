from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from panehitch.cli import _inject_events, _write_seen, init_templates, inject
from panehitch.models import Pane, PaneSnapshot


class Backend:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.reads = 0

    def list(self) -> Sequence[Pane]:
        return [Pane("p-1", label="review")]

    def read(self, pane_id: str) -> PaneSnapshot:
        self.reads += 1
        return PaneSnapshot("queued output", "idle" if self.reads == 1 else "working")

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
        {"target": "p-1", "confirmed": True, "action": "state_transition", "id": "e-1"}
    ]
    assert json.loads(state.read_text(encoding="utf-8")) == ["e-1"]


def test_inbox_marks_each_confirmed_event_before_later_failure(tmp_path: Path) -> None:
    inbox, prompt, state = tmp_path / "inbox", tmp_path / "prompt.md", tmp_path / "state.json"
    inbox.mkdir()
    prompt.write_text("hello", encoding="utf-8")
    (inbox / "01-good.json").write_text(
        json.dumps({"id": "good", "target": "review", "prompt_file": str(prompt)}), encoding="utf-8"
    )
    (inbox / "02-bad.json").write_text(
        json.dumps({"id": "bad", "target": "review", "prompt_file": str(tmp_path / "none.md")}),
        encoding="utf-8",
    )
    backend = Backend()
    reports = _inject_events(backend, inbox, state)
    assert json.loads(state.read_text(encoding="utf-8")) == ["good"]
    assert len(backend.prompts) == 1
    assert any(report["id"] == "bad" and report["confirmed"] is False for report in reports)
    _inject_events(backend, inbox, state)
    assert len(backend.prompts) == 1
    assert not state.with_name(f".{state.name}.tmp").exists()


def test_unconfirmed_event_does_not_advance_seen(tmp_path: Path) -> None:
    class Unconfirmed(Backend):
        def read(self, pane_id: str) -> PaneSnapshot:
            self.reads += 1
            return PaneSnapshot("", None)

    inbox, prompt, state = tmp_path / "inbox", tmp_path / "prompt.md", tmp_path / "state.json"
    inbox.mkdir()
    prompt.write_text("hello", encoding="utf-8")
    (inbox / "event.json").write_text(
        json.dumps({"id": "e-1", "target": "review", "prompt_file": str(prompt)}), encoding="utf-8"
    )
    _inject_events(Unconfirmed(), inbox, state)
    assert not state.exists()


def test_inject_reads_preview_before_prompt(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello", encoding="utf-8")
    backend = Backend()
    inject(backend, "review", prompt)
    assert backend.reads == 2
    assert backend.prompts == ["hello"]


def test_inbox_does_not_confirm_a_prompt_swallowed_by_done_pane(tmp_path: Path) -> None:
    class AlreadyDone(Backend):
        def read(self, pane_id: str) -> PaneSnapshot:
            self.reads += 1
            return PaneSnapshot("", "done")

    inbox, prompt, state = tmp_path / "inbox", tmp_path / "prompt.md", tmp_path / "state.json"
    inbox.mkdir()
    prompt.write_text("hello", encoding="utf-8")
    (inbox / "event.json").write_text(
        json.dumps({"id": "e-1", "target": "review", "prompt_file": str(prompt)}),
        encoding="utf-8",
    )
    backend = AlreadyDone()
    reports = _inject_events(backend, inbox, state)
    assert reports == [{"target": "p-1", "confirmed": False, "action": "unconfirmed", "id": "e-1"}]
    assert backend.prompts == ["hello"]
    assert not state.exists()


def test_inject_rejects_ambiguous_target_without_prompt(tmp_path: Path) -> None:
    class Ambiguous(Backend):
        def list(self) -> Sequence[Pane]:
            return [Pane("p-1", label="review"), Pane("p-2", label="review")]

    prompt = tmp_path / "prompt.md"
    prompt.write_text("hello", encoding="utf-8")
    backend = Ambiguous()
    with pytest.raises(ValueError, match="exactly one"):
        inject(backend, "review", prompt)
    assert backend.prompts == []


def test_templates_include_expected_material(tmp_path: Path) -> None:
    destination = tmp_path / "starter"
    init_templates(destination)
    assert (destination / "CLAUDE.md").exists()
    assert (destination / "prompt.md").exists()
    assert (destination / "deploy/systemd/panehitch.service.example").exists()
    assert (destination / "launchd/com.example.panehitch.plist.example").exists()


def test_templates_refuse_nonempty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "starter"
    destination.mkdir()
    (destination / "keep.md").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        init_templates(destination)
    assert (destination / "keep.md").read_text(encoding="utf-8") == "keep"


def test_seen_state_uses_atomic_replace(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state.json"
    calls: list[tuple[Path, Path]] = []
    original = Path.replace

    def record_replace(source: Path, target: Path) -> Path:
        calls.append((source, target))
        return original(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)
    _write_seen(state, {"e-1"})
    assert calls == [(state.with_name(".state.json.tmp"), state)]
    assert json.loads(state.read_text(encoding="utf-8")) == ["e-1"]
