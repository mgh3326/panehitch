"""Data objects shared by command and backend layers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Lane:
    label: str
    cwd: Path
    agent_kind: str
    agent_args: list[str]
    tools: list[str]
    prompt_file: Path
    prompt_header: str
    marker: str
    timeout_s: float
    artifact_globs: list[str]
    backend_kind: str
    workspace: str
    report_dir: Path


@dataclass(frozen=True)
class Pane:
    pane_id: str
    tab_id: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class PaneSnapshot:
    text: str
    status: str | None
