#!/usr/bin/env python3
"""Run a protected Binance export baseline dry-run in a disposable test DB.

This script intentionally refuses non-test database names through the same safety
helper used by the test suite. It imports the gitignored Binance export archives
from data/binance_data into a disposable database and writes a JSON evidence
report without touching portfolio_dev.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import zipfile
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db.base import Base
from app.db.models import ImportArtifact, Transaction
from app.db.safety import (
    assert_safe_destructive_database_url,
    quote_postgresql_identifier,
)
from app.services.analytics import calculate_holdings
from app.services.binance_export_parser import (
    BinanceExportParserError,
    _iter_archive_members,
    _iter_rows,
    _member_schema_supported,
    _parse_member,
    parse_binance_exports,
    summarize_binance_entries,
)
from app.services.binance_ingest import confirm_binance_import, parse_binance_file
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://portfolio:portfolio@127.0.0.1:5433/"
    "portfolio_binance_baseline_test"
)


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object is not JSON serializable: {type(value)!r}")


def _build_baseline_zip(export_dir: Path) -> bytes:
    buffer = io.BytesIO()
    used_names: Counter[str] = Counter()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for archive in sorted(export_dir.glob("*.zip")):
            with zipfile.ZipFile(archive, "r") as source:
                for info in source.infolist():
                    if info.is_dir() or not info.filename.lower().endswith(".csv"):
                        continue
                    member_name = Path(info.filename).name
                    used_names[member_name] += 1
                    if used_names[member_name] > 1:
                        stem = Path(member_name).stem
                        suffix = Path(member_name).suffix
                        member_name = f"{stem}__{archive.stem}{suffix}"
                    out.writestr(member_name, source.read(info.filename))
    return buffer.getvalue()


def audit_exports(
    export_dir: Path,
) -> tuple[list[dict[str, Any]], list[tuple[str, bytes]]]:
    coverage: list[dict[str, Any]] = []
    blobs: list[tuple[str, bytes]] = []
    for archive in sorted(export_dir.glob("*.zip")):
        file_bytes = archive.read_bytes()
        blobs.append((archive.name, file_bytes))
        for member_name, text_body in _iter_archive_members(archive.name, file_bytes):
            header, rows = _iter_rows(text_body)
            supported = bool(header and _member_schema_supported(member_name, header))
            entry_count = 0
            status = "unsupported_empty"
            error = None
            by_type: dict[str, str] = {}
            by_source_type: dict[str, str] = {}
            if supported:
                try:
                    member_entries = _parse_member(member_name, text_body)
                    entry_count = len(member_entries)
                    if entry_count:
                        status = "parsed"
                        member_summary = summarize_binance_entries(member_entries)
                        by_type = {
                            str(k): str(v)
                            for k, v in dict(member_summary["by_type"]).items()
                        }
                        by_source_type = {
                            str(k): str(v)
                            for k, v in dict(member_summary["by_source_type"]).items()
                        }
                    elif rows:
                        status = "supported_unmapped_with_data"
                        error = "supported schema produced no importable rows"
                    else:
                        status = "empty_supported"
                except Exception as exc:  # noqa: BLE001 - this is an evidence report
                    status = "parse_error"
                    error = f"{type(exc).__name__}: {exc}"
            elif rows:
                status = "unsupported_with_data"
                error = "unsupported schema contains data rows"

            coverage.append(
                {
                    "archive": archive.name,
                    "member": member_name,
                    "header": header,
                    "row_count": len(rows),
                    "supported": supported,
                    "status": status,
                    "accepted_entries": entry_count,
                    "by_type": by_type,
                    "by_source_type": by_source_type,
                    "error": error,
                }
            )
    return coverage, blobs


async def recreate_database(database_url: str) -> None:
    assert_safe_destructive_database_url(database_url, context=__file__)
    url = make_url(database_url)
    if not url.database:
        raise RuntimeError("Database URL must include a database name")
    quoted_database = quote_postgresql_identifier(url.database)
    admin_url = url.set(database="postgres").render_as_string(hide_password=False)
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": url.database},
            )
            await conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            await conn.execute(text(f"CREATE DATABASE {quoted_database}"))
    finally:
        await engine.dispose()


async def _table_counts(session) -> dict[str, int]:
    count_queries = {
        "transactions": "SELECT count(*) FROM transactions",
        "import_artifacts": "SELECT count(*) FROM import_artifacts",
        "assets": "SELECT count(*) FROM assets",
        "position_snapshots": "SELECT count(*) FROM position_snapshots",
    }
    counts: dict[str, int] = {}
    for table, query in count_queries.items():
        result = await session.execute(text(query))
        counts[table] = int(result.scalar_one())
    return counts


async def run_dry_run(
    export_dir: Path,
    database_url: str,
    output_json: Path,
) -> dict[str, Any]:
    coverage, blobs = audit_exports(export_dir)
    blocking_statuses = {
        "unsupported_with_data",
        "supported_unmapped_with_data",
        "parse_error",
    }
    blocking = [row for row in coverage if row["status"] in blocking_statuses]
    if blocking:
        message = "; ".join(
            f"{row['archive']}:{row['member']}={row['status']}" for row in blocking
        )
        raise BinanceExportParserError(
            "Blocking Binance export coverage gaps found: " + message
        )

    parsed_entries = parse_binance_exports(blobs)
    parsed_summary = summarize_binance_entries(parsed_entries)
    baseline_zip = _build_baseline_zip(export_dir)

    await recreate_database(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            pre_counts = await _table_counts(session)
            artifact = await parse_binance_file(
                baseline_zip,
                "binance-export-baseline-2026-05-03.zip",
                session,
            )
            confirm_result = await confirm_binance_import(artifact.id, session)
            post_counts = await _table_counts(session)

        async with session_factory() as session:
            tx_stmt = select(Transaction).order_by(
                Transaction.timestamp,
                Transaction.id,
            )
            transactions = (await session.execute(tx_stmt)).scalars().all()
            artifact_stmt = select(ImportArtifact).order_by(ImportArtifact.id)
            artifacts = (await session.execute(artifact_stmt)).scalars().all()
            holdings = calculate_holdings(transactions)
            nonzero_cost_holdings = [h for h in holdings if h.total_cost_usd > 0]
            holdings_top_cost = sorted(
                nonzero_cost_holdings,
                key=lambda h: h.total_cost_usd,
                reverse=True,
            )[:20]

        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "export_dir": str(export_dir),
            "database_url_redacted": str(
                make_url(database_url).render_as_string(hide_password=True)
            ),
            "coverage_counts": dict(Counter(row["status"] for row in coverage)),
            "coverage": coverage,
            "parsed_summary": parsed_summary,
            "pre_counts": pre_counts,
            "post_counts": post_counts,
            "artifact": {
                "id": artifacts[0].id if artifacts else None,
                "institution": artifacts[0].institution if artifacts else None,
                "filename": artifacts[0].filename if artifacts else None,
                "status": artifacts[0].status if artifacts else None,
                "parsed_count": artifacts[0].parsed_count if artifacts else None,
                "committed_count": artifacts[0].committed_count if artifacts else None,
                "duplicate_count": artifacts[0].duplicate_count if artifacts else None,
            },
            "confirm_result": confirm_result,
            "transaction_type_counts": dict(Counter(tx.tx_type for tx in transactions)),
            "transaction_source_counts": dict(
                Counter(
                    (tx.raw_data or {}).get("source_type", "unknown")
                    for tx in transactions
                )
            ),
            "cost_basis": {
                "holdings_count": len(holdings),
                "nonzero_cost_holdings_count": len(nonzero_cost_holdings),
                "top_nonzero_cost_holdings": [
                    {
                        "symbol": h.symbol,
                        "quantity": h.quantity,
                        "total_cost_usd": h.total_cost_usd,
                        "avg_buy_price_usd": h.avg_buy_price_usd,
                    }
                    for h in holdings_top_cost
                ],
            },
        }
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=_json_default),
            encoding="utf-8",
        )
        return report
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", default="data/binance_data")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument(
        "--output-json",
        default="docs/binance_export_baseline_dry_run_2026-05-03.json",
    )
    args = parser.parse_args()
    report = asyncio.run(
        run_dry_run(Path(args.export_dir), args.database_url, Path(args.output_json))
    )
    print(json.dumps(report, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
