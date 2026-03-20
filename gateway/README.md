# gateway

Channel and node control-plane helpers.

This package is where Somi tracks sessions, delivery surfaces, connected nodes,
and message-facing runtime state.

## Key Files

- `service.py`
  - high-level gateway service and snapshot view
- `manager.py`
  - channel management and orchestration helpers
- `channels.py`
  - channel-specific normalization and routing support
- `auth.py`
  - pairing/authentication helpers
- `store.py`
  - persisted gateway state
- `models.py`
  - typed records for sessions, nodes, and channel state
- `surface_policy.py`
  - distribution-sovereignty adapter contract for optional edge-policy handling
- `federation.py`
  - store-and-forward task and knowledge envelopes for future Somi node sync

## Read This Package When

- you are debugging Telegram or other delivery-surface behavior
- you want to understand node/session tracking
- you are tracing how Somi bridges runtime work back to a channel
- you need to keep store or platform policy isolated from the self-hosted core
