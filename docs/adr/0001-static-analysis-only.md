# ADR 0001: Static repository analysis only (no live cluster queries)

**Status:** Accepted
**Date:** 2026-08-26

## Context

The flux-topology server builds dependency/topology graphs for a FluxCD GitOps
repo (`fleet-infra`). Three sources of truth were considered:

1. **Static** — parse the Git checkout (YAML, HelmRelease values, kustomizations)
2. **Live** — query the Kubernetes API / Flux controllers for actual state
3. **Hybrid** — static core, live reconciliation as an overlay

## Decision

V1 is a pure static analyzer over the Git working tree. The server holds no
cluster connectivity, no kubeconfig, no Flux API access.

## Rationale

- The repo is a disciplined GitOps source; Git *is* the intended state.
- Deterministic, fast, offline-capable, trivially testable — the right shape for
  an MCP tool consumed by coding agents mid-edit (pre-commit, pre-reconcile).
- Mirrors Graft's model: analyze source, not runtime.
- Avoids auth/kubeconfig/network complexity in the critical path.

## Consequences

- Drift between Git and cluster is invisible (deferred to a possible future
  reconciliation tool).
- Connection strings inside SOPS-encrypted Secrets are unreadable without
  decryption; implicit edges hidden in encrypted blobs are missed.
- Remote charts' templates are not rendered; edges from those apps come from
  Flux values only, not from chart internals.
