"""
Binance REST client using binance-connector SDK.
Wraps the Spot client which handles all SAPI endpoints too.
"""

import logging
import time
from datetime import UTC, datetime

from binance.error import ClientError, ServerError
from binance.spot import Spot
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.models.binance import (
    AccountType,
    AssetBalance,
    BinanceAccountSummary,
    OpenOrder,
    StakingPosition,
    Transaction,
    TransactionType,
    Transfer,
)

logger = logging.getLogger(__name__)


class BinanceError(Exception):
    def __init__(self, message: str, code: int | None = None):
        self.message = message
        self.code = code
        super().__init__(self.message)


class RateLimitError(BinanceError):
    pass


class AuthenticationError(BinanceError):
    pass


def _is_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, RateLimitError)


def _base_asset(symbol: str) -> str:
    upper = symbol.upper()
    for quote in ("USDT", "BUSD", "FDUSD", "USDC", "BTC", "ETH"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)]
    return upper


def _open_order_base_asset(order: dict) -> str:
    base_asset = str(order.get("baseAsset") or "").strip().upper()
    if base_asset:
        return base_asset

    market_symbol = str(order.get("symbol") or "").strip().upper()
    quote_asset = str(order.get("quoteAsset") or "").strip().upper()
    if (
        quote_asset
        and market_symbol.endswith(quote_asset)
        and len(market_symbol) > len(quote_asset)
    ):
        return market_symbol[: -len(quote_asset)]

    return ""


