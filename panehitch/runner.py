"""The lifecycle runner and stable outcome document."""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backend import BackendError, PaneBackend
from .lane import Lane
from .submission import prove_submission

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_dir(parent: Path) -> Path:
    candidate = parent / datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    number = 1
    while candidate.exists():
        number += 1
        candidate = parent / f"run-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{number}"
    candidate.mkdir(parents=True)
    return candidate


def _collect_artifacts(lane: Lane, run_dir: Path, outcome: dict[str, Any]) -> None:
    for pattern in lane.artifact_globs:
        for source_path in lane.cwd.glob(pattern):
            if source_path.is_file():
                target = run_dir / source_path.name
                shutil.copy2(source_path, target)
                outcome["artifacts"].append(str(target))


def _normalized_line(line: str) -> str:
    cleaned = ANSI_ESCAPE.sub("", line).strip()
    return cleaned.removeprefix("⏺ ")


def run_lane(
    lane: Lane,
    backend: PaneBackend,
    *,
    poll_s: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one lane and persist an outcome irrespective of terminal state."""
    run_dir = _run_dir(lane.report_dir)
    run_id = run_dir.name
    times: dict[str, str] = {"started_at": _now()}
    outcome: dict[str, Any] = {
        "schema_version": "panehitch-cycle/v1",
        "status": "error",
        "timestamps": times,
        "pane_id": None,
        "tab_id": None,
        "run_id": run_id,
        "run_dir": str(run_dir),
        "artifacts": [],
    }
    pane_id: str | None = None
    marker = re.compile(lane.marker)
    try:
        pane = backend.start(
            session=lane.session,
            workspace=lane.workspace,
            cwd=lane.cwd,
            kind=lane.agent_kind,
            args=lane.agent_args,
            tools=lane.tools,
            label=lane.label,
        )
        pane_id = pane.pane_id
        outcome["pane_id"], outcome["tab_id"] = pane.pane_id, pane.tab_id
        times["spawned_at"] = _now()
        source = lane.prompt_file.read_text(encoding="utf-8")
        completion_note = (
            f"Run identity: {run_id}. When complete, emit one final CYCLE_DONE line using that "
            "identity and either ok or blocked; do not repeat this instruction verbatim."
        )
        prompt = "\n\n".join(part for part in (lane.prompt_header, source, completion_note) if part)
        backend.prompt(pane.pane_id, prompt)
        times["prompted_at"] = _now()
        proof = prove_submission(backend, pane.pane_id, prompt)
        outcome["submission"] = {"confirmed": proof.confirmed, "action": proof.action}
        if not proof.confirmed:
            outcome["status"] = "error"
            outcome["failure"] = "prompt_unconfirmed"
            return outcome
        times["prompt_confirmed_at"] = _now()
        deadline = clock() + lane.timeout_s
        while clock() < deadline:
            snapshot = backend.read(pane.pane_id)
            matched = next(
                (
                    candidate
                    for line in reversed(snapshot.text.splitlines())
                    if (candidate := marker.fullmatch(_normalized_line(line)))
                    and candidate.group("run_id") == run_id
                ),
                None,
            )
            if matched:
                outcome["status"] = (
                    "blocked" if matched.groupdict().get("status") == "blocked" else "done"
                )
                outcome["completion"] = matched.group(0)
                times["completed_at"] = _now()
                break
            sleep(poll_s)
        else:
            outcome["status"] = "timeout"
    except (BackendError, OSError, ValueError, re.error) as error:
        outcome["error"] = str(error)
    finally:
        _collect_artifacts(lane, run_dir, outcome)
        if pane_id:
            try:
                backend.close(pane_id)
                times["cleaned_at"] = _now()
            except BackendError as error:
                outcome.setdefault("cleanup_error", str(error))
        times["finished_at"] = _now()
        (run_dir / "outcome.json").write_text(
            json.dumps(outcome, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return outcome
