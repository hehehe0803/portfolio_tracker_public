# Binance Accounting Policy

## Purpose

This document codifies how the portfolio tracker should ingest, classify, and reconcile Binance activity so Binance performance can be compared fairly against XTB and the combined portfolio.

It combines:
- the user's accounting decisions for their own activity,
- the Binance export files currently available locally in `data/binance_data/`,
- the current Binance implementation in `api/app/services/binance_client.py` and `api/app/services/binance_sync.py`, and
- official Binance developer docs reviewed on 2026-04-20.

## User-specific accounting decisions

These rules are now the default policy for this portfolio.

### External cashflows
Treat the following as external capital movement:
- **P2P fiat -> USDT in Funding** = `external_deposit`
- **P2P USDT -> fiat out** = `external_withdrawal`
- crypto/fiat deposits from outside the tracked portfolio = `external_deposit`
- withdrawals to bank / fiat off-ramp = `external_withdrawal`

### Bridge transfers
Some withdrawals are not money out of the portfolio.

Treat likely transfers to the user's own other venues as bridge transfers when matched:
- **Hyperliquid**
- **Aster / Aster Exchange**

Suggested event classes:
- `bridge_transfer_out`
- `bridge_transfer_in`

If a transfer cannot be confidently matched, classify it as:
- `unclassified_external_transfer`

This is preferred over forcing a wrong `external_withdrawal` classification.

### Product scope actually used
The user reported using:
- spot
- convert
- Simple Earn / staking
- P2P

The user reported **not** using:
- futures
- margin
- Binance Pay

### Cost basis and rewards policy
- Goal: **accounting-accurate cost basis and realized PnL as much as possible**.
- Preserve reward rows at raw granularity; aggregate only in reporting.
- Treat reward-like income separately from invested capital:
  - Simple Earn rewards
  - locked rewards
  - staking rewards
  - asset dividends / airdrops

## Source-of-truth hierarchy

### 1. Raw export files = historical source of truth
Use Binance export files as the baseline for:
- spot trades
- convert trades
- deposits
- withdrawals
- Simple Earn subscriptions / redemptions / rewards
- locked subscriptions / redemptions / rewards
- staking / WBETH / BNSOL history where exported

Reason: exports preserve historical activity that API-only reconstruction can miss, especially fully exited spot assets.

### 2. API history = incremental source of truth
Use the Binance API after the historical baseline import for ongoing deltas and reconciliation **within the currently supported live coverage set**.

This means the user does **not** need to download exports after every deposit, withdrawal, convert, Simple Earn, or C2C/P2P event.
However, spot trades, internal transfers, dividends, and dust remain export-only for now, so the user should import a fresh export after that activity.

Recommended operational model:
- initial full export import for baseline history
- regular API sync for supported recent deltas
- periodic fresh exports for reconciliation
- immediate fresh export after unsupported live activity (spot trading, internal transfers, dividends, dust)

Suggested cadence for fresh exports:
- monthly, or
- before final reporting / audit / tax-style review, or
- after heavy activity / new-product usage, especially if that activity is still export-only

### 3. Snapshot balances = reconciliation only
Current balances and positions are useful for:
- current holdings
- quantity reconciliation
- account health checks

They are **not** sufficient for:
- exact historical cost basis
- fully accurate realized PnL
- reconstructing fully exited assets

## Recommended ingestion architecture

### Layer 1 — Raw archive
Preserve original ZIP exports unchanged.

### Layer 2 — Typed source rows
Parse each export/API payload into typed staging rows with:
- source file / endpoint
- source row index / API cursor metadata
- raw payload
- parsed UTC timestamp
- Decimal-safe quantities
- parse warnings

### Layer 3 — Canonical ledger events
Map staging rows into canonical event classes such as:
- `external_deposit`
- `external_withdrawal`
- `bridge_transfer_out`
- `bridge_transfer_in`
- `spot_trade_buy`
- `spot_trade_sell`
- `convert_buy`
- `convert_sell`
- `earn_subscribe`
- `earn_redeem`
- `earn_reward`
- `staking_subscribe`
- `staking_redeem`
- `staking_reward`
- `airdrop`
- `dividend`
- `dust_convert`
- `fee`
- `unclassified_external_transfer`

## Precedence rules

When multiple sources overlap, use this precedence:

1. **Dedicated export files**
2. **Dedicated history APIs**
3. **Binance Transaction History export** for reconciliation / support classification
4. **Current balance / position snapshots** for present-state reconciliation only

### Export/API overlap suppression policy
The baseline overlap rule remains exact deterministic fingerprint matching.

A completed export-vs-live-API shadow evaluation on 2026-04-20 showed that exact fingerprint-only matching is too strict for some Simple Earn rows because Binance export labels/timestamps and live API payloads do not always normalize to the same fingerprint even when they represent the same economic event.

Current policy:
- keep overlap suppression deterministic and source-specific
- do **not** add generic fuzzy dedupe
- apply stronger deterministic overlap suppression only where live evidence is already strong enough
- treat export-imported ledger rows as the historical baseline for overlap decisions

Implemented overlap suppression scope:
- `simple_earn_locked_reward`
- `simple_earn_locked_redemption`

