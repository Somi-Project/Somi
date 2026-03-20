# Plugin Federation

Somi can adapt external `SKILL.md` ecosystems without inheriting their trust
model.

## Flow

1. Preview the bundle with `skills_local.federation.dry_run_import_skill()`
2. Review origin and policy with `skills_local.adapters.review_skill_bundle()`
3. Register the descriptor in `skills_local/registry/`
4. Promote the trust tier only after review with
   `skills_local.adapters.approve_imported_plugin()`

## Trust Tiers

- `native`: shipped and maintained by Somi
- `adapted_reviewed`: imported and explicitly reviewed
- `adapted_experimental`: imported but still review-gated
- `disabled`: stored for reference only

## Guardrails

- imported bundles do not silently gain execution rights
- tool hints are inferred into approval expectations
- `system_change`, `external_message`, `financial`, and `destructive`
  implications should still route through Somi's action-policy layer

## Compatibility

The current adapter path supports:

- generic markdown `SKILL.md` bundles
- frontmatter-heavy Codex-style skill bundles
- best-effort origin tagging for bundle paths that clearly reference Hermes,
  OpenClaw, or DeerFlow ecosystems
