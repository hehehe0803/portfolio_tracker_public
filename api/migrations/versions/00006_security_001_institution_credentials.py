"""
Encrypt institution credentials at rest and track rotation metadata.

Revision ID: sec001_institution_creds
Revises: platform_003_timeseries
Create Date: 2026-04-21
"""

from __future__ import annotations

import base64
import hashlib
import os
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

revision: str = "sec001_institution_creds"
down_revision: str | None = "platform_003_timeseries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cipher_from_env() -> Fernet:
    master_key = os.environ.get("INSTITUTION_CREDENTIALS_MASTER_KEY", "")
    if not master_key:
        raise RuntimeError(
            "INSTITUTION_CREDENTIALS_MASTER_KEY must be set before "
            "migrating existing institution credentials"
        )
    derived_key = base64.urlsafe_b64encode(
        hashlib.sha256(master_key.encode("utf-8")).digest()
    )
    return Fernet(derived_key)


def upgrade() -> None:
    op.add_column(
        "institutions",
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("api_secret_encrypted", sa.Text(), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("credentials_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column(
            "credential_rotation_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    bind = op.get_bind()
    institutions = sa.table(
        "institutions",
        sa.column("id", sa.Integer()),
        sa.column("api_key", sa.Text()),
        sa.column("api_secret", sa.Text()),
        sa.column("api_key_encrypted", sa.Text()),
        sa.column("api_secret_encrypted", sa.Text()),
        sa.column("credentials_updated_at", sa.DateTime(timezone=True)),
    )
    rows = list(
        bind.execute(
            sa.select(
                institutions.c.id,
                institutions.c.api_key,
                institutions.c.api_secret,
            ).where(
                sa.or_(
                    institutions.c.api_key.is_not(None),
                    institutions.c.api_secret.is_not(None),
                )
            )
        )
    )
    if rows:
        cipher = _cipher_from_env()
        migrated_at = datetime.now(UTC)
        for row in rows:
            bind.execute(
                institutions.update()
                .where(institutions.c.id == row.id)
                .values(
                    api_key_encrypted=(
                        cipher.encrypt(row.api_key.encode("utf-8")).decode("utf-8")
                        if row.api_key is not None
                        else None
                    ),
                    api_secret_encrypted=(
                        cipher.encrypt(row.api_secret.encode("utf-8")).decode("utf-8")
                        if row.api_secret is not None
                        else None
                    ),
                    credentials_updated_at=migrated_at,
                )
            )

    op.drop_column("institutions", "api_secret")
    op.drop_column("institutions", "api_key")
    op.alter_column(
        "institutions",
        "credential_rotation_count",
        server_default=None,
    )


def downgrade() -> None:
    op.add_column("institutions", sa.Column("api_key", sa.Text(), nullable=True))
    op.add_column("institutions", sa.Column("api_secret", sa.Text(), nullable=True))

    bind = op.get_bind()
    institutions = sa.table(
        "institutions",
        sa.column("id", sa.Integer()),
        sa.column("api_key", sa.Text()),
        sa.column("api_secret", sa.Text()),
        sa.column("api_key_encrypted", sa.Text()),
        sa.column("api_secret_encrypted", sa.Text()),
    )
    rows = list(
        bind.execute(
            sa.select(
                institutions.c.id,
                institutions.c.api_key_encrypted,
                institutions.c.api_secret_encrypted,
            ).where(
                sa.or_(
                    institutions.c.api_key_encrypted.is_not(None),
                    institutions.c.api_secret_encrypted.is_not(None),
                )
            )
        )
    )
    if rows:
        cipher = _cipher_from_env()
        for row in rows:
            bind.execute(
                institutions.update()
                .where(institutions.c.id == row.id)
                .values(
                    api_key=(
                        cipher.decrypt(row.api_key_encrypted.encode("utf-8")).decode("utf-8")
                        if row.api_key_encrypted is not None
                        else None
                    ),
                    api_secret=(
                        cipher.decrypt(row.api_secret_encrypted.encode("utf-8")).decode("utf-8")
                        if row.api_secret_encrypted is not None
                        else None
                    ),
                )
            )

    op.drop_column("institutions", "credential_rotation_count")
    op.drop_column("institutions", "credentials_updated_at")
    op.drop_column("institutions", "api_secret_encrypted")
    op.drop_column("institutions", "api_key_encrypted")