These categories are now allowed a stronger source-specific deterministic overlap match against import-backed export baseline rows because the shadow evaluation recovered a large, stable overlap there.

Flexible rewards remain on exact fingerprint matching for now. The same shadow evaluation recovered only a small deterministic subset there and left a meaningful residual unmatched set, so broader suppression is **not** justified yet. If future expansion is needed, it should stay source-specific and deterministic rather than heuristic.

### Why Transaction History should not be the only source
The `Transaction History` export is valuable, but it compresses many semantics into:
- account
- operation
- coin
- change
- remark

That makes it useful for reconciliation and classification, but weaker than specialized exports for exact accounting and cost basis.

## Official Binance API coverage reviewed

The following endpoints were verified from official Binance developer docs on 2026-04-20.

| Domain | Purpose | Official route | Docs URL | Current repo status | Notes |
|---|---|---|---|---|---|
| Spot | current spot balances | `GET /api/v3/account` | `https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints` | implemented | Used now for spot balance snapshots. |
| Spot | symbol-scoped trade history | `GET /api/v3/myTrades` | `https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints` | implemented | Useful, but requires known symbol universe. Not sufficient alone for full account history. |
| Wallet/Capital | deposit history | `GET /sapi/v1/capital/deposit/hisrec` | `https://developers.binance.com/docs/wallet/capital/deposite-history` | implemented | Used by post-baseline API delta sync for external cashflow history. |
| Wallet/Capital | withdraw history | `GET /sapi/v1/capital/withdraw/history` | `https://developers.binance.com/docs/wallet/capital/withdraw-history` | implemented | Used by post-baseline API delta sync for withdrawals and bridge-transfer review. |
| Wallet/Asset | asset dividend record | `GET /sapi/v1/asset/assetDividend` | `https://developers.binance.com/docs/wallet/asset/assets-divided-record` | export-only | Covered by export imports for now; live API delta sync does not ingest it yet. |
| Wallet/Asset | dust log | `GET /sapi/v1/asset/dribblet` | `https://developers.binance.com/docs/wallet/asset/dust-log` | export-only | Covered by export imports for now; live API delta sync does not ingest it yet. |
| Wallet/Asset | universal transfer history | `GET /sapi/v1/asset/transfer` | `https://developers.binance.com/docs/wallet/asset/query-user-universal-transfer` | export-only | Current client wraps this, but live API delta sync still treats internal transfers as export-only. |
| Wallet/Asset | funding wallet balances | `POST /sapi/v1/asset/get-funding-asset` | `https://developers.binance.com/docs/wallet/asset/funding-wallet` | implemented | Current-state snapshot use only. Snapshot refresh is all-or-nothing. |
| Wallet/Asset | user assets | `POST /sapi/v3/asset/getUserAsset` | `https://developers.binance.com/docs/wallet/asset/user-assets` | **not implemented** | Can help reconciliation of current assets. |
| Wallet/Account | daily account snapshot | `GET /sapi/v1/accountSnapshot` | `https://developers.binance.com/docs/wallet/account/daily-account-snapshoot` | **not implemented** | Useful for reconciliation/backfill of balances, not a replacement for trade ledger. |
| Convert | convert trade history | `GET /sapi/v1/convert/tradeFlow` | `https://developers.binance.com/docs/convert/trade/Get-Convert-Trade-History` | implemented | Used by post-baseline API delta sync for convert activity. |
| C2C / P2P | C2C trade history | `GET /sapi/v1/c2c/orderMatch/listUserOrderHistory` | `https://developers.binance.com/docs/c2c/rest-api` | implemented | Used by post-baseline API delta sync for P2P fiat<->USDT cashflows. |
| Simple Earn | flexible product position | `GET /sapi/v1/simple-earn/flexible/position` | `https://developers.binance.com/docs/simple_earn/flexible-locked/account/Get-Flexible-Product-Position` | implemented | Current-state snapshot use only. Snapshot refresh is all-or-nothing. |
| Simple Earn | locked product position | `GET /sapi/v1/simple-earn/locked/position` | `https://developers.binance.com/docs/simple_earn/flexible-locked/account/Get-Locked-Product-Position` | **not implemented** | Useful for current-state reconciliation. |
| Simple Earn | flexible subscription record | `GET /sapi/v1/simple-earn/flexible/history/subscriptionRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Flexible-Subscription-Record` | implemented | Used by post-baseline API delta sync for internal wallet->earn flows. |
| Simple Earn | flexible redemption record | `GET /sapi/v1/simple-earn/flexible/history/redemptionRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Flexible-Redemption-Record` | implemented | Used by post-baseline API delta sync for earn unwind flows. |
| Simple Earn | flexible rewards history | `GET /sapi/v1/simple-earn/flexible/history/rewardsRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Flexible-Rewards-History` | implemented | Used by post-baseline API delta sync for flexible earn income. |
| Simple Earn | locked subscription record | `GET /sapi/v1/simple-earn/locked/history/subscriptionRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Locked-Subscription-Record` | implemented | Used by post-baseline API delta sync for locked earn flows. |
| Simple Earn | locked redemption record | `GET /sapi/v1/simple-earn/locked/history/redemptionRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Locked-Redemption-Record` | implemented | Used by post-baseline API delta sync for locked earn redemptions. |
| Simple Earn | locked rewards history | `GET /sapi/v1/simple-earn/locked/history/rewardsRecord` | `https://developers.binance.com/docs/simple_earn/flexible-locked/history/Get-Locked-Rewards-History` | implemented | Used by post-baseline API delta sync for locked earn income. |

