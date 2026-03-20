# Contributor Map

This is the shortest useful route through Somi for a new contributor.

Use it when you want to answer one question fast:
"Where does this capability live, and where should I start reading?"

## If You Are A Basic User Trying To Understand The Product

Read these first:

1. [`README.md`](/C:/somex/README.md)
2. [`docs/architecture/SYSTEM_MAP.md`](/C:/somex/docs/architecture/SYSTEM_MAP.md)
3. [`gui/README.md`](/C:/somex/gui/README.md)
4. [`runtime/README.md`](/C:/somex/runtime/README.md)

That path gives you the product posture, the architecture spine, the desktop
shell, and the runtime safety layer.

## If You Are A Developer Trying To Modify Somi

Read these first:

1. [`somi.py`](/C:/somex/somi.py)
2. [`somicontroller.py`](/C:/somex/somicontroller.py)
3. [`somicontroller_parts/README.md`](/C:/somex/somicontroller_parts/README.md)
4. [`workshop/toolbox/README.md`](/C:/somex/workshop/toolbox/README.md)
5. [`workshop/toolbox/stacks/README.md`](/C:/somex/workshop/toolbox/stacks/README.md)

That path shows the CLI/control surface, the desktop shell entry point, the
split GUI controller helpers, the tool runtime, and the capability stacks.

## Capability Map

### Search And Research

- quick/specialized search entry:
  - [`workshop/toolbox/stacks/web_core/README.md`](/C:/somex/workshop/toolbox/stacks/web_core/README.md)
- deep research engine:
  - [`workshop/toolbox/stacks/research_core/README.md`](/C:/somex/workshop/toolbox/stacks/research_core/README.md)
- answer shaping:
  - [`executive/synthesis/README.md`](/C:/somex/executive/synthesis/README.md)

### GUI And Shell

- shell entry:
  - [`somicontroller.py`](/C:/somex/somicontroller.py)
- split controller helpers:
  - [`somicontroller_parts/README.md`](/C:/somex/somicontroller_parts/README.md)
- panel implementations:
  - [`gui/README.md`](/C:/somex/gui/README.md)

### Coding

- coding control plane:
  - [`workshop/toolbox/coding/README.md`](/C:/somex/workshop/toolbox/coding/README.md)
- coding studio surface:
  - [`gui/codingstudio.py`](/C:/somex/gui/codingstudio.py)

### Runtime, Safety, And Ops

- runtime policy/audit helpers:
  - [`runtime/README.md`](/C:/somex/runtime/README.md)
- ops/doctor/release tools:
  - [`somi.py`](/C:/somex/somi.py)
  - [`ops/README.md`](/C:/somex/ops/README.md)
- channel and node control plane:
  - [`gateway/README.md`](/C:/somex/gateway/README.md)
- bounded workflow execution:
  - [`workflow_runtime/README.md`](/C:/somex/workflow_runtime/README.md)

## Most Common "Where Is X?" Questions

- "Why did Somi browse?"
  - start in [`workshop/toolbox/stacks/web_core/websearch.py`](/C:/somex/workshop/toolbox/stacks/web_core/websearch.py)
- "Why did it keep researching?"
  - start in [`workshop/toolbox/stacks/research_core/answer_adequacy.py`](/C:/somex/workshop/toolbox/stacks/research_core/answer_adequacy.py)
- "How did the GUI get this status card?"
  - start in [`somicontroller_parts/status_methods.py`](/C:/somex/somicontroller_parts/status_methods.py)
- "How does Coding Studio do this?"
  - start in [`workshop/toolbox/coding/control_plane.py`](/C:/somex/workshop/toolbox/coding/control_plane.py)
- "Where are the release and gauntlet commands?"
  - start in [`somi.py`](/C:/somex/somi.py)

## Safe Contributor Workflow

1. Create a phase backup with `somi backup create`.
2. Read the nearest folder `README.md`.
3. Read the test file that covers the area you are touching.
4. Make the smallest coherent change.
5. Run the focused tests before broad validation.

For a shorter operational checklist, read
[`NEWCOMER_CHECKLIST.md`](/C:/somex/docs/architecture/NEWCOMER_CHECKLIST.md).

## Good First Places To Add Tests

- [`tests/README.md`](/C:/somex/tests/README.md)
  - phased runtime and platform regressions
- root `test_*.py`
  - GUI and shell integration coverage
- `executive/memory/tests/`
  - memory-specific checks
