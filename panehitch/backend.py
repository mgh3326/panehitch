"""Backend protocol and the adapter for the current pane command-line tool."""

from __future__ import annotations

import json
import subprocess
import time
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
    """Adapter for the 0.8 command surface, with tab ownership retained locally."""

    def __init__(self, executable: str = "herdr", *, command_timeout_s: float = 130) -> None:
        self.executable = executable
        self.command_timeout_s = command_timeout_s
        self._tabs: dict[str, str] = {}

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.executable, *args],
                text=True,
                capture_output=True,
                check=False,
                timeout=self.command_timeout_s,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise BackendError("backend command unavailable") from error
        if result.returncode:
            raise BackendError(result.stderr.strip() or "backend command failed")
        return result

    def _json(self, args: Sequence[str]) -> dict[str, Any]:
        try:
            payload = json.loads(self._run(args).stdout)
        except json.JSONDecodeError as error:
            raise BackendError("backend returned invalid JSON") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            raise BackendError("backend response has no result envelope")
        return payload["result"]

    @staticmethod
    def _pane(item: dict[str, Any]) -> Pane:
        pane_id = item.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            raise BackendError("backend response has no pane_id")
        tab_id, label = item.get("tab_id"), item.get("label") or item.get("name")
        return Pane(
            pane_id,
            tab_id if isinstance(tab_id, str) else None,
            label if isinstance(label, str) else None,
        )

    def _agent(self, pane_id: str) -> dict[str, Any]:
        agent = self._json(["agent", "get", pane_id]).get("agent")
        if not isinstance(agent, dict):
            raise BackendError("backend response has no agent")
        return agent

    def _workspace_id(self, label_or_id: str) -> str:
        workspaces = self._json(["workspace", "list"]).get("workspaces")
        if not isinstance(workspaces, list):
            raise BackendError("backend response has no workspaces")
        for workspace in workspaces:
            if isinstance(workspace, dict) and label_or_id in {
                workspace.get("label"),
                workspace.get("workspace_id"),
            }:
                workspace_id = workspace.get("workspace_id")
                if isinstance(workspace_id, str):
                    return workspace_id
        raise BackendError("workspace was not found")

    def _wait_for_settled_start(self, pane_id: str) -> None:
        deadline = time.monotonic() + 120
        unknown_count = 0
        while time.monotonic() < deadline:
            status = self._agent(pane_id).get("agent_status")
            if status in {"idle", "done"}:
                return
            if status == "blocked":
                raise BackendError(
                    "agent startup blocked; trust the working directory before running"
                )
            if status == "unknown":
                unknown_count += 1
                if unknown_count >= 20:
                    raise BackendError("agent startup remained unknown")
            else:
                unknown_count = 0
            time.sleep(0.25)
        raise BackendError("agent did not reach a settled startup state")

    @staticmethod
    def _error_code(error: BackendError) -> str | None:
        try:
            payload = json.loads(str(error))
        except json.JSONDecodeError:
            return None
        value = payload.get("error") if isinstance(payload, dict) else None
        code = value.get("code") if isinstance(value, dict) else None
        return code if isinstance(code, str) else None

    def start(
        self,
        *,
        workspace: str,
        cwd: Path,
        kind: str,
        args: Sequence[str],
        tools: Sequence[str],
        label: str,
    ) -> Pane:
        workspace_id = self._workspace_id(workspace)
        created = self._json(
            [
                "tab",
                "create",
                "--workspace",
                workspace_id,
                "--cwd",
                str(cwd),
                "--label",
                label,
                "--no-focus",
            ]
        )
        root_pane = created.get("root_pane")
        if not isinstance(root_pane, dict):
            raise BackendError("tab creation returned no root pane")
        tab = created.get("tab")
        if (
            isinstance(tab, dict)
            and "tab_id" not in root_pane
            and isinstance(tab.get("tab_id"), str)
        ):
            root_pane = {**root_pane, "tab_id": tab["tab_id"]}
        pane = self._pane(root_pane)
        try:
            start_args = [
                "agent",
                "start",
                label,
                "--kind",
                kind,
                "--pane",
                pane.pane_id,
                "--timeout",
                "120000",
                "--",
                *args,
                "--allowedTools",
                ",".join(tools),
            ]
            for attempt in range(40):
                try:
                    self._run(start_args)
                    break
                except BackendError as error:
                    code = self._error_code(error)
                    if code in {"agent_not_ready", "timeout"}:
                        self._wait_for_settled_start(pane.pane_id)
                        break
                    if code == "agent_pane_busy" and attempt < 39:
                        time.sleep(0.25)
                        continue
                    raise
            # A recognized agent can report a transient startup block before it
            # reaches the shell-ready idle state. Wait through that documented
            # transition; a persistent block still fails closed.
            started = self._pane(self._agent(pane.pane_id))
        except BackendError:
            if pane.tab_id:
                try:
                    self._run(["tab", "close", pane.tab_id])
                except BackendError:
                    pass
            raise
        if not started.tab_id:
            raise BackendError("agent response has no tab_id")
        self._tabs[started.pane_id] = started.tab_id
        return started

    def list(self) -> Sequence[Pane]:
        agents = self._json(["agent", "list"]).get("agents")
        if not isinstance(agents, list):
            raise BackendError("backend response has no agents")
        return [self._pane(agent) for agent in agents if isinstance(agent, dict)]

    def prompt(self, pane_id: str, text: str) -> None:
        self._run(["agent", "prompt", pane_id, text])
        # Give the authoritative status tracker one sampling interval to observe
        # the post-prompt lifecycle transition before submission proof reads it.
        time.sleep(0.5)

    def read(self, pane_id: str) -> PaneSnapshot:
        text = self._run(
            ["agent", "read", pane_id, "--source", "recent-unwrapped", "--lines", "120"]
        ).stdout
        status = self._agent(pane_id).get("agent_status")
        return PaneSnapshot(text, status if isinstance(status, str) else None)

    def send_return(self, pane_id: str) -> None:
        self._run(["agent", "send-keys", pane_id, "return"])

    def close(self, pane_id: str) -> None:
        tab_id = self._tabs.get(pane_id) or self._pane(self._agent(pane_id)).tab_id
        if not tab_id:
            raise BackendError("agent response has no tab_id")
        self._run(["tab", "close", tab_id])
        self._tabs.pop(pane_id, None)
