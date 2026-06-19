from __future__ import annotations

import subprocess
from pathlib import Path

PRIVATE_ACCOUNT_ID = "529" + "14551"
FORBIDDEN_CURRENT_TREE_TOKENS = (
    PRIVATE_ACCOUNT_ID,
    f"account_{PRIVATE_ACCOUNT_ID}",
)


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(path) for path in result.stdout.splitlines()]


def test_current_tree_does_not_expose_private_account_identifiers():
    offenders: list[str] = []

    for path in _tracked_files():
        for token in FORBIDDEN_CURRENT_TREE_TOKENS:
            if token in path.as_posix():
                offenders.append(f"{path}: path contains {token}")

            if token.encode() in path.read_bytes():
                offenders.append(f"{path}: contains {token}")

    assert offenders == []
