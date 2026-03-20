# toolbox stacks

Capability stacks grouped by problem domain.

These are the layers most contributors eventually need to read when they want
to change how Somi searches, reads, composes, extracts, or contracts data.

## Main Stack Families

- `web_core/`
  - general web search routing, snippet collection, special-case handlers, and
    search bundles
- `research_core/`
  - browse planning, evidence extraction, deep reading, adequacy checks,
    GitHub local analysis, and research composition
- `ocr_core/`
  - OCR pipelines and extraction helpers
- `image_core/`
  - image tooling and rendering helpers
- `contracts_core/`
  - typed artifact/contract helpers used across stacks

## How The Search Path Usually Flows

1. `agent_core` or runtime routing decides the task needs web/research help.
2. `web_core` handles intent routing and lightweight/specialized search paths.
3. `research_core` takes over for deeper browse/read/evidence loops.
4. `executive/synthesis` or the GUI surfaces the final answer/report.

## Best Entry Points

- Search behavior:
  - [`web_core/README.md`](/C:/somex/workshop/toolbox/stacks/web_core/README.md)
- Deep research behavior:
  - [`research_core/README.md`](/C:/somex/workshop/toolbox/stacks/research_core/README.md)
- Contract and artifact primitives:
  - read the package modules under `contracts_core/`

## Related Maps

- [`workshop/toolbox/README.md`](/C:/somex/workshop/toolbox/README.md)
- [`docs/architecture/CONTRIBUTOR_MAP.md`](/C:/somex/docs/architecture/CONTRIBUTOR_MAP.md)
