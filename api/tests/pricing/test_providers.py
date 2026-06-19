"""Tests for Binance pricing and pricing-service routing."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from app.services import binance_price_client
from app.services.pricing import (
    CRYPTO_SYMBOLS,
    _fetch_price,
    _fetch_yahoo,
    _fetch_yahoo_with_currency,
    _get_yahoo_symbol,
    get_prices_bulk,
)


class TestPricingRouting:
    @pytest.mark.asyncio
    async def test_fetch_price_routes_crypto_to_binance(self):
        """Known crypto symbols should route to Binance."""
        with patch(
            "app.services.binance_price_client.get_price",
            new_callable=AsyncMock,
            return_value=97500.0,
        ) as mock_binance:
            price = await _fetch_price("BTC")

        assert price == 97500.0
        mock_binance.assert_called_once_with("BTC")

    @pytest.mark.asyncio
    async def test_fetch_price_routes_non_crypto_to_yahoo(self):
        """All non-crypto symbols should route to Yahoo Finance."""
        with patch(
            "app.services.pricing._fetch_yahoo",
            new_callable=AsyncMock,
            return_value=185.0,
        ) as mock_yahoo:
            price = await _fetch_price("AAPL")

        assert price == 185.0
        mock_yahoo.assert_called_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_fetch_price_maps_xau_to_gc_future(self):
        """Gold should use Yahoo's GC=F symbol instead of a CoinGecko token."""
        with patch(
            "app.services.pricing._fetch_yahoo",
            new_callable=AsyncMock,
            return_value=2400.0,
        ) as mock_yahoo:
            price = await _fetch_price("XAU")

        assert price == 2400.0
        mock_yahoo.assert_called_once_with("GC=F")

    @pytest.mark.asyncio
    async def test_fetch_price_uses_binance_alias_fallback_for_wbeth(self):
        """Wrapped ETH staking receipts should fall back to Binance aliases."""
        with patch(
            "app.services.binance_price_client.get_price",
            new_callable=AsyncMock,
            side_effect=[None, 2145.5],
        ) as mock_binance:
            price = await _fetch_price("WBETH")

        assert price == 2145.5
        assert mock_binance.await_args_list == [call("WBETH"), call("BETH")]

    def test_get_yahoo_symbol_normalizes_supported_suffixes(self):
        assert _get_yahoo_symbol("MU.US") == "MU"
        assert _get_yahoo_symbol("CSPX.UK") == "CSPX.L"
        assert _get_yahoo_symbol("SAP.DE") == "SAP.DE"
        assert _get_yahoo_symbol("AIR.PA") == "AIR.PA"
        assert _get_yahoo_symbol("SOI.FR") == "SOI.PA"
        assert _get_yahoo_symbol("SIVE.SE") == "SIVE.ST"

    @pytest.mark.asyncio
    async def test_fetch_yahoo_with_currency_returns_price_and_currency(self):
        """Yahoo helper should surface both price and quote currency."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 185.42,
                            "currency": "USD",
                        }
                    }
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.pricing.httpx.AsyncClient", return_value=mock_client):
            price, currency = await _fetch_yahoo_with_currency("AAPL")

        assert price == 185.42
        assert currency == "USD"

    @pytest.mark.asyncio
    async def test_fetch_yahoo_converts_eur_quote_to_usd(self):
        """EU Yahoo quotes should be converted into USD using Yahoo FX."""
        with (
            patch(
                "app.services.pricing._fetch_yahoo_with_currency",
                new_callable=AsyncMock,
                return_value=(100.0, "EUR"),
            ) as mock_yahoo_quote,
            patch(
                "app.services.pricing._get_fx_rate",
                new_callable=AsyncMock,
                return_value=1.08,
            ) as mock_fx_rate,
        ):
            price = await _fetch_yahoo("SAP.DE")

        assert price == pytest.approx(108.0)
        mock_yahoo_quote.assert_called_once_with("SAP.DE")
        mock_fx_rate.assert_called_once_with("EUR", "USD")

    @pytest.mark.asyncio
    async def test_get_prices_bulk_routes_crypto_and_yahoo_symbols(self):
        """Bulk pricing should batch Binance candidates and Yahoo symbols."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch("app.services.pricing._redis_client", return_value=mock_redis),
            patch(
                "app.services.pricing.binance_price_client.get_prices_bulk",
                new_callable=AsyncMock,
                return_value={"BTC": 50000.0, "AAPL": None, "SAP.DE": None},
            ) as mock_binance_bulk,
            patch(
                "app.services.pricing._fetch_yahoo",
                new_callable=AsyncMock,
                side_effect=lambda symbol: {"AAPL": 185.0, "SAP.DE": 210.0}.get(symbol),
            ) as mock_yahoo,
        ):
            result = await get_prices_bulk(["BTC", "AAPL", "SAP.DE"])

        assert result == {"BTC": 50000.0, "AAPL": 185.0, "SAP.DE": 210.0}
        mock_binance_bulk.assert_called_once_with(["BTC", "AAPL"])
        assert mock_yahoo.await_count == 2

    @pytest.mark.asyncio
    async def test_get_prices_bulk_uses_alias_fallbacks_for_long_tail_assets(
        self,
    ):
        """Binance-only symbols should resolve via alias candidates first."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with (
            patch("app.services.pricing._redis_client", return_value=mock_redis),
            patch(
                "app.services.pricing.binance_price_client.get_prices_bulk",
                new_callable=AsyncMock,
                return_value={"WBETH": None, "BETH": 2145.5, "FET": 1.25, "AAPL": None},
            ) as mock_binance_bulk,
            patch(
                "app.services.pricing._fetch_yahoo",
                new_callable=AsyncMock,
                return_value=185.0,
            ) as mock_yahoo,
        ):
            result = await get_prices_bulk(["WBETH", "FET", "AAPL"])

        assert result == {"WBETH": 2145.5, "FET": 1.25, "AAPL": 185.0}
        mock_binance_bulk.assert_called_once_with(
            ["WBETH", "BETH", "ETH", "FET", "AAPL"]
        )
        mock_yahoo.assert_awaited_once_with("AAPL")

    def test_crypto_symbol_registry_contains_expected_assets(self):
        """Core crypto and stable-value symbols should stay in the registry."""
        assert "BTC" in CRYPTO_SYMBOLS
        assert "ETH" in CRYPTO_SYMBOLS
        assert "USDT" in CRYPTO_SYMBOLS


class TestBinancePriceClient:
    @pytest.mark.asyncio
    async def test_get_price_returns_float(self):
        """Binance get_price should return the price as float."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "BTCUSDT", "price": "97500.12"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            price = await binance_price_client.get_price("BTC")

        assert price == pytest.approx(97500.12)

    @pytest.mark.asyncio
    async def test_get_price_returns_none_on_zero(self):
        """Binance get_price should return None for zero price."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "FAKEUSDT", "price": "0"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            price = await binance_price_client.get_price("FAKE")

        assert price is None

    @pytest.mark.asyncio
    async def test_get_price_handles_404(self):
        """Binance get_price should return None for 400 (pair not found)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        from httpx import HTTPStatusError

        mock_resp.raise_for_status.side_effect = HTTPStatusError(
            "Bad Request",
            request=MagicMock(),
            response=mock_resp,
        )

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            price = await binance_price_client.get_price("NOTREAL")

        assert price is None

    @pytest.mark.asyncio
    async def test_get_prices_bulk_filters_from_all_tickers(self):
        """Binance bulk should filter relevant pairs from full ticker list."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"symbol": "BTCUSDT", "price": "97500.00"},
            {"symbol": "ETHUSDT", "price": "3450.00"},
            {"symbol": "SOLUSDT", "price": "145.00"},
            {"symbol": "DOGEUSDT", "price": "0.18"},
        ]
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await binance_price_client.get_prices_bulk(["BTC", "ETH", "SOL"])

        assert result["BTC"] == pytest.approx(97500.0)
        assert result["ETH"] == pytest.approx(3450.0)
        assert result["SOL"] == pytest.approx(145.0)

    @pytest.mark.asyncio
    async def test_get_prices_bulk_handles_http_error(self):
        """Binance bulk should return None for all symbols on HTTP error."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("Connection error")

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            result = await binance_price_client.get_prices_bulk(["BTC", "ETH"])

        assert result["BTC"] is None
        assert result["ETH"] is None

    @pytest.mark.asyncio
    async def test_get_price_maps_usd_to_usdt(self):
        """Binance get_price should map USD quote to USDT."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"symbol": "BTCUSDT", "price": "97500.00"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.binance_price_client.httpx.AsyncClient",
            return_value=mock_client,
        ):
            price = await binance_price_client.get_price("BTC", quote="USD")

        assert price == pytest.approx(97500.0)
        mock_client.get.assert_called_once()
        call_params = mock_client.get.call_args[1]["params"]
        assert call_params["symbol"] == "BTCUSDT"
