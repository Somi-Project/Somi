# Somi Knowledge Packs

These packs are the first offline-ready reference hooks for Somi's degraded-network
mode. They are intentionally lightweight so they work on consumer hardware and are
easy for contributors to expand.

Current seeded categories:
- `repair_basics`
- `survival_basics`
- `infrastructure_basics`
- `sanitation_basics`
- `field_health_basics`
- `food_production_basics`
- `power_recovery_basics`

Design notes:
- Each pack ships with a `manifest.json` and one or more Markdown documents.
- The current manifest contract supports `schema_version`, `variant`,
  `trust`, and `updated_at` so packs can stay compact on weaker systems while
  still carrying provenance-rich metadata.
- The offline resilience audit scans this directory to report what Somi can still use
  when web search is weak or unavailable.
- The websearch layer can fall back to these packs for relevant questions and clearly
  mark those answers as bundled local knowledge.

Helpful commands:

```powershell
somi offline status --root C:\somex
somi offline catalog --root C:\somex --query "purify water"
```
