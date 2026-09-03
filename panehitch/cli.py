"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .backend import BackendError, HerdrBackend, Pane
from .lane import LaneError, load_lane
from .models import PaneSnapshot
from .runner import run_lane
from .submission import prove_submission


class InjectionBackend(Protocol):
    def list(self) -> Sequence[Pane]: ...

    def prompt(self, pane_id: str, text: str) -> None: ...

    def read(self, pane_id: str) -> PaneSnapshot: ...

    def send_return(self, pane_id: str) -> None: ...


def _resolve(backend: InjectionBackend, target: str) -> tuple[Pane, PaneSnapshot]:
    choices = [pane for pane in backend.list() if pane.pane_id == target or pane.label == target]
    if len(choices) != 1:
        raise ValueError("target must identify exactly one pane")
    pane = choices[0]
    preview = backend.read(pane.pane_id)  # required preview before a disruptive prompt
    return pane, preview


def inject(backend: InjectionBackend, target: str, source: Path) -> dict[str, object]:
    pane, preview = _resolve(backend, target)
    prompt = source.read_text(encoding="utf-8")
    backend.prompt(pane.pane_id, prompt)
    proof = prove_submission(
        backend, pane.pane_id, prompt, pre_prompt_status=preview.status
    )
    return {"target": pane.pane_id, "confirmed": proof.confirmed, "action": proof.action}


def _write_seen(state: Path, seen: set[str]) -> None:
    state.parent.mkdir(parents=True, exist_ok=True)
    temporary = state.with_name(f".{state.name}.tmp")
    temporary.write_text(json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8")
    temporary.replace(state)


def _inject_events(backend: InjectionBackend, inbox: Path, state: Path) -> list[dict[str, object]]:
    seen = set(json.loads(state.read_text(encoding="utf-8"))) if state.exists() else set()
    reports: list[dict[str, object]] = []
    for event_path in sorted(inbox.glob("*.json")):
        event = json.loads(event_path.read_text(encoding="utf-8"))
        event_id, target, prompt_file = (
            event.get("id"),
            event.get("target"),
            event.get("prompt_file"),
        )
        if (
            not all(isinstance(value, str) and value for value in (event_id, target, prompt_file))
            or event_id in seen
        ):
            continue
        try:
            report = inject(backend, target, Path(prompt_file))
        except (OSError, ValueError) as error:
            reports.append({"id": event_id, "confirmed": False, "error": str(error)})
            continue
        report["id"] = event_id
        reports.append(report)
        if report["confirmed"]:
            seen.add(event_id)
            _write_seen(state, seen)
    return reports


def _template_source() -> Path:
    bundled = Path(__file__).resolve().parent / "templates"
    return bundled if bundled.exists() else Path(__file__).resolve().parents[1] / "templates"


def init_templates(destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("template destination must be empty")
    shutil.copytree(_template_source(), destination, dirs_exist_ok=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="panehitch")
    commands = root.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--lane", required=True, type=Path)
    run.add_argument("--herdr", default="herdr")
    run.add_argument("--poll-s", type=float, default=1.0)
    inject_parser = commands.add_parser("inject")
    inject_parser.add_argument("--target")
    inject_parser.add_argument("--file", type=Path)
    inject_parser.add_argument("--inbox", type=Path)
    inject_parser.add_argument("--state", type=Path)
    inject_parser.add_argument("--herdr", default="herdr")
    templates = commands.add_parser("templates")
    template_commands = templates.add_subparsers(dest="template_command", required=True)
    init = template_commands.add_parser("init")
    init.add_argument("directory", type=Path)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            lane = load_lane(args.lane)
            result = run_lane(lane, _backend_for(lane.backend_kind, args.herdr), poll_s=args.poll_s)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] in {"done", "blocked"} else 1
        if args.command == "inject":
            backend = HerdrBackend(args.herdr)
            if args.inbox:
                if not args.state:
                    raise ValueError("--state is required with --inbox")
                result: object = _inject_events(backend, args.inbox, args.state)
            elif args.target and args.file:
                result = inject(backend, args.target, args.file)
            else:
                raise ValueError("use --target with --file, or --inbox with --state")
            print(json.dumps(result, sort_keys=True))
            return 0
        init_templates(args.directory)
        return 0
    except (BackendError, LaneError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"panehitch: {error}", file=sys.stderr)
        return 2


def _backend_for(kind: str, executable: str) -> HerdrBackend:
    if kind == "herdr":
        return HerdrBackend(executable)
    raise LaneError("backend.kind is unsupported")
