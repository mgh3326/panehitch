"""Backend protocol and the current command-line adapter."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from .models import Pane, PaneSnapshot


class BackendError(RuntimeError):
    """A backend command failed or returned an unusable response."""


class PaneBackend(Protocol):
    """Minimum pane operations; alternate multiplexers can implement this."""

    def start(
        self,
        *,
        session: str,
        workspace: str,
        cwd: Path,
        kind: str,
        args: Sequence[str],
        tools: Sequence[str],
        label: str,
    ) -> Pane: ...

    def list(self) -> Sequence[Pane]: ...

    def prompt(self, pane_id: str, text: str) -> None: ...

    def read(self, pane_id: str) -> PaneSnapshot: ...

    def send_return(self, pane_id: str) -> None: ...

    def close(self, pane_id: str) -> None: ...


class HerdrBackend:
    """Adapter for the currently supported pane command-line program."""

    def __init__(self, executable: str = "herdr") -> None:
        self.executable = executable

    def _json(self, args: Sequence[str]) -> Any:
        try:
            result = subprocess.run(
                [self.executable, *args], text=True, capture_output=True, check=False, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BackendError("backend command unavailable") from error
        if result.returncode:
            raise BackendError(result.stderr.strip() or "backend command failed")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise BackendError("backend returned invalid JSON") from error

    @staticmethod
    def _items(payload: Any) -> Sequence[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("agents", "panes", "items"):
                if isinstance(payload.get(key), list):
                    return [item for item in payload[key] if isinstance(item, dict)]
            return [payload]
        return []

    @staticmethod
    def _pane(item: dict[str, Any]) -> Pane:
        pane_id = item.get("pane_id") or item.get("id")
        if not isinstance(pane_id, str) or not pane_id:
            raise BackendError("backend response has no pane_id")
        tab_id = item.get("tab_id")
        label = item.get("label") or item.get("name")
        return Pane(
            pane_id,
            tab_id if isinstance(tab_id, str) else None,
            label if isinstance(label, str) else None,
        )

    def start(
        self,
        *,
        session: str,
        workspace: str,
        cwd: Path,
        kind: str,
        args: Sequence[str],
        tools: Sequence[str],
        label: str,
    ) -> Pane:
        payload = self._json(
            [
                "agent",
                "start",
                "--session",
                session,
                "--workspace",
                workspace,
                "--cwd",
                str(cwd),
                "--kind",
                kind,
                "--label",
                label,
                "--tools",
                ",".join(tools),
                "--json",
                *args,
            ]
        )
        return self._pane(self._items(payload)[0])

    def list(self) -> Sequence[Pane]:
        return [self._pane(item) for item in self._items(self._json(["agent", "list", "--json"]))]

    def prompt(self, pane_id: str, text: str) -> None:
        self._json(["agent", "prompt", pane_id, text, "--json"])

    def read(self, pane_id: str) -> PaneSnapshot:
        payload = self._json(["agent", "read", pane_id, "--lines", "10", "--json"])
        item = self._items(payload)[0]
        text = item.get("text") or item.get("output") or ""
        status = item.get("status")
        return PaneSnapshot(str(text), status if isinstance(status, str) else None)

    def send_return(self, pane_id: str) -> None:
        self._json(["agent", "send-keys", pane_id, "return", "--json"])

    def close(self, pane_id: str) -> None:
        self._json(["agent", "close", pane_id, "--json"])
