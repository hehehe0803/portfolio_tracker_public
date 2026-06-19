"""
Binance API test fixtures - Mock data for testing.

This module contains fixture responses from the Binance API
for use in unit tests and integration testing.
"""

from datetime import datetime, timezone
from typing import Any

# Spot Account Response (simulated)
SPOT_ACCOUNT_RESPONSE: dict[str, Any] = {
    "permissions": ["SPOT"],
    "buyerCommissionPaid": 0,
    "makerCommissionPaid": 0,
    "takerCommissionPaid": 0,
    "timestamp": 1703001600000,
    "accountType": "SPOT",
    "balances": [
        {
            "asset": "BTC",
            "free": "1.23456789",
            "locked": "0.12345678",
        },
        {
            "asset": "ETH",
            "free": "10.54321098",
            "locked": "0.00000000",
        },
        {
            "asset": "USDT",
            "free": "50000.00000000",
            "locked": "1000.00000000",
        },
        {
            "asset": "BNB",
            "free": "100.00000000",
            "locked": "0.00000000",
        },
        {
            "asset": "ADA",
            "free": "0.00000000",
            "locked": "0.00000000",
        },
    ],
    "nonce": 1234567890,
}

# Funding Account Response (simulated)
FUNDING_ACCOUNT_RESPONSE: dict[str, Any] = {
    "code": "200000",
    "message": "success",
    "asset": [
        {
            "asset": "BTC",
            "free": "2.50000000",
            "locked": "0.00000000",
        },
        {
            "asset": "ETH",
            "free": "15.00000000",
            "locked": "0.00000000",
        },
        {
            "asset": "USDT",
            "free": "100000.00000000",
            "locked": "0.00000000",
        },
        {
            "asset": "BNB",
            "free": "50.00000000",
            "locked": "10.00000000",
        },
    ],
}

# Transfer Response (simulated)
TRANSFER_RESPONSE: dict[str, Any] = {
    "code": "200000",
    "message": "success",
    "data": [
        {
            "amount": "0.1",
            "asset": "BTC",
            "fromAccount": "SPOT",
            "toAccount": "MAIN",
            "tranTime": 1703001600000,
            "transId": 12345678901,
            "type": "MAIN_TO_MAIN",
        },
        {
            "amount": "1000",
            "asset": "USDT",
            "fromAccount": "MAIN",
            "toAccount": "SPOT",
            "tranTime": 1702915200000,
            "transId": 12345678902,
            "type": "MAIN_TO_SPOT",
        },
        {
            "amount": "0.5",
            "asset": "ETH",
            "fromAccount": "SPOT",
            "toAccount": "MAIN",
            "tranTime": 1702828800000,
            "transId": 12345678903,
            "type": "MAIN_TO_MAIN",
        },
    ],
}

# Staking Position Response (simulated - Launchpool)
STAKING_POSITION_RESPONSE: dict[str, Any] = {
    "code": "200000",
    "message": "success",
    "codeMsg": "",
    "totalPage": 1,
    "total": 2,
    "data": [
        {
            "id": 12345,
            "asset": "BTT",
            "amountStaked": "10000.00000000",
            "apy": "15.5",
            "period": "9",
            "rewardAsset": "BTT",
            "rewardAmount": "123.45",
            "subscribeTime": 1703001600000,
            "unlockTime": 1703865600000,
        },
        {
            "id": 12346,
            "asset": "DOGE",
            "amountStaked": "5000.00000000",
            "apy": "25.3",
            "period": "7",
            "rewardAsset": "DOGE",
            "rewardAmount": "89.12",
            "subscribeTime": 1702915200000,
            "unlockTime": 1703606400000,
        },
    ],
}

# Earn Cash Account Response (simulated)
EARN_CASH_ACCOUNT_RESPONSE: dict[str, Any] = {
    "code": "200000",
    "message": "success",
    "data": [
        {
            "asset": "USDT",
            "principal": "5000.00000000",
            "pendingInterest": "25.50000000",
            "annualizedYield": "5.5",
        },
        {
            "asset": "BUSD",
            "principal": "3000.00000000",
            "pendingInterest": "12.30000000",
            "annualizedYield": "4.8",
        },
        {
            "asset": "BTC",
            "principal": "0.50000000",
            "pendingInterest": "0.00012000",
            "annualizedYield": "2.1",
        },
    ],
}

# Staking Records Response (simulated)
STAKING_RECORD_RESPONSE: dict[str, Any] = {
    "code": "200000",
    "message": "success",
    "total": 3,
    "data": [
        {
            "recordId": "REC001",
            "positionId": 12345,
            "asset": "ETH",
            "amount": "2.5",
            "type": "STAKING",
            "status": "COMPLETED",
            "subscribeTime": 1703001600000,
            "rewards": [
                {
                    "asset": "ETH",
                    "amount": "0.025",
                    "createdAt": 1703088000000,
                }
            ],
        },
        {
            "recordId": "REC002",
            "positionId": 12346,
            "asset": "BTC",
            "amount": "0.1",
            "type": "STAKING",
            "status": "COMPLETED",
            "subscribeTime": 1702915200000,
            "rewards": [
                {
                    "asset": "BTC",
                    "amount": "0.001",
                    "createdAt": 1703001600000,
                }
            ],
        },
    ],
}

# Spot MyTrades Response (simulated)
SPOT_TRADES_RESPONSE: list[dict[str, Any]] = [
    {
        "id": 123456789,
        "orderId": 987654321,
        "symbol": "BTCUSDT",
        "price": "42000.00",
        "qty": "0.001",
        "commission": "4.2",
        "commissionAsset": "USDT",
        "isBuyer": True,
        "isMaker": True,
        "time": 1703001600000,
    },
    {
        "id": 123456790,
        "orderId": 987654322,
        "symbol": "ETHUSDT",
        "price": "2200.00",
        "qty": "0.1",
        "commission": "2.2",
        "commissionAsset": "USDT",
        "isBuyer": False,
        "isMaker": False,
        "time": 1702915200000,
    },
    {
        "id": 123456791,
        "orderId": 987654323,
        "symbol": "BNBUSDT",
        "price": "300.00",
        "qty": "1.0",
        "commission": "0.3",
        "commissionAsset": "BNB",
        "isBuyer": True,
        "isMaker": False,
        "time": 1702828800000,
    },
]

# Rate Limit Headers
RATE_LIMIT_HEADERS: dict[str, str] = {
    "X-MBX-USED-WEIGHT-1M": "100",
    "X-MBX-ORDER-USED-WEIGHT-1M": "5",
    "X-MBX-RAW-REQUEST-COUNT": "1",
}

# Error Responses
INVALID_API_KEY_ERROR: dict[str, Any] = {
    "code": -2014,
    "msg": "API-key format invalid",
}

RATE_LIMIT_ERROR: dict[str, Any] = {
    "code": -1003,
    "msg": "Too many new requests; the current limit is 1200 requests per minute. "
    "Please contact us if you need to increase the standard rate limit.",
}

ACCOUNT_NOT_ENABLED_ERROR: dict[str, Any] = {
    "code": -2015,
    "msg": "Invalid API key, secret or required passphrase",
}
