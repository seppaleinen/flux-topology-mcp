"""Query layer: freshness gate + the 5 topology query functions.

Each query_* function prints its result (human markdown or --json) and returns
an exit code: 0 = found/fresh, 1 = not-found/stale/corrupt, 3 = no-cache
(check-freshness only). Human mode reuses the output strings formerly emitted
by the MCP server tools (server.py), so agent-facing output is unchanged.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal, cast

from .cache import (
    compute_fingerprint,
    freshness_state,
    read_cached_fingerprint,
    read_wiring_graph,
    write_cache,
)
from .discovery import discover_apps
from .extract import extract_app_data
from .edges import resolve_edges, build_wiring_graph
from .models import WiringGraph

FreshnessState = Literal["NO_CACHE", "STALE", "FRESH", "CORRUPT"]

# Human notices for STALE/CORRUPT when a query command hits a non-fresh cache.
_STALE_NOTICE = (
    "⚠ Cache is STALE (fingerprint no longer matches). Data may be outdated.\n"
    "Run `flux-topology build [dir] --force` to rebuild before trusting these results."
)
_CORRUPT_NOTICE = (
    "⚠ Cache is CORRUPT (fingerprint no longer matches). Data may be outdated.\n"
    "Run `flux-topology build [dir] --force` to rebuild before trusting these results."
)

_JSON_STATUS = {
    "NO_CACHE": "no-cache",
    "STALE": "stale",
    "FRESH": "fresh",
    "CORRUPT": "corrupt",
}


def resolve_flux_root(dir_arg: str | Path) -> Path:
    """Resolve a directory argument to the analysis root.

    Prefer ``<dir>/flux`` when that directory exists (matching the old
    ``_get_flux_root`` convention); otherwise use the resolved path itself as
    the flux root.
    """
    root = Path(dir_arg).resolve()
    flux_dir = root / "flux"
    if flux_dir.is_dir():
        return flux_dir
    return root


def build_topology(flux_root: Path, *, progress: bool = False) -> WiringGraph:
    """Build the wiring graph for flux_root.

    Mirrors the former server._build_cache / cmd_build body:
    discover_apps -> extract_app_data per app -> resolve_edges ->
    compute_fingerprint -> build_wiring_graph -> write_cache.
    Returns the graph.

    ``progress=True`` prints the two intermediate progress lines to stdout
    (used by the CLI ``build`` subcommand). Default stays False so the
    NO_CACHE auto-build path in _graph_or_exit stays silent — that path must
    not pollute stdout when a query runs with --json.
    """
    if not flux_root.is_dir():
        raise FileNotFoundError(f"flux/ directory not found at {flux_root}")

    apps = discover_apps(flux_root)
    if progress:
        print(f"  Discovered {len(apps)} apps")
    for app in apps:
        extract_app_data(app, flux_root)

    edges, warnings = resolve_edges(apps, flux_root)
    if progress:
        print(f"  Resolved {len(edges)} edges, {len(warnings)} warnings")
    fingerprint = compute_fingerprint(flux_root)
    graph = build_wiring_graph(apps, edges, warnings, flux_root, fingerprint)
    write_cache(flux_root, apps, edges, warnings, graph)
    return graph


def ensure_ready(flux_root: Path) -> tuple[FreshnessState, WiringGraph | None]:
    """Triage gate over cache freshness.

    NO_CACHE -> graph None (query cmds auto-build then re-run);
    STALE/CORRUPT -> graph None (query cmds surface notice, exit 1);
    FRESH -> graph loaded from cache.
    """
    state = cast(FreshnessState, freshness_state(flux_root))
    if state == "FRESH":
        return state, read_wiring_graph(flux_root)
    return state, None


def _check_root(flux_root: Path, json_out: bool) -> int | None:
    """Return exit code 1 if flux_root is not a directory, else None."""
    if flux_root.is_dir():
        return None
    if json_out:
        print(json.dumps({"error": "invalid-directory", "path": str(flux_root)}))
    else:
        print(f"Error: flux/ directory not found in {flux_root}", file=sys.stderr)
    return 1


def _graph_or_exit(flux_root: Path, json_out: bool) -> tuple[int, WiringGraph | None]:
    """Freshness gate shared by map/trace/find-refs/app-card.

    Returns (exit_code, graph). A nonzero exit_code means the caller should
    return immediately; otherwise proceed with the FRESH graph.
    """
    state, graph = ensure_ready(flux_root)

    if state == "NO_CACHE":
        # Auto-build once, then re-check.
        build_topology(flux_root)
        state, graph = ensure_ready(flux_root)

    if state == "STALE":
        if json_out:
            print(json.dumps({"status": "stale"}))
        else:
            print(_STALE_NOTICE)
        return 1, None

    if state == "CORRUPT":
        if json_out:
            print(json.dumps({"status": "corrupt"}))
        else:
            print(_CORRUPT_NOTICE)
        return 1, None

    assert state == "FRESH", f"unexpected freshness state {state!r}"
    return 0, graph


def _not_found(app_id: str, graph: WiringGraph, json_out: bool) -> int:
    """Emit the app-not-found response (human server.py string or --json)."""
    available = [a["id"] for a in graph.apps[:20]]
    if json_out:
        print(json.dumps({"app": app_id, "error": "not-found",
                          "available": available}))
    else:
        print(f"App '{app_id}' not found. Available: {available}")
    return 1


def query_map(flux_root: Path, *, json_out: bool = False) -> int:
    """Map topology: domains, hub apps by edge count, warnings summary."""
    code = _check_root(flux_root, json_out)
    if code is not None:
        return code

    code, graph = _graph_or_exit(flux_root, json_out)
    if code:
        return code
    assert graph is not None

    if json_out:
        payload = {
            "schema_version": graph.schema_version,
            "root": graph.root,
            "built_at": graph.built_at,
            "fingerprint": graph.fingerprint.get("sha256", ""),
            "domains": [
                {"name": d["name"], "app_count": len(d["apps"]), "apps": d["apps"]}
                for d in graph.domains
            ],
            "app_count": len(graph.apps),
            "edge_count": len(graph.edges),
            "hub_apps": _hub_apps(graph),
            "warnings": [
                f"[{w['app']}] {w['kind']}: {w['detail']}" for w in graph.warnings
            ],
        }
        print(json.dumps(payload))
        return 0

    # Human mode: exact server.py fluxtop_map rendering.
    edge_count: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        edge_count[e["from"]] += 1
        edge_count[e["to"]] += 1

    hub_apps = sorted(edge_count.items(), key=lambda x: -x[1])[:10]

    lines = []
    lines.append("# Flux Topology Map")
    lines.append("")
    lines.append(f"**Domains**: {len(graph.domains)}")
    lines.append(f"**Apps**: {len(graph.apps)}")
    lines.append(f"**Edges**: {len(graph.edges)}")
    lines.append(f"**Warnings**: {len(graph.warnings)}")
    lines.append(f"**Built at**: {graph.built_at}")
    lines.append("")

    lines.append("## Domains")
    lines.append("")
    for domain in graph.domains:
        lines.append(f"- **{domain['name']}**: {len(domain['apps'])} apps")
    lines.append("")

    if hub_apps:
        lines.append("## Hub Apps (by edge count)")
        lines.append("")
        for app_id, count in hub_apps:
            lines.append(f"- **{app_id}**: {count} edges")
        lines.append("")

    if graph.warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in graph.warnings[:20]:
            lines.append(f"- [{w['app']}] {w['kind']}: {w['detail']}")
        if len(graph.warnings) > 20:
            lines.append(f"- ... and {len(graph.warnings) - 20} more")
        lines.append("")

    print("\n".join(lines))
    return 0


def _hub_apps(graph: WiringGraph) -> list[dict]:
    """Top 10 hub apps by out_degree, then in_degree, then name."""
    out_deg: dict[str, int] = defaultdict(int)
    in_deg: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        out_deg[e["from"]] += 1
        in_deg[e["to"]] += 1

    app_ids = sorted(
        set(out_deg) | set(in_deg),
        key=lambda a: (-out_deg[a], -in_deg[a], a),
    )[:10]
    return [
        {"app_id": a, "out_degree": out_deg[a], "in_degree": in_deg[a]}
        for a in app_ids
    ]


def query_trace(flux_root: Path, app_id: str, *, direction: str = "out",
                depth: int = 5, json_out: bool = False) -> int:
    """BFS trace from an app: blast radius with typed edges.

    direction: 'out' = what this app depends on, 'in' = what depends on this
    app, 'both' = both. depth: max BFS depth.
    """
    code = _check_root(flux_root, json_out)
    if code is not None:
        return code

    code, graph = _graph_or_exit(flux_root, json_out)
    if code:
        return code
    assert graph is not None

    app = next((a for a in graph.apps if a["id"] == app_id), None)
    if app is None:
        return _not_found(app_id, graph, json_out)

    # Build adjacency
    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_edges: dict[str, list[dict]] = defaultdict(list)
    for e in graph.edges:
        out_edges[e["from"]].append(e)
        in_edges[e["to"]].append(e)

    # BFS — same traversal order as the former server.py tool.
    visited: set[str] = set()
    visited_order: list[str] = []
    result_edges: list[dict] = []
    queue: list[tuple[str, int]] = [(app_id, 0)]

    while queue:
        current, current_depth = queue.pop(0)
        if current in visited or current_depth > depth:
            continue
        visited.add(current)
        visited_order.append(current)

        if direction in ("out", "both"):
            for e in out_edges.get(current, []):
                result_edges.append(e)
                if e["to"] not in visited:
                    queue.append((e["to"], current_depth + 1))

        if direction in ("in", "both"):
            for e in in_edges.get(current, []):
                result_edges.append(e)
                if e["from"] not in visited:
                    queue.append((e["from"], current_depth + 1))

    if json_out:
        payload = {
            "app": app_id,
            "direction": direction,
            "depth": depth,
            "visited": visited_order,
            "edges": result_edges,
        }
        print(json.dumps(payload))
        return 0

    # Human mode: exact server.py fluxtop_trace rendering.
    lines = []
    lines.append(f"# Trace: {app_id} (direction={direction}, depth={depth})")
    lines.append("")
    lines.append(f"**Visited**: {len(visited)} apps")
    lines.append(f"**Edges**: {len(result_edges)}")
    lines.append("")

    if result_edges:
        lines.append("## Edges")
        lines.append("")
        for e in result_edges:
            lines.append(f"- **{e['from']}** → **{e['to']}** ({e['type']}) — {e['evidence']}")
        lines.append("")

    if visited:
        lines.append("## Visited Apps")
        lines.append("")
        for v in sorted(visited):
            lines.append(f"- {v}")
        lines.append("")

    print("\n".join(lines))
    return 0


def query_find_refs(flux_root: Path, pattern: str, *, json_out: bool = False) -> int:
    """Search for references matching a regex pattern, grouped by consuming app."""
    code = _check_root(flux_root, json_out)
    if code is not None:
        return code

    code, graph = _graph_or_exit(flux_root, json_out)
    if code:
        return code
    assert graph is not None

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        if json_out:
            print(json.dumps({"pattern": pattern, "error": "invalid-regex"}))
        else:
            print(f"Invalid regex pattern: {e}")
        return 1

    matches: dict[str, list[dict]] = defaultdict(list)
    for app in graph.apps:
        for ref in app.get("refs", []):
            raw = ref.get("raw", "")
            if regex.search(raw):
                matches[app["id"]].append(ref)

    if not matches:
        if json_out:
            print(json.dumps({"pattern": pattern, "total": 0, "apps": {}}))
        else:
            print(f"No references found for pattern '{pattern}'")
        return 1

    if json_out:
        payload = {
            "pattern": pattern,
            "total": sum(len(refs) for refs in matches.values()),
            "apps": {
                app_id: [r.get("raw", "") for r in refs]
                for app_id, refs in sorted(matches.items())
            },
        }
        print(json.dumps(payload))
        return 0

    # Human mode: exact server.py fluxtop_find_refs rendering (found case).
    lines = []
    lines.append(f"# References matching: `{pattern}`")
    lines.append("")

    total = sum(len(refs) for refs in matches.values())
    lines.append(f"**{total} matches** across **{len(matches)} apps**")
    lines.append("")

    for app_id in sorted(matches.keys()):
        refs = matches[app_id]
        lines.append(f"### {app_id}")
        lines.append("")
        for ref in refs:
            resolved = f" → {ref['resolved_to']}" if ref.get("resolved_to") else ""
            file_str = f" (in {ref['file']})" if ref.get("file") else ""
            lines.append(f"- `{ref['raw']}` [{ref['kind']}]{resolved}{file_str}")
        lines.append("")

    print("\n".join(lines))
    return 0


def query_app_card(flux_root: Path, app_id: str, *, json_out: bool = False) -> int:
    """Get the app card: markdown + structured data for one app."""
    code = _check_root(flux_root, json_out)
    if code is not None:
        return code

    code, graph = _graph_or_exit(flux_root, json_out)
    if code:
        return code
    assert graph is not None

    app = next((a for a in graph.apps if a["id"] == app_id), None)
    if app is None:
        return _not_found(app_id, graph, json_out)

    out_edges = [e for e in graph.edges if e["from"] == app_id]
    in_edges = [e for e in graph.edges if e["to"] == app_id]
    app_warnings = [w for w in graph.warnings if w.get("app") == app_id]

    if json_out:
        payload = {
            "app": app,
            "edges_in": in_edges,
            "edges_out": out_edges,
            "warnings": [f"[{w['kind']}] {w['detail']}" for w in app_warnings],
        }
        print(json.dumps(payload))
        return 0

    # Human mode: exact server.py fluxtop_app_card rendering.
    lines = []
    lines.append(f"# App: {app['name']}")
    lines.append("")
    lines.append(f"- **Domain**: {app['domain']}")
    lines.append(f"- **Path**: `{app['path']}`")
    lines.append(f"- **ID**: `{app['id']}`")
    if app.get("signals"):
        lines.append(f"- **Signals**: {', '.join(app['signals'])}")
    lines.append("")

    if app.get("workloads"):
        lines.append("## Workloads")
        lines.append("")
        for w in app["workloads"]:
            replicas_str = f" (×{w['replicas']})" if w.get("replicas") is not None else ""
            lines.append(f"- {w['kind']}: {w['name']}{replicas_str}")
        lines.append("")

    if app.get("services"):
        lines.append("## Services")
        lines.append("")
        for svc in app["services"]:
            ns_str = f" (ns: {svc['namespace']})" if svc.get("namespace") else ""
            lines.append(f"- {svc['name']}{ns_str}")
        lines.append("")

    if app.get("ingress_hosts"):
        lines.append("## Ingress Hosts")
        lines.append("")
        for h in app["ingress_hosts"]:
            lines.append(f"- `{h}`")
        lines.append("")

    if out_edges:
        lines.append("## Depends On")
        lines.append("")
        for e in out_edges:
            lines.append(f"- **{e['to']}** ({e['type']}) — {e['evidence']}")
        lines.append("")

    if in_edges:
        lines.append("## Referenced By")
        lines.append("")
        for e in in_edges:
            lines.append(f"- **{e['from']}** ({e['type']}) — {e['evidence']}")
        lines.append("")

    if app.get("encrypted"):
        lines.append("## Encrypted")
        lines.append("")
        lines.append("Contains SOPS-encrypted secrets")
        lines.append("")

    if app_warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in app_warnings:
            lines.append(f"- [{w['kind']}] {w['detail']}")
        lines.append("")

    print("\n".join(lines))
    return 0


def query_check_freshness(flux_root: Path, *, json_out: bool = False) -> int:
    """Check if the topology cache is fresh or stale (without rebuild)."""
    code = _check_root(flux_root, json_out)
    if code is not None:
        return code

    state = freshness_state(flux_root)

    if state == "NO_CACHE":
        # Never auto-builds.
        if json_out:
            print(json.dumps({"status": "no-cache"}))
        else:
            print("Status: **NO CACHE** — run `flux-topology build` first.")
        return 3

    if state == "FRESH":
        current_fp = compute_fingerprint(flux_root)
        text = (f"Status: **FRESH** — {current_fp['files']} YAML files, "
                f"hash matches cached fingerprint.")
        exit_code = 0
    elif state == "STALE":
        current_fp = compute_fingerprint(flux_root)
        cached_fp = read_cached_fingerprint(flux_root) or {}
        text = (f"Status: **STALE** — current: {current_fp['files']} files / "
                f"{current_fp['sha256'][:16]}..., "
                f"cached: {cached_fp.get('files')} files / "
                f"{cached_fp.get('sha256', '')[:16]}...")
        exit_code = 1
    else:  # CORRUPT
        text = "Status: **CORRUPT** — fingerprint file missing, rebuild needed."
        exit_code = 1

    if json_out:
        print(json.dumps({"status": _JSON_STATUS[state]}))
    else:
        print(text)
    return exit_code