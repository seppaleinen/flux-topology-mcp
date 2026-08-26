---
name: flux-topology
description: Navigate and reason about FluxCD GitOps repository topology — discover apps, trace dependencies, find blast radius, and search cross-references.
---

# flux-topology

An MCP server that builds a dependency and topology graph of a FluxCD GitOps repository by static analysis.

## When to use

- Debugging or exploring a FluxCD/Kubernetes GitOps repo
- Understanding blast radius before deleting or modifying an app
- Finding all references to a shared resource (Helm chart, image, config)
- Onboarding to an unfamiliar Flux repository
- Reviewing topology changes in a PR

## Prerequisites

The `flux-topology` MCP server must be installed and configured. See the [README](../../README.md) for setup instructions.

## How it works

The server analyzes YAML files under `flux/` in the working directory. The topology cache (`.fluxtop/`) rebuilds automatically on every query — no manual refresh needed.

## Tools

### Start here: `fluxtop_map`

Always call this first. Returns an overview of all domains, apps, edge counts, and warnings.

### Drill down: `fluxtop_app_card`

Get the full card for one app: workloads, services, ingress hosts, edges in both directions, and warnings.

### Blast radius: `fluxtop_trace`

BFS trace from any app with typed edges. Use before deleting or modifying an app.

- `direction="out"` — what this app depends on
- `direction="in"` — what depends on this app
- `direction="both"` — full blast radius
- `depth` — max hops (default 5)

### Find references: `fluxtop_find_refs`

Regex search across all apps. Use when renaming or removing shared resources (charts, images, configs).

### Health check: `fluxtop_check_freshness`

Check if the cache is up to date. Normally not needed — cache rebuilds automatically.

## Typical workflow

```
1. fluxtop_map          → see the landscape
2. fluxtop_app_card     → inspect a specific app
3. fluxtop_trace        → understand dependencies before changes
4. fluxtop_find_refs    → find all consumers of a shared resource
```

## Cache

The cache lives in `.fluxtop/` and is gitignored. It rebuilds automatically when YAML files change — agents never need to trigger a rebuild manually.
