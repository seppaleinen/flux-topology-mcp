---
name: flux-topology
description: Navigate and reason about FluxCD GitOps repository topology — discover apps, trace dependencies, find blast radius, and search cross-references.
---

# flux-topology

A CLI + skill that builds a dependency and topology graph of a FluxCD GitOps repository by static analysis.

## When to use

- Debugging or exploring a FluxCD/Kubernetes GitOps repo
- Understanding blast radius before deleting or modifying an app
- Finding all references to a shared resource (Helm chart, image, config)
- Onboarding to an unfamiliar Flux repository
- Reviewing topology changes in a PR

## Prerequisites

```bash
pip install flux-topology
npx skills add seppaleinen/flux-topology-mcp   # this skill
```

No MCP server is required — `flux-topology` is a plain CLI.

## READ FIRST (no binary needed)

Prefer the cache files directly — they are greppable and cheap:

1. **`.fluxtop/apps/*.md`** — one human-readable markdown card per App
   (workloads, services, ingress hosts, depends-on/referenced-by, warnings).
   Grep or open these for per-app detail.
2. **`.fluxtop/wiring.json`** — the machine-readable graph. Use targeted
   `jq` queries (e.g. `jq '.apps[].id' .fluxtop/wiring.json`) as needed.
   **NEVER dump the whole file** — it is large and expensive.

## Computed queries (binary)

Use the CLI only for queries that need computation over the whole graph:

| Command | Purpose |
|---|---|
| `flux-topology map` | Overview: domains, hub apps by edge count, warnings |
| `flux-topology trace <app>` | BFS blast radius with typed edges |
| `flux-topology find-refs <pattern>` | Regex search for references across all apps |
| `flux-topology app-card <app>` | Full card for one app |
| `flux-topology check-freshness` | Check if the cache is fresh/stale/absent (never rebuilds) |

Trace options: `--direction out|in|both` (default `out`) and `--depth N`
(default 5). All commands accept `[dir]` (default `.`) and `--json` for
machine-readable output.

## Build on change

```bash
flux-topology build [dir] [--force]
```

Run `build` when the repo was moved, after YAML changes, or when a STALE
notice appears. Query commands auto-build only when there is **no** cache at
all; a **STALE** cache is surfaced as a notice with exit code 1 — rebuild
before trusting the results.

## Exit codes

- `0` — fresh / found
- `1` — stale, not-found, or invalid input
- `2` — usage error (argparse)
- `3` — no cache (`check-freshness` only)

## Typical workflow

1. `flux-topology map` → see the landscape
2. `flux-topology app-card <app>` → inspect a specific app
3. `flux-topology trace <app>` → understand dependencies before changes
4. `flux-topology find-refs <pattern>` → find all consumers of a shared resource