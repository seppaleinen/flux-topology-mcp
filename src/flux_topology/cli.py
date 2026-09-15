"""Console entry point: flux-topology build/map/trace/find-refs/app-card/check-freshness."""

from __future__ import annotations

import argparse
import sys

from .cache import is_cache_fresh
from .query import (
    build_topology,
    query_app_card,
    query_check_freshness,
    query_find_refs,
    query_map,
    query_trace,
    resolve_flux_root,
)


def cmd_build(args: argparse.Namespace) -> int:
    """Build the topology cache."""
    flux_root = resolve_flux_root(args.directory)

    if not flux_root.is_dir():
        print(f"Error: flux/ directory not found in {flux_root}", file=sys.stderr)
        return 1

    if not args.force and is_cache_fresh(flux_root):
        print(f"Cache is fresh for {flux_root}. Use --force to rebuild.")
        return 0

    print(f"Building topology for {flux_root}...")
    graph = build_topology(flux_root, progress=True)
    print(f"  Cache written to {flux_root}/.fluxtop/")
    print(f"  {len(graph.domains)} domains, {len(graph.apps)} apps")
    return 0


def _cmd_map(args: argparse.Namespace) -> int:
    return query_map(resolve_flux_root(args.directory), json_out=args.json_out)


def _cmd_trace(args: argparse.Namespace) -> int:
    return query_trace(
        resolve_flux_root(args.directory),
        args.app_id,
        direction=args.direction,
        depth=args.depth,
        json_out=args.json_out,
    )


def _cmd_find_refs(args: argparse.Namespace) -> int:
    return query_find_refs(
        resolve_flux_root(args.directory),
        args.pattern,
        json_out=args.json_out,
    )


def _cmd_app_card(args: argparse.Namespace) -> int:
    return query_app_card(
        resolve_flux_root(args.directory),
        args.app_id,
        json_out=args.json_out,
    )


def _cmd_check_freshness(args: argparse.Namespace) -> int:
    return query_check_freshness(
        resolve_flux_root(args.directory),
        json_out=args.json_out,
    )


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
    build_parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even if the cache is fresh",
    )
    build_parser.set_defaults(func=cmd_build)

    # map subcommand
    map_parser = subparsers.add_parser(
        "map",
        help="Map topology: domains, hub apps by edge count, warnings summary",
    )
    map_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    map_parser.add_argument("--json", action="store_true", dest="json_out",
                           help="Emit JSON instead of markdown")
    map_parser.set_defaults(func=_cmd_map)

    # trace subcommand
    trace_parser = subparsers.add_parser(
        "trace",
        help="BFS trace from an app: blast radius with typed edges",
    )
    trace_parser.add_argument("app_id", help="App ID to trace from")
    trace_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    trace_parser.add_argument(
        "--direction",
        choices=["out", "in", "both"],
        default="out",
        help="'out' = what this app depends on, 'in' = what depends on this app, "
             "'both' = both (default: out)",
    )
    trace_parser.add_argument(
        "--depth",
        type=int,
        default=5,
        help="Max BFS depth (default: 5)",
    )
    trace_parser.add_argument("--json", action="store_true", dest="json_out",
                           help="Emit JSON instead of markdown")
    trace_parser.set_defaults(func=_cmd_trace)

    # find-refs subcommand
    find_refs_parser = subparsers.add_parser(
        "find-refs",
        help="Search for references matching a regex pattern, grouped by app",
    )
    find_refs_parser.add_argument("pattern", help="Regex pattern to match against refs")
    find_refs_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    find_refs_parser.add_argument("--json", action="store_true", dest="json_out",
                                 help="Emit JSON instead of markdown")
    find_refs_parser.set_defaults(func=_cmd_find_refs)

    # app-card subcommand
    app_card_parser = subparsers.add_parser(
        "app-card",
        help="Get the app card: markdown + structured data for one app",
    )
    app_card_parser.add_argument("app_id", help="App ID to show")
    app_card_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    app_card_parser.add_argument("--json", action="store_true", dest="json_out",
                                help="Emit JSON instead of markdown")
    app_card_parser.set_defaults(func=_cmd_app_card)

    # check-freshness subcommand
    check_freshness_parser = subparsers.add_parser(
        "check-freshness",
        help="Check if the topology cache is fresh or stale (without rebuild)",
    )
    check_freshness_parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Repository root directory (default: current directory)",
    )
    check_freshness_parser.add_argument("--json", action="store_true", dest="json_out",
                                       help="Emit JSON instead of markdown")
    check_freshness_parser.set_defaults(func=_cmd_check_freshness)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
