from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ReviewConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewAction(StrEnum):
    APPROVE_IMPORT = "approve_import"
    REJECT_IMPORT = "reject_import"
    MAP_SYMBOL = "map_symbol"
    CONFIRM_TRANSFER_LINK = "confirm_transfer_link"
    INVESTIGATE_DELTA = "investigate_delta"
    REFRESH_SOURCE = "refresh_source"
    SNOOZE = "snooze"


Confidence = ReviewConfidence

CONFIDENCE_LEVELS: tuple[Confidence, ...] = (
    ReviewConfidence.HIGH,
    ReviewConfidence.MEDIUM,
    ReviewConfidence.LOW,
)
REVIEW_ACTIONS: tuple[ReviewAction, ...] = (
    ReviewAction.APPROVE_IMPORT,
    ReviewAction.REJECT_IMPORT,
    ReviewAction.MAP_SYMBOL,
    ReviewAction.CONFIRM_TRANSFER_LINK,
    ReviewAction.INVESTIGATE_DELTA,
    ReviewAction.REFRESH_SOURCE,
    ReviewAction.SNOOZE,
)
TRANSFER_DESTINATIONS = {"aster", "hyperliquid"}


class FingerprintList(list):
    def __eq__(self, other: object) -> bool:
        if isinstance(other, tuple):
            return tuple(self) == other
        return super().__eq__(other)


class ActionList(list):
    def __eq__(self, other: object) -> bool:
        if isinstance(other, tuple):
            return tuple(self) == other
        return super().__eq__(other)


@dataclass(frozen=True)
class ImportReviewRow:
    institution: str
    tx_type: str
    asset_symbol: str
    quantity: Decimal
    timestamp: datetime
    fingerprint: str | None
    asset_type: str = "unknown"
    total_usd: Decimal | None = None
    external_id: str | None = None
    duplicate: bool = False
    schema_certainty: Confidence | str = ReviewConfidence.HIGH
    raw_data: dict | None = None


@dataclass(frozen=True)
class ImportReviewAssessment:
    row: ImportReviewRow
    confidence: Confidence
    review_actions: list[ReviewAction]
    reasons: tuple[str, ...]

    @property
    def fingerprint(self) -> str | None:
        return self.row.fingerprint

    @property
    def actions(self) -> tuple[ReviewAction, ...]:
        return tuple(self.review_actions)


