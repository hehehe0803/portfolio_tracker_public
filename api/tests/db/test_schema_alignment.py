"""Schema alignment tests for the core migration."""

# ruff: noqa: S101, S105, S603, S607
from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import app.db.models  # noqa: F401 - ensure ORM tables are registered
import pytest
from app.config import settings
from app.db.base import Base
from app.db.safety import (
    DEFAULT_TEST_DATABASE_SERVER_URL,
    assert_safe_destructive_database_url,
    build_temporary_test_database_url,
    pick_safe_test_database_server_url,
)
from sqlalchemy import (
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "api" / "Alembic.ini"
EXPECTED_TABLES = {
    "users",
    "auth_sessions",
    "institutions",
    "transactions",
    "import_artifacts",
    "alert_rules",
    "alert_events",
    "tags",
    "asset_tags",
    "themes",
    "asset_themes",
    "notes",
    "note_versions",
    "activity_logs",
    "watchlist_items",
    "watchlist_target_alerts",
    "assets",
    "position_snapshots",
    "pending_orders",
    "benchmark_quotes",
    "accounting_transfer_links",
    "accounting_external_cashflow_classifications",
    "accounting_import_approvals",
    "accounting_cost_basis_decisions",
    "accounting_reconciliation_tasks",
    "accounting_evidence_claims",
}
EXPECTED_INDEXES = {
    "auth_sessions": {
        "ix_auth_sessions_user_id",
        "ix_auth_sessions_revoked_at",
    },
    "transactions": {
        "ix_transactions_asset_symbol",
        "ix_transactions_timestamp",
        "ix_transactions_institution",
    },
    "alert_events": {"ix_alert_events_triggered_at"},
    "notes": {"ix_notes_entity", "ix_notes_created_at"},
    "note_versions": {"ix_note_versions_note_id"},
    "activity_logs": {
        "ix_activity_logs_created_at",
        "ix_activity_logs_source_status",
        "ix_activity_logs_artifact_id",
    },
    "watchlist_items": {"ix_watchlist_items_status_priority"},
    "watchlist_target_alerts": {"ix_watchlist_target_alerts_triggered_at"},
    "position_snapshots": {"ix_position_snapshots_captured_at"},
    "benchmark_quotes": {"ix_benchmark_quotes_captured_at"},
    "accounting_transfer_links": {
        "ix_accounting_transfer_links_occurred_at",
        "ix_accounting_transfer_links_sources",
        "uq_accounting_transfer_links_active_group",
        "uq_accounting_transfer_links_active_from_evidence",
        "uq_accounting_transfer_links_active_to_evidence",
    },
    "accounting_external_cashflow_classifications": {
        "ix_acct_cashflow_occurred_at",
        "ix_acct_cashflow_source",
        "uq_acct_cashflow_active_key",
        "uq_acct_cashflow_active_evidence",
    },
    "accounting_import_approvals": {
        "ix_accounting_import_approvals_source_scope",
        "ix_accounting_import_approvals_coverage",
        "uq_accounting_import_approvals_active_key",
    },
    "accounting_cost_basis_decisions": {
        "ix_accounting_cost_basis_decisions_asset_effective_at",
        "uq_accounting_cost_basis_decisions_active_key",
    },
    "accounting_reconciliation_tasks": {
        "ix_accounting_reconciliation_tasks_source_occurred_at",
        "ix_accounting_reconciliation_tasks_status_severity",
        "uq_accounting_reconciliation_tasks_task_id",
        "uq_accounting_reconciliation_tasks_active_key",
    },
    "accounting_evidence_claims": {
        "ix_accounting_evidence_claims_source",
    },
}
EXPECTED_CHECK_CONSTRAINTS = {
    "accounting_transfer_links": {
        "ck_accounting_transfer_links_status",
        "ck_accounting_transfer_links_decision_source",
        "ck_accounting_transfer_links_confidence_state",
        "ck_accounting_transfer_links_void_lifecycle",
        "ck_accounting_transfer_links_quantity_sanity",
        "ck_accounting_transfer_links_fee_sanity",
        "ck_accounting_transfer_links_amount_sanity",
        "ck_accounting_transfer_links_distinct_evidence",
    },
    "accounting_external_cashflow_classifications": {
        "ck_acct_cashflow_status",
        "ck_acct_cashflow_decision_source",
        "ck_acct_cashflow_confidence_state",
        "ck_acct_cashflow_void_lifecycle",
        "ck_acct_cashflow_cashflow_type",
        "ck_acct_cashflow_movement_type",
        "ck_acct_cashflow_capital_effect",
        "ck_acct_cashflow_type_movement_pair",
    },
    "accounting_import_approvals": {
        "ck_accounting_import_approvals_status",
        "ck_accounting_import_approvals_decision_source",
        "ck_accounting_import_approvals_confidence_state",
        "ck_accounting_import_approvals_void_lifecycle",
        "ck_accounting_import_approvals_coverage_order",
    },
    "accounting_cost_basis_decisions": {
        "ck_accounting_cost_basis_decisions_status",
        "ck_accounting_cost_basis_decisions_decision_source",
        "ck_accounting_cost_basis_decisions_confidence_state",
        "ck_accounting_cost_basis_decisions_void_lifecycle",
        "ck_accounting_cost_basis_decisions_decision_type",
        "ck_accounting_cost_basis_decisions_basis_scope",
        "ck_accounting_cost_basis_decisions_manual_value",
        "ck_accounting_cost_basis_decisions_quantity_positive",
        "ck_accounting_cost_basis_decisions_total_nonnegative",
        "ck_accounting_cost_basis_decisions_unit_nonnegative",
        "ck_accounting_cost_basis_decisions_value_consistent",
        "ck_accounting_cost_basis_decisions_unknown_not_trusted",
    },
    "accounting_reconciliation_tasks": {
        "ck_accounting_reconciliation_tasks_status",
        "ck_accounting_reconciliation_tasks_severity",
        "ck_accounting_reconciliation_tasks_task_type",
        "ck_accounting_reconciliation_tasks_void_lifecycle",
        "ck_accounting_reconciliation_tasks_resolution_lifecycle",
        "ck_accounting_reconciliation_tasks_quantity_sanity",
        "ck_accounting_reconciliation_tasks_amount_sanity",
        "ck_accounting_reconciliation_tasks_decision_reference",
    },
    "accounting_evidence_claims": {
        "ck_accounting_evidence_claims_source_table",
        "ck_accounting_evidence_claims_role",
    },
}


def _resolve_database_url():
    return make_url(
        pick_safe_test_database_server_url(
            os.environ.get("SCHEMA_TEST_DATABASE_URL")
            or os.environ.get("TEST_DATABASE_BASE_URL")
            or os.environ.get("DATABASE_URL")
            or settings.DATABASE_URL,
            default_url=DEFAULT_TEST_DATABASE_SERVER_URL,
        )
    )


def _run_alembic(command: str, database_url: str, revision: str | None = None) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    action = revision or ("head" if command == "upgrade" else "base")
    subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), command, action],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )


async def _create_legacy_backend_foundation_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    CREATE TABLE assets (
                        id BIGSERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        asset_type VARCHAR(20) NOT NULL,
                        last_price_usd NUMERIC(20, 6),
                        last_seen_at TIMESTAMPTZ,
                        CONSTRAINT uq_assets_symbol UNIQUE (symbol)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE position_snapshots (
                        id BIGSERIAL PRIMARY KEY,
                        asset_id BIGINT NOT NULL
                            REFERENCES assets (id) ON DELETE CASCADE,
                        captured_at TIMESTAMPTZ NOT NULL,
                        quantity NUMERIC(30, 10) NOT NULL,
                        avg_buy_price_usd NUMERIC(20, 6),
                        total_cost_usd NUMERIC(20, 6) NOT NULL,
                        current_price_usd NUMERIC(20, 6),
                        current_value_usd NUMERIC(20, 6),
                        unrealized_pnl_usd NUMERIC(20, 6),
                        unrealized_pnl_pct NUMERIC(20, 10),
                        CONSTRAINT uq_position_snapshots_asset_id_captured_at
                            UNIQUE (asset_id, captured_at)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX ix_position_snapshots_captured_at "
                    "ON position_snapshots (captured_at)"
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE pending_orders (
                        id BIGSERIAL PRIMARY KEY,
                        asset_id BIGINT NOT NULL
                            REFERENCES assets (id) ON DELETE CASCADE,
                        institution VARCHAR(50) NOT NULL,
                        external_order_id VARCHAR(100) NOT NULL,
                        symbol VARCHAR(20) NOT NULL,
                        order_type VARCHAR(20) NOT NULL,
                        status VARCHAR(20) NOT NULL,
                        side VARCHAR(10) NOT NULL,
                        quantity NUMERIC(30, 10) NOT NULL,
                        limit_price NUMERIC(20, 6),
                        stop_price NUMERIC(20, 6),
                        placed_at TIMESTAMPTZ,
                        CONSTRAINT uq_pending_orders_institution_external_order_id
                            UNIQUE (institution, external_order_id)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE benchmark_quotes (
                        id BIGSERIAL PRIMARY KEY,
                        symbol VARCHAR(20) NOT NULL,
                        captured_at TIMESTAMPTZ NOT NULL,
                        price_usd NUMERIC(20, 6) NOT NULL,
                        CONSTRAINT uq_benchmark_quotes_symbol_captured_at
                            UNIQUE (symbol, captured_at)
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    "CREATE INDEX ix_benchmark_quotes_captured_at "
                    "ON benchmark_quotes (captured_at)"
                )
            )
    finally:
        await engine.dispose()


@contextmanager
def temporary_database_url() -> Iterator[str]:
    base_url = _resolve_database_url()
    if base_url.get_backend_name() != "postgresql":
        pytest.skip("schema alignment requires a PostgreSQL DATABASE_URL")

    database_url = build_temporary_test_database_url(
        base_url,
        name_prefix="portfolio_tracker_schema",
        context="api/tests/db/test_schema_alignment.py",
    )
    database_name = make_url(database_url).database
    assert_safe_destructive_database_url(
        database_url,
        context="api/tests/db/test_schema_alignment.py",
    )
    env = os.environ.copy()
    if base_url.host:
        env["PGHOST"] = base_url.host
    if base_url.port:
        env["PGPORT"] = str(base_url.port)
    if base_url.username:
        env["PGUSER"] = base_url.username
    if base_url.password:
        env["PGPASSWORD"] = base_url.password

    try:
        subprocess.run(["createdb", database_name], cwd=REPO_ROOT, env=env, check=True)
    except FileNotFoundError:
        pytest.skip("createdb is not available on this system")
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"unable to create a disposable postgres database: {exc}")

    try:
        yield base_url.set(database=database_name).render_as_string(hide_password=False)
    finally:
        subprocess.run(
            ["dropdb", "--if-exists", database_name],
            cwd=REPO_ROOT,
            env=env,
            check=False,
        )


def _metadata_signature() -> dict[str, object]:
    tables = set(Base.metadata.tables)
    unique_constraints: dict[str, set[tuple[str, ...]]] = {}
    indexes: dict[str, set[str]] = {}
    foreign_keys: dict[
        str, set[tuple[tuple[str, ...], str, tuple[str, ...], str | None]]
    ] = {}
    check_constraints: dict[str, set[str]] = {}

    for table_name, table in Base.metadata.tables.items():
        if table_name not in EXPECTED_TABLES:
            continue
        unique_constraints[table_name] = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        indexes[table_name] = {
            index.name for index in table.indexes if isinstance(index, Index)
        }
        foreign_keys[table_name] = {
            (
                tuple(constraint.column_keys),
                next(iter(constraint.elements)).column.table.name,
                tuple(element.column.key for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in table.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        }
        check_constraints[table_name] = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint) and constraint.name is not None
        }

    return {
        "tables": tables,
        "unique_constraints": unique_constraints,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
        "check_constraints": check_constraints,
    }


def _inspect_schema(connection) -> dict[str, object]:
    inspector = inspect(connection)
    tables = {
        table_name
        for table_name in inspector.get_table_names()
        if table_name in EXPECTED_TABLES
    }
    unique_constraints = {
        table_name: {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table_name)
        }
        for table_name in EXPECTED_TABLES
    }
    indexes = {
        table_name: {
            index["name"]
            for index in inspector.get_indexes(table_name)
            if index["name"] in EXPECTED_INDEXES.get(table_name, set())
        }
        for table_name in EXPECTED_TABLES
    }
    foreign_keys = {
        table_name: {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        for table_name in EXPECTED_TABLES
    }
    check_constraints = {
        table_name: {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
            if constraint["name"] in EXPECTED_CHECK_CONSTRAINTS.get(table_name, set())
        }
        for table_name in EXPECTED_TABLES
    }
    return {
        "tables": tables,
        "unique_constraints": unique_constraints,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
        "check_constraints": check_constraints,
    }


def _inspect_timescale_objects(connection) -> dict[str, object]:
    extension_installed = bool(
        connection.exec_driver_sql(
            "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"
        ).scalar()
    )
    hypertables: set[str] = set()
    continuous_aggregates: set[str] = set()

    if extension_installed:
        hypertables = {
            row[0]
            for row in connection.exec_driver_sql(
                """
                SELECT hypertable_name
                FROM timescaledb_information.hypertables
                WHERE hypertable_schema = 'public'
                """
            )
        }
        continuous_aggregates = {
            row[0]
            for row in connection.exec_driver_sql(
                """
                SELECT view_name
                FROM timescaledb_information.continuous_aggregates
                WHERE view_schema = 'public'
                """
            )
        }

    return {
        "extension_installed": extension_installed,
        "hypertables": hypertables,
        "continuous_aggregates": continuous_aggregates,
    }


def _live_signature(database_url: str) -> dict[str, object]:
    async def collect() -> dict[str, object]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_inspect_schema)
        finally:
            await engine.dispose()

    return asyncio.run(collect())


