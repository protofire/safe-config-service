# Release Changes — v2.95.0 → v2.96.1

> Note: the fork's real content baseline is `v2.95.0`, not `v2.89.0`. The
> raw `git merge-base` points to `v2.89.0` because a prior rollout
> (`8518817 "Upgrage from v2.89.0 to v2.95.0"`) was done by squash/overwrite
> rather than a true `git merge`. Content-equivalence check confirmed
> `development-rollout-2.96.1` is diff-identical to `v2.95.0` aside from 6
> Protofire-added files, so all analysis below uses `v2.95.0..v2.96.1` as the
> real upstream delta.

## Upstream commits merged (2)

- `306dba2` feat: Order chain gas tokens by priority (#1587)
- `3b13df6` feat(relayer): add sponsorship fields and validation to Chain model (#1584)

## New ENV vars

None.

## Deprecated ENV vars

None.

## Breaking changes

- **`GET /api/v1/chains/` (and v2) response shape**: the flat `relayer_type`
  field on the Chain serializer is **removed** and replaced by a nested
  `relayer` object:
  ```json
  "relayer": {
    "type": "...",
    "safe_creation_sponsored": false,
    "safe_transaction_sponsored": false,
    "enable_tenderly_simulation_before_relay": false
  }
  ```
  Source: `src/chains/serializers.py` (`ChainSerializer.Meta.fields`,
  new `RelayerSerializer`). Any consumer reading `relayer_type` directly off
  the chain payload (e.g. safe-client-gateway, safe-wallet-monorepo) needs to
  switch to `relayer.type`. **Action item:** check downstream consumers of
  this API before/while deploying.

- **`GasToken` model validation**: `Chain.clean()` now raises a
  `ValidationError` if `relayer_safe_creation_sponsored` or
  `relayer_safe_transaction_sponsored` is set `True` while `relayer_type` is
  `None`. This only affects model-level `.full_clean()` / admin form saves,
  not raw `.save()` calls, but is good to know for the Django admin.

## Build / dependency changes

None — no changes to `pyproject.toml` or `uv.lock` in this delta.

## New services

None.

## Other functional changes

- `GasToken` gains a `priority` field (`SmallIntegerField`, default `100`,
  lower = higher priority). `GasTokensListView` now orders by
  `("priority", "symbol", "id")` instead of `("symbol", "id")`. Admin list
  view/fieldsets updated to show/edit priority.

## Action items

1. Coordinate the `relayer_type` → `relayer.type` API shape change with any
   downstream consumers (safe-client-gateway, safe-wallet-monorepo) before
   this reaches a deployed environment.
2. No env var or dependency changes needed in deployment configs.
