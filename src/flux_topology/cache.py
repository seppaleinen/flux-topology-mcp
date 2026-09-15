"""Topology cache writer: .fluxtop/ folder with cards + wiring graph."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .models import App, Edge, Warning, WiringGraph
from .cards import render_card


FLUXTOP_DIR = ".fluxtop"
APPS_DIR = "apps"
WIRING_FILE = "wiring.json"
FINGERPRINT_FILE = "fingerprint.json"


def compute_fingerprint(flux_root: Path) -> dict:
    """Compute a fingerprint of all YAML files under flux/."""
    sha = hashlib.sha256()
    count = 0
    for f in sorted(flux_root.rglob("*.yaml")):
        try:
            content = f.read_bytes()
            sha.update(content)
            count += 1
        except OSError:
            continue
    for f in sorted(flux_root.rglob("*.yml")):
        try:
            content = f.read_bytes()
            sha.update(content)
            count += 1
        except OSError:
            continue
    return {"files": count, "sha256": sha.hexdigest()}


def read_cached_fingerprint(flux_root: Path) -> dict | None:
    """Read the cached fingerprint from .fluxtop/fingerprint.json."""
    fp_file = flux_root / FLUXTOP_DIR / FINGERPRINT_FILE
    if not fp_file.exists():
        return None
    try:
        return json.loads(fp_file.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def fingerprint_matches(flux_root: Path) -> bool:
    """Check if the cached fingerprint matches the current state."""
    current = compute_fingerprint(flux_root)
    cached = read_cached_fingerprint(flux_root)
    if cached is None:
        return False
    return (current.get("files") == cached.get("files") and
            current.get("sha256") == cached.get("sha256"))


def write_cache(flux_root: Path, apps: list[App], edges: list[Edge],
                warnings: list[Warning], graph: WiringGraph) -> None:
    """Write the .fluxtop/ cache: cards, wiring.json, fingerprint."""
    fluxtop = flux_root / FLUXTOP_DIR
    fluxtop.mkdir(parents=True, exist_ok=True)

    # Write wiring.json
    wiring_file = fluxtop / WIRING_FILE
    wiring_file.write_text(json.dumps(graph.to_dict(), indent=2))

    # Write fingerprint
    fp_file = fluxtop / FINGERPRINT_FILE
    fp_file.write_text(json.dumps(graph.fingerprint, indent=2))

    # Write app cards
    apps_dir = fluxtop / APPS_DIR
    apps_dir.mkdir(exist_ok=True)

    for app in apps:
        card_content = render_card(app, edges, warnings)
        card_file = apps_dir / f"{app.id.replace('/', '__')}.md"
        card_file.parent.mkdir(parents=True, exist_ok=True)
        card_file.write_text(card_content)

    # Ensure .fluxtop/ is in .gitignore
    _ensure_gitignore(flux_root)


def _ensure_gitignore(flux_root: Path) -> None:
    """Append flux/.fluxtop/ to the repo root .gitignore if not present.

    flux_root is the flux/ directory; the repo root is its parent.
    """
    repo_root = flux_root.parent
    gitignore = repo_root / ".gitignore"
    # Pattern relative to repo root: flux/.fluxtop/
    line_to_add = f"{flux_root.name}/{FLUXTOP_DIR}/"

    if gitignore.exists():
        try:
            content = gitignore.read_text()
            if line_to_add in content or f"{FLUXTOP_DIR}/" in content:
                return
        except OSError:
            pass

    try:
        with gitignore.open("a") as f:
            f.write(f"\n{line_to_add}\n")
    except OSError:
        pass


def is_cache_fresh(flux_root: Path) -> bool:
    """Check if the cache is fresh (fingerprint matches)."""
    if not (flux_root / FLUXTOP_DIR / WIRING_FILE).exists():
        return False
    return fingerprint_matches(flux_root)


def read_wiring_graph(flux_root: Path) -> WiringGraph | None:
    """Read the cached wiring graph, or None if missing."""
    wiring_file = flux_root / FLUXTOP_DIR / WIRING_FILE
    if not wiring_file.exists():
        return None
    try:
        data = json.loads(wiring_file.read_text())
        return WiringGraph.from_dict(data)
    except (OSError, json.JSONDecodeError):
        return None


def freshness_state(flux_root: Path) -> str:
    """Return one of NO_CACHE / STALE / FRESH / CORRUPT."""
    # 1. wiring.json missing -> "NO_CACHE"
    if not (flux_root / FLUXTOP_DIR / WIRING_FILE).exists():
        return "NO_CACHE"
    # 2. cached fingerprint missing (read_cached_fingerprint None) -> "CORRUPT"
    if read_cached_fingerprint(flux_root) is None:
        return "CORRUPT"
    # 3. fingerprint_matches(flux_root) is False -> "STALE"
    if not fingerprint_matches(flux_root):
        return "STALE"
    # 4. read_wiring_graph(flux_root) is None -> "CORRUPT"
    if read_wiring_graph(flux_root) is None:
        return "CORRUPT"
    # 5. else -> "FRESH"
    return "FRESH"
