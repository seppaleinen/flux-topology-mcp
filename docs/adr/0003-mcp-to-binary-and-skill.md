# ADR 0003: Drop the always-on MCP server — binary + on-demand skill primary

**Status:** Accepted
**Date:** 2026-09-07

## Context

The tool shipped as an always-on MCP server (`flux-topology mcp` over stdio)
with 5 tools (`fluxtop_map`, `fluxtop_trace`, `fluxtop_find_refs`,
`fluxtop_app_card`, `fluxtop_check_freshness`). That model has a standing cost:

- **Token tax:** an always-on MCP server injects its tool schema into every
  agent turn (~550–650 tokens/turn/agent), even when topology is irrelevant
  to the task.
- **Coupling:** `src/flux_topology/server.py` was the only MCP-coupled file
  (FastMCP import + `@mcp.tool()` decorators); everything else is pure
  analysis or cache IO.
- **Cache is already disk-first** (ADR 0002): the `.fluxtop/` folder with
  greppable per-App markdown cards plus `wiring.json` means agents can answer
  most questions by reading files, without any MCP call at all.

## Decision

- **Delete MCP entirely:** remove `server.py`, the `mcp>=1.2.0` dependency,
  and the `flux-topology mcp` subcommand; update package metadata (keywords,
  description) to drop MCP framing.
- **Binary becomes primary.** The CLI gains 5 query subcommands
  (`map`, `trace`, `find-refs`, `app-card`, `check-freshness`) in a new
  `query.py` module plus the existing `build`, all returning stable exit codes
  (`0` found/fresh, `1` stale/not-found/invalid, `2` usage error, `3` no cache)
  with human-markdown default output and `--json` for machine consumers.
- **Hybrid freshness:** query commands auto-build **only** when there is no
  cache (`NO_CACHE`); a **STALE** or **CORRUPT** cache surfaces a notice and
  exits 1 instead of rebuilding silently. `build --force` is the explicit
  rebuild path. `check-freshness` never auto-builds.
- **Skill rewritten** to be cards-first (read `.fluxtop/apps/*.md` and
  targeted `jq` on `wiring.json`, never a full dump) with the binary reserved
  for computed queries.
- **Install stays two-step** (`pip install flux-topology` +
  `npx skills add seppaleinen/flux-topology-mcp`); this is a one-off scope for
  this tool, not a platform statement against MCP generally.

## Rationale

- With no MCP server registered, no tool schema is injected by default — the
  token tax disappears for every turn, not just topology-relevant ones.
- The CLI is deterministic and scriptable: exit codes + `--json` give agents
  and shell pipelines a stable contract instead of MCP tool-call strings.
- The skill becomes on-demand: agents opt in by reading the skill card, so the
  cost is proportional to use.
- Cards-first reading (`grep`/`open` on `.fluxtop/apps/`) is cheaper than any
  tool call and matches how agents already work with repo files.

## Consequences

- Agents must remember to run `flux-topology build` (or rely on the NO_CACHE
  auto-build) before querying; there is no zero-config server anymore.
- A stale cache persists until an explicit rebuild — queries refuse to answer
  silently from outdated data (exit 1 + notice) instead of auto-refreshing.
- Existing 5 analysis/test modules (discovery, extract, edges, cards, models,
  yamlsafe) are untouched; the API surface they tested is unchanged.
- Deployment: remove `flux-topology` from the shared MCP server list in the
  user's dotfiles environment (Stow) and re-push the rewritten skill via
  `skills.sh`.