def _live_timescale_signature(database_url: str) -> dict[str, object]:
    async def collect() -> dict[str, object]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(_inspect_timescale_objects)
        finally:
            await engine.dispose()

    return asyncio.run(collect())


def test_alembic_env_uses_repo_relative_import_path() -> None:
    tree = ast.parse((REPO_ROOT / "api" / "migrations" / "env.py").read_text())
    sys_path_inserts = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "insert"
        and isinstance(node.func.value, ast.Attribute)
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "sys"
        and node.func.value.attr == "path"
    ]
    assert not sys_path_inserts


def test_importing_app_db_registers_new_tables() -> None:
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")  # noqa: S108
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            (
                "import json; "
                "import app.db; "
                "from app.db.base import Base; "
                "print(json.dumps(sorted(Base.metadata.tables)))"
            ),
        ],
        cwd=REPO_ROOT / "api",
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    table_names = set(json.loads(result.stdout))

    assert {
        "tags",
        "notes",
        "activity_logs",
        "accounting_transfer_links",
        "accounting_external_cashflow_classifications",
        "accounting_import_approvals",
        "accounting_cost_basis_decisions",
        "accounting_reconciliation_tasks",
        "accounting_evidence_claims",
    } <= table_names


def test_metadata_signature_includes_tag_note_and_activity_tables() -> None:
    expected_unique_constraints = {
        "users": {("username",)},
        "auth_sessions": {("session_id",)},
        "institutions": {("name",)},
        "transactions": {("fingerprint",)},
        "tags": {("name",)},
        "themes": {("name",)},
        "note_versions": {("note_id", "version")},
        "watchlist_items": {("symbol",)},
        "assets": {("symbol",)},
        "position_snapshots": {("asset_id", "captured_at")},
        "pending_orders": {("institution", "external_order_id")},
        "benchmark_quotes": {("symbol", "captured_at")},
        "accounting_evidence_claims": {("evidence_key",)},
    }
    expected_foreign_keys = {
        "auth_sessions": {
            (("user_id",), "users", ("id",), "CASCADE"),
        },
        "transactions": {
            (("import_id",), "import_artifacts", ("id",), "SET NULL"),
        },
        "alert_events": {
            (("rule_id",), "alert_rules", ("id",), "CASCADE"),
        },
        "asset_tags": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
            (("tag_id",), "tags", ("id",), "CASCADE"),
        },
        "asset_themes": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
            (("theme_id",), "themes", ("id",), "CASCADE"),
        },
        "notes": {
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "note_versions": {
            (("note_id",), "notes", ("id",), "CASCADE"),
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "activity_logs": {
            (("artifact_id",), "import_artifacts", ("id",), "SET NULL"),
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "position_snapshots": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
        },
        "pending_orders": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
        },
        "watchlist_items": {
            (("owned_asset_id",), "assets", ("id",), "SET NULL"),
        },
        "watchlist_target_alerts": {
            (("watchlist_item_id",), "watchlist_items", ("id",), "CASCADE"),
        },
        "accounting_transfer_links": {
            (("supersedes_id",), "accounting_transfer_links", ("id",), "SET NULL"),
        },
        "accounting_external_cashflow_classifications": {
            (
                ("supersedes_id",),
                "accounting_external_cashflow_classifications",
                ("id",),
                "SET NULL",
            ),
        },
        "accounting_import_approvals": {
            (("supersedes_id",), "accounting_import_approvals", ("id",), "SET NULL"),
        },
        "accounting_cost_basis_decisions": {
            (
                ("supersedes_id",),
                "accounting_cost_basis_decisions",
                ("id",),
                "SET NULL",
            ),
        },
        "accounting_reconciliation_tasks": {
            (
                ("supersedes_id",),
                "accounting_reconciliation_tasks",
                ("id",),
                "SET NULL",
            ),
        },
    }

    metadata_signature = _metadata_signature()

    assert metadata_signature["tables"] == EXPECTED_TABLES

    for table_name, expected in expected_unique_constraints.items():
        assert metadata_signature["unique_constraints"][table_name] == expected

    for table_name, expected in EXPECTED_INDEXES.items():
        assert metadata_signature["indexes"][table_name] == expected

    for table_name, expected in expected_foreign_keys.items():
        assert metadata_signature["foreign_keys"][table_name] == expected

    for table_name, expected in EXPECTED_CHECK_CONSTRAINTS.items():
        assert metadata_signature["check_constraints"][table_name] == expected


