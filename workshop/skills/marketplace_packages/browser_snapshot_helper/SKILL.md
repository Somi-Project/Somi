---
name: Browser Snapshot Helper
description: Guide Somi through safe browser snapshots, evidence capture, and page-state verification.
metadata: {"runtime":{"skillKey":"browser_snapshot_helper","requires":{"bins":["python"]},"homepage":"https://somi.local/skills/browser_snapshot_helper"}}
---
Use this skill when the operator needs grounded browser captures without pushing into risky active automation.

Preferred pattern:
- inspect page state first
- capture screenshots only when they add value
- summarize what changed before proposing a click or form action
- keep the operator informed about safety boundaries
