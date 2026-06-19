"""Pricing service: Binance for crypto, Yahoo Finance for everything else."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import httpx
import redis.asyncio as aioredis

from app.config import settings
from app.services import binance_price_client

logger = logging.getLogger(__name__)

CRYPTO_TTL = 60
EQUITY_TTL = 300
FX_TTL = 300
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

STABLE_VALUE_SYMBOLS = {"USD", "USDT", "USDC", "BUSD", "FDUSD", "DAI"}
YAHOO_SYMBOL_OVERRIDES = {
    "XAU": "GC=F",
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
}
BINANCE_ALIAS_SYMBOLS: dict[str, tuple[str, ...]] = {
    "WBETH": ("BETH", "ETH"),
    "BETH": ("ETH",),
    "WBTC": ("BTC",),
    "WETH": ("ETH",),
    "BNSOL": ("SOL",),
}

HistoricalPriceReasonCode = str
HistoricalPriceProvider = Callable[
    [str, datetime],
    Awaitable[Decimal | float | str | None],
]


@dataclass(frozen=True)
class HistoricalPriceResult:
    symbol: str
    as_of: datetime
    price_usd: Decimal | None
    reason_code: HistoricalPriceReasonCode | None


CRYPTO_SYMBOLS: set[str] = {
    "BTC",
    "ETH",
    "BNB",
    "SOL",
    "ADA",
    "XRP",
    "DOT",
    "DOGE",
    "AVAX",
    "MATIC",
    "LINK",
    "UNI",
    "ATOM",
    "LTC",
    "BCH",
    "NEAR",
    "ALGO",
    "VET",
    "FIL",
    "TRX",
    "SHIB",
    "USDT",
    "USDC",
    "BUSD",
    "DAI",
    "FDUSD",
}


def _redis_client() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


def _is_crypto_symbol(symbol: str) -> bool:
    return symbol in CRYPTO_SYMBOLS


def _is_yahoo_only_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return normalized in YAHOO_SYMBOL_OVERRIDES or any(
        normalized.endswith(suffix)
        for suffix in (".US", ".UK", ".FR", ".SE", ".DE", ".PA", ".ST")
    )


def _is_binance_candidate_symbol(symbol: str) -> bool:
    normalized = symbol.upper()
    return (
        normalized.isalnum()
        and len(normalized) <= 12
        and not _is_yahoo_only_symbol(normalized)
    )


def _binance_symbol_candidates(symbol: str) -> list[str]:
    normalized = symbol.upper()
    candidates: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(normalized)
    if normalized.startswith("LD") and len(normalized) > 2:
        add(normalized[2:])
    for candidate in list(candidates):
        for alias in BINANCE_ALIAS_SYMBOLS.get(candidate, ()):
            add(alias)
    return candidates


def _get_yahoo_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized in YAHOO_SYMBOL_OVERRIDES:
        return YAHOO_SYMBOL_OVERRIDES[normalized]
    if normalized.endswith(".US"):
        return normalized[:-3]
    if normalized.endswith(".UK"):
        return f"{normalized[:-3]}.L"
    if normalized.endswith(".FR"):
        return f"{normalized[:-3]}.PA"
    if normalized.endswith(".SE"):
        return f"{normalized[:-3]}.ST"
    return normalized


def _normalize_yahoo_currency(currency: str | None) -> tuple[str | None, float]:
    if not currency:
        return None, 1.0
    if currency == "GBp":
        return "GBP", 0.01
    return currency.upper(), 1.0


async def _cache_get_float(key: str) -> float | None:
    try:
        r = _redis_client()
        cached = await r.get(key)
        await r.aclose()
        return float(cached) if cached else None
    except Exception:
        return None


async def _cache_set_float(key: str, ttl: int, value: float) -> None:
    try:
        r = _redis_client()
        await r.setex(key, ttl, str(value))
        await r.aclose()
    except Exception as exc:
        logger.debug("Redis cache set failed for %s: %s", key, exc)


async def get_price_usd(symbol: str) -> float | None:
    """Return USD price for a symbol. Tries cache first, then live fetch."""
    symbol = symbol.upper()
    if symbol in STABLE_VALUE_SYMBOLS:
        return 1.0

    cache_key = f"price:{symbol}"
    cached = await _cache_get_float(cache_key)
    if cached is not None:
        return cached

    price = await _fetch_price(symbol)
    if price is not None:
        ttl = CRYPTO_TTL if _is_crypto_symbol(symbol) else EQUITY_TTL
        await _cache_set_float(cache_key, ttl, price)

    return price


async def get_historical_price_usd(
    symbol: str,
    as_of: datetime,
    *,
    provider: HistoricalPriceProvider | None = None,
) -> HistoricalPriceResult:
    """Return a historical USD price without falling back to live/current quotes."""
    normalized = symbol.upper()
    if normalized in STABLE_VALUE_SYMBOLS:
        return HistoricalPriceResult(
            symbol=normalized,
            as_of=as_of,
            price_usd=Decimal("1"),
            reason_code=None,
        )
    if provider is None:
        return HistoricalPriceResult(
            symbol=normalized,
            as_of=as_of,
            price_usd=None,
            reason_code="missing_historical_price",
        )

    price = await provider(normalized, as_of)
    if price is None:
        return HistoricalPriceResult(
            symbol=normalized,
            as_of=as_of,
            price_usd=None,
            reason_code="missing_historical_price",
        )
    return HistoricalPriceResult(
        symbol=normalized,
        as_of=as_of,
        price_usd=Decimal(str(price)),
        reason_code=None,
    )


async def _fetch_price(symbol: str) -> float | None:
    """Fetch a live USD price for a symbol."""
    if symbol in STABLE_VALUE_SYMBOLS:
        return 1.0

    if _is_crypto_symbol(symbol) or _is_binance_candidate_symbol(symbol):
        for candidate in _binance_symbol_candidates(symbol):
            price = await binance_price_client.get_price(candidate)
            if price is not None:
                return price
        if _is_crypto_symbol(symbol):
            return None

    return await _fetch_yahoo(_get_yahoo_symbol(symbol))


async def _fetch_yahoo_with_currency(
    symbol: str,
) -> tuple[float | None, str | None]:
    """Fetch a Yahoo quote and return both the price and quote currency."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{YAHOO_BASE}/{symbol}",
                params={"interval": "1d", "range": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice") or meta.get("previousClose")
            currency = meta.get("currency")
            return (float(price), currency) if price else (None, currency)
    except Exception as e:
        logger.warning("Yahoo Finance price fetch failed for %s: %s", symbol, e)
        return None, None


async def _get_fx_rate(base_currency: str, quote_currency: str = "USD") -> float | None:
    base_currency = base_currency.upper()
    quote_currency = quote_currency.upper()
    if base_currency == quote_currency:
        return 1.0

    cache_key = f"fx:{base_currency}{quote_currency}"
    cached = await _cache_get_float(cache_key)
    if cached is not None:
        return cached

    pair_symbol = f"{base_currency}{quote_currency}=X"
    price, _ = await _fetch_yahoo_with_currency(pair_symbol)
    if price is not None:
        await _cache_set_float(cache_key, FX_TTL, price)
    return price


async def _fetch_yahoo(symbol: str) -> float | None:
    """Fetch a Yahoo quote and normalize it into USD."""
    price, currency = await _fetch_yahoo_with_currency(symbol)
    if price is None:
        return None

    normalized_currency, unit_scale = _normalize_yahoo_currency(currency)
    normalized_price = price * unit_scale
    if not normalized_currency or normalized_currency == "USD":
        return normalized_price

    fx_rate = await _get_fx_rate(normalized_currency, "USD")
    if fx_rate is None:
        logger.warning(
            "Yahoo Finance FX conversion failed for %s priced in %s",
            symbol,
            currency,
        )
        return None

    return normalized_price * fx_rate


async def get_prices_bulk(symbols: list[str]) -> dict[str, float | None]:
    """Fetch prices for multiple symbols."""
    results: dict[str, float | None] = {}
    binance_requests: list[str] = []
    yahoo_symbols: list[str] = []
    symbol_candidates: dict[str, list[str]] = {}

    for symbol in symbols:
        sym = symbol.upper()
        if sym in STABLE_VALUE_SYMBOLS:
            results[sym] = 1.0
            continue

        if _is_crypto_symbol(sym) or _is_binance_candidate_symbol(sym):
            candidates = _binance_symbol_candidates(sym)
            symbol_candidates[sym] = candidates
            for candidate in candidates:
                if candidate not in binance_requests:
                    binance_requests.append(candidate)
            continue

        yahoo_symbols.append(sym)

    uncached_binance: list[str] = []
    uncached_yahoo: list[str] = []

    try:
        r = _redis_client()
        for sym in binance_requests:
            cached = await r.get(f"price:{sym}")
            if cached:
                results[sym] = float(cached)
            else:
                uncached_binance.append(sym)
        for sym in yahoo_symbols:
            cached = await r.get(f"price:{sym}")
            if cached:
                results[sym] = float(cached)
            else:
                uncached_yahoo.append(sym)
        await r.aclose()
    except Exception:
        uncached_binance = list(binance_requests)
        uncached_yahoo = list(yahoo_symbols)

    binance_results: dict[str, float | None] = {
        sym: results[sym] for sym in binance_requests if sym in results
    }
    if uncached_binance:
        fetched_binance_results = await binance_price_client.get_prices_bulk(
            uncached_binance
        )
        for sym, price in fetched_binance_results.items():
            binance_results[sym] = price
            if price is not None:
                await _cache_set_float(f"price:{sym}", CRYPTO_TTL, price)

    unresolved_yahoo: list[str] = []
    for sym, candidates in symbol_candidates.items():
        price = next(
            (
                binance_results.get(candidate)
                for candidate in candidates
                if binance_results.get(candidate) is not None
            ),
            None,
        )
        results[sym] = price
        if price is None and not _is_crypto_symbol(sym):
            unresolved_yahoo.append(sym)

    for sym in dict.fromkeys(uncached_yahoo + unresolved_yahoo):
        yahoo_symbol = _get_yahoo_symbol(sym)
        price = await _fetch_yahoo(yahoo_symbol)
        results[sym] = price
        if price is not None:
            await _cache_set_float(f"price:{sym}", EQUITY_TTL, price)

    return {symbol.upper(): results.get(symbol.upper()) for symbol in symbols}
