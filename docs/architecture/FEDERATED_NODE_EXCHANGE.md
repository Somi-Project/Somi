# Federated Node Exchange

Somi's federated node exchange is a store-and-forward layer for degraded or
intermittent networking.

## Purpose

- move task bundles between Somi nodes
- share local knowledge deltas and recovery notes
- keep the exchange durable enough for manual transport or delayed sync

## Current Shape

- envelopes are stored as JSON under `state/node_exchange/`
- directions:
  - `inbox`
  - `outbox`
  - `archive`
- each envelope carries:
  - `node_id`
  - `lane`
  - `subject`
  - `body`
  - `capabilities`
  - `artifacts`
  - status and timestamps

## Why File-Based First

- survives intermittent or absent networking
- easy to audit and replicate
- easy to sync over LAN, removable media, or a future transport adapter

## Near-Term Use

- continuity-task handoff
- research or field-note synchronization
- local gateway visibility into pending node work

## Long-Term Direction

This layer is transport-neutral on purpose. Future adapters can move the same
envelopes over LAN sync, Matrix, A2A-style brokers, or delay-tolerant links
without changing the core payload contract.
