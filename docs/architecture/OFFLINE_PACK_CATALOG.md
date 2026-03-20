# Offline Pack Catalog

The offline pack catalog turns Somi's bundled knowledge packs into an
inspectable subsystem instead of a hidden fallback.

## Why It Exists

- show which bundled packs are available on disk
- surface which pack variant is preferred for the current hardware tier
- preview which local documents would answer a degraded-network query
- keep pack integrity, variant, and trust metadata visible to operators

## Inputs

- `knowledge_packs/*/manifest.json`
- bundled markdown or text documents
- hardware-tier advice from `ops/hardware_tiers.py`

## Outputs

- catalog summary for CLI and diagnostics
- preferred and fallback local query hits
- preview docs with `sha256`, trust, and variant metadata

## CLI

```powershell
somi offline catalog --root C:\somex --runtime-mode survival --query "purify water"
```

## Design Notes

- the catalog is capability-preserving: it does not remove packs on weaker
  hardware
- hardware tiers only influence preferred variant ordering and operator advice
- local pack integrity stays content-derived so offline audits remain possible