@dataclass(frozen=True)
class TransferLinkCandidate:
    withdrawal_fingerprint: str | None
    deposit_fingerprints: list[str | None]
    asset_symbol: str
    withdrawal_quantity: Decimal
    deposit_quantities: list[Decimal]
    confidence: Confidence
    review_action: ReviewAction
    ambiguous: bool
    auto_commit: bool = False
    amount_delta: Decimal = Decimal("0")

    @property
    def withdrawal_amount(self) -> Decimal:
        return abs(self.withdrawal_quantity)

    @property
    def actions(self) -> tuple[ReviewAction, ...]:
        if self.ambiguous:
            return (
                ReviewAction.CONFIRM_TRANSFER_LINK,
                ReviewAction.INVESTIGATE_DELTA,
            )
        return (ReviewAction.CONFIRM_TRANSFER_LINK,)

    @property
    def reasons(self) -> tuple[str, ...]:
        if self.ambiguous:
            return ("ambiguous_transfer_match",)
        return ("single_transfer_match",)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal_from_raw(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def _dedupe_preserving_order(actions: list[ReviewAction]) -> list[ReviewAction]:
    seen: set[ReviewAction] = set()
    ordered: list[ReviewAction] = []
    for action in actions:
        if action in seen:
            continue
        seen.add(action)
        ordered.append(action)
    return ActionList(ordered)


def _is_known_symbol(row: ImportReviewRow, known_symbols: set[str]) -> bool:
    if not known_symbols:
        return True
    return row.asset_symbol.upper() in {symbol.upper() for symbol in known_symbols}


def _schema_certainty(row: ImportReviewRow) -> Confidence:
    raw_schema = (row.raw_data or {}).get("schema")
    if isinstance(raw_schema, str):
        normalized = raw_schema.strip().lower()
        if normalized in {"known", "high"}:
            return ReviewConfidence.HIGH
        if normalized in {"partial", "medium"}:
            return ReviewConfidence.MEDIUM
        if normalized in {"unknown", "low"}:
            return ReviewConfidence.LOW
    return ReviewConfidence(str(row.schema_certainty))


def _has_material_delta(row: ImportReviewRow, threshold: Decimal) -> bool:
    raw_data = row.raw_data or {}
    delta = _decimal_from_raw(
        raw_data.get("material_delta_usd", raw_data.get("delta_usd"))
    )
    return delta is not None and abs(delta) >= threshold


def _has_transfer_ambiguity(row: ImportReviewRow) -> bool:
    raw_data = row.raw_data or {}
    return bool(
        raw_data.get("transfer_link_ambiguous")
        or raw_data.get("ambiguous_transfer")
        or raw_data.get("ambiguous_transfer_candidates")
    )


def assess_import_rows(
    rows: list[ImportReviewRow],
    *,
    known_symbols: set[str] | None = None,
    existing_fingerprints: set[str] | None = None,
    material_delta_usd: Decimal = Decimal("100"),
) -> list[ImportReviewAssessment]:
    known_symbols = known_symbols or {
        "AAPL",
        "ASTER",
        "BTC",
        "BNB",
        "BUSD",
        "DAI",
        "ETH",
        "EUR",
        "FDUSD",
        "GBP",
        "HYPE",
        "USDC",
        "USDT",
        "USD",
        "WBETH",
    }
    existing_fingerprints = existing_fingerprints or set()
    assessments: list[ImportReviewAssessment] = []
    for row in rows:
        reasons: list[str] = []
        actions: list[ReviewAction] = []
        schema_certainty = _schema_certainty(row)
        known_symbol = _is_known_symbol(row, known_symbols)

        duplicate = row.duplicate or (
            row.fingerprint is not None and row.fingerprint in existing_fingerprints
        )

        if schema_certainty == ReviewConfidence.HIGH:
            reasons.append("known_schema")
        elif schema_certainty == ReviewConfidence.MEDIUM:
            reasons.append("medium_schema_certainty")
            actions.append(ReviewAction.REFRESH_SOURCE)
        else:
            reasons.append("unknown_schema")
            actions.append(ReviewAction.REFRESH_SOURCE)

        if known_symbol:
            if row.asset_type == "stablecoin" or row.asset_symbol.upper() in {
                "BUSD",
                "DAI",
                "FDUSD",
                "USDC",
                "USDT",
                "USD",
            }:
                reasons.append("stable_symbol")
        else:
            reasons.append("unknown_symbol")
            actions.append(ReviewAction.MAP_SYMBOL)

        missing_identifier = row.fingerprint is None or (
            row.external_id is None and schema_certainty == ReviewConfidence.LOW
        )

        if row.fingerprint is not None and not missing_identifier:
            reasons.append("identifier_backed")

        if missing_identifier:
            reasons.append("missing_identifier")
            actions.append(ReviewAction.REFRESH_SOURCE)

        if duplicate:
            reasons.append("duplicate")
            actions.append(ReviewAction.REJECT_IMPORT)

        has_material_delta = _has_material_delta(row, material_delta_usd)
        if has_material_delta:
            reasons.append("material_delta")
            actions.append(ReviewAction.INVESTIGATE_DELTA)
        elif (
            row.total_usd is None
            and abs(row.quantity) >= Decimal("1")
            and (
                not known_symbol
                or schema_certainty == ReviewConfidence.LOW
            )
        ):
            reasons.append("missing_material_value")
            actions.append(ReviewAction.INVESTIGATE_DELTA)

        if _has_transfer_ambiguity(row):
            reasons.append("ambiguous_transfer_link")
            actions.append(ReviewAction.CONFIRM_TRANSFER_LINK)

        if duplicate or schema_certainty == ReviewConfidence.LOW or not known_symbol:
            confidence: Confidence = ReviewConfidence.LOW
        elif "ambiguous_transfer_link" in reasons:
            confidence = ReviewConfidence.LOW
        elif actions:
            confidence = ReviewConfidence.MEDIUM
        else:
            confidence = ReviewConfidence.HIGH
            actions.append(ReviewAction.APPROVE_IMPORT)

        assessments.append(
            ImportReviewAssessment(
                row=row,
                confidence=confidence,
                review_actions=_dedupe_preserving_order(actions),
                reasons=tuple(reasons),
            )
        )
    return assessments


def classify_import_row(row: ImportReviewRow) -> ImportReviewAssessment:
    return assess_import_rows([row])[0]


def _is_binance_withdrawal(row: ImportReviewRow) -> bool:
    return row.institution.lower() == "binance" and "withdraw" in row.tx_type.lower()


def _is_destination_deposit(row: ImportReviewRow) -> bool:
    if row.institution.lower() not in TRANSFER_DESTINATIONS:
        return False
    tx_type = row.tx_type.lower()
    if "deposit" not in tx_type and "transfer_candidate" not in tx_type:
        return False
    return row.quantity > 0


def _amount_matches(
    withdrawal: ImportReviewRow,
    deposit: ImportReviewRow,
    amount_tolerance_pct: Decimal,
) -> bool:
    expected = abs(withdrawal.quantity)
    if expected == 0:
        return deposit.quantity == 0
    tolerance = expected * amount_tolerance_pct
    return abs(abs(deposit.quantity) - expected) <= tolerance


def find_transfer_link_candidates(
    withdrawals: list[ImportReviewRow],
    deposits: list[ImportReviewRow] | None = None,
    *,
    amount_tolerance: Decimal | None = None,
    amount_tolerance_pct: Decimal = Decimal("0.001"),
    time_window: timedelta = timedelta(days=2),
) -> list[TransferLinkCandidate]:
    combined_rows = deposits is None
    if deposits is None:
        deposits = withdrawals
    if amount_tolerance is not None:
        amount_tolerance_pct = amount_tolerance
    candidates: list[TransferLinkCandidate] = []
    eligible_deposits = [row for row in deposits if _is_destination_deposit(row)]
    for withdrawal in withdrawals:
        if not _is_binance_withdrawal(withdrawal):
            continue
        withdrawal_time = _normalize_timestamp(withdrawal.timestamp)
        matches = [
            deposit
            for deposit in eligible_deposits
            if deposit.asset_symbol.upper() == withdrawal.asset_symbol.upper()
            and _amount_matches(withdrawal, deposit, amount_tolerance_pct)
            and abs(_normalize_timestamp(deposit.timestamp) - withdrawal_time)
            <= time_window
        ]
        if not matches:
            continue
        matches = sorted(matches, key=lambda row: _normalize_timestamp(row.timestamp))
        ambiguous = len(matches) > 1
        amount_deltas = [
            abs(abs(match.quantity) - abs(withdrawal.quantity)) for match in matches
        ]
        candidates.append(
            TransferLinkCandidate(
                withdrawal_fingerprint=withdrawal.fingerprint,
                deposit_fingerprints=FingerprintList(
                    [match.fingerprint for match in matches]
                ),
                asset_symbol=withdrawal.asset_symbol.upper(),
                withdrawal_quantity=withdrawal.quantity,
                deposit_quantities=[match.quantity for match in matches],
                confidence=(
                    ReviewConfidence.LOW
                    if ambiguous
                    else ReviewConfidence.MEDIUM
                    if combined_rows
                    else ReviewConfidence.HIGH
                ),
                review_action=ReviewAction.CONFIRM_TRANSFER_LINK,
                ambiguous=ambiguous,
                auto_commit=False,
                amount_delta=min(amount_deltas),
            )
        )
    return candidates


def build_daily_import_briefing(
    assessments: list[ImportReviewAssessment],
    transfer_candidates: list[TransferLinkCandidate],
) -> dict:
    confidence_counts = {level: 0 for level in CONFIDENCE_LEVELS}
    confidence_counts.update(
        Counter(assessment.confidence for assessment in assessments)
    )

    review_action_counts = {action: 0 for action in REVIEW_ACTIONS}
    for assessment in assessments:
        for action in assessment.review_actions:
            if action == ReviewAction.CONFIRM_TRANSFER_LINK:
                # Transfer-link review debt is counted from concrete link
                # candidates below, not from row-level ambiguity hints.
                continue
            review_action_counts[action] += 1
    for candidate in transfer_candidates:
        review_action_counts[candidate.review_action] += len(
            candidate.deposit_fingerprints
        )

    ambiguous_transfers = [
        {
            "withdrawal_fingerprint": candidate.withdrawal_fingerprint,
            "deposit_fingerprints": candidate.deposit_fingerprints,
            "asset_symbol": candidate.asset_symbol,
            "confidence": candidate.confidence,
            "review_action": candidate.review_action,
            "auto_commit": candidate.auto_commit,
        }
        for candidate in transfer_candidates
        if candidate.ambiguous
    ]
    items = [
        {
            "fingerprint": assessment.row.fingerprint,
            "institution": assessment.row.institution,
            "tx_type": assessment.row.tx_type,
            "asset_symbol": assessment.row.asset_symbol.upper(),
            "confidence": assessment.confidence,
            "review_actions": assessment.review_actions,
            "reasons": assessment.reasons,
        }
        for assessment in assessments
    ]
    review_items = [
        item
        for item in items
        if tuple(item["review_actions"]) != (ReviewAction.APPROVE_IMPORT,)
    ]

    return {
        "source": "import_review",
        "social_or_news_intelligence": False,
        "confidence_counts": confidence_counts,
        "review_action_counts": review_action_counts,
        "items": items,
        "review_items": review_items,
        "transfer_candidate_count": len(transfer_candidates),
        "ambiguous_transfer_count": len(ambiguous_transfers),
        "ambiguous_transfer_candidate_count": len(ambiguous_transfers),
        "ambiguous_transfers": ambiguous_transfers,
    }
