"""
Portfolio analytics: holdings aggregation, weighted-average cost basis, P&L.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Transaction

# Transaction types that represent buying (increasing position)
BUY_TYPES = {
    "buy",
    "spot_trade_buy",
    "convert_buy",
    "staking_reward",
    "staking_subscribe",
    "dividend",
    "deposit",
    "transfer_in",
    "earn_interest",
    "earn_reward",
    "airdrop",
}
# Transaction types that represent selling (decreasing position)
SELL_TYPES = {
    "sell",
    "spot_trade_sell",
    "convert_sell",
    "withdrawal",
    "transfer_out",
    "fee",
    "staking_redeem",
    "earn_redeem",
}
BENCHMARK_PROXY_SYMBOLS = ("SPY", "BTC", "XAU")
STABLECOINS = {"USDT", "USDC", "FDUSD", "BUSD", "DAI"}
EXCLUDED_HOLDING_SYMBOLS = {"USD", *STABLECOINS}
BINANCE_LD_ASSET_SYMBOLS = {
    "LDBTC",
    "LDETH",
    "LDBNSOL",
    "LDASTER",
    "LDWBETH",
    "LDBNB",
    "LDAUDIO",
}


@dataclass
class HoldingStats:
    symbol: str
    asset_type: str
    quantity: Decimal
    avg_buy_price_usd: Decimal | None
    total_cost_usd: Decimal
    current_price_usd: Decimal | None = None
    current_value_usd: Decimal | None = None
    unrealized_pnl_usd: Decimal | None = None
    unrealized_pnl_pct: Decimal | None = None
    institution: str = "unknown"
    source_drilldown: list[dict] | None = None


@dataclass
class BinanceSnapshotAggregation:
    quantities: dict[str, Decimal]
    source_drilldown: dict[str, list[dict]]


def _classify_tx_side(tx_type: str) -> str:
    """Return 'buy', 'sell', or 'neutral' for a transaction type."""
    t = tx_type.lower()
    if any(t == bt or t.endswith(bt) for bt in BUY_TYPES):
        return "buy"
    if any(t == st or t.endswith(st) for st in SELL_TYPES):
        return "sell"
    # XTB-style types
    if t in ("open", "buy"):
        return "buy"
    if t in ("close", "sell"):
        return "sell"
    return "neutral"


def _merge_institution(current: str | None, new: str) -> str:
    if not current or current == new:
        return new
    return "multiple"


def _normalize_holding_symbol(tx: Transaction) -> str:
    symbol = tx.asset_symbol.upper()
    if tx.institution == "binance" and symbol in BINANCE_LD_ASSET_SYMBOLS:
        return symbol[2:]
    return symbol


def _is_binance_snapshot_tx(tx: Transaction) -> bool:
    return tx.institution == "binance" and (
        tx.tx_type.startswith("balance_snapshot_") or tx.tx_type == "staking_position"
    )


def _binance_snapshot_source(tx: Transaction) -> str:
    symbol = tx.asset_symbol.upper()
    if symbol in BINANCE_LD_ASSET_SYMBOLS:
        return "ld_receipt_token"
    if symbol in {"BETH", "WBETH"}:
        return "wbeth_beth_wrapper"
    if tx.tx_type == "staking_position":
        return "staking_position"
    if tx.tx_type == "balance_snapshot_earn":
        return "earn_position"
    if tx.tx_type == "balance_snapshot_funding":
        return "funding_wallet"
    if tx.tx_type == "balance_snapshot_spot":
        return "spot_wallet"
    return "other_snapshot"


def _snapshot_detail(
    tx: Transaction,
    *,
    normalized_symbol: str,
    included: bool,
    reason: str,
) -> dict:
    return {
        "asset_symbol": tx.asset_symbol.upper(),
        "normalized_symbol": normalized_symbol,
        "source": _binance_snapshot_source(tx),
        "tx_type": tx.tx_type,
        "quantity": tx.quantity,
        "included": included,
        "reason": reason,
    }


def latest_binance_snapshot_aggregation(
    transactions: list[Transaction],
    *,
    include_cash: bool = False,
) -> BinanceSnapshotAggregation:
    snapshot_transactions = [tx for tx in transactions if _is_binance_snapshot_tx(tx)]
    quantities: dict[str, Decimal] = defaultdict(Decimal)
    source_drilldown: dict[str, list[dict]] = defaultdict(list)
    if not snapshot_transactions:
        return BinanceSnapshotAggregation(dict(quantities), dict(source_drilldown))

    latest_timestamp = max(tx.timestamp for tx in snapshot_transactions)
    latest_rows = [
        tx for tx in snapshot_transactions if tx.timestamp == latest_timestamp
    ]
    economic_sources_by_symbol: dict[str, set[str]] = defaultdict(set)
    for tx in latest_rows:
        normalized_symbol = _normalize_holding_symbol(tx)
        source = _binance_snapshot_source(tx)
        if not include_cash and normalized_symbol in EXCLUDED_HOLDING_SYMBOLS:
            continue
        if source != "ld_receipt_token":
            economic_sources_by_symbol[normalized_symbol].add(source)

    for tx in latest_rows:
        normalized_symbol = _normalize_holding_symbol(tx)
        if not include_cash and normalized_symbol in EXCLUDED_HOLDING_SYMBOLS:
            source_drilldown[normalized_symbol].append(
                _snapshot_detail(
                    tx,
                    normalized_symbol=normalized_symbol,
                    included=False,
                    reason="cash_or_stablecoin_excluded_from_holdings",
                )
            )
            continue

        source = _binance_snapshot_source(tx)
        duplicate_sources = economic_sources_by_symbol.get(normalized_symbol, set())
        is_duplicate_receipt = source == "ld_receipt_token" and bool(
            duplicate_sources
            & {"earn_position", "staking_position", "wbeth_beth_wrapper"}
        )
        if is_duplicate_receipt:
            source_drilldown[normalized_symbol].append(
                _snapshot_detail(
                    tx,
                    normalized_symbol=normalized_symbol,
                    included=False,
                    reason="ld_receipt_token_excluded_corresponding_position_present",
                )
            )
            continue

        is_duplicate_staking = (
            source == "staking_position" and "earn_position" in duplicate_sources
        )
        if is_duplicate_staking:
            source_drilldown[normalized_symbol].append(
                _snapshot_detail(
                    tx,
                    normalized_symbol=normalized_symbol,
                    included=False,
                    reason="staking_position_excluded_corresponding_earn_position_present",
                )
            )
            continue

        quantities[normalized_symbol] += tx.quantity
        reason = (
            "ld_receipt_token_included_no_corresponding_position"
            if source == "ld_receipt_token"
            else "included_economic_exposure"
        )
        source_drilldown[normalized_symbol].append(
            _snapshot_detail(
                tx,
                normalized_symbol=normalized_symbol,
                included=True,
                reason=reason,
            )
        )
    return BinanceSnapshotAggregation(dict(quantities), dict(source_drilldown))


def _latest_binance_snapshot_quantities(
    transactions: list[Transaction],
) -> dict[str, Decimal]:
    return latest_binance_snapshot_aggregation(transactions).quantities


def calculate_holdings(transactions: list[Transaction]) -> list[HoldingStats]:
    qty: dict[str, Decimal] = defaultdict(Decimal)
    cost: dict[str, Decimal] = defaultdict(Decimal)
    asset_type_map: dict[str, str] = {}
    institution_map: dict[str, str] = {}
    latest_binance_snapshot = latest_binance_snapshot_aggregation(transactions)
    latest_binance_snapshot_qty = latest_binance_snapshot.quantities

    for tx in sorted(
        transactions,
        key=lambda row: (row.timestamp, getattr(row, "id", 0)),
    ):
        sym = _normalize_holding_symbol(tx)
        if sym in EXCLUDED_HOLDING_SYMBOLS:
            continue
        asset_type_map[sym] = tx.asset_type
        institution_map[sym] = _merge_institution(
            institution_map.get(sym), tx.institution
        )

        if latest_binance_snapshot_qty and tx.institution == "binance":
            continue

        if tx.tx_type.lower() in {"staking_subscribe", "earn_subscribe"}:
            raw_data = getattr(tx, "raw_data", {}) or {}
            source_asset = (
                raw_data.get("stake_asset")
                or raw_data.get("from_account_asset")
                or raw_data.get("coin")
            )
            source_amount = _decimal_or_zero(
                raw_data.get("stake_amount")
                or raw_data.get("amount")
                or raw_data.get("subscription_amount")
            )
            if source_asset and source_amount > 0:
                source_symbol = source_asset.upper()
                previous_qty = qty[source_symbol]
                if previous_qty > 0:
                    moved_qty = min(previous_qty, source_amount)
                    moved_cost = cost[source_symbol] * (moved_qty / previous_qty)
                    qty[source_symbol] -= moved_qty
                    cost[source_symbol] -= moved_cost
                    qty[sym] += tx.quantity
                    cost[sym] += moved_cost
                    continue

        if tx.tx_type.lower() in {"staking_redeem", "earn_redeem"}:
            raw_data = getattr(tx, "raw_data", {}) or {}
            source_asset = raw_data.get("redeem_asset") or raw_data.get("coin") or sym
            source_amount = _decimal_or_zero(
                raw_data.get("redeem_amount")
                or raw_data.get("principal_redeemed")
                or tx.quantity
            )
            if source_asset and source_amount > 0:
                source_symbol = source_asset.upper()
                previous_qty = qty[source_symbol]
                if previous_qty > 0:
                    moved_qty = min(previous_qty, source_amount)
                    moved_cost = cost[source_symbol] * (moved_qty / previous_qty)
                    qty[source_symbol] -= moved_qty
                    cost[source_symbol] -= moved_cost
                    qty[sym] += tx.quantity
                    cost[sym] += moved_cost
                    continue

        if _is_convert_basis_swap(tx):
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx.tx_type.lower() == "convert_sell":
                destination_asset = raw_data.get("convert_to_asset")
                destination_quantity = _decimal_or_zero(
                    raw_data.get("convert_to_quantity")
                )
                if destination_asset and destination_quantity > 0:
                    previous_qty = qty[sym]
                    if previous_qty > 0:
                        moved_qty = min(previous_qty, tx.quantity)
                        moved_cost = cost[sym] * (moved_qty / previous_qty)
                        qty[sym] -= moved_qty
                        cost[sym] -= moved_cost
                        destination_symbol = destination_asset.upper()
                        qty[destination_symbol] += destination_quantity
                        cost[destination_symbol] += moved_cost
                continue
            continue

        side = _classify_tx_side(tx.tx_type)

        if tx.tx_type.lower() == "split":
            if tx.quantity > 0 and qty[sym] > 0:
                qty[sym] *= tx.quantity
        elif side == "buy":
            qty[sym] += tx.quantity
            if tx.price_usd is not None:
                cost[sym] += tx.quantity * tx.price_usd
        elif side == "sell":
            previous_qty = qty[sym]
            sell_quantity = tx.quantity
            if getattr(tx, "fee_currency", "").upper() == sym:
                sell_quantity += getattr(tx, "fee", Decimal("0"))
            qty[sym] -= sell_quantity
            if previous_qty > 0:
                cost[sym] -= cost[sym] * (sell_quantity / previous_qty)
        elif tx.institution in ("binance",):
            if "transfer_in" in tx.tx_type:
                qty[sym] += tx.quantity
            elif "transfer_out" in tx.tx_type:
                qty[sym] -= tx.quantity

    for sym, snapshot_qty in latest_binance_snapshot_qty.items():
        qty[sym] += snapshot_qty
        institution_map[sym] = _merge_institution(institution_map.get(sym), "binance")

    holdings: list[HoldingStats] = []
    for sym, q in qty.items():
        if q <= Decimal("0.000001"):
            continue
        total_cost = cost.get(sym, Decimal("0"))
        avg_buy = total_cost / q if q > 0 and total_cost > 0 else None
        holdings.append(
            HoldingStats(
                symbol=sym,
                asset_type=asset_type_map.get(sym, "unknown"),
                quantity=q,
                avg_buy_price_usd=avg_buy,
                total_cost_usd=total_cost,
                institution=institution_map.get(sym, "unknown"),
                source_drilldown=latest_binance_snapshot.source_drilldown.get(sym),
            )
        )
    return sorted(holdings, key=lambda h: -(h.total_cost_usd or Decimal("0")))


async def fetch_transactions(session: AsyncSession) -> list[Transaction]:
    result = await session.execute(
        select(Transaction).order_by(Transaction.timestamp, Transaction.id)
    )
    return list(result.scalars().all())


async def get_holdings(session: AsyncSession) -> list[HoldingStats]:
    """
    Compute current holdings with weighted-average cost basis from all transactions.
    Binance snapshot records are treated as authoritative current balances.
    Cash-like assets are excluded from holdings.
    """
    transactions = await fetch_transactions(session)
    return calculate_holdings(transactions)


async def enrich_with_prices(
    holdings: list[HoldingStats], prices: dict[str, float | None]
) -> list[HoldingStats]:
    """Attach live prices and compute unrealized P&L."""
    for h in holdings:
        price = prices.get(h.symbol)
        if price is not None:
            h.current_price_usd = Decimal(str(price))
            h.current_value_usd = h.quantity * h.current_price_usd
            if h.total_cost_usd > 0:
                h.unrealized_pnl_usd = h.current_value_usd - h.total_cost_usd
                h.unrealized_pnl_pct = (
                    h.unrealized_pnl_usd / h.total_cost_usd * Decimal("100")
                )
    return holdings


def calculate_benchmark_ratios(
    prices: dict[str, float | None],
) -> dict[str, Decimal | None]:
    """Compute benchmark ratios using SPY as the S&P 500 proxy."""

    def _ratio(numerator: float | None, denominator: float | None) -> Decimal | None:
        if numerator is None or denominator in (None, 0):
            return None
        return Decimal(str(numerator)) / Decimal(str(denominator))

    spx_usd = prices.get("SPY")
    btc_usd = prices.get("BTC")
    gold_usd = prices.get("XAU")

    return {
        "spx_in_btc": _ratio(spx_usd, btc_usd),
        "spx_in_gold": _ratio(spx_usd, gold_usd),
    }


def portfolio_price_symbols(holdings: list[HoldingStats]) -> list[str]:
    """Return held symbols plus benchmark proxies, preserving first-seen order."""
    return list(
        dict.fromkeys(
            [holding.symbol for holding in holdings] + list(BENCHMARK_PROXY_SYMBOLS)
        )
    )


INCOME_TYPES = {"earn_reward", "staking_reward", "dividend", "airdrop", "reward_claim"}
EXTERNAL_DEPOSIT_TYPES = {"deposit", "external_deposit"}
EXTERNAL_WITHDRAWAL_TYPES = {"withdrawal", "external_withdrawal"}
BRIDGE_OUT_TYPES = {"bridge_transfer_out"}
BRIDGE_IN_TYPES = {"bridge_transfer_in"}
BRIDGE_PROVENANCE_KEYWORDS = ("hyperliquid", "aster")
INTERNAL_TRANSFER_TYPES = {
    "transfer_in",
    "transfer_out",
    "earn_subscribe",
    "earn_redeem",
    "staking_subscribe",
    "staking_redeem",
}


@dataclass
class PerformanceBucket:
    gross_deposits_usd: Decimal = Decimal("0")
    gross_withdrawals_usd: Decimal = Decimal("0")
    net_invested_capital_usd: Decimal = Decimal("0")
    bridge_transfer_out_usd: Decimal = Decimal("0")
    bridge_transfer_in_usd: Decimal = Decimal("0")
    unclassified_transfer_usd: Decimal = Decimal("0")
    reward_income_usd: Decimal = Decimal("0")
    fees_usd: Decimal = Decimal("0")
    realized_pnl_usd: Decimal = Decimal("0")
    total_cost_usd: Decimal = Decimal("0")
    current_value_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    total_pnl_usd: Decimal = Decimal("0")
    xirr: Decimal | None = None


@dataclass
class LotState:
    quantity: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")


def _decimal_or_zero(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if not text:
        return Decimal("0")
    return Decimal(text)


def _accounting_value_usd(tx: Transaction) -> Decimal:
    if tx.total_usd is not None:
        return tx.total_usd
    raw_value = (
        tx.raw_data.get("accounting_value_usd")
        if getattr(tx, "raw_data", None)
        else None
    )
    if raw_value not in (None, ""):
        return Decimal(str(raw_value))
    if tx.price_usd is not None:
        return tx.quantity * tx.price_usd
    if tx.asset_symbol.upper() in STABLECOINS | {"USD"}:
        return tx.quantity
    return Decimal("0")


def _tx_type(tx: Transaction) -> str:
    return tx.tx_type.lower()


def _is_convert_basis_swap(tx: Transaction) -> bool:
    tx_kind = _tx_type(tx)
    if tx_kind not in {"convert_sell", "convert_buy"}:
        return False
    raw_data = getattr(tx, "raw_data", {}) or {}
    total_usd = getattr(tx, "total_usd", None)
    if tx_kind == "convert_sell":
        return bool(raw_data.get("convert_to_asset")) and total_usd is None
    return bool(raw_data.get("convert_from_asset")) and total_usd is None


def _tx_key(tx: Transaction) -> str:
    fingerprint = getattr(tx, "fingerprint", None)
    if fingerprint:
        return str(fingerprint)
    raw_data = getattr(tx, "raw_data", {}) or {}
    return "|".join(
        [
            getattr(tx, "institution", "unknown"),
            getattr(tx, "tx_type", "unknown"),
            getattr(tx, "asset_symbol", "unknown"),
            str(getattr(tx, "quantity", "0")),
            tx.timestamp.isoformat() if getattr(tx, "timestamp", None) else "na",
            str(raw_data.get("remark", raw_data.get("address", ""))),
        ]
    )


def _is_bridge_candidate_pair(withdrawal: Transaction, deposit: Transaction) -> bool:
    if withdrawal.asset_symbol.upper() != deposit.asset_symbol.upper():
        return False
    if withdrawal.timestamp >= deposit.timestamp:
        return False
    if deposit.timestamp - withdrawal.timestamp > timedelta(days=7):
        return False
    if not _has_bridge_provenance(withdrawal, deposit):
        return False
    base_qty = max(withdrawal.quantity, deposit.quantity)
    if base_qty <= 0:
        return False
    return abs(withdrawal.quantity - deposit.quantity) <= max(
        base_qty * Decimal("0.01"), Decimal("0.001")
    )


def _has_bridge_provenance(*transactions: Transaction) -> bool:
    for tx in transactions:
        raw_data = getattr(tx, "raw_data", {}) or {}
        if raw_data.get("bridge_group"):
            return True
        provenance_parts = [
            str(raw_data.get("address", "")),
            str(raw_data.get("remark", "")),
            str(raw_data.get("memo", "")),
        ]
        combined = " ".join(provenance_parts).lower()
        if any(keyword in combined for keyword in BRIDGE_PROVENANCE_KEYWORDS):
            return True
    return False


def _bridge_override_types(transactions: list[Transaction]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    explicit_out = {
        _tx_key(_tx): "bridge_transfer_out"
        for _tx in transactions
        if _tx_type(_tx) in BRIDGE_OUT_TYPES
    }
    explicit_in = {
        _tx_key(_tx): "bridge_transfer_in"
        for _tx in transactions
        if _tx_type(_tx) in BRIDGE_IN_TYPES
    }
    overrides.update(explicit_out)
    overrides.update(explicit_in)

    withdrawals = [
        tx
        for tx in transactions
        if _tx_type(tx) in EXTERNAL_WITHDRAWAL_TYPES and _tx_key(tx) not in overrides
    ]
    deposits = [
        tx
        for tx in transactions
        if _tx_type(tx) in EXTERNAL_DEPOSIT_TYPES and _tx_key(tx) not in overrides
    ]
    used_deposits: set[str] = set()
    for withdrawal in sorted(withdrawals, key=lambda row: row.timestamp):
        for deposit in sorted(deposits, key=lambda row: row.timestamp):
            deposit_key = _tx_key(deposit)
            if deposit_key in used_deposits:
                continue
            if _is_bridge_candidate_pair(withdrawal, deposit):
                withdrawal_key = _tx_key(withdrawal)
                overrides[withdrawal_key] = "bridge_transfer_out"
                overrides[deposit_key] = "bridge_transfer_in"
                used_deposits.add(deposit_key)
                synthetic_group = (
                    f"bridge:{withdrawal.asset_symbol.upper()}:"
                    f"{withdrawal.quantity}:{withdrawal.timestamp.isoformat()}"
                )
                withdrawal_raw = getattr(withdrawal, "raw_data", {}) or {}
                deposit_raw = getattr(deposit, "raw_data", {}) or {}
                withdrawal_raw.setdefault("bridge_group", synthetic_group)
                deposit_raw.setdefault("bridge_group", synthetic_group)
                withdrawal.raw_data = withdrawal_raw
                deposit.raw_data = deposit_raw
                break
    return overrides


def _bridge_group(tx: Transaction) -> str | None:
    raw_data = getattr(tx, "raw_data", {}) or {}
    bridge_group = raw_data.get("bridge_group")
    if bridge_group in (None, ""):
        return None
    return str(bridge_group)


def _bridge_transferred_cost(tx: Transaction) -> Decimal | None:
    raw_data = getattr(tx, "raw_data", {}) or {}
    transferred_cost = raw_data.get("bridge_transferred_cost_usd")
    if transferred_cost in (None, ""):
        return None
    return Decimal(str(transferred_cost))


def _annotate_bridge_transferred_costs(
    transactions: list[Transaction],
    bridge_overrides: dict[str, str],
    current_prices: dict[str, Decimal],
) -> None:
    lot_states_by_institution: dict[str, dict[str, LotState]] = defaultdict(
        lambda: defaultdict(LotState)
    )
    pending_bridge_costs: dict[str, Decimal] = {}

    scoped_transactions = sorted(
        transactions, key=lambda row: (row.timestamp, getattr(row, "id", 0))
    )
    for tx in scoped_transactions:
        institution_states = lot_states_by_institution[tx.institution]
        tx_kind = bridge_overrides.get(_tx_key(tx), _tx_type(tx))
        value_usd = _accounting_value_usd(tx)
        symbol = tx.asset_symbol.upper()

        if _is_convert_basis_swap(tx):
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "convert_sell":
                destination_asset = raw_data.get("convert_to_asset")
                destination_quantity = _decimal_or_zero(
                    raw_data.get("convert_to_quantity")
                )
                if destination_asset and destination_quantity > 0:
                    _move_cost_between_assets(
                        institution_states,
                        tx.asset_symbol,
                        tx.quantity,
                        destination_asset,
                        destination_quantity,
                    )
            continue

        if tx_kind == "bridge_transfer_out":
            if symbol in EXCLUDED_HOLDING_SYMBOLS:
                continue
            state = institution_states[symbol]
            if state.quantity <= 0 or tx.quantity <= 0:
                continue
            qty_to_remove = min(state.quantity, tx.quantity)
            removed_cost = state.cost * (qty_to_remove / state.quantity)
            state.quantity -= qty_to_remove
            state.cost -= removed_cost
            bridge_group = _bridge_group(tx)
            if bridge_group:
                pending_bridge_costs[bridge_group] = removed_cost
            continue

        if tx_kind == "bridge_transfer_in":
            if symbol in EXCLUDED_HOLDING_SYMBOLS:
                continue
            state = institution_states[symbol]
            bridge_group = _bridge_group(tx)
            transferred_cost = (
                pending_bridge_costs.pop(bridge_group)
                if bridge_group and bridge_group in pending_bridge_costs
                else value_usd
            )
            tx_raw = getattr(tx, "raw_data", {}) or {}
            tx_raw["bridge_transferred_cost_usd"] = str(transferred_cost)
            tx.raw_data = tx_raw
            state.quantity += tx.quantity
            state.cost += transferred_cost
            continue

        if tx_kind in EXTERNAL_DEPOSIT_TYPES:
            if symbol not in EXCLUDED_HOLDING_SYMBOLS:
                state = institution_states[symbol]
                state.quantity += tx.quantity
                state.cost += value_usd
            continue

        if tx_kind in EXTERNAL_WITHDRAWAL_TYPES:
            state = institution_states[symbol]
            total_qty_out = tx.quantity + (
                tx.fee if tx.fee_currency.upper() == symbol else Decimal("0")
            )
            if state.quantity > 0 and total_qty_out > 0:
                qty_to_remove = min(state.quantity, total_qty_out)
                removed_cost = state.cost * (qty_to_remove / state.quantity)
                state.quantity -= qty_to_remove
                state.cost -= removed_cost
            continue

        if tx_kind in INTERNAL_TRANSFER_TYPES:
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "staking_subscribe":
                source_asset = raw_data.get("stake_asset")
                source_amount = _decimal_or_zero(raw_data.get("stake_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        institution_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            elif tx_kind == "staking_redeem":
                source_asset = raw_data.get("redeem_asset")
                source_amount = _decimal_or_zero(raw_data.get("redeem_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        institution_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            continue

        if tx_kind in INCOME_TYPES:
            income_value = value_usd
            if income_value == 0:
                current_price = current_prices.get(symbol)
                if current_price is not None:
                    income_value = tx.quantity * current_price
            state = institution_states[symbol]
            state.quantity += tx.quantity
            state.cost += income_value
            continue

        fee_value_usd = _tx_fee_value_usd(tx, current_prices)
        side = _classify_tx_side(tx_kind)
        state = institution_states[symbol]
        if side == "buy":
            net_quantity = tx.quantity
            if tx.fee_currency.upper() == symbol:
                net_quantity -= tx.fee
            state.quantity += net_quantity
            if tx.price_usd is not None:
                state.cost += tx.quantity * tx.price_usd + fee_value_usd
        elif side == "sell" and state.quantity > 0:
            qty_to_sell = min(state.quantity, tx.quantity)
            avg_cost = (
                state.cost / state.quantity if state.quantity > 0 else Decimal("0")
            )
            realized_cost = avg_cost * qty_to_sell
            state.quantity -= qty_to_sell
            state.cost -= realized_cost
            if tx.fee_currency.upper() == symbol:
                fee_qty = min(state.quantity, tx.fee)
                if fee_qty > 0 and state.quantity > 0:
                    fee_cost = state.cost * (fee_qty / state.quantity)
                    state.quantity -= fee_qty
                    state.cost -= fee_cost


def _xnpv(rate: float, cashflows: list[tuple[datetime, Decimal]]) -> float:
    start_date = min(date for date, _ in cashflows)
    total = 0.0
    for date, amount in cashflows:
        years = (date - start_date).days / 365.0
        total += float(amount) / ((1.0 + rate) ** years)
    return total


def _compute_xirr(cashflows: list[tuple[datetime, Decimal]]) -> Decimal | None:
    if len(cashflows) < 2:
        return None
    has_positive = any(amount > 0 for _, amount in cashflows)
    has_negative = any(amount < 0 for _, amount in cashflows)
    if not (has_positive and has_negative):
        return None
    low, high = -0.9999, 10.0
    npv_low = _xnpv(low, cashflows)
    npv_high = _xnpv(high, cashflows)
    if npv_low == 0:
        return Decimal(str(low))
    if npv_high == 0:
        return Decimal(str(high))
    if npv_low * npv_high > 0:
        return None
    for _ in range(100):
        mid = (low + high) / 2
        npv_mid = _xnpv(mid, cashflows)
        if abs(npv_mid) < 1e-7:
            return Decimal(str(mid))
        if npv_low * npv_mid <= 0:
            high = mid
            npv_high = npv_mid
        else:
            low = mid
            npv_low = npv_mid
    return Decimal(str((low + high) / 2))


def _tx_fee_value_usd(tx: Transaction, current_prices: dict[str, Decimal]) -> Decimal:
    if tx.fee <= 0:
        return Decimal("0")
    raw_data = getattr(tx, "raw_data", {}) or {}
    explicit_fee_value = raw_data.get("fee_value_usd")
    if explicit_fee_value not in (None, ""):
        return Decimal(str(explicit_fee_value))
    fee_currency = tx.fee_currency.upper()
    if fee_currency in STABLECOINS | {"USD"}:
        return tx.fee
    if fee_currency == tx.asset_symbol.upper():
        if tx.price_usd is not None:
            return tx.fee * tx.price_usd
        if tx.total_usd is not None and tx.quantity > 0:
            return tx.fee * (tx.total_usd / tx.quantity)
    fee_price = current_prices.get(fee_currency)
    if fee_price is not None:
        return tx.fee * fee_price
    return Decimal("0")


def _move_cost_between_assets(
    lot_states: dict[str, LotState],
    source_symbol: str,
    source_amount: Decimal,
    destination_symbol: str,
    destination_amount: Decimal,
) -> None:
    source_state = lot_states[source_symbol.upper()]
    destination_state = lot_states[destination_symbol.upper()]
    if source_state.quantity <= 0 or source_amount <= 0 or destination_amount <= 0:
        return
    qty_to_move = min(source_state.quantity, source_amount)
    transferred_cost = source_state.cost * (qty_to_move / source_state.quantity)
    source_state.quantity -= qty_to_move
    source_state.cost -= transferred_cost
    destination_state.quantity += destination_amount
    destination_state.cost += transferred_cost


def _finalize_bucket(
    bucket: PerformanceBucket,
    lot_states: dict[str, LotState],
    current_prices: dict[str, Decimal],
    cashflows: list[tuple[datetime, Decimal]],
    as_of: datetime,
) -> dict[str, Decimal | None]:
    current_value = Decimal("0")
    residual_cost = Decimal("0")
    for symbol, state in lot_states.items():
        if state.quantity <= 0:
            continue
        current_price = current_prices.get(symbol)
        if current_price is not None:
            current_value += state.quantity * current_price
        residual_cost += state.cost
    bucket.current_value_usd = current_value
    bucket.total_cost_usd = residual_cost
    bucket.unrealized_pnl_usd = current_value - residual_cost
    bucket.total_pnl_usd = (
        bucket.realized_pnl_usd + bucket.unrealized_pnl_usd + bucket.reward_income_usd
    )
    if current_value > 0:
        cashflows = [*cashflows, (as_of, current_value)]
    bucket.xirr = _compute_xirr(cashflows)
    return {
        "gross_deposits_usd": bucket.gross_deposits_usd,
        "gross_withdrawals_usd": bucket.gross_withdrawals_usd,
        "net_invested_capital_usd": bucket.net_invested_capital_usd,
        "bridge_transfer_out_usd": bucket.bridge_transfer_out_usd,
        "bridge_transfer_in_usd": bucket.bridge_transfer_in_usd,
        "unclassified_transfer_usd": bucket.unclassified_transfer_usd,
        "reward_income_usd": bucket.reward_income_usd,
        "fees_usd": bucket.fees_usd,
        "realized_pnl_usd": bucket.realized_pnl_usd,
        "total_cost_usd": bucket.total_cost_usd,
        "current_value_usd": bucket.current_value_usd,
        "unrealized_pnl_usd": bucket.unrealized_pnl_usd,
        "total_pnl_usd": bucket.total_pnl_usd,
        "xirr": bucket.xirr,
    }


@dataclass
class AssetContributionBucket:
    symbol: str
    asset_type: str = "unknown"
    quantity: Decimal = Decimal("0")
    total_cost_usd: Decimal = Decimal("0")
    current_value_usd: Decimal = Decimal("0")
    unrealized_pnl_usd: Decimal = Decimal("0")
    realized_pnl_usd: Decimal = Decimal("0")
    reward_income_usd: Decimal = Decimal("0")
    fees_usd: Decimal = Decimal("0")
    net_lifetime_pnl_usd: Decimal = Decimal("0")
    institutions: set[str] | None = None


def _asset_bucket(
    buckets: dict[str, AssetContributionBucket],
    tx: Transaction,
) -> AssetContributionBucket:
    symbol = _normalize_holding_symbol(tx)
    bucket = buckets.get(symbol)
    if bucket is None:
        bucket = AssetContributionBucket(
            symbol=symbol,
            asset_type=getattr(tx, "asset_type", "unknown") or "unknown",
            institutions=set(),
        )
        buckets[symbol] = bucket
    if bucket.asset_type == "unknown" and getattr(tx, "asset_type", None):
        bucket.asset_type = tx.asset_type
    if bucket.institutions is None:
        bucket.institutions = set()
    bucket.institutions.add(tx.institution)
    return bucket


def _asset_contribution_row(bucket: AssetContributionBucket) -> dict[str, object]:
    institutions = sorted(bucket.institutions or [])
    institution = institutions[0] if len(institutions) == 1 else "multiple"
    return {
        "symbol": bucket.symbol,
        "asset_type": bucket.asset_type,
        "institution": institution,
        "institutions": institutions,
        "quantity": bucket.quantity,
        "total_cost_usd": bucket.total_cost_usd,
        "current_value_usd": bucket.current_value_usd,
        "realized_pnl_usd": bucket.realized_pnl_usd,
        "unrealized_pnl_usd": bucket.unrealized_pnl_usd,
        "reward_income_usd": bucket.reward_income_usd,
        "fees_usd": bucket.fees_usd,
        "net_lifetime_pnl_usd": bucket.net_lifetime_pnl_usd,
    }


def _sorted_asset_rows(
    rows: list[dict[str, object]],
    *,
    sort_by: str,
    order: str,
) -> list[dict[str, object]]:
    sortable_fields = {
        "symbol",
        "current_value_usd",
        "realized_pnl_usd",
        "unrealized_pnl_usd",
        "reward_income_usd",
        "fees_usd",
        "net_lifetime_pnl_usd",
    }
    selected_sort = sort_by if sort_by in sortable_fields else "net_lifetime_pnl_usd"
    reverse = order != "asc"

    def sort_key(row: dict[str, object]) -> tuple[Decimal | str, str]:
        value = row[selected_sort]
        if selected_sort == "symbol":
            return (str(value), str(row["symbol"]))
        numeric_value = (
            value if isinstance(value, Decimal | float | int | str) else None
        )
        return (_decimal_or_zero(numeric_value), str(row["symbol"]))

    return sorted(rows, key=sort_key, reverse=reverse)


async def calculate_asset_contribution_summary(
    transactions: list[Transaction],
    current_prices: Mapping[str, Decimal | float | int | None],
    *,
    sort_by: str = "net_lifetime_pnl_usd",
    order: str = "desc",
) -> dict[str, object]:
    """Compute winners/losers contribution metrics by asset.

    Returns frontend-ready rows with realized P/L for closed lots, open-position
    unrealized P/L, reward/income, fee totals, current value, and net lifetime
    P/L. Cash/stablecoin rows are excluded from asset ranking to keep the table
    focused on investable winners/losers rather than funding rails.
    """
    normalized_prices = {
        symbol.upper(): _decimal_or_zero(price)
        for symbol, price in current_prices.items()
        if price is not None
    }
    relevant_transactions = [
        tx for tx in transactions if not _is_binance_snapshot_tx(tx)
    ]
    bridge_overrides = _bridge_override_types(relevant_transactions)
    _annotate_bridge_transferred_costs(
        relevant_transactions,
        bridge_overrides,
        normalized_prices,
    )
    lot_states: dict[str, LotState] = defaultdict(LotState)
    buckets: dict[str, AssetContributionBucket] = {}
    pending_bridge_costs: dict[str, Decimal] = {}

    for tx in sorted(
        relevant_transactions, key=lambda row: (row.timestamp, getattr(row, "id", 0))
    ):
        tx_kind = bridge_overrides.get(_tx_key(tx), _tx_type(tx))
        symbol = _normalize_holding_symbol(tx)
        value_usd = _accounting_value_usd(tx)

        if _is_convert_basis_swap(tx):
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "convert_sell":
                destination_asset = raw_data.get("convert_to_asset")
                destination_quantity = _decimal_or_zero(
                    raw_data.get("convert_to_quantity")
                )
                if destination_asset and destination_quantity > 0:
                    _move_cost_between_assets(
                        lot_states,
                        tx.asset_symbol,
                        tx.quantity,
                        destination_asset,
                        destination_quantity,
                    )
            continue

        if symbol in EXCLUDED_HOLDING_SYMBOLS:
            continue

        bucket = _asset_bucket(buckets, tx)
        state = lot_states[symbol]

        if tx_kind == "bridge_transfer_out":
            bucket_current_qty = state.quantity
            if bucket_current_qty > 0 and tx.quantity > 0:
                qty_to_remove = min(bucket_current_qty, tx.quantity)
                removed_cost = state.cost * (qty_to_remove / bucket_current_qty)
                state.quantity -= qty_to_remove
                state.cost -= removed_cost
                bridge_group = _bridge_group(tx)
                if bridge_group:
                    pending_bridge_costs[bridge_group] = removed_cost
            continue
        if tx_kind == "bridge_transfer_in":
            bridge_group = _bridge_group(tx)
            annotated_transferred_cost = _bridge_transferred_cost(tx)
            transferred_cost = (
                pending_bridge_costs.pop(bridge_group)
                if bridge_group and bridge_group in pending_bridge_costs
                else annotated_transferred_cost
                if annotated_transferred_cost is not None
                else value_usd
            )
            state.quantity += tx.quantity
            state.cost += transferred_cost
            continue
        if tx_kind in EXTERNAL_DEPOSIT_TYPES:
            state.quantity += tx.quantity
            state.cost += value_usd
            continue
        if tx_kind in EXTERNAL_WITHDRAWAL_TYPES:
            fee_value_usd = _tx_fee_value_usd(tx, normalized_prices)
            bucket.fees_usd += fee_value_usd
            total_qty_out = tx.quantity + (
                tx.fee if tx.fee_currency.upper() == symbol else Decimal("0")
            )
            if state.quantity > 0 and total_qty_out > 0:
                qty_to_remove = min(state.quantity, total_qty_out)
                removed_cost = state.cost * (qty_to_remove / state.quantity)
                state.quantity -= qty_to_remove
                state.cost -= removed_cost
            bucket.realized_pnl_usd -= fee_value_usd
            continue
        if tx_kind in INTERNAL_TRANSFER_TYPES:
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "staking_subscribe":
                source_asset = raw_data.get("stake_asset")
                source_amount = _decimal_or_zero(raw_data.get("stake_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        lot_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            elif tx_kind == "staking_redeem":
                source_asset = raw_data.get("redeem_asset")
                source_amount = _decimal_or_zero(raw_data.get("redeem_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        lot_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            continue
        if tx_kind in INCOME_TYPES:
            income_value = value_usd
            if income_value == 0:
                current_price = normalized_prices.get(symbol)
                if current_price is not None:
                    income_value = tx.quantity * current_price
            bucket.reward_income_usd += income_value
            state.quantity += tx.quantity
            state.cost += income_value
            continue
        if tx_kind == "fee":
            bucket.fees_usd += value_usd
            bucket.realized_pnl_usd -= value_usd
            continue

        fee_value_usd = _tx_fee_value_usd(tx, normalized_prices)
        side = _classify_tx_side(tx_kind)
        if side == "buy":
            net_quantity = tx.quantity
            if tx.fee_currency.upper() == symbol:
                net_quantity -= tx.fee
            state.quantity += net_quantity
            if tx.price_usd is not None:
                state.cost += tx.quantity * tx.price_usd + fee_value_usd
            bucket.fees_usd += fee_value_usd
        elif side == "sell":
            if state.quantity > 0:
                qty_to_sell = min(state.quantity, tx.quantity)
                avg_cost = (
                    state.cost / state.quantity
                    if state.quantity > 0
                    else Decimal("0")
                )
                realized_cost = avg_cost * qty_to_sell
                proceeds = (
                    tx.total_usd
                    if tx.total_usd is not None
                    else (tx.price_usd or Decimal("0")) * qty_to_sell
                )
                bucket.realized_pnl_usd += proceeds - realized_cost - fee_value_usd
                state.quantity -= qty_to_sell
                state.cost -= realized_cost
                if tx.fee_currency.upper() == symbol:
                    fee_qty = min(state.quantity, tx.fee)
                    if fee_qty > 0 and state.quantity > 0:
                        fee_cost = state.cost * (fee_qty / state.quantity)
                        state.quantity -= fee_qty
                        state.cost -= fee_cost
                bucket.fees_usd += fee_value_usd

    for symbol, bucket in buckets.items():
        state = lot_states[symbol]
        bucket.quantity = state.quantity if state.quantity > 0 else Decimal("0")
        bucket.total_cost_usd = state.cost if state.quantity > 0 else Decimal("0")
        current_price = normalized_prices.get(symbol)
        if current_price is not None:
            bucket.current_value_usd = bucket.quantity * current_price
        else:
            bucket.current_value_usd = Decimal("0")
        bucket.unrealized_pnl_usd = bucket.current_value_usd - bucket.total_cost_usd
        bucket.net_lifetime_pnl_usd = (
            bucket.realized_pnl_usd
            + bucket.unrealized_pnl_usd
            + bucket.reward_income_usd
        )

    rows = [_asset_contribution_row(bucket) for bucket in buckets.values()]
    normalized_order = "asc" if order == "asc" else "desc"
    normalized_sort = (
        sort_by
        if sort_by
        in {
            "symbol",
            "current_value_usd",
            "realized_pnl_usd",
            "unrealized_pnl_usd",
            "reward_income_usd",
            "fees_usd",
            "net_lifetime_pnl_usd",
        }
        else "net_lifetime_pnl_usd"
    )
    rows = _sorted_asset_rows(rows, sort_by=normalized_sort, order=normalized_order)
    totals = {
        "current_value_usd": sum(
            (bucket.current_value_usd for bucket in buckets.values()), Decimal("0")
        ),
        "realized_pnl_usd": sum(
            (bucket.realized_pnl_usd for bucket in buckets.values()), Decimal("0")
        ),
        "unrealized_pnl_usd": sum(
            (bucket.unrealized_pnl_usd for bucket in buckets.values()), Decimal("0")
        ),
        "reward_income_usd": sum(
            (bucket.reward_income_usd for bucket in buckets.values()), Decimal("0")
        ),
        "fees_usd": sum(
            (bucket.fees_usd for bucket in buckets.values()), Decimal("0")
        ),
        "net_lifetime_pnl_usd": sum(
            (bucket.net_lifetime_pnl_usd for bucket in buckets.values()),
            Decimal("0"),
        ),
    }
    return {
        "assets": rows,
        "totals": totals,
        "sort": {"sort_by": normalized_sort, "order": normalized_order},
    }


def _capital_flow_category(
    tx: Transaction, bridge_overrides: dict[str, str]
) -> tuple[str, str | None]:
    tx_kind = bridge_overrides.get(_tx_key(tx), _tx_type(tx))
    side = _classify_tx_side(tx_kind)

    if tx_kind in EXTERNAL_DEPOSIT_TYPES:
        return "external_capital_in", None
    if tx_kind in EXTERNAL_WITHDRAWAL_TYPES:
        return "external_capital_out", None
    if tx_kind in {"bridge_transfer_out", "bridge_transfer_in"}:
        return "internal_movement", "matched_or_explicit_bridge_transfer"
    if tx_kind in {"transfer_in", "transfer_out"}:
        return "unclassified_transfer", "transfer_requires_manual_classification"
    if tx_kind in INTERNAL_TRANSFER_TYPES or tx_kind.startswith("balance_snapshot_"):
        return "internal_movement", None
    if tx_kind in INCOME_TYPES:
        return "income_reward", None
    if tx_kind == "fee":
        return "fee_tax_cost", None
    if tx_kind.startswith("convert_"):
        return "convert", None
    if side == "buy":
        return "trade_buy", None
    if side == "sell":
        return "trade_sell", None
    return "data_quality_excluded", "unsupported_or_ambiguous_transaction_type"


async def calculate_capital_truth_summary(
    transactions: list[Transaction],
    *,
    current_value_usd: Decimal | float | int | str | None = None,
    current_prices: Mapping[str, Decimal | float | int | None] | None = None,
    current_value_source: str | None = None,
) -> dict[str, object]:
    """Compute lifetime accounting truth from external capital flows.

    Deposits/withdrawals affect money-in/out. Trades, converts, Earn/staking
    moves, snapshots, rewards, and fees are audited but excluded from capital
    totals so internal Binance movements cannot double-count new investment.
    """
    normalized_prices = {
        symbol.upper(): _decimal_or_zero(price)
        for symbol, price in (current_prices or {}).items()
        if price is not None
    }
    if current_value_usd is None:
        performance = await calculate_performance_summary(
            transactions, normalized_prices
        )
        combined_summary = performance.get("combined")
        combined_current_value = (
            combined_summary.get("current_value_usd")
            if isinstance(combined_summary, dict)
            else None
        )
        current_value = _decimal_or_zero(combined_current_value)
        value_source = current_value_source or "transaction_lot_valuation"
    else:
        current_value = _decimal_or_zero(current_value_usd)
        value_source = current_value_source or "provided_current_value"

    bridge_overrides = _bridge_override_types(
        [tx for tx in transactions if not _is_binance_snapshot_tx(tx)]
    )
    money_in = Decimal("0")
    money_out = Decimal("0")
    excluded_count = 0
    unclassified_count = 0
    audit_rows: list[dict[str, Decimal | bool | str | None]] = []

    for tx in sorted(
        transactions, key=lambda row: (row.timestamp, getattr(row, "id", 0))
    ):
        category, reason = _capital_flow_category(tx, bridge_overrides)
        amount_usd = _accounting_value_usd(tx)
        included = False
        exclusion_reason = reason

        if category in {"external_capital_in", "external_capital_out"}:
            if amount_usd <= 0:
                category = "data_quality_excluded"
                exclusion_reason = "missing_reliable_usd_value"
                excluded_count += 1
            else:
                included = True
                if category == "external_capital_in":
                    money_in += amount_usd
                else:
                    money_out += amount_usd
        elif category == "unclassified_transfer":
            unclassified_count += 1

        audit_rows.append(
            {
                "transaction_id": getattr(tx, "id", None),
                "timestamp": tx.timestamp.isoformat() if tx.timestamp else None,
                "institution": tx.institution,
                "tx_type": tx.tx_type,
                "asset_symbol": tx.asset_symbol,
                "economic_category": category,
                "amount_usd": amount_usd,
                "included_in_capital_totals": included,
                "exclusion_reason": exclusion_reason,
            }
        )

    net_capital_in = money_in - money_out
    lifetime_pnl = current_value + money_out - money_in
    lifetime_return_pct = (
        lifetime_pnl / net_capital_in * Decimal("100") if net_capital_in > 0 else None
    )
    warnings: list[str] = []
    if excluded_count:
        plural = "row" if excluded_count == 1 else "rows"
        warnings.append(
            f"{excluded_count} capital-flow {plural} excluded because no reliable "
            "USD value was available"
        )
    if unclassified_count:
        plural = "row" if unclassified_count == 1 else "rows"
        warnings.append(
            f"{unclassified_count} transfer {plural} requires manual classification "
            "before it can affect lifetime P/L"
        )

    return {
        "money_in_usd": money_in,
        "money_out_usd": money_out,
        "net_capital_in_usd": net_capital_in,
        "current_value_usd": current_value,
        "lifetime_pnl_usd": lifetime_pnl,
        "lifetime_return_pct": lifetime_return_pct,
        "current_value_source": value_source,
        "excluded_row_count": excluded_count,
        "unclassified_transfer_count": unclassified_count,
        "warnings": warnings,
        "capital_flow_audit": audit_rows,
    }


def _summarize_scope(
    transactions: list[Transaction],
    current_prices: dict[str, Decimal],
    *,
    apply_bridge_lot_moves: bool = False,
    bridge_overrides: dict[str, str] | None = None,
) -> dict[str, Decimal | None]:
    bucket = PerformanceBucket()
    lot_states: dict[str, LotState] = defaultdict(LotState)
    bridge_overrides = bridge_overrides or _bridge_override_types(transactions)
    cashflows: list[tuple[datetime, Decimal]] = []
    pending_bridge_costs: dict[str, Decimal] = {}

    scoped_transactions = sorted(
        transactions, key=lambda row: (row.timestamp, getattr(row, "id", 0))
    )
    as_of = max((tx.timestamp for tx in scoped_transactions), default=datetime.now(UTC))

    for tx in scoped_transactions:
        tx_kind = bridge_overrides.get(_tx_key(tx), _tx_type(tx))
        value_usd = _accounting_value_usd(tx)

        if _is_convert_basis_swap(tx):
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "convert_sell":
                destination_asset = raw_data.get("convert_to_asset")
                destination_quantity = _decimal_or_zero(
                    raw_data.get("convert_to_quantity")
                )
                if destination_asset and destination_quantity > 0:
                    _move_cost_between_assets(
                        lot_states,
                        tx.asset_symbol,
                        tx.quantity,
                        destination_asset,
                        destination_quantity,
                    )
            continue

        if tx_kind == "bridge_transfer_out":
            bucket.bridge_transfer_out_usd += value_usd
            if (
                apply_bridge_lot_moves
                and tx.asset_symbol.upper() not in EXCLUDED_HOLDING_SYMBOLS
            ):
                symbol = tx.asset_symbol.upper()
                state = lot_states[symbol]
                if state.quantity > 0 and tx.quantity > 0:
                    qty_to_remove = min(state.quantity, tx.quantity)
                    removed_cost = state.cost * (qty_to_remove / state.quantity)
                    state.quantity -= qty_to_remove
                    state.cost -= removed_cost
                    bridge_group = _bridge_group(tx)
                    if bridge_group:
                        pending_bridge_costs[bridge_group] = removed_cost
            continue
        if tx_kind == "bridge_transfer_in":
            bucket.bridge_transfer_in_usd += value_usd
            if (
                apply_bridge_lot_moves
                and tx.asset_symbol.upper() not in EXCLUDED_HOLDING_SYMBOLS
            ):
                symbol = tx.asset_symbol.upper()
                state = lot_states[symbol]
                bridge_group = _bridge_group(tx)
                annotated_transferred_cost = _bridge_transferred_cost(tx)
                transferred_cost = (
                    pending_bridge_costs.pop(bridge_group)
                    if bridge_group and bridge_group in pending_bridge_costs
                    else annotated_transferred_cost
                    if annotated_transferred_cost is not None
                    else value_usd
                )
                state.quantity += tx.quantity
                state.cost += transferred_cost
            continue
        if tx_kind in EXTERNAL_DEPOSIT_TYPES:
            bucket.gross_deposits_usd += value_usd
            bucket.net_invested_capital_usd += value_usd
            symbol = tx.asset_symbol.upper()
            if symbol not in EXCLUDED_HOLDING_SYMBOLS:
                state = lot_states[symbol]
                state.quantity += tx.quantity
                state.cost += value_usd
            if value_usd:
                cashflows.append((tx.timestamp, -value_usd))
            continue
        if tx_kind in EXTERNAL_WITHDRAWAL_TYPES:
            bucket.gross_withdrawals_usd += value_usd
            bucket.net_invested_capital_usd -= value_usd
            fee_value_usd = _tx_fee_value_usd(tx, current_prices)
            bucket.fees_usd += fee_value_usd
            bucket.realized_pnl_usd -= fee_value_usd
            symbol = tx.asset_symbol.upper()
            state = lot_states[symbol]
            total_qty_out = tx.quantity + (
                tx.fee if tx.fee_currency.upper() == symbol else Decimal("0")
            )
            if state.quantity > 0 and total_qty_out > 0:
                qty_to_remove = min(state.quantity, total_qty_out)
                removed_cost = state.cost * (qty_to_remove / state.quantity)
                state.quantity -= qty_to_remove
                state.cost -= removed_cost
            if value_usd:
                cashflows.append((tx.timestamp, value_usd - fee_value_usd))
            continue
        if tx_kind in INTERNAL_TRANSFER_TYPES:
            raw_data = getattr(tx, "raw_data", {}) or {}
            if tx_kind == "staking_subscribe":
                source_asset = raw_data.get("stake_asset")
                source_amount = _decimal_or_zero(raw_data.get("stake_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        lot_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            elif tx_kind == "staking_redeem":
                source_asset = raw_data.get("redeem_asset")
                source_amount = _decimal_or_zero(raw_data.get("redeem_amount"))
                if source_asset and source_amount > 0:
                    _move_cost_between_assets(
                        lot_states,
                        source_asset,
                        source_amount,
                        tx.asset_symbol,
                        tx.quantity,
                    )
            continue
        if tx_kind in INCOME_TYPES:
            income_value = value_usd
            if income_value == 0:
                current_price = current_prices.get(tx.asset_symbol.upper())
                if current_price is not None:
                    income_value = tx.quantity * current_price
            bucket.reward_income_usd += income_value
            state = lot_states[tx.asset_symbol.upper()]
            state.quantity += tx.quantity
            state.cost += income_value
            continue
        if tx_kind == "fee":
            bucket.fees_usd += value_usd
            continue

        symbol = tx.asset_symbol.upper()
        state = lot_states[symbol]
        fee_value_usd = _tx_fee_value_usd(tx, current_prices)
        side = _classify_tx_side(tx_kind)
        if side == "buy":
            net_quantity = tx.quantity
            if tx.fee_currency.upper() == symbol:
                net_quantity -= tx.fee
            state.quantity += net_quantity
            if tx.price_usd is not None:
                state.cost += tx.quantity * tx.price_usd + fee_value_usd
            bucket.fees_usd += fee_value_usd
        elif side == "sell":
            if state.quantity > 0:
                qty_to_sell = min(state.quantity, tx.quantity)
                avg_cost = (
                    state.cost / state.quantity if state.quantity > 0 else Decimal("0")
                )
                realized_cost = avg_cost * qty_to_sell
                proceeds = (
                    tx.total_usd
                    if tx.total_usd is not None
                    else (tx.price_usd or Decimal("0")) * qty_to_sell
                )
                bucket.realized_pnl_usd += proceeds - realized_cost - fee_value_usd
                state.quantity -= qty_to_sell
                state.cost -= realized_cost
                if tx.fee_currency.upper() == symbol:
                    fee_qty = min(state.quantity, tx.fee)
                    if fee_qty > 0 and state.quantity > 0:
                        fee_cost = state.cost * (fee_qty / state.quantity)
                        state.quantity -= fee_qty
                        state.cost -= fee_cost
                bucket.fees_usd += fee_value_usd
            else:
                bucket.unclassified_transfer_usd += value_usd

    return _finalize_bucket(bucket, lot_states, current_prices, cashflows, as_of)


async def calculate_performance_summary(
    transactions: list[Transaction],
    current_prices: Mapping[str, Decimal | float | int | None],
) -> dict[str, object]:
    normalized_prices = {
        symbol.upper(): _decimal_or_zero(price)
        for symbol, price in current_prices.items()
        if price is not None
    }
    by_institution: dict[str, list[Transaction]] = defaultdict(list)
    relevant_transactions = [
        tx for tx in transactions if not _is_binance_snapshot_tx(tx)
    ]
    bridge_overrides = _bridge_override_types(relevant_transactions)
    _annotate_bridge_transferred_costs(
        relevant_transactions,
        bridge_overrides,
        normalized_prices,
    )
    for tx in relevant_transactions:
        by_institution[tx.institution].append(tx)

    institution_summaries = {
        institution: _summarize_scope(
            scope_transactions,
            normalized_prices,
            apply_bridge_lot_moves=True,
            bridge_overrides=bridge_overrides,
        )
        for institution, scope_transactions in by_institution.items()
    }
    combined_summary = _summarize_scope(
        relevant_transactions,
        normalized_prices,
        apply_bridge_lot_moves=True,
        bridge_overrides=bridge_overrides,
    )

    binance = institution_summaries.get(
        "binance", _summarize_scope([], normalized_prices)
    )
    xtb = institution_summaries.get("xtb", _summarize_scope([], normalized_prices))
    comparisons = {
        "binance_vs_xtb": {
            "total_pnl_delta_usd": _decimal_or_zero(binance.get("total_pnl_usd"))
            - _decimal_or_zero(xtb.get("total_pnl_usd")),
            "net_invested_delta_usd": _decimal_or_zero(
                binance.get("net_invested_capital_usd")
            )
            - _decimal_or_zero(xtb.get("net_invested_capital_usd")),
        }
    }
    return {
        "institutions": institution_summaries,
        "combined": combined_summary,
        "comparisons": comparisons,
    }
