"""Lane TOML decoding and validation."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from .models import Lane


class LaneError(ValueError):
    pass


def _table(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict):
        raise LaneError(f"missing table: {name}")
    return value


def _strings(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise LaneError(f"{name} must be a string list")
    return value


def load_lane(path: Path) -> Lane:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    agent, tools, prompt, completion, artifacts, backend, herdr, report = (
        _table(data, name)
        for name in (
            "agent",
            "tools",
            "prompt",
            "completion",
            "artifacts",
            "backend",
            "herdr",
            "report",
        )
    )
    label, cwd = data.get("label"), data.get("cwd")
    if not isinstance(label, str) or not isinstance(cwd, str):
        raise LaneError("label and cwd are required strings")
    kind = agent.get("kind")
    if kind not in {"claude", "codex", "gemini"}:
        raise LaneError("agent.kind is unsupported")
    marker, timeout_s = completion.get("marker"), data.get("timeout_s")
    if not isinstance(marker, str) or not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise LaneError("completion.marker and positive timeout_s are required")
    try:
        compiled_marker = re.compile(marker)
    except re.error as error:
        raise LaneError("completion.marker is invalid") from error
    if not {"run_id", "status"} <= set(compiled_marker.groupindex):
        raise LaneError("completion.marker needs named run_id and status groups")
    backend_kind = backend.get("kind")
    if backend_kind != "herdr":
        raise LaneError("backend.kind is unsupported")
    prompt_file = prompt.get("file")
    if not isinstance(prompt_file, str):
        raise LaneError("prompt.file is required")
    return Lane(
        label,
        Path(cwd),
        kind,
        _strings(agent.get("args", []), "agent.args"),
        _strings(tools.get("allow"), "tools.allow"),
        Path(prompt_file),
        str(prompt.get("header", "")),
        marker,
        float(timeout_s),
        _strings(artifacts.get("globs", []), "artifacts.globs"),
        backend_kind,
        str(herdr.get("workspace", "default")),
        Path(str(report.get("dir", "reports"))),
    )
