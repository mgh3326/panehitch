"""The lifecycle runner and stable outcome document."""

from __future__ import annotations

import json
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backend import BackendError, PaneBackend
from .lane import Lane
from .submission import prove_submission


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


def run_lane(lane: Lane, backend: PaneBackend, *, poll_s: float = 1.0) -> dict[str, Any]:
    """Run one lane and persist an outcome irrespective of terminal state."""
    run_dir = _run_dir(lane.report_dir)
    times: dict[str, str] = {"started_at": _now()}
    outcome: dict[str, Any] = {
        "schema_version": "panehitch-cycle/v1",
        "status": "error",
        "timestamps": times,
        "pane_id": None,
        "tab_id": None,
        "run_dir": str(run_dir),
        "artifacts": [],
    }
    pane_id: str | None = None
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
        prompt = "\n\n".join(part for part in (lane.prompt_header, source) if part)
        backend.prompt(pane.pane_id, prompt)
        times["prompted_at"] = _now()
        proof = prove_submission(backend, pane.pane_id, prompt)
        outcome["submission"] = {"confirmed": proof.confirmed, "action": proof.action}
        if not proof.confirmed:
            outcome["status"] = "error"
            outcome["failure"] = "prompt_unconfirmed"
            return outcome
        deadline, marker = time.monotonic() + lane.timeout_s, re.compile(lane.marker)
        while time.monotonic() < deadline:
            snapshot = backend.read(pane.pane_id)
            matched = marker.search(snapshot.text)
            if matched:
                outcome["status"] = (
                    "blocked" if matched.groupdict().get("status") == "blocked" else "done"
                )
                outcome["completion"] = matched.group(0)
                times["completed_at"] = _now()
                break
            time.sleep(poll_s)
        else:
            outcome["status"] = "timeout"
        for pattern in lane.artifact_globs:
            for source_path in lane.cwd.glob(pattern):
                if source_path.is_file():
                    target = run_dir / source_path.name
                    shutil.copy2(source_path, target)
                    outcome["artifacts"].append(str(target))
    except (BackendError, OSError, ValueError, re.error) as error:
        outcome["error"] = str(error)
    finally:
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
