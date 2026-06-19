"""
Binance public price API client for cryptocurrency prices.

Uses the public ticker/price endpoint — no auth required.
Free, unlimited rate limits for public endpoints.
Docs: https://binance-docs.github.io/apidocs/spot/en/#symbol-price-ticker
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BINANCE_BASE = "https://api.binance.com/api/v3"


async def get_price(symbol: str, quote: str = "USDT") -> Optional[float]:
    """Fetch current price for a crypto pair (e.g. BTC/USDT).

    Args:
        symbol: Base asset (e.g. "BTC", "ETH").
        quote: Quote asset (default "USDT"). Use "USD" for USD stablecoins.

    Returns price as float, or None on failure.
    """
    # Normalize: Binance uses USDT as primary quote, map USD → USDT
    if quote.upper() == "USD":
        quote = "USDT"
    pair = f"{symbol.upper()}{quote.upper()}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{BINANCE_BASE}/ticker/price",
                params={"symbol": pair},
            )
            resp.raise_for_status()
            data = resp.json()
            price_str = data.get("price")
            if price_str:
                price = float(price_str)
                if price > 0:
                    return price
            logger.warning("Binance returned zero/empty price for %s", pair)
            return None
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 400:
            # Symbol pair doesn't exist on Binance — not an error, just unsupported
            logger.debug("Binance pair %s not found", pair)
        else:
            logger.warning("Binance price fetch failed for %s: %s", pair, e)
        return None
    except Exception as e:
        logger.warning("Binance price fetch failed for %s: %s", pair, e)
        return None


async def get_prices_bulk(
    symbols: list[str], quote: str = "USDT"
) -> dict[str, Optional[float]]:
    """Fetch prices for multiple crypto assets via Binance.

    Uses the bulk ticker endpoint which returns all symbols in one call.
    Much more efficient than individual requests.

    Args:
        symbols: List of base assets (e.g. ["BTC", "ETH", "SOL"]).
        quote: Quote asset (default "USDT").

    Returns dict mapping symbol → price (or None if not found).
    """
    results: dict[str, Optional[float]] = {}
    if not symbols:
        return results

    if quote.upper() == "USD":
        quote = "USDT"

    # Build lookup of requested pairs
    pair_map: dict[str, str] = {}
    for sym in symbols:
        sym_upper = sym.upper()
        pair = f"{sym_upper}{quote.upper()}"
        pair_map[pair] = sym_upper

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{BINANCE_BASE}/ticker/price")
            resp.raise_for_status()
            all_tickers = resp.json()

        # Filter to requested pairs
        for ticker in all_tickers:
            pair_name = ticker.get("symbol", "")
            if pair_name in pair_map:
                sym = pair_map[pair_name]
                try:
                    price = float(ticker["price"])
                    results[sym] = price if price > 0 else None
                except (ValueError, TypeError, KeyError):
                    results[sym] = None

        # Mark missing symbols
        for sym in symbols:
            results.setdefault(sym.upper(), None)

    except Exception as e:
        logger.warning("Binance bulk price fetch failed: %s", e)
        for sym in symbols:
            results[sym.upper()] = None

    return results
