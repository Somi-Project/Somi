# browser

Local browser session helpers used when Somi needs persistent browser runtime
state outside of a one-shot page fetch.

## Key Files

- `runtime.py`
  - browser runtime orchestration and lifecycle helpers
- `store.py`
  - persisted browser state and session bookkeeping

## Use This Layer When

- a task needs browser continuity across more than one action
- you are debugging browser session persistence or cleanup
- you want to understand where browser-runtime state is stored versus where
  page-reading logic lives

## Related Layers

- [`workshop/toolbox/stacks/web_core/README.md`](/C:/somex/workshop/toolbox/stacks/web_core/README.md)
- [`workshop/toolbox/stacks/research_core/README.md`](/C:/somex/workshop/toolbox/stacks/research_core/README.md)
