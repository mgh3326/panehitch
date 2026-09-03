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
    proof = prove_submission(backend, "p-1", "a long prompt")
    assert proof.confirmed is True
    assert proof.action == "return"
    assert backend.returns == 1


def test_pasted_chip_still_present_is_unconfirmed() -> None:
    backend = FakeBackend(
        [
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
            PaneSnapshot("[Pasted text #1 +2 lines]", "idle"),
        ]
    )
    assert prove_submission(backend, "p-1", "prompt").confirmed is False


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


def test_already_working_is_submission_signal() -> None:
    backend = FakeBackend([PaneSnapshot("normal output", "working")])
    proof = prove_submission(backend, "p-1", "prompt")
    assert proof.confirmed is True
    assert proof.action == "already_working"


def test_missing_status_fails_closed() -> None:
    backend = FakeBackend([PaneSnapshot("normal output", None)])
    proof = prove_submission(backend, "p-1", "prompt")
    assert proof.confirmed is False
    assert proof.action == "unconfirmed"
