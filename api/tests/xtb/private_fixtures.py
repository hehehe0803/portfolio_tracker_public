from __future__ import annotations

import os
from pathlib import Path

PRIVATE_XTB_FIXTURE_DIR = Path(
    os.environ.get("XTB_PRIVATE_FIXTURE_DIR", "data/xtb_statement_reference")
)
XTB_PRIVATE_XLSX_FIXTURE = os.environ.get("XTB_PRIVATE_XLSX_FIXTURE")
XTB_PRIVATE_MHTML_FIXTURE = os.environ.get("XTB_PRIVATE_MHTML_FIXTURE")
XTB_PRIVATE_PDF_FIXTURE = os.environ.get("XTB_PRIVATE_PDF_FIXTURE")
SYNTHETIC_XTB_WORKBOOK_NAME = "xtb_private_regression_workbook.xlsx"
SYNTHETIC_XTB_MHTML_NAME = "xtb_private_regression_statement.mhtml"
SYNTHETIC_XTB_DAILY_PDF_NAME = "xtb_private_daily_statement.pdf"


def _fixture_path(
    *,
    env_path: str | None,
    pattern: str,
    fallback_name: str,
) -> Path:
    if env_path:
        return Path(env_path)

    if PRIVATE_XTB_FIXTURE_DIR.exists():
        matches = [
            candidate
            for candidate in sorted(PRIVATE_XTB_FIXTURE_DIR.glob(pattern))
            if candidate.is_file()
        ]
        if len(matches) == 1:
            return matches[0]

    return PRIVATE_XTB_FIXTURE_DIR / fallback_name


XLSX_FIXTURE_PATH = _fixture_path(
    env_path=XTB_PRIVATE_XLSX_FIXTURE,
    pattern="*_en_xlsx_2025-09-07_2025-10-08.xlsx",
    fallback_name=SYNTHETIC_XTB_WORKBOOK_NAME,
)
MHTML_FIXTURE_PATH = _fixture_path(
    env_path=XTB_PRIVATE_MHTML_FIXTURE,
    pattern="*_en_html_2005-12-31_2026-02-03.mhtml",
    fallback_name=SYNTHETIC_XTB_MHTML_NAME,
)
MHTML_SNAPSHOT_PATH = PRIVATE_XTB_FIXTURE_DIR / "expected/xtb_mhtml_normalized.json"
ENCRYPTED_PDF_FIXTURE_PATH = _fixture_path(
    env_path=XTB_PRIVATE_PDF_FIXTURE,
    pattern="*_20250925_DailyStatement.pdf",
    fallback_name=SYNTHETIC_XTB_DAILY_PDF_NAME,
)
