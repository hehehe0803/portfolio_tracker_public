"""
SQLAlchemy ORM Models.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

asset_tags = Table(
    "asset_tags",
    Base.metadata,
    Column(
        "asset_id",
        BigInteger,
        ForeignKey("assets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    ),
)


class AssetTheme(Base):
    __tablename__ = "asset_themes"

    asset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True
    )
    theme_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("themes.id", ondelete="CASCADE"), primary_key=True
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    notes: Mapped[list["Note"]] = relationship("Note", back_populates="user")
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="user"
    )
    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        "AuthSession", back_populates="user"
    )


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credential_rotation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    def set_api_credentials(
        self,
        api_key: str,
        api_secret: str,
        *,
        rotated: bool = False,
    ) -> None:
        from app.services.credentials import get_credential_cipher

        cipher = get_credential_cipher()
        self.api_key_encrypted = cipher.encrypt(api_key)
        self.api_secret_encrypted = cipher.encrypt(api_secret)
        self.credentials_updated_at = utcnow()
        if self.credential_rotation_count is None:
            self.credential_rotation_count = 0
        if rotated:
            self.credential_rotation_count += 1

    def get_api_credentials(self) -> dict[str, str | None]:
        from app.services.credentials import get_credential_cipher

        if not self.api_key_encrypted and not self.api_secret_encrypted:
            return {"api_key": None, "api_secret": None}

        cipher = get_credential_cipher()
        return {
            "api_key": (
                cipher.decrypt(self.api_key_encrypted)
                if self.api_key_encrypted is not None
                else None
            ),
            "api_secret": (
                cipher.decrypt(self.api_secret_encrypted)
                if self.api_secret_encrypted is not None
                else None
            ),
        }


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (UniqueConstraint("symbol", name="uq_assets_symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )
    sector: Mapped[str | None] = mapped_column(String(80), nullable=True)
    thesis_status: Mapped[str] = mapped_column(
        String(30), default="none", nullable=False
    )
    last_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    position_snapshots: Mapped[list["PositionSnapshot"]] = relationship(
        "PositionSnapshot", back_populates="asset", passive_deletes=True
    )
    pending_orders: Mapped[list["PendingOrder"]] = relationship(
        "PendingOrder", back_populates="asset", passive_deletes=True
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag", secondary=asset_tags, back_populates="assets"
    )
    themes: Mapped[list["Theme"]] = relationship(
        "Theme", secondary="asset_themes", back_populates="assets"
    )


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "captured_at", name="uq_position_snapshots_asset_id_captured_at"
        ),
        Index("ix_position_snapshots_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    avg_buy_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    total_cost_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    current_price_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    current_value_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    unrealized_pnl_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    unrealized_pnl_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10), nullable=True
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="position_snapshots")


class PendingOrder(Base):
    __tablename__ = "pending_orders"
    __table_args__ = (
        UniqueConstraint(
            "institution",
            "external_order_id",
            name="uq_pending_orders_institution_external_order_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("assets.id", ondelete="CASCADE"),
        nullable=False,
    )
    institution: Mapped[str] = mapped_column(String(50), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    placed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="pending_orders")


class BenchmarkQuote(Base):
    __tablename__ = "benchmark_quotes"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "captured_at",
            name="uq_benchmark_quotes_symbol_captured_at",
        ),
        Index("ix_benchmark_quotes_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    price_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)


class Transaction(Base):
    """Normalized transaction record from any broker."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_transactions_fingerprint"),
        Index("ix_transactions_asset_symbol", "asset_symbol"),
        Index("ix_transactions_timestamp", "timestamp"),
        Index("ix_transactions_institution", "institution"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    institution: Mapped[str] = mapped_column(String(50), nullable=False)
    tx_type: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_type: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    total_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 10), default=Decimal("0"), nullable=False
    )
    fee_currency: Mapped[str] = mapped_column(String(20), default="USD", nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    import_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("import_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    import_artifact: Mapped["ImportArtifact | None"] = relationship(
        "ImportArtifact", back_populates="transactions"
    )


class ImportArtifact(Base):
    """Raw uploaded file + parsing status."""

    __tablename__ = "import_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    institution: Mapped[str] = mapped_column(String(50), nullable=False)
    filename: Mapped[str] = mapped_column(String(256), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    parsed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    committed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    committed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        "Transaction", back_populates="import_artifact"
    )
    activity_logs: Mapped[list["ActivityLog"]] = relationship(
        "ActivityLog", back_populates="artifact"
    )


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    condition: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    events: Mapped[list["AlertEvent"]] = relationship(
        "AlertEvent", back_populates="rule", passive_deletes=True
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_triggered_at", "triggered_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_delivered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rule: Mapped["AlertRule"] = relationship("AlertRule", back_populates="events")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("symbol", name="uq_watchlist_items_symbol"),
        Index("ix_watchlist_items_status_priority", "status", "priority"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    market: Mapped[str | None] = mapped_column(String(30), nullable=True)
    asset_type: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False
    )
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="idea", nullable=False)
    target_entry_min: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    target_entry_max: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalyst: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_review_date: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    owned_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    target_alerts: Mapped[list["WatchlistTargetAlert"]] = relationship(
        "WatchlistTargetAlert", back_populates="watchlist_item", passive_deletes=True
    )


class WatchlistTargetAlert(Base):
    __tablename__ = "watchlist_target_alerts"
    __table_args__ = (Index("ix_watchlist_target_alerts_triggered_at", "triggered_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    watchlist_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("watchlist_items.id", ondelete="CASCADE"), nullable=False
    )
    trigger_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    target_entry_max: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_delivered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    watchlist_item: Mapped["WatchlistItem"] = relationship(
        "WatchlistItem", back_populates="target_alerts"
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_auth_sessions_session_id"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_revoked_at", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_jti: Mapped[str] = mapped_column(String(36), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="auth_sessions")


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset", secondary=asset_tags, back_populates="tags"
    )


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset", secondary="asset_themes", back_populates="themes"
    )


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_entity", "entity_type", "entity_id"),
        Index("ix_notes_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User | None"] = relationship("User", back_populates="notes")


class NoteVersion(Base):
    __tablename__ = "note_versions"
    __table_args__ = (
        UniqueConstraint("note_id", "version", name="uq_note_versions_note_id_version"),
        Index("ix_note_versions_note_id", "note_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    note_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_activity_logs_created_at", "created_at"),
        Index("ix_activity_logs_source_status", "source", "status"),
        Index("ix_activity_logs_artifact_id", "artifact_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSON, default=dict, nullable=False
    )
    artifact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("import_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    artifact: Mapped["ImportArtifact | None"] = relationship(
        "ImportArtifact", back_populates="activity_logs"
    )
    user: Mapped["User | None"] = relationship("User", back_populates="activity_logs")


class AccountingTransferLink(Base):
    __tablename__ = "accounting_transfer_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'voided')",
            name="ck_accounting_transfer_links_status",
        ),
        CheckConstraint(
            "decision_source IN ('manual', 'system', 'import', 'deterministic')",
            name="ck_accounting_transfer_links_decision_source",
        ),
        CheckConstraint(
            "confidence_state IN ('trusted', 'warning', 'provisional', "
            "'review_required', 'blocked')",
            name="ck_accounting_transfer_links_confidence_state",
        ),
        CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_accounting_transfer_links_void_lifecycle",
        ),
        CheckConstraint(
            "from_quantity > 0 AND to_quantity > 0 AND quantity_delta >= 0",
            name="ck_accounting_transfer_links_quantity_sanity",
        ),
        CheckConstraint(
            "fee_quantity IS NULL OR fee_quantity >= 0",
            name="ck_accounting_transfer_links_fee_sanity",
        ),
        CheckConstraint(
            "amount_usd IS NULL OR amount_usd >= 0",
            name="ck_accounting_transfer_links_amount_sanity",
        ),
        CheckConstraint(
            "from_evidence_key <> to_evidence_key",
            name="ck_accounting_transfer_links_distinct_evidence",
        ),
        Index("ix_accounting_transfer_links_occurred_at", "occurred_at"),
        Index("ix_accounting_transfer_links_sources", "from_source", "to_source"),
        Index(
            "uq_accounting_transfer_links_active_group",
            "link_group_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_accounting_transfer_links_active_from_evidence",
            "from_evidence_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_accounting_transfer_links_active_to_evidence",
            "to_evidence_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    link_group_key: Mapped[str] = mapped_column(String(128), nullable=False)
    from_evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    to_evidence: Mapped[dict | list[dict]] = mapped_column(JSON, nullable=False)
    from_evidence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    to_evidence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    from_quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    to_quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    fee_quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 10), nullable=True)
    fee_asset_symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    from_source: Mapped[str] = mapped_column(String(50), nullable=False)
    to_source: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    confidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    review_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accounting_transfer_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountingExternalCashflowClassification(Base):
    __tablename__ = "accounting_external_cashflow_classifications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'voided')",
            name="ck_acct_cashflow_status",
        ),
        CheckConstraint(
            "decision_source IN ('manual', 'system', 'import', 'deterministic')",
            name="ck_acct_cashflow_decision_source",
        ),
        CheckConstraint(
            "confidence_state IN ('trusted', 'warning', 'provisional', "
            "'review_required', 'blocked')",
            name="ck_acct_cashflow_confidence_state",
        ),
        CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_acct_cashflow_void_lifecycle",
        ),
        CheckConstraint(
            "cashflow_type IN ('external_deposit', 'external_withdrawal', "
            "'not_external_cashflow')",
            name="ck_acct_cashflow_cashflow_type",
        ),
        CheckConstraint(
            "movement_type IN ('external_cashflow', 'internal_movement', "
            "'trade_allocation')",
            name="ck_acct_cashflow_movement_type",
        ),
        CheckConstraint(
            "((cashflow_type = 'external_deposit' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd >= 0)) OR "
            "(cashflow_type = 'external_withdrawal' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd <= 0)) OR "
            "(cashflow_type = 'not_external_cashflow' AND "
            "(capital_effect_usd IS NULL OR capital_effect_usd = 0)))",
            name="ck_acct_cashflow_capital_effect",
        ),
        CheckConstraint(
            "((cashflow_type IN ('external_deposit', 'external_withdrawal') "
            "AND movement_type = 'external_cashflow') OR "
            "(cashflow_type = 'not_external_cashflow' "
            "AND movement_type <> 'external_cashflow'))",
            name="ck_acct_cashflow_type_movement_pair",
        ),
        Index(
            "ix_acct_cashflow_occurred_at",
            "occurred_at",
        ),
        Index(
            "ix_acct_cashflow_source",
            "source",
        ),
        Index(
            "uq_acct_cashflow_active_key",
            "classification_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_acct_cashflow_active_evidence",
            "evidence_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    classification_key: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cashflow_type: Mapped[str] = mapped_column(String(40), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(30, 10), nullable=False)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    capital_effect_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    confidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    materiality_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    review_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "accounting_external_cashflow_classifications.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountingImportApproval(Base):
    __tablename__ = "accounting_import_approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'voided')",
            name="ck_accounting_import_approvals_status",
        ),
        CheckConstraint(
            "decision_source IN ('manual', 'system', 'import', 'deterministic')",
            name="ck_accounting_import_approvals_decision_source",
        ),
        CheckConstraint(
            "confidence_state IN ('trusted', 'warning', 'provisional', "
            "'review_required', 'blocked')",
            name="ck_accounting_import_approvals_confidence_state",
        ),
        CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_accounting_import_approvals_void_lifecycle",
        ),
        CheckConstraint(
            "coverage_start IS NULL OR coverage_end IS NULL OR "
            "coverage_start <= coverage_end",
            name="ck_accounting_import_approvals_coverage_order",
        ),
        Index(
            "ix_accounting_import_approvals_source_scope",
            "source",
            "import_scope_id",
        ),
        Index(
            "ix_accounting_import_approvals_coverage",
            "coverage_start",
            "coverage_end",
        ),
        Index(
            "uq_accounting_import_approvals_active_key",
            "approval_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    approval_key: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    import_scope_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_fingerprints: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    coverage_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    coverage_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_scope: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    control_totals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    review_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accounting_import_approvals.id", ondelete="SET NULL"),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountingCostBasisDecision(Base):
    __tablename__ = "accounting_cost_basis_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded', 'voided')",
            name="ck_accounting_cost_basis_decisions_status",
        ),
        CheckConstraint(
            "decision_source IN ('manual', 'system', 'import', 'deterministic')",
            name="ck_accounting_cost_basis_decisions_decision_source",
        ),
        CheckConstraint(
            "confidence_state IN ('trusted', 'warning', 'provisional', "
            "'review_required', 'blocked')",
            name="ck_accounting_cost_basis_decisions_confidence_state",
        ),
        CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_accounting_cost_basis_decisions_void_lifecycle",
        ),
        CheckConstraint(
            "decision_type IN ('manual_cost_basis', 'unknown_cost_basis')",
            name="ck_accounting_cost_basis_decisions_decision_type",
        ),
        CheckConstraint(
            "basis_scope IN ('lot', 'position', 'asset_source', 'asset_global')",
            name="ck_accounting_cost_basis_decisions_basis_scope",
        ),
        CheckConstraint(
            "decision_type <> 'manual_cost_basis' OR "
            "cost_basis_usd IS NOT NULL OR "
            "(quantity IS NOT NULL AND unit_cost_usd IS NOT NULL)",
            name="ck_accounting_cost_basis_decisions_manual_value",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0",
            name="ck_accounting_cost_basis_decisions_quantity_positive",
        ),
        CheckConstraint(
            "cost_basis_usd IS NULL OR cost_basis_usd >= 0",
            name="ck_accounting_cost_basis_decisions_total_nonnegative",
        ),
        CheckConstraint(
            "unit_cost_usd IS NULL OR unit_cost_usd >= 0",
            name="ck_accounting_cost_basis_decisions_unit_nonnegative",
        ),
        CheckConstraint(
            "cost_basis_usd IS NULL OR quantity IS NULL OR unit_cost_usd IS NULL OR "
            "cost_basis_usd = round(quantity * unit_cost_usd, 6)",
            name="ck_accounting_cost_basis_decisions_value_consistent",
        ),
        CheckConstraint(
            "decision_type <> 'unknown_cost_basis' OR confidence_state <> 'trusted'",
            name="ck_accounting_cost_basis_decisions_unknown_not_trusted",
        ),
        Index(
            "ix_accounting_cost_basis_decisions_asset_effective_at",
            "asset_symbol",
            "effective_at",
        ),
        Index(
            "uq_accounting_cost_basis_decisions_active_key",
            "basis_key",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    basis_key: Mapped[str] = mapped_column(String(160), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_account_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    basis_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 10), nullable=True)
    cost_basis_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 6), nullable=True
    )
    unit_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    basis_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidence_state: Mapped[str] = mapped_column(String(30), nullable=False)
    affected_metric_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accounting_cost_basis_decisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountingReconciliationTask(Base):
    __tablename__ = "accounting_reconciliation_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'superseded', 'voided')",
            name="ck_accounting_reconciliation_tasks_status",
        ),
        CheckConstraint(
            "severity IN ('warning', 'provisional', 'review_required', 'blocked')",
            name="ck_accounting_reconciliation_tasks_severity",
        ),
        CheckConstraint(
            "task_type IN ('unknown_outgoing_transfer', 'missing_cost_basis', "
            "'import_approval', 'source_coverage_gap')",
            name="ck_accounting_reconciliation_tasks_task_type",
        ),
        CheckConstraint(
            "((status = 'voided' AND voided_at IS NOT NULL AND voided_by IS NOT NULL) "
            "OR (status <> 'voided' AND voided_at IS NULL AND voided_by IS NULL))",
            name="ck_accounting_reconciliation_tasks_void_lifecycle",
        ),
        CheckConstraint(
            "((status = 'resolved' AND resolved_at IS NOT NULL "
            "AND resolved_by IS NOT NULL "
            "AND resolved_by_decision_type IS NOT NULL "
            "AND resolved_by_decision_id IS NOT NULL) OR "
            "(status <> 'resolved' AND resolved_at IS NULL "
            "AND resolved_by IS NULL "
            "AND resolved_by_decision_type IS NULL "
            "AND resolved_by_decision_id IS NULL))",
            name="ck_accounting_reconciliation_tasks_resolution_lifecycle",
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity >= 0",
            name="ck_accounting_reconciliation_tasks_quantity_sanity",
        ),
        CheckConstraint(
            "amount_usd IS NULL OR amount_usd >= 0",
            name="ck_accounting_reconciliation_tasks_amount_sanity",
        ),
        CheckConstraint(
            "resolved_by_decision_type IS NULL OR "
            "resolved_by_decision_type IN ("
            "'accounting_transfer_link', "
            "'accounting_external_cashflow_classification', "
            "'accounting_import_approval', "
            "'accounting_cost_basis_decision')",
            name="ck_accounting_reconciliation_tasks_decision_reference",
        ),
        Index(
            "ix_accounting_reconciliation_tasks_source_occurred_at",
            "source",
            "occurred_at",
        ),
        Index(
            "ix_accounting_reconciliation_tasks_status_severity",
            "status",
            "severity",
        ),
        Index(
            "uq_accounting_reconciliation_tasks_task_id",
            "task_id",
            unique=True,
        ),
        Index(
            "uq_accounting_reconciliation_tasks_active_key",
            "task_key",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    task_key: Mapped[str] = mapped_column(String(180), nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    asset_symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(30, 10), nullable=True)
    amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    candidate_actions: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    affected_metric_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    resolved_by_decision_type: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    resolved_by_decision_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(80), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("accounting_reconciliation_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class AccountingEvidenceClaim(Base):
    __tablename__ = "accounting_evidence_claims"
    __table_args__ = (
        UniqueConstraint("evidence_key", name="uq_accounting_evidence_claims_key"),
        CheckConstraint(
            "source_table IN ('accounting_transfer_links', "
            "'accounting_external_cashflow_classifications')",
            name="ck_accounting_evidence_claims_source_table",
        ),
        CheckConstraint(
            "claim_role IN ('transfer_from', 'transfer_to', 'cashflow')",
            name="ck_accounting_evidence_claims_role",
        ),
        Index("ix_accounting_evidence_claims_source", "source_table", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    evidence_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source_table: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    claim_role: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
