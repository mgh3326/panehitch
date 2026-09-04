from __future__ import annotations

from dataclasses import dataclass

from panehitch.models import PaneSnapshot
from panehitch.submission import prove_submission


@dataclass
class FakeBackend:
    snapshots: list[PaneSnapshot]
    returns: int = 0

    def read(self, pane_id: str) -> PaneSnapshot:
        return self.snapshots.pop(0)

    def send_return(self, pane_id: str) -> None:
        self.returns += 1


def test_pasted_chip_needs_return_and_recheck() -> None:
    backend = FakeBackend(
        [
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
            PaneSnapshot("working", "working"),
        ]
    )
    proof = prove_submission(
        backend,
        "p-1",
        "a long prompt",
        pre_prompt=PaneSnapshot("before", "idle"),
    )
    assert proof.confirmed is True
    assert proof.action == "return"
    assert backend.returns == 1


def test_authoritative_backend_wait_confirms_without_screen_signal() -> None:
    snapshot = PaneSnapshot("", "done")
    proof = prove_submission(
        FakeBackend([snapshot]),
        "p-1",
        "prompt",
        pre_prompt=snapshot,
        authoritative_submission=True,
    )
    assert proof.confirmed is True
    assert proof.action == "backend_wait"


def test_failed_authoritative_backend_wait_fails_closed() -> None:
    snapshot = PaneSnapshot("", "done")
    proof = prove_submission(
        FakeBackend([snapshot]),
        "p-1",
        "prompt",
        pre_prompt=snapshot,
        authoritative_submission=False,
    )
    assert proof.confirmed is False
    assert proof.action == "backend_wait"


def test_pasted_chip_still_present_is_unconfirmed() -> None:
    backend = FakeBackend(
        [
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
        ]
    )
    assert (
        prove_submission(backend, "p-1", "prompt", confirmation_attempts=2, wait_s=0).confirmed
        is False
    )


def test_queued_message_does_not_receive_return() -> None:
    backend = FakeBackend(
        [
            PaneSnapshot("Press up to edit queued messages\nprompt", "idle"),
            PaneSnapshot("still idle", "idle"),
        ]
    )
    proof = prove_submission(backend, "p-1", "prompt")
    assert proof.confirmed is True
    assert proof.action == "queued"
    assert backend.returns == 0


def test_unchanged_working_pane_fails_closed() -> None:
    snapshot = PaneSnapshot("normal output", "working")
    proof = prove_submission(FakeBackend([snapshot]), "p-1", "prompt", pre_prompt=snapshot)
    assert proof.confirmed is False


def test_done_is_submission_signal_for_an_instant_turn() -> None:
    proof = prove_submission(
        FakeBackend([PaneSnapshot("final output", "done")]),
        "p-1",
        "prompt",
        pre_prompt_status="idle",
    )
    assert proof.confirmed is True
    assert proof.action == "state_transition"


def test_done_without_a_post_prompt_transition_fails_closed() -> None:
    proof = prove_submission(
        FakeBackend([PaneSnapshot("ordinary output", "done")]),
        "p-1",
        "prompt",
        pre_prompt_status="done",
    )
    assert proof.confirmed is False


def test_missing_status_fails_closed() -> None:
    backend = FakeBackend([PaneSnapshot("normal output", None)])
    proof = prove_submission(backend, "p-1", "prompt")
    assert proof.confirmed is False
    assert proof.action == "unconfirmed"


def test_chip_overrides_queued_notice_and_uses_one_return() -> None:
    backend = FakeBackend(
        [
            PaneSnapshot("[Pasted text #1 +2 lines]\nPress up to edit queued messages", "idle"),
            PaneSnapshot("working", "working"),
        ]
    )
    assert (
        prove_submission(
            backend,
            "p-1",
            "prompt",
            pre_prompt=PaneSnapshot("before", "idle"),
        ).confirmed
        is True
    )
    assert backend.returns == 1


def test_return_waits_for_a_visible_prompt_echo() -> None:
    prompt = "deliver this"
    baseline = PaneSnapshot("old output", "done")
    backend = FakeBackend(
        [
            PaneSnapshot("[Pasted text #1 +2 lines]", "done"),
            PaneSnapshot("[Pasted text #1 +2 lines]", "done"),
            PaneSnapshot(prompt, "done"),
        ]
    )
    waits: list[float] = []
    proof = prove_submission(
        backend,
        "p-1",
        prompt,
        pre_prompt=baseline,
        confirmation_attempts=2,
        wait_s=0,
        sleep=waits.append,
    )
    assert proof.confirmed is True
    assert proof.action == "return"
    assert waits == [0]


def test_prompt_timestamp_change_confirms_without_status_transition() -> None:
    baseline = PaneSnapshot("old output", "done", "before")
    proof = prove_submission(
        FakeBackend([PaneSnapshot("old output", "done", "after")]),
        "p-1",
        "prompt",
        pre_prompt=baseline,
    )
    assert proof.confirmed is True
    assert proof.action == "state_transition"
