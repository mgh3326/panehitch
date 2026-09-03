"""Guard the public tree against private operational residue."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(r"100\.\d+\.\d+\.\d+"),
    re.compile(r"Bearer [A-Za-z0-9]{20,}"),
    re.compile(
        r"(kis|kiwoom|upbit|toss|binance|alpaca|nhplug|broker|order_|krb1|b0x|policy[-_]table|매수|매도|계좌|robinco)",
        re.IGNORECASE,
    ),
    re.compile(r"/Users/|/root/|/home/"),
]


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in root.rglob("*"):
        if (
            not path.is_file()
            or ".git" in path.parts
            or ".venv" in path.parts
            or ".pytest_cache" in path.parts
            or ".ruff_cache" in path.parts
            or ".ty" in path.parts
            or "reports" in path.parts
            or "__pycache__" in path.parts
            or path.name == "test_public_hygiene.py"
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in PATTERNS:
            if pattern.search(text):
                found.append(str(path.relative_to(root)))
                break
    return found


def test_public_tree_has_no_private_residue() -> None:
    assert violations(ROOT) == []


def test_forbidden_word_mutant_is_detected(tmp_path: Path) -> None:
    (tmp_path / "guide.md").write_text("ki" + "s", encoding="utf-8")
    assert violations(tmp_path) == ["guide.md"]
