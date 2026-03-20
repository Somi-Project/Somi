# web_core

The lightweight web-search entry layer.

`web_core` owns the first-pass decision about whether a request should use a
specialized handler, general web search, or the deeper research pipeline.

## Key Files

- `websearch.py`
  - main web/search handler and routing entry point
- `search_bundle.py`
  - normalized search result bundle types used downstream
- `websearch_tools/`
  - provider and vertical helpers such as weather, news, finance, general
    search, and query formatting

## When To Read This First

- you are debugging why a query did or did not browse
- you want to improve vertical routing or quick-answer behavior
- you are tracing search output before deep research composition takes over

## Important Note

Weather, news, and finance are intentionally more fragile-specialized routes.
Treat them carefully and avoid broad refactors unless a specific bug demands it.

## Related Layers

- [`workshop/toolbox/stacks/research_core/README.md`](/C:/somex/workshop/toolbox/stacks/research_core/README.md)
- [`websearch.py`](/C:/somex/websearch.py)
