# Local Data

This directory is for local-only broker exports, statements, account reports, and
derived snapshots that may contain private trading history.

Git intentionally ignores everything under `data/` except this README. Keep
synthetic fixtures in service test directories, but keep real account exports
and derived private-account snapshots here.

Expected local paths:

- `data/binance_data/`
- `data/aster_data/`
- `data/hyperliquid_data/`
- `data/xtb/`
- `data/xtb_statement_reference/`

Do not move these files back under `docs/` or service test fixtures unless they
have been sanitized and explicitly approved for version control.
