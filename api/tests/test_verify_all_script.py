from __future__ import annotations

import shlex
from pathlib import Path


def test_verify_all_references_existing_search_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "verify_all.sh"
    missing_paths: list[str] = []

    for raw_line in script.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or "rg " not in line:
            continue

        if line.startswith("! "):
            line = line[2:]

        parts = shlex.split(line)
        if not parts or parts[0] != "rg":
            continue

        args = parts[1:]
        while args and args[0].startswith("-"):
            args = args[1:]

        if not args:
            continue

        for candidate in args[1:]:
            if candidate.startswith("-"):
                continue
            if _looks_like_path(candidate) and not (repo_root / candidate).exists():
                missing_paths.append(candidate)

    assert missing_paths == []


def _looks_like_path(value: str) -> bool:
    known_root_files = {".tool-versions", "AGENTS.md", "Makefile", "README.md", "package.json", "pyproject.toml"}
    return value in known_root_files or value == "docs" or "/" in value
