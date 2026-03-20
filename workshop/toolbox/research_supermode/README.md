# research_supermode

Durable storage and export helpers for long-form research artifacts.

This layer is narrower than `research_core`: it focuses on preserving evidence
graphs, exports, and stored research outputs once a deep research task has
produced them.

## Key Files

- `service.py`
  - top-level service orchestration for persisted research artifacts
- `store.py`
  - storage and retrieval for research outputs
- `exports.py`
  - export helpers for research bundles
- `evidence_graph.py`
  - graph-oriented evidence relationships

## Use This Layer When

- a research task needs durable artifacts after browsing is complete
- you want to add new export formats for deep research results
- you are debugging how research outputs are stored or recalled later

## Related Layers

- [`workshop/toolbox/stacks/research_core/README.md`](/C:/somex/workshop/toolbox/stacks/research_core/README.md)
- [`executive/synthesis/README.md`](/C:/somex/executive/synthesis/README.md)
