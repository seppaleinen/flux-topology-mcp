"""FastMCP server with 5 topology query tools."""

import json
from collections import defaultdict
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .models import WiringGraph, App, Edge, Warning
from .cache import (
    read_wiring_graph, is_cache_fresh, compute_fingerprint,
    read_cached_fingerprint, write_cache, FLUXTOP_DIR,
)
from .discovery import discover_apps
from .extract import extract_app_data
from .edges import resolve_edges, build_wiring_graph


mcp = FastMCP("flux-topology")


def _get_flux_root() -> Path:
    """Get the flux/ directory path from the working directory.

    The working directory is the repo root; flux/ is the analysis target.
    """
    cwd = Path.cwd()
    flux_dir = cwd / "flux"
    if flux_dir.is_dir():
        return flux_dir
    return cwd


def _ensure_cache(flux_root: Path) -> WiringGraph:
    """Ensure cache exists and is fresh. Rebuild if needed."""
    if is_cache_fresh(flux_root):
        graph = read_wiring_graph(flux_root)
        if graph is not None:
            return graph

    # Rebuild
    return _build_cache(flux_root)


def _build_cache(flux_root: Path) -> WiringGraph:
    """Build the topology cache from scratch."""
    # flux_root is the flux/ directory
    if not flux_root.is_dir():
        raise FileNotFoundError(f"flux/ directory not found at {flux_root}")

    apps = discover_apps(flux_root)
    for app in apps:
        extract_app_data(app, flux_root)

    edges, warnings = resolve_edges(apps, flux_root)
    fingerprint = compute_fingerprint(flux_root)
    graph = build_wiring_graph(apps, edges, warnings, flux_root, fingerprint)
    write_cache(flux_root, apps, edges, warnings, graph)
    return graph


@mcp.tool()
def fluxtop_map() -> str:
    """Map topology: domains, hub apps by edge count, warnings summary."""
    flux_root = _get_flux_root()
    graph = _ensure_cache(flux_root)

    # Count edges per app
    edge_count: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        edge_count[e["from"]] += 1
        edge_count[e["to"]] += 1

    # Sort by edge count descending
    hub_apps = sorted(edge_count.items(), key=lambda x: -x[1])[:10]

    # Build summary
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

    return "\n".join(lines)


@mcp.tool()
def fluxtop_trace(app_id: str, direction: str = "out", depth: int = 5) -> str:
    """BFS trace from an app: blast radius with typed edges.

    direction: 'out' = what this app depends on, 'in' = what depends on this app, 'both' = both.
    depth: max BFS depth.
    """
    flux_root = _get_flux_root()
    graph = _ensure_cache(flux_root)

    # Find the app
    app = None
    for a in graph.apps:
        if a["id"] == app_id:
            app = a
            break
    if app is None:
        return f"App '{app_id}' not found. Available: {[a['id'] for a in graph.apps[:20]]}"

    # Build adjacency
    out_edges: dict[str, list[dict]] = defaultdict(list)
    in_edges: dict[str, list[dict]] = defaultdict(list)
    for e in graph.edges:
        out_edges[e["from"]].append(e)
        in_edges[e["to"]].append(e)

    # BFS
    visited: set[str] = set()
    result_edges: list[dict] = []
    queue: list[tuple[str, int]] = [(app_id, 0)]

    while queue:
        current, current_depth = queue.pop(0)
        if current in visited or current_depth > depth:
            continue
        visited.add(current)

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

    return "\n".join(lines)


@mcp.tool()
def fluxtop_find_refs(pattern: str) -> str:
    """Search for references matching a regex pattern, grouped by consuming app."""
    import re

    flux_root = _get_flux_root()
    graph = _ensure_cache(flux_root)

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"Invalid regex pattern: {e}"

    matches: dict[str, list[dict]] = defaultdict(list)

    for app in graph.apps:
        for ref in app.get("refs", []):
            raw = ref.get("raw", "")
            if regex.search(raw):
                matches[app["id"]].append(ref)

    lines = []
    lines.append(f"# References matching: `{pattern}`")
    lines.append("")

    if not matches:
        lines.append("No matches found.")
        return "\n".join(lines)

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

    return "\n".join(lines)


@mcp.tool()
def fluxtop_app_card(app_id: str) -> str:
    """Get the app card: markdown + structured data for one app."""
    flux_root = _get_flux_root()
    graph = _ensure_cache(flux_root)

    # Find the app
    app = None
    for a in graph.apps:
        if a["id"] == app_id:
            app = a
            break
    if app is None:
        return f"App '{app_id}' not found. Available: {[a['id'] for a in graph.apps[:20]]}"

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

    # Edges involving this app
    out_edges = [e for e in graph.edges if e["from"] == app_id]
    in_edges = [e for e in graph.edges if e["to"] == app_id]

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

    # App warnings
    app_warnings = [w for w in graph.warnings if w.get("app") == app_id]
    if app_warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in app_warnings:
            lines.append(f"- [{w['kind']}] {w['detail']}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def fluxtop_check_freshness() -> str:
    """Check if the topology cache is fresh or stale (without rebuild)."""
    flux_root = _get_flux_root()
    flux_dir = flux_root / "flux"

    wiring_file = flux_dir / FLUXTOP_DIR / "wiring.json"
    if not wiring_file.exists():
        return "Status: **NO CACHE** — run `flux-topology build` first."

    cached_fp = read_cached_fingerprint(flux_dir)
    current_fp = compute_fingerprint(flux_dir)

    if cached_fp is None:
        return "Status: **CORRUPT** — fingerprint file missing, rebuild needed."

    files_match = current_fp.get("files") == cached_fp.get("files")
    hash_match = current_fp.get("sha256") == cached_fp.get("sha256")

    if files_match and hash_match:
        return (f"Status: **FRESH** — {current_fp['files']} YAML files, "
                f"hash matches cached fingerprint.")
    else:
        return (f"Status: **STALE** — current: {current_fp['files']} files / "
                f"{current_fp['sha256'][:16]}..., "
                f"cached: {cached_fp['files']} files / "
                f"{cached_fp['sha256'][:16]}...")


def run_server() -> None:
    """Run the MCP server over stdio."""
    mcp.run()
