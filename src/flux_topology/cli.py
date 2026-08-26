"""Console entry point: flux-topology build [dir] and flux-topology mcp [dir]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def cmd_build(args: argparse.Namespace) -> None:
    """Build the topology cache."""
    from .cache import compute_fingerprint, write_cache, is_cache_fresh
    from .models import WiringGraph
    from .discovery import discover_apps
    from .extract import extract_app_data
    from .edges import resolve_edges, build_wiring_graph

    flux_root = Path(args.directory).resolve()
    flux_dir = flux_root / "flux"

    if not flux_dir.is_dir():
        print(f"Error: flux/ directory not found in {flux_root}", file=sys.stderr)
        sys.exit(1)

    if is_cache_fresh(flux_dir):
        print(f"Cache is fresh for {flux_dir}. Use --force to rebuild.")
        return

    print(f"Building topology for {flux_root}...")

    # Discover apps
    apps = discover_apps(flux_dir)
    print(f"  Discovered {len(apps)} apps")

    # Extract data for each app
    for app in apps:
        extract_app_data(app, flux_dir)

    # Resolve edges
    edges, warnings = resolve_edges(apps, flux_dir)
    print(f"  Resolved {len(edges)} edges, {len(warnings)} warnings")

    # Build graph
    fingerprint = compute_fingerprint(flux_dir)
    graph = build_wiring_graph(apps, edges, warnings, flux_dir, fingerprint)

    # Write cache
    write_cache(flux_dir, apps, edges, warnings, graph)
    print(f"  Cache written to {flux_dir}/.fluxtop/")
    print(f"  {len(graph.domains)} domains, {len(graph.apps)} apps")


def cmd_mcp(args: argparse.Namespace) -> None:
    """Run the MCP server."""
    from .server import run_server

    # Set working directory for MCP tools
    import os
    os.chdir(args.directory)
    run_server()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="flux-topology",
        description="Static topology graph for FluxCD GitOps repos",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build subcommand
    build_parser = subparsers.add_parser(
        "build",
        help="Build the topology cache (.fluxtop/)",
    )
    build_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )

    # mcp subcommand
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Run the MCP server over stdio",
    )
    mcp_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )

    args = parser.parse_args()

    if args.command == "build":
        cmd_build(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
