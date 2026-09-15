# flux-topology

[![skills.sh](https://skills.sh/b/seppaleinen/flux-topology-mcp)](https://skills.sh/seppaleinen/flux-topology-mcp)

A CLI + agent skill that builds a dependency and topology graph of a
Kubernetes/FluxCD GitOps repository by static analysis, so AI agents can
reason about service relationships without cluster access.

## Install

```bash
pip install flux-topology
```

Optional — install the agent skill from
[skills.sh](https://skills.sh/seppaleinen/flux-topology-mcp):

```bash
npx skills add seppaleinen/flux-topology-mcp
```

No MCP server is required. Run the CLI from your GitOps repo root; it reads
from `flux/` in the working directory.

## Subcommands

| Command | Description |
|---------|-------------|
| `build [dir] [--force]` | Build the topology cache (`.fluxtop/`) |
| `map [dir] [--json]` | Top-level view: domains, hub apps by edge count, warnings |
| `trace <app> [dir] [--direction out\|in\|both] [--depth N] [--json]` | BFS blast radius from any app with typed edges |
| `find-refs <pattern> [dir] [--json]` | Regex search for references across all apps |
| `app-card <app> [dir] [--json]` | Full card for one app: workloads, services, edges |
| `check-freshness [dir] [--json]` | Check if the topology cache is up to date (never rebuilds) |

`[dir]` defaults to `.`. A directory is resolved to its `flux/` subdirectory
when present; otherwise the directory itself is treated as the flux root.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Found / fresh |
| `1` | Stale, corrupt, not-found, or invalid input |
| `2` | Usage error (argparse) |
| `3` | No cache (`check-freshness` only) |

## CLI examples

```bash
# Build the topology cache (.fluxtop/)
flux-topology build

# Rebuild even when the cache is fresh
flux-topology build --force

# Human-readable overview
flux-topology map

# Machine-readable output
flux-topology map --json

# Blast radius: what depends on this app? (depth 5)
flux-topology trace apps/backend --direction in

# Find every app referencing a shared resource
flux-topology find-refs "postgres-rw\.postgres\.svc\."

# Full card for one app
flux-topology app-card apps/radarr

# Freshness check (exit codes 0/1/3)
flux-topology check-freshness
```

## How it works

1. **Discovers** apps by walking `flux/` and finding ownership signals
   (HelmReleases, Kustomizations, Deployments, Services)
2. **Extracts** workloads, services, ingress hosts, and refs per app
3. **Resolves** edges between apps from cross-references
4. **Caches** everything in `.fluxtop/` — rebuilt only when source files change

### Hybrid freshness

The cache is checked against a fingerprint of all YAML files on every query:

- **No cache** — `map`/`trace`/`find-refs`/`app-card` auto-build once and then
  answer normally. `check-freshness` instead reports `NO CACHE` (exit 3) and
  never rebuilds.
- **Fresh** — the cache matches the working tree; queries answer from it.
- **Stale / corrupt** — queries surface a notice and exit 1 *without*
  rebuilding, so results are never silently outdated. Rebuild explicitly with
  `flux-topology build --force`, or just `build` (which also rebuilds when the
  fingerprint no longer matches).

## Deployment note (dotfiles env)

The always-on `flux-topology` MCP server was removed from the shared MCP list
in the user's dotfiles environment (Stow-managed). The tool is now used
on-demand via the CLI + skill. Re-push the rewritten skill via `skills.sh`.

## Development

```bash
git clone https://github.com/seppaleinen/flux-topology-mcp.git
cd flux-topology-mcp
pip install -e ".[dev]"
pytest
```

## License

MIT
