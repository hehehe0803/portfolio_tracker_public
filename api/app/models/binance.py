"""
Binance data models - Normalized schemas for Binance API responses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    """Types of Binance transactions."""
    SPOT_TRADE = "spot_trade"
    FUNDING_DEPOSIT = "funding_deposit"
    FUNDING_WITHDRAWAL = "funding_withdrawal"
    SPOT_TO_FUNDING = "spot_to_funding"
    FUNDING_TO_SPOT = "funding_to_spot"
    EARN_DEPOSIT = "earn_deposit"
    EARN_WITHDRAWAL = "earn_withdrawal"
    STAKING_SUBSCRIBE = "staking_subscribe"
    STAKING_REDEEM = "staking_redeem"
    REWARD_CLAIM = "reward_claim"


class AccountType(str, Enum):
    """Binance account types."""
    SPOT = "spot"
    FUNDING = "funding"
    EARN = "earn"


class AssetBalance(BaseModel):
    """Normalized asset balance model."""
    asset: str = Field(..., description="Asset symbol (e.g., BTC, USDT)")
    free: float = Field(..., description="Available balance")
    locked: float = Field(..., description="Locked balance")
    account_type: AccountType = Field(..., description="Account type")

    @property
    def total(self) -> float:
        """Total balance including locked amount."""
        return self.free + self.locked


class StakingPosition(BaseModel):
    """Normalized staking position model."""
    position_id: str = Field(..., description="Staking position ID")
    asset: str = Field(..., description="Staked asset")
    amount: float = Field(..., description="Total staked amount")
    apy: Optional[float] = Field(None, description="Annual Percentage Yield")
    start_date: Optional[datetime] = Field(None, description="Staking start date")
    end_date: Optional[datetime] = Field(None, description="Staking end date")
    status: str = Field(default="active", description="Position status")
    account_type: AccountType = Field(default=AccountType.EARN, description="Account type")


class Transfer(BaseModel):
    """Normalized transfer model."""
    id: str = Field(..., description="Transfer ID")
    asset: str = Field(..., description="Asset symbol")
    amount: float = Field(..., description="Transfer amount")
    from_account: AccountType = Field(..., description="Source account")
    to_account: AccountType = Field(..., description="Destination account")
    timestamp: Optional[datetime] = Field(None, description="Transfer timestamp")
    status: str = Field(default="completed", description="Transfer status")


class OpenOrder(BaseModel):
    """Normalized open or pending spot order."""

    order_id: str = Field(..., description="Binance order identifier")
    symbol: str = Field(..., description="Base asset symbol")
    market_symbol: str = Field(..., description="Exchange trading pair symbol")
    order_type: str = Field(..., description="Order type")
    status: str = Field(..., description="Normalized order status")
    side: str = Field(..., description="Order side")
    quantity: float = Field(..., description="Original order quantity")
    limit_price: Optional[float] = Field(None, description="Limit price if present")
    stop_price: Optional[float] = Field(None, description="Stop price if present")
    placed_at: Optional[datetime] = Field(None, description="Order creation time")


class Transaction(BaseModel):
    """Normalized transaction model."""
    id: str = Field(..., description="Transaction ID")
    type: TransactionType = Field(..., description="Transaction type")
    asset: str = Field(..., description="Asset symbol")
    amount: float = Field(..., description="Transaction amount")
    account_type: AccountType = Field(..., description="Account type")
    timestamp: datetime = Field(..., description="Transaction timestamp")
    status: str = Field(default="completed", description="Transaction status")
    fee: Optional[float] = Field(None, description="Transaction fee")
    fee_asset: Optional[str] = Field(None, description="Fee asset")


class BinanceAccountSummary(BaseModel):
    """Summary of all Binance account data."""
    spot_balances: list[AssetBalance] = Field(
        default_factory=list, description="Spot account balances"
    )
    funding_balances: list[AssetBalance] = Field(
        default_factory=list, description="Funding account balances"
    )
    earn_balances: list[AssetBalance] = Field(
        default_factory=list, description="Earn account balances"
    )
    staking_positions: list[StakingPosition] = Field(
        default_factory=list, description="Staking positions"
    )
    transfers: list[Transfer] = Field(
        default_factory=list, description="Recent transfers"
    )
    transactions: list[Transaction] = Field(
        default_factory=list, description="All transactions"
    )

    @property
    def total_balance(self) -> dict[str, float]:
        """Aggregate balance by asset across all accounts."""
        balance_by_asset: dict[str, float] = {}
        for account_type in AccountType:
            for balance in getattr(
                self, f"{account_type.value}_balances", []
            ):
                if balance.asset not in balance_by_asset:
                    balance_by_asset[balance.asset] = 0
                balance_by_asset[balance.asset] += balance.total
        return balance_by_asset