def test_core_schema_alignment_after_full_migration_cycle() -> None:
    expected_unique_constraints = {
        "users": {("username",)},
        "auth_sessions": {("session_id",)},
        "institutions": {("name",)},
        "transactions": {("fingerprint",)},
        "tags": {("name",)},
        "themes": {("name",)},
        "note_versions": {("note_id", "version")},
        "watchlist_items": {("symbol",)},
        "assets": {("symbol",)},
        "position_snapshots": {("asset_id", "captured_at")},
        "pending_orders": {("institution", "external_order_id")},
        "benchmark_quotes": {("symbol", "captured_at")},
        "accounting_evidence_claims": {("evidence_key",)},
    }
    expected_foreign_keys = {
        "auth_sessions": {
            (("user_id",), "users", ("id",), "CASCADE"),
        },
        "transactions": {
            (("import_id",), "import_artifacts", ("id",), "SET NULL"),
        },
        "alert_events": {
            (("rule_id",), "alert_rules", ("id",), "CASCADE"),
        },
        "asset_tags": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
            (("tag_id",), "tags", ("id",), "CASCADE"),
        },
        "asset_themes": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
            (("theme_id",), "themes", ("id",), "CASCADE"),
        },
        "notes": {
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "note_versions": {
            (("note_id",), "notes", ("id",), "CASCADE"),
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "activity_logs": {
            (("artifact_id",), "import_artifacts", ("id",), "SET NULL"),
            (("user_id",), "users", ("id",), "SET NULL"),
        },
        "position_snapshots": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
        },
        "pending_orders": {
            (("asset_id",), "assets", ("id",), "CASCADE"),
        },
        "watchlist_items": {
            (("owned_asset_id",), "assets", ("id",), "SET NULL"),
        },
        "watchlist_target_alerts": {
            (("watchlist_item_id",), "watchlist_items", ("id",), "CASCADE"),
        },
        "accounting_transfer_links": {
            (("supersedes_id",), "accounting_transfer_links", ("id",), "SET NULL"),
        },
        "accounting_external_cashflow_classifications": {
            (
                ("supersedes_id",),
                "accounting_external_cashflow_classifications",
                ("id",),
                "SET NULL",
            ),
        },
        "accounting_import_approvals": {
            (("supersedes_id",), "accounting_import_approvals", ("id",), "SET NULL"),
        },
        "accounting_cost_basis_decisions": {
            (
                ("supersedes_id",),
                "accounting_cost_basis_decisions",
                ("id",),
                "SET NULL",
            ),
        },
        "accounting_reconciliation_tasks": {
            (
                ("supersedes_id",),
                "accounting_reconciliation_tasks",
                ("id",),
                "SET NULL",
            ),
        },
    }

    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url)
        _run_alembic("downgrade", database_url)
        _run_alembic("upgrade", database_url)

        metadata_signature = _metadata_signature()
        live_signature = _live_signature(database_url)

        assert metadata_signature["tables"] == EXPECTED_TABLES
        assert live_signature["tables"] == EXPECTED_TABLES

        for table_name, expected in expected_unique_constraints.items():
            assert metadata_signature["unique_constraints"][table_name] == expected
            assert live_signature["unique_constraints"][table_name] == expected

        for table_name, expected in EXPECTED_INDEXES.items():
            assert metadata_signature["indexes"][table_name] == expected
            assert live_signature["indexes"][table_name] == expected

        for table_name, expected in expected_foreign_keys.items():
            assert metadata_signature["foreign_keys"][table_name] == expected
            assert live_signature["foreign_keys"][table_name] == expected

        for table_name, expected in EXPECTED_CHECK_CONSTRAINTS.items():
            assert metadata_signature["check_constraints"][table_name] == expected
            assert live_signature["check_constraints"][table_name] == expected


