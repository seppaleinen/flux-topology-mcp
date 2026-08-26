# ADR 0002: Build-once graph cached in the target repository (Graft model)

**Status:** Accepted
**Date:** 2026-08-26

## Context

The topology graph can be computed either on every tool call (stateless
server, always fresh) or built once and persisted for queries. Graft (the
code-intelligence precedent this project mirrors) builds once into a folder
inside the analyzed repo and treats it as a regenerable local cache.

## Decision

Mirroring Graft:

- `flux-topology build [dir]` parses the GitOps repo once and writes a
  `.fluxtop/` folder into the *target* repo: one human-readable markdown card
  per App plus a machine-readable `wiring.json` (typed Apps, edges, warnings).
- `.fluxtop/` is added to the target repo's `.gitignore` — it is a local,
  regenerable cache, never committed.
- Query tools read `.fluxtop/`, not raw YAML. Each retrieval stats a build
  fingerprint; if the working tree moved since the last build, a structural
  re-sync happens transparently before answering (no LLM, near-zero cost).
- V1 ships five query tools (`map`, `trace`, `find_refs`, `app_card`,
  `check_freshness`) over stdio MCP. No `init` wizard, no post-edit hooks yet.

## Rationale

- Agents can grep/open App cards like any repo file even without MCP calls —
  the graph doubles as documentation.
- Build-once + fingerprint refresh gives Graft's freshness guarantee without a
  daemon or rescan-per-call overhead.
- Writing the cache into the target repo keeps multi-repo usage natural and
  matches the mental model users already know from Graft.

## Consequences

- The server mutates the analyzed repo's directory tree (one ignored folder +
  possibly one .gitignore line); acceptable trade-off for cache semantics.
- Staleness between builds is hidden by auto-refresh, but a corrupted or
  deleted `.fluxtop/` requires an explicit rebuild (tools say so clearly).