class BinanceClient:
    """
    Read-only Binance client covering spot/funding/earn balances,
    transfers, trades, and staking.
    """

    MIN_DELAY = 0.05  # seconds between requests

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool = False,
    ):
        self.api_key = api_key or settings.BINANCE_API_KEY
        self.api_secret = api_secret or settings.BINANCE_API_SECRET
        self._last_request = 0.0

        base_url = (
            "https://testnet.binance.vision" if testnet else "https://api.binance.com"
        )
        self._client = Spot(
            api_key=self.api_key,
            api_secret=self.api_secret,
            base_url=base_url,
        )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.MIN_DELAY:
            time.sleep(self.MIN_DELAY - elapsed)
        self._last_request = time.monotonic()

    @retry(
        retry=retry_if_exception_type(RateLimitError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
    )
    def _call(self, method_name: str, *args, **kwargs):
        self._throttle()
        try:
            method = getattr(self._client, method_name)
            return method(*args, **kwargs)
        except ClientError as e:
            code = e.error_code
            msg = e.error_message
            if code in (-2014, -2015):
                raise AuthenticationError(msg, code=code) from e
            if code == -1003 or "RATE_LIMIT" in str(msg).upper():
                raise RateLimitError(msg, code=code) from e
            raise BinanceError(msg, code=code) from e
        except ServerError as e:
            raise BinanceError(str(e)) from e

    # ── Spot ──────────────────────────────────────────────────────────────

    def get_spot_balances(self) -> list[AssetBalance]:
        data = self._call("account")
        return [
            AssetBalance(
                asset=b["asset"],
                free=float(b["free"]),
                locked=float(b["locked"]),
                account_type=AccountType.SPOT,
            )
            for b in data.get("balances", [])
            if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0
        ]

    def get_open_orders(self) -> list[OpenOrder]:
        data = self._call("get_open_orders")
        return [
            OpenOrder(
                order_id=str(order.get("orderId") or order.get("clientOrderId") or ""),
                symbol=_open_order_base_asset(order),
                market_symbol=str(order.get("symbol") or "").strip().upper(),
                order_type=str(order.get("type") or "unknown").lower(),
                status=str(order.get("status") or "open").lower(),
                side=str(order.get("side") or "buy").lower(),
                quantity=float(order.get("origQty") or order.get("qty") or 0),
                limit_price=(
                    float(order["price"])
                    if float(order.get("price") or 0) > 0
                    else None
                ),
                stop_price=(
                    float(order["stopPrice"])
                    if float(order.get("stopPrice") or 0) > 0
                    else None
                ),
                placed_at=(
                    datetime.fromtimestamp(
                        (
                            order.get("time")
                            or order.get("transactTime")
                            or order.get("updateTime")
                            or 0
                        )
                        / 1000,
                        tz=UTC,
                    )
                    if (
                        order.get("time")
                        or order.get("transactTime")
                        or order.get("updateTime")
                    )
                    else None
                ),
            )
            for order in (data or [])
        ]

    # ── Funding ───────────────────────────────────────────────────────────

    def get_funding_balances(
        self,
        *,
        suppress_errors: bool = True,
    ) -> list[AssetBalance]:
        try:
            data = self._call("funding_wallet")
            return [
                AssetBalance(
                    asset=b["asset"],
                    free=float(b["free"]),
                    locked=float(b["locked"]),
                    account_type=AccountType.FUNDING,
                )
                for b in (data or [])
                if float(b.get("free", 0)) + float(b.get("locked", 0)) > 0
            ]
        except BinanceError:
            if suppress_errors:
                return []
            raise

    # ── Earn / Flexible ──────────────────────────────────────────────────

    def get_flexible_products(
        self,
        *,
        suppress_errors: bool = True,
    ) -> list[AssetBalance]:
        """Fetch Simple Earn flexible and locked product positions."""
        try:
            balances: list[AssetBalance] = []
            for endpoint in (
                "get_flexible_product_position",
                "get_locked_product_position",
            ):
                resp = self._call(endpoint)
                rows = resp.get("rows", []) if isinstance(resp, dict) else (resp or [])
                for row in rows:
                    amount = float(
                        row.get(
                            "totalAmount",
                            row.get(
                                "amount",
                                row.get(
                                    "positionAmount",
                                    row.get("freeAmount", row.get("principal", 0)),
                                ),
                            ),
                        )
                    )
                    if amount <= 0:
                        continue
                    balances.append(
                        AssetBalance(
                            asset=row["asset"],
                            free=amount,
                            locked=0.0,
                            account_type=AccountType.EARN,
                        )
                    )
            return balances
        except (BinanceError, Exception):
            if suppress_errors:
                return []
            raise

    def get_staking_positions(
        self,
        *,
        suppress_errors: bool = True,
    ) -> list[StakingPosition]:
        """ETH staking only — old general staking API is removed."""
        positions: list[StakingPosition] = []
        try:
            data = self._call("eth_staking_account")
            eth_amount = float((data or {}).get("holdingInETH", 0))
            if eth_amount > 0:
                positions.append(
                    StakingPosition(
                        position_id="eth_staking",
                        asset="ETH",
                        amount=eth_amount,
                        apy=None,
                        start_date=None,
                        status="active",
                        account_type=AccountType.EARN,
                    )
                )
        except (BinanceError, Exception) as exc:
            if suppress_errors:
                logger.debug("ETH staking position fetch failed: %s", exc)
                return positions
            raise
        return positions

    # ── Transfers ────────────────────────────────────────────────────────

    def get_universal_transfers(
        self,
        type_: str = "MAIN_UMFUTURE",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Transfer]:
        try:
            params: dict = {"type": type_}
            if start_time:
                params["startTime"] = int(start_time.timestamp() * 1000)
            if end_time:
                params["endTime"] = int(end_time.timestamp() * 1000)
            data = self._call("query_universal_transfer_history", **params)
            rows = data.get("rows", []) if isinstance(data, dict) else (data or [])
            return [
                Transfer(
                    id=str(r.get("tranId", "")),
                    asset=r.get("asset", ""),
                    amount=float(r.get("amount", 0)),
                    from_account=AccountType.FUNDING,
                    to_account=AccountType.SPOT,
                    timestamp=datetime.fromtimestamp(
                        r.get("timestamp", 0) / 1000, tz=UTC
                    ),
                    status=r.get("status", "").lower(),
                )
                for r in rows
            ]
        except BinanceError:
            return []

    # ── Trade history ────────────────────────────────────────────────────

    def get_my_trades(self, symbol: str, limit: int = 500) -> list[Transaction]:
        try:
            data = self._call("my_trades", symbol=symbol, limit=limit)
            return [
                Transaction(
                    id=str(t.get("id", "")),
                    type=TransactionType.SPOT_TRADE,
                    asset=_base_asset(symbol),
                    amount=float(t.get("qty", 0)),
                    account_type=AccountType.SPOT,
                    timestamp=datetime.fromtimestamp(t.get("time", 0) / 1000, tz=UTC),
                    status="completed",
                    fee=float(t.get("commission", 0)),
                    fee_asset=t.get("commissionAsset", ""),
                )
                for t in (data or [])
            ]
        except BinanceError:
            return []

    # ── History endpoints ───────────────────────────────────────────────────

    def _history_params(
        self,
        *,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
        extra: dict | None = None,
        start_key: str = "startTime",
        end_key: str = "endTime",
    ) -> dict:
        params: dict = dict(extra or {})
        if start_time:
            params[start_key] = int(start_time.timestamp() * 1000)
        if end_time:
            params[end_key] = int(end_time.timestamp() * 1000)
        if limit is not None:
            params["limit"] = limit
        return params

    def get_deposit_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        *,
        limit: int = 1000,
        offset: int = 0,
    ):
        return self._call(
            "deposit_history",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                extra={"offset": offset},
            ),
        )

    def get_withdraw_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        *,
        limit: int = 1000,
        offset: int = 0,
    ):
        return self._call(
            "withdraw_history",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                extra={"offset": offset},
            ),
        )

    def get_asset_dividend_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 500,
    ):
        return self._call(
            "asset_dividend_record",
            **self._history_params(
                start_time=start_time, end_time=end_time, limit=limit
            ),
        )

    def get_dust_log(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ):
        return self._call(
            "dust_log",
            **self._history_params(start_time=start_time, end_time=end_time),
        )

    def get_convert_trade_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ):
        return self._call(
            "get_convert_trade_history",
            **self._history_params(
                start_time=start_time, end_time=end_time, limit=limit
            ),
        )

    def get_c2c_trade_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        trade_type: str | None = None,
        page: int = 1,
    ):
        extra = (
            {"tradeType": trade_type, "page": page, "rows": limit}
            if trade_type
            else {"page": page, "rows": limit}
        )
        return self._call(
            "c2c_trade_history",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra=extra,
                start_key="startTimestamp",
                end_key="endTimestamp",
            ),
        )

    def get_flexible_subscription_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        current: int = 1,
    ):
        return self._call(
            "get_flexible_subscription_record",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra={"current": current, "size": limit},
            ),
        )

    def get_flexible_redemption_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        current: int = 1,
    ):
        return self._call(
            "get_flexible_redemption_record",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra={"current": current, "size": limit},
            ),
        )

    def get_flexible_rewards_history(
        self,
        rewards_type: str = "BONUS",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ):
        return self._call(
            "get_flexible_rewards_history",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                extra={"type": rewards_type},
            ),
        )

    def get_locked_subscription_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        current: int = 1,
    ):
        return self._call(
            "get_locked_subscription_record",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra={"current": current, "size": limit},
            ),
        )

    def get_locked_redemption_records(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        current: int = 1,
    ):
        return self._call(
            "get_locked_redemption_record",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra={"current": current, "size": limit},
            ),
        )

    def get_locked_rewards_history(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        current: int = 1,
    ):
        return self._call(
            "get_locked_rewards_history",
            **self._history_params(
                start_time=start_time,
                end_time=end_time,
                extra={"current": current, "size": limit},
            ),
        )

    # ── Summary ──────────────────────────────────────────────────────────

    def get_account_summary(self) -> BinanceAccountSummary:
        return BinanceAccountSummary(
            spot_balances=self.get_spot_balances(),
            funding_balances=self.get_funding_balances(),
            earn_balances=self.get_flexible_products(),
            staking_positions=self.get_staking_positions(),
            transfers=[],
            transactions=[],
        )

    def validate_connection(self) -> bool:
        try:
            self._call("ping")
            return True
        except BinanceError:
            return False


def create_binance_client(
    testnet: bool = False,
    api_key: str | None = None,
    api_secret: str | None = None,
) -> BinanceClient:
    return BinanceClient(api_key=api_key, api_secret=api_secret, testnet=testnet)
