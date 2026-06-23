# Migration Risk Analysis — v2.95.0 → v2.96.1

## New migrations (2)

### `src/chains/migrations/0057_chain_relayer_sponsoring.py`
- 3x `AddField` on `Chain`: `relayer_safe_creation_sponsored`,
  `relayer_safe_transaction_sponsored`,
  `relayer_enable_tenderly_simulation_before_relay` — all `BooleanField`
  with both `default=False` and `db_default=False`.
- **Risk: Safe.** `db_default` set means the column backfill happens at the
  database level without a table rewrite/lock concern for existing rows.

### `src/chains/migrations/0058_gastoken_priority.py`
- 1x `AddField` on `GasToken`: `priority` (`SmallIntegerField`,
  `default=100`, no `db_default`).
- **Risk: Safe.** `GasToken` is a small reference table (per-chain gas
  tokens), not a hot/large table, and a `default` is set so existing rows
  get a value. No app-level default-handling required since Django passes
  `default` as the field default for new rows.

## Summary

| Migration | Risk |
|---|---|
| 0057_chain_relayer_sponsoring | Safe |
| 0058_gastoken_priority | Safe |

No high or medium risk migrations in this rollout.
