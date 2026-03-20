# Offline Knowledge Packs

Somi's offline packs are the first durable layer for degraded-network or
blackout conditions.

Current contract:
- each pack lives under `knowledge_packs/<pack_id>/`
- each pack ships with `manifest.json` plus one or more text documents
- the manifest now carries:
  - `schema_version`
  - `variant`
  - `trust`
  - `updated_at`
- the scanner computes pack-level integrity and document-level hashes so local
  knowledge remains traceable even when it is bundled

Design intent:
- `compact` packs stay practical on weaker hardware and storage budgets
- future `expanded` packs can add more documents without changing the retrieval
  contract
- local citations use `local://knowledge-pack/<pack_id>/<doc_slug>` so answers
  can point back to a specific bundled source

Current trust posture:
- bundled packs are read-heavy and defensive
- they are not a replacement for the web; they are the first fallback when the
  network degrades
- packs should stay provenance-rich and easy to review by humans
