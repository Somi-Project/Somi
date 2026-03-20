# Distribution Sovereignty

Somi's core should remain self-hosted, local-first, and app-store-independent.

This means:
- the core runtime does not require centralized identity by default
- client-edge policy handling belongs in a thin adapter layer, not in the core
  cognition or memory system
- platform distribution pressure must not weaken Somi's reasoning or local
  ownership model

Implementation notes:
- `gateway/surface_policy.py` defines the optional surface-policy contract
- direct-download, portable, LAN, and self-hosted paths remain sovereign-core
  surfaces
- app-store or managed-mobile surfaces can attach an edge adapter without
  changing the behavior of the self-hosted core
- financial and destructive actions still remain human-approved regardless of
  surface policy

The intent is not to evade platform rules. The intent is to preserve user-owned
core behavior while keeping any unavoidable compatibility handling disposable
and isolated.
