"""Prompt submission proof, deliberately distinct from prompt injection."""

from __future__ import annotations

import time
from collections.abc import Callable
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


def prove_submission(
    backend: SubmissionBackend,
    pane_id: str,
    prompt: str,
    *,
    pre_prompt_status: str | None = None,
    pre_prompt: PaneSnapshot | None = None,
    authoritative_submission: bool | None = None,
    confirmation_attempts: int = 8,
    wait_s: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> SubmissionProof:
    """Confirm delivery while never submitting an acknowledged queued message twice."""
    if confirmation_attempts < 1:
        raise ValueError("confirmation_attempts must be positive")
    baseline_status = pre_prompt.status if pre_prompt else pre_prompt_status
    before = backend.read(pane_id)
    if authoritative_submission is True:
        return SubmissionProof(True, "backend_wait", before.status, before.status)
    if authoritative_submission is False:
        return SubmissionProof(False, "backend_wait", before.status, before.status)
    pasted_chip = "[Pasted text" in before.text
    queued = "Press up to edit queued messages" in before.text
    literal_prompt = bool(prompt) and prompt in before.text
    if queued and not pasted_chip:
        return SubmissionProof(True, "queued", before.status, before.status)
    if pasted_chip or literal_prompt:
        backend.send_return(pane_id)
        return _confirm_after_return(
            backend,
            pane_id,
            prompt,
            before,
            pre_prompt,
            baseline_status,
            confirmation_attempts,
            wait_s,
            sleep,
        )
    if _submission_signal(before, prompt, pre_prompt, baseline_status):
        return SubmissionProof(True, "state_transition", before.status, before.status)
    return SubmissionProof(False, "unconfirmed", before.status, before.status)


def _confirm_after_return(
    backend: SubmissionBackend,
    pane_id: str,
    prompt: str,
    before: PaneSnapshot,
    pre_prompt: PaneSnapshot | None,
    baseline_status: str | None,
    confirmation_attempts: int,
    wait_s: float,
    sleep: Callable[[float], None],
) -> SubmissionProof:
    for attempt in range(confirmation_attempts):
        after = backend.read(pane_id)
        if _submission_signal(after, prompt, pre_prompt, baseline_status):
            return SubmissionProof(True, "return", before.status, after.status)
        if attempt + 1 < confirmation_attempts:
            sleep(wait_s)
    return SubmissionProof(False, "return", before.status, after.status)


def _submission_signal(
    snapshot: PaneSnapshot,
    prompt: str,
    pre_prompt: PaneSnapshot | None,
    baseline_status: str | None,
) -> bool:
    if baseline_status is not None and snapshot.status != baseline_status:
        return True
    if pre_prompt and snapshot.prompt_at and snapshot.prompt_at != pre_prompt.prompt_at:
        return True
    return bool(
        pre_prompt
        and snapshot.text != pre_prompt.text
        and "[Pasted text" not in snapshot.text
        and (prompt in snapshot.text or bool(snapshot.text.strip()))
    )
