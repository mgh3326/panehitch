"""Prompt submission proof, deliberately distinct from prompt injection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import PaneSnapshot


class SubmissionBackend(Protocol):
    def read(self, pane_id: str) -> PaneSnapshot: ...

    def send_return(self, pane_id: str) -> None: ...


@dataclass(frozen=True)
class SubmissionProof:
    confirmed: bool
    action: str
    before_status: str | None
    after_status: str | None


def prove_submission(backend: SubmissionBackend, pane_id: str, prompt: str) -> SubmissionProof:
    """Confirm delivery while never submitting an acknowledged queued message twice."""
    before = backend.read(pane_id)
    pasted_chip = "[Pasted text" in before.text
    queued = "Press up to edit queued messages" in before.text
    literal_prompt = bool(prompt) and prompt in before.text
    if queued and not pasted_chip:
        return SubmissionProof(True, "queued", before.status, before.status)
    if pasted_chip or literal_prompt:
        backend.send_return(pane_id)
        after = backend.read(pane_id)
        still_present = "[Pasted text" in after.text or (bool(prompt) and prompt in after.text)
        return SubmissionProof(not still_present, "return", before.status, after.status)
    if before.status == "idle":
        after = backend.read(pane_id)
        if after.status == "working":
            return SubmissionProof(True, "state_transition", before.status, after.status)
        return SubmissionProof(False, "unconfirmed", before.status, after.status)
    return SubmissionProof(True, "already_working", before.status, before.status)
