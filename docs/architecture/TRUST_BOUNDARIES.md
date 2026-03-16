# Trust Boundaries

This document explains the intended blast radius of Somi's default framework posture before packaging.

## Local Trusted Surfaces

- `gui`
- `desktop`
- `control_room`
- `coding_studio`

Default posture:

- trusted local surfaces may observe, prompt, and control the framework
- execution is still mediated by runtime policy, approvals, and tool contracts
- local execution should not be silently widened to system-wide mutation

## Service Surfaces

- `telegram`
- `heartbeat`
- `automation`
- `workflow`

Default posture:

- service surfaces are trusted for delivery and orchestration
- they should not bypass approval gates for mutating tools
- scheduled execution must stay inside the tool registry and runtime policy envelope

## Remote Surfaces

- future web clients
- paired devices
- remote observer nodes

Default posture:

- unpaired remote sessions are pair-only
- paired remote sessions may observe, prompt, and receive delivery
- remote sessions must not cross the execution boundary by default

## Execution Boundary

Actions treated as execution-boundary crossings:

- `execute`
- `install`
- `system`
- bulk external mutation

Rules:

- untrusted or remote-safe contexts must not cross this boundary
- mutating tools should require approval unless explicitly designed otherwise
- high-risk automation exposure should be treated as a release blocker

## Storage Boundary

Critical persistence surfaces:

- `database/`
- `sessions/`
- `backups/`
- `workshop/tools/registry.json`
- `docs/architecture/`

Rules:

- verify backups before major edits or release preparation
- treat missing backup verification as a high-severity operational issue
- preserve wrapper compatibility files during refactors

## Secret Boundary

Secrets that should be configured before enterprise release:

- `AUDIT_HMAC_SECRET` or `SOMI_AUDIT_SECRET`
- `SOMI_APPROVAL_SECRET`
- integration credentials such as Telegram tokens

Rules:

- default fallbacks are acceptable for local development only
- release candidates should use explicit secrets so audits and approvals are durable