## Additional connector-supported APIs worth validating next

The installed Binance connector surface also exposes methods that are likely relevant but were not fully documented in today's official-doc pass:
- `eth_staking_account` (already used for current position)
- `get_eth_staking_history`
- `get_wbeth_rewards_history`
- `get_wbeth_wrap_history`
- `get_wbeth_unwrap_history`

These should be validated against live responses and, if used, documented alongside the official URL once the public docs page is confirmed.

## What the current repo already implements

Current historical/data calls in `api/app/services/binance_client.py`:
- snapshot/current-state:
  - `account`
  - `funding_wallet`
  - `get_flexible_product_position`
  - `eth_staking_account`
- post-baseline API delta coverage:
  - `deposit_history`
  - `withdraw_history`
  - `get_convert_trade_history`
  - `c2c_trade_history`
  - `get_flexible_subscription_record`
  - `get_flexible_redemption_record`
  - `get_flexible_rewards_history`
  - `get_locked_subscription_record`
  - `get_locked_redemption_record`
  - `get_locked_rewards_history`
- wrapped but still export-only for now:
  - `query_universal_transfer_history`
  - `asset_dividend_record`
  - `dust_log`
  - `my_trades`

Current sync behavior in `api/app/services/binance_sync.py`:
- persists current-state snapshot rows only when all snapshot components succeed:
  - `balance_snapshot_spot`
  - `balance_snapshot_funding`
  - `balance_snapshot_earn`
  - `staking_position`
- extends the export-confirmed ledger baseline with API delta rows for:
  - `deposit`
  - `withdrawal`
  - `convert_buy` / `convert_sell`
  - `earn_subscribe` / `earn_redeem` / `earn_reward`
  - `external_deposit` / `external_withdrawal` (C2C/P2P)
- persists degraded sync warnings through `ActivityLog` and `/v1/sync/status`

### Consequence
This is sufficient for current holdings visibility, but insufficient for:
- exact Binance cost basis
- complete realized PnL
- preserving fully exited historical assets
- correct classification of P2P / bridge transfers / rewards over time

## APIs most worth adding next

Priority order for the current follow-up scope:

1. real export-vs-API shadow evaluation tooling for ambiguous overlap / dedupe decisions
2. `asset_dividend_record` live API ingestion (currently export-only)
3. `dust_log` live API ingestion (currently export-only)
4. `query_universal_transfer_history` live API ingestion for internal transfer deltas
5. safe live strategy for spot-trade delta coverage beyond export refreshes
6. `accountSnapshot` for reconciliation only

## Tradeoffs: export-first vs API-first

### Export-first baseline + API delta sync
**Recommended.**

Pros:
- best cost-basis accuracy
- best auditability
- preserves fully exited assets
- easier dispute tracing

Cons:
- more parser work
- periodic export refresh still needed for maximum confidence

### API-only
Pros:
- less manual operator effort
- easy incremental sync

Cons:
- account-wide spot history remains incomplete because `myTrades` is symbol-scoped
- more likely to miss fully exited coins
- weaker realized PnL / cost basis confidence

## Known time-window limits from prior live probing

These were previously validated against live Binance responses and should be respected by the ingestion code:
- `deposit_history`: max 90-day window
- `withdraw_history`: max 90-day window
- `asset_dividend_record`: max 180-day window
- Simple Earn / staking / WBETH history endpoints: max 90-day window

Implementation rule: paginate by time windows from earliest relevant year forward rather than requesting all history in one call.

## Implementation requirements

### Canonical classification rules
- P2P fiat -> USDT = `external_deposit`
- P2P USDT -> fiat = `external_withdrawal`
- internal Spot/Funding/Earn/Staking movements = internal transfers, not capital flows
- temporary transfers to Hyperliquid/Aster = bridge transfers when matched
- unmatched off-platform transfers = `unclassified_external_transfer`
- rewards / dividends / staking accrual = income, not new invested capital

### Data retention and provenance
Every normalized row should preserve provenance:
- source file or API endpoint
- source row / transaction id / cursor metadata
- raw payload
- deterministic fingerprint

### Presentation requirements
Analytics should separate:
1. Contributions — deposits, withdrawals, net invested
2. Operations — trades, converts, internal transfers, bridge transfers, fees
3. Income — earn/staking/dividend/airdrop rewards
4. Performance — realized PnL, unrealized PnL, total return, XIRR

## Summary decision

The tracker should use:
- **exports** as the historical baseline and periodic reconciliation source,
- **API history** as the incremental sync layer,
- **snapshot endpoints** as present-state reconciliation only,
- **Transaction History export** as a supporting classification source rather than the sole accounting ledger.