def test_backend_foundation_tables_revision_preserves_legacy_primary_keys() -> None:
    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url, revision="backend_foundation_tables")

        async def collect() -> dict[str, list[str]]:
            engine = create_async_engine(database_url)
            try:
                async with engine.connect() as connection:

                    def inspect_primary_keys(sync_connection):
                        inspector = inspect(sync_connection)
                        return {
                            "position_snapshots": inspector.get_pk_constraint(
                                "position_snapshots"
                            )["constrained_columns"],
                            "benchmark_quotes": inspector.get_pk_constraint(
                                "benchmark_quotes"
                            )["constrained_columns"],
                        }

                    return await connection.run_sync(inspect_primary_keys)
            finally:
                await engine.dispose()

        assert asyncio.run(collect()) == {
            "position_snapshots": ["id"],
            "benchmark_quotes": ["id"],
        }


def test_legacy_backend_foundation_schema_upgrades_to_timescale_compatible_shape() -> (
    None
):
    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url, revision="auth_sessions")
        asyncio.run(_create_legacy_backend_foundation_schema(database_url))
        _run_alembic("stamp", database_url, revision="backend_foundation_tables")
        _run_alembic("upgrade", database_url)

        async def collect() -> tuple[dict[str, list[str]], dict[str, object]]:
            engine = create_async_engine(database_url)
            try:
                async with engine.connect() as connection:

                    def inspect_state(sync_connection):
                        inspector = inspect(sync_connection)
                        primary_keys = {
                            "position_snapshots": inspector.get_pk_constraint(
                                "position_snapshots"
                            )["constrained_columns"],
                            "benchmark_quotes": inspector.get_pk_constraint(
                                "benchmark_quotes"
                            )["constrained_columns"],
                        }
                        timescale = _inspect_timescale_objects(sync_connection)
                        return primary_keys, timescale

                    return await connection.run_sync(inspect_state)
            finally:
                await engine.dispose()

        primary_keys, timescale = asyncio.run(collect())

        assert primary_keys == {
            "position_snapshots": ["id", "captured_at"],
            "benchmark_quotes": ["id", "captured_at"],
        }
        assert {"position_snapshots", "benchmark_quotes"} <= timescale["hypertables"]


