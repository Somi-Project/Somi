# Skills.MD to Tool Scaffold Specification (Future)

Status: Draft specification (not yet implemented)
Owner: `workshop/toolbox`
Scope: Convert a standards-compliant `SKILL.md` (or `skills.md`) into a runnable tool scaffold under `workshop/tools/workspace/`.

## 1) Goal

Define a deterministic, reviewable conversion path from skill definitions to tool packages so external LLMs with tool-calling (for example Qwen-class models) can invoke Somi capabilities through a stable registry.

This spec does not enable autonomous self-coding. It defines the contract for a future codegen pipeline.

## 2) Inputs

Required input file:`r`n- `SKILL.md` or `skills.md` (case-insensitive loader in future implementation)

Optional adjacent inputs:
- `manifest.json` (skill-local metadata)
- `scripts/*` (operational helpers)
- `templates/*` (prompt or output templates)
- `references/*` (docs used by the skill)

## 3) Minimum SKILL.md Contract

A skill is eligible for conversion only if these fields can be resolved:
- `name`: human-readable skill name
- `description`: concise capability summary
- `entrypoint`: command/tool action to execute
- `arguments`: explicit args schema (name, type, required, default)
- `safety`: read-only vs mutating behavior, risk notes
- `examples`: at least one invocation example

Recommended optional fields:
- `aliases`
- `tags`
- `dependencies`
- `timeouts`
- `output_contract`

## 4) Conversion Outputs

For a skill `X`, scaffold target:
- `workshop/tools/workspace/<tool_slug>/`

Generated files:
- `manifest.json`
- `tool.py`
- `README.md`
- `test_tool.py` (basic contract tests)

### 4.1 `manifest.json` mapping
- `name`: normalized tool slug
- `version`: starts at `0.1.0`
- `description`: from skill description
- `aliases`: from skill aliases + normalized name alias
- `tags`: from skill tags
- `examples`: from skill examples
- `input_schema`: from skill argument spec
- `policy`:
  - `read_only`: from skill safety
  - `risk_tier`: inferred (`LOW|MEDIUM|HIGH`)
  - `requires_approval`: true for mutating or high-risk actions

### 4.2 `tool.py` contract
Generated entrypoint must match:
- `run(args: dict, ctx: dict) -> dict`

Rules:
- Validate required args strictly.
- Return structured result (`ok`, `error`, payload fields).
- Never execute destructive operations without policy gating.
- No hidden network/system side effects.

### 4.3 `README.md` contract
Must include:
- purpose
- supported args
- sample invocations
- policy/risk notes

## 5) Validation Pipeline (Future)

1. Parse skill metadata and argument schema.
2. Build scaffold files.
3. Run static checks (`run(args, ctx)` signature, schema consistency).
4. Run unit smoke test (`test_tool.py`).
5. Stage in workspace.
6. Optional install to `workshop/tools/installed/<name>/<version>/`.
7. Register via `sync-tools`.

## 6) Registry and Routing Integration

- Tool visibility source: `workshop/tools/registry.json`.
- Install/register path must preserve file hashes.
- Runtime routing uses registry metadata + policy fields.
- Model prompt context should expose:
  - tool registry snapshot
  - route reason
  - execution report (success/failure)

## 7) Safety and Governance Requirements

- Generated tool policy defaults to conservative values.
- Mutating tools must require approval by default.
- Command allowlists and protected paths remain enforced by runtime policy layers.
- Conversion output is proposal-first; execution remains explicitly gated.

## 8) Migration-Kit Relationship

This spec defines skill-to-tool generation.
`MIGRATION_KIT.md` covers import/adaptation of existing external tool folders.

Future flow can combine both:
- `SKILL.md` conversion for new tools
- migration kit for prebuilt tools
- common validation + registry registration path

## 9) Non-Goals (Current Phase)

- autonomous code repair
- automatic dependency healing
- automatic semantic equivalence proofs
- unsupervised production installs

## 10) Acceptance Criteria for Implementation

A future implementation is complete when:
- a compliant `SKILL.md` produces valid scaffold files,
- generated tool passes signature/schema checks,
- tool can be registered and discovered,
- internal runtime can invoke it safely with policy enforcement,
- failure cases return deterministic validation errors.