def test_security_001_downgrade_restores_plaintext_institution_credentials() -> None:
    import importlib.util

    import sqlalchemy as sa

    migration_path = (
        REPO_ROOT
        / "api"
        / "migrations"
        / "versions"
        / "00006_security_001_institution_credentials.py"
    )
    spec = importlib.util.spec_from_file_location(
        "security_001_institution_credentials", migration_path
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    from sqlalchemy import create_engine

    engine = create_engine("sqlite+pysqlite:///:memory:")
    connection = engine.connect()
    try:
        connection.execute(
            text(
                """
                CREATE TABLE institutions (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    api_key_encrypted TEXT,
                    api_secret_encrypted TEXT,
                    credentials_updated_at TIMESTAMP,
                    credential_rotation_count INTEGER NOT NULL DEFAULT 0,
                    last_sync_at TIMESTAMP,
                    created_at TIMESTAMP
                )
                """
            )
        )

        original_master_key = os.environ.get("INSTITUTION_CREDENTIALS_MASTER_KEY")
        os.environ["INSTITUTION_CREDENTIALS_MASTER_KEY"] = "security-test-master-key"
        try:
            cipher = migration._cipher_from_env()
            connection.execute(
                text(
                    """
                    INSERT INTO institutions (
                        id,
                        name,
                        api_key_encrypted,
                        api_secret_encrypted,
                        credentials_updated_at,
                        credential_rotation_count
                    )
                    VALUES (
                        1,
                        'binance',
                        :api_key_encrypted,
                        :api_secret_encrypted,
                        CURRENT_TIMESTAMP,
                        2
                    )
                    """
                ),
                {
                    "api_key_encrypted": cipher.encrypt(b"legacy-key").decode("utf-8"),
                    "api_secret_encrypted": cipher.encrypt(b"legacy-secret").decode(
                        "utf-8"
                    ),
                },
            )
        finally:
            if original_master_key is None:
                os.environ.pop("INSTITUTION_CREDENTIALS_MASTER_KEY", None)
            else:
                os.environ["INSTITUTION_CREDENTIALS_MASTER_KEY"] = original_master_key

        class FakeOp:
            def add_column(self, table_name: str, column) -> None:
                type_name = "TEXT"
                if isinstance(column.type, sa.Integer):
                    type_name = "INTEGER"
                elif isinstance(column.type, sa.DateTime):
                    type_name = "TIMESTAMP"
                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN {column.name} {type_name}"
                    )
                )

            def drop_column(self, table_name: str, column_name: str) -> None:
                connection.execute(
                    text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
                )

            def get_bind(self):
                return connection

        original_op = migration.op
        original_master_key = os.environ.get("INSTITUTION_CREDENTIALS_MASTER_KEY")
        os.environ["INSTITUTION_CREDENTIALS_MASTER_KEY"] = "security-test-master-key"
        migration.op = FakeOp()
        try:
            migration.downgrade()
        finally:
            migration.op = original_op
            if original_master_key is None:
                os.environ.pop("INSTITUTION_CREDENTIALS_MASTER_KEY", None)
            else:
                os.environ["INSTITUTION_CREDENTIALS_MASTER_KEY"] = original_master_key

        row = (
            connection.execute(
                text(
                    """
                SELECT api_key, api_secret
                FROM institutions
                WHERE name = 'binance'
                """
                )
            )
            .mappings()
            .one()
        )
        columns = {
            column["name"] for column in inspect(connection).get_columns("institutions")
        }

        assert dict(row) == {
            "api_key": "legacy-key",
            "api_secret": "legacy-secret",
        }
        assert {"api_key", "api_secret"} <= columns

        assert {
            "api_key_encrypted",
            "api_secret_encrypted",
            "credentials_updated_at",
            "credential_rotation_count",
        }.isdisjoint(columns)
    finally:
        connection.close()
        engine.dispose()


def test_timescale_objects_exist_after_migration() -> None:
    expected_hypertables = {"position_snapshots", "benchmark_quotes"}
    expected_continuous_aggregates = {
        "benchmark_quotes_daily",
        "benchmark_quotes_hourly",
        "benchmark_quotes_monthly",
        "benchmark_quotes_weekly",
        "portfolio_snapshots_daily",
        "portfolio_snapshots_hourly",
        "portfolio_snapshots_monthly",
        "portfolio_snapshots_weekly",
    }

    with temporary_database_url() as database_url:
        _run_alembic("upgrade", database_url)

        live_signature = _live_timescale_signature(database_url)

        assert live_signature["extension_installed"] is True
        assert expected_hypertables <= live_signature["hypertables"]
        assert expected_continuous_aggregates <= live_signature["continuous_aggregates"]
