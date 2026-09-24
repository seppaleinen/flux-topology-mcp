"""Self-contained CLI tests against a tiny fake flux/ tree.

Builds a two-app fake tree in tmp_path and exercises the CLI via subprocess
``python -m flux_topology.cli`` — no fleet-infra dependency.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = [sys.executable, "-m", "flux_topology.cli"]

# Fake tree shape:
#   flux/
#     apps/
#       backend/backend-helmrelease.yaml
#       backend/service.yaml        -> kind: Service (name=backend, ns=apps)
#       frontend/frontend-helmrelease.yaml
#       frontend/values.yaml        -> contains a resolvable + a broken dns ref
# frontend dependsOn backend -> 1 edge; backend is a separate app.
# The dns-full ref "backend.apps.svc.cluster.local" resolves to apps/backend
# (exact Service match + name/namespace fallback) -> 1 dns-ref edge.
# "nonexistent.apps.svc.cluster.local" is genuinely broken -> 1 warning.
# External .labb.site hosts are self-references (no edge, no warning).

BACKEND_HR = """\
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: backend
  namespace: apps
spec:
  values:
    ingress:
      host: backend.labb.site
"""

BACKEND_SERVICE = """\
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: apps
spec:
  selector:
    app: backend
  ports:
    - port: 80
"""

FRONTEND_HR = """\
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: frontend
  namespace: apps
spec:
  dependsOn:
    - name: backend
  values:
    ingress:
      host: frontend.labb.site
"""

FRONTEND_VALUES = (
    "backend: backend.apps.svc.cluster.local\n"
    "missing: nonexistent.apps.svc.cluster.local\n"
)


@pytest.fixture
def flux_tree(tmp_path: Path) -> Path:
    """Create a tiny flux/ tree with two apps. Returns the repo root."""
    frontend = tmp_path / "flux" / "apps" / "frontend"
    backend = tmp_path / "flux" / "apps" / "backend"
    frontend.mkdir(parents=True)
    backend.mkdir(parents=True)
    (frontend / "frontend-helmrelease.yaml").write_text(FRONTEND_HR)
    (frontend / "values.yaml").write_text(FRONTEND_VALUES)
    (backend / "backend-helmrelease.yaml").write_text(BACKEND_HR)
    (backend / "service.yaml").write_text(BACKEND_SERVICE)
    return tmp_path


def run_cli(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*CLI, *args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def fluxtop(root: Path) -> Path:
    return root / "flux" / ".fluxtop"


def make_stale(root: Path) -> None:
    """Mutate a YAML file so the cached fingerprint no longer matches."""
    backend_hr = root / "flux" / "apps" / "backend" / "backend-helmrelease.yaml"
    backend_hr.write_text("# drifted\n" + backend_hr.read_text())


# --- build ---------------------------------------------------------------

def test_build_creates_cache(flux_tree: Path):
    result = run_cli(flux_tree, "build")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (fluxtop(flux_tree) / "wiring.json").exists()
    assert (fluxtop(flux_tree) / "fingerprint.json").exists()
    # One card per app: app id "apps/frontend" -> apps__frontend.md
    assert (fluxtop(flux_tree) / "apps" / "apps__frontend.md").exists()
    assert (fluxtop(flux_tree) / "apps" / "apps__backend.md").exists()


def test_build_idempotent_fresh_skip(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "build")
    assert result.returncode == 0
    assert "Cache is fresh" in result.stdout
    assert "--force" in result.stdout


def test_build_force_rebuilds(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "build", "--force")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Building topology" in result.stdout


# --- map -----------------------------------------------------------------

def test_map_human_after_build(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "map")
    assert result.returncode == 0
    assert "# Flux Topology Map" in result.stdout
    assert "**Apps**: 2" in result.stdout
    assert "**Edges**: 2" in result.stdout
    assert "apps/frontend" in result.stdout


def test_map_json(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "map", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["schema_version"] == 1
    assert data["app_count"] == 2
    assert data["edge_count"] == 2
    assert data["root"].endswith("flux")
    assert data["built_at"]
    assert data["fingerprint"]
    assert len(data["domains"]) == 1
    assert data["domains"][0]["name"] == "apps"
    assert data["domains"][0]["app_count"] == 2
    assert len(data["domains"][0]["apps"]) == 2
    hub = {h["app_id"]: h for h in data["hub_apps"]}
    assert hub["apps/frontend"]["out_degree"] == 2
    assert hub["apps/backend"]["in_degree"] == 2
    assert len(data["warnings"]) >= 1


def test_map_no_cache_auto_builds(flux_tree: Path):
    run_cli(flux_tree, "build")
    shutil_rmtree(fluxtop(flux_tree))
    result = run_cli(flux_tree, "map")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (fluxtop(flux_tree) / "wiring.json").exists()


def test_map_stale_human_notice_no_rebuild(flux_tree: Path):
    run_cli(flux_tree, "build")
    wiring_before = (fluxtop(flux_tree) / "wiring.json").read_text()
    make_stale(flux_tree)
    result = run_cli(flux_tree, "map")
    assert result.returncode == 1
    assert "⚠ Cache is STALE" in result.stdout
    assert "build [dir] --force" in result.stdout
    # Cache must NOT be rebuilt by a stale query.
    assert (fluxtop(flux_tree) / "wiring.json").read_text() == wiring_before


def test_map_stale_json(flux_tree: Path):
    run_cli(flux_tree, "build")
    make_stale(flux_tree)
    result = run_cli(flux_tree, "map", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"status": "stale"}


def test_map_corrupt(flux_tree: Path):
    run_cli(flux_tree, "build")
    (fluxtop(flux_tree) / "fingerprint.json").unlink()
    result = run_cli(flux_tree, "map")
    assert result.returncode == 1
    assert "⚠ Cache is CORRUPT" in result.stdout
    result = run_cli(flux_tree, "map", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"status": "corrupt"}


# --- trace ---------------------------------------------------------------

def test_trace_found_human_and_json(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "trace", "apps/frontend")
    assert result.returncode == 0
    assert "# Trace: apps/frontend (direction=out, depth=5)" in result.stdout
    assert "apps/backend" in result.stdout

    result = run_cli(flux_tree, "trace", "apps/backend", "--direction", "in",
                     "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data["app"] == "apps/backend"
    assert data["direction"] == "in"
    assert data["depth"] == 5
    assert "apps/backend" in data["visited"]
    assert "apps/frontend" in data["visited"]
    assert any(e["from"] == "apps/frontend" and e["to"] == "apps/backend"
               for e in data["edges"])


def test_trace_missing_human(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "trace", "nope")
    assert result.returncode == 1
    assert "App 'nope' not found" in result.stdout
    assert "Available: " in result.stdout


def test_trace_missing_json(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "trace", "nope", "--json")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data == {"app": "nope", "error": "not-found",
                    "available": ["apps/backend", "apps/frontend"]}


def test_trace_depth_zero_visited_start_only(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "trace", "apps/frontend", "--depth", "0",
                     "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["visited"] == ["apps/frontend"]


# --- app-card ------------------------------------------------------------

def test_app_card_found_missing_json(flux_tree: Path):
    run_cli(flux_tree, "build")

    result = run_cli(flux_tree, "app-card", "apps/frontend")
    assert result.returncode == 0
    assert "# App: frontend" in result.stdout
    assert "apps/backend" in result.stdout  # Depends On section

    result = run_cli(flux_tree, "app-card", "nope")
    assert result.returncode == 1
    assert "not found" in result.stdout

    result = run_cli(flux_tree, "app-card", "apps/frontend", "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["app"]["id"] == "apps/frontend"
    assert data["app"]["domain"] == "apps"
    assert any(e["to"] == "apps/backend" for e in data["edges_out"])
    assert isinstance(data["edges_in"], list)
    assert isinstance(data["warnings"], list)


# --- find-refs -----------------------------------------------------------

def test_find_refs_matching(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "find-refs", "svc.cluster.local")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "apps/frontend" in result.stdout
    assert "backend.apps.svc.cluster.local" in result.stdout

    result = run_cli(flux_tree, "find-refs", "labb.site", "--json")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["pattern"] == "labb.site"
    assert data["total"] >= 2
    assert "apps/backend" in data["apps"]
    assert "apps/frontend" in data["apps"]


def test_find_refs_no_match(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "find-refs", "nomatchxyz")
    assert result.returncode == 1
    assert "No references found for pattern 'nomatchxyz'" in result.stdout

    result = run_cli(flux_tree, "find-refs", "nomatchxyz", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"pattern": "nomatchxyz", "total": 0,
                                         "apps": {}}


def test_find_refs_invalid_regex(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "find-refs", "[")
    assert result.returncode == 1
    assert "Invalid regex pattern" in result.stdout

    result = run_cli(flux_tree, "find-refs", "[", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"pattern": "[",
                                         "error": "invalid-regex"}


# --- check-freshness -----------------------------------------------------

def test_check_freshness_fresh(flux_tree: Path):
    run_cli(flux_tree, "build")
    result = run_cli(flux_tree, "check-freshness")
    assert result.returncode == 0
    assert "Status: **FRESH**" in result.stdout
    assert "YAML files" in result.stdout

    result = run_cli(flux_tree, "check-freshness", "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"status": "fresh"}


def test_check_freshness_stale(flux_tree: Path):
    run_cli(flux_tree, "build")
    make_stale(flux_tree)
    result = run_cli(flux_tree, "check-freshness")
    assert result.returncode == 1
    assert "Status: **STALE**" in result.stdout

    result = run_cli(flux_tree, "check-freshness", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"status": "stale"}


def test_check_freshness_no_cache_never_builds(flux_tree: Path):
    result = run_cli(flux_tree, "check-freshness")
    assert result.returncode == 3
    assert "Status: **NO CACHE**" in result.stdout
    assert "build" in result.stdout
    # Must NOT auto-build.
    assert not fluxtop(flux_tree).exists()

    result = run_cli(flux_tree, "check-freshness", "--json")
    assert result.returncode == 3
    assert json.loads(result.stdout) == {"status": "no-cache"}
    assert not fluxtop(flux_tree).exists()


def test_check_freshness_corrupt(flux_tree: Path):
    run_cli(flux_tree, "build")
    (fluxtop(flux_tree) / "fingerprint.json").unlink()
    result = run_cli(flux_tree, "check-freshness")
    assert result.returncode == 1
    assert "Status: **CORRUPT**" in result.stdout

    result = run_cli(flux_tree, "check-freshness", "--json")
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"status": "corrupt"}


# --- usage / dir handling ------------------------------------------------

def test_usage_error_trace_without_app_id(flux_tree: Path):
    result = run_cli(flux_tree, "trace")
    assert result.returncode == 2
    assert result.stderr  # argparse usage errors go to stderr


def test_dir_not_found_does_not_build(flux_tree: Path):
    result = run_cli(flux_tree, "map", "does-not-exist")
    assert result.returncode == 1
    assert "Error: flux/ directory not found" in result.stderr
    assert not (flux_tree / "does-not-exist").exists()


def test_dir_not_found_json(flux_tree: Path):
    result = run_cli(flux_tree, "map", "does-not-exist", "--json")
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["error"] == "invalid-directory"
    assert data["path"].endswith("does-not-exist")


def test_json_stdout_is_pure_json(flux_tree: Path):
    """No progress/notice text may leak onto stdout in --json mode."""
    run_cli(flux_tree, "build")
    for args in [("map", "--json"),
                 ("app-card", "apps/frontend", "--json"),
                 ("check-freshness", "--json")]:
        result = run_cli(flux_tree, *args)
        # json.loads raises if stdout is polluted with non-JSON text
        json.loads(result.stdout)


# --- entry points --------------------------------------------------------

def test_help_lists_subcommands():
    result = subprocess.run([*CLI, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    for sub in ("build", "map", "trace", "find-refs", "app-card",
                "check-freshness"):
        assert sub in result.stdout


def test_main_defined():
    """Console script entry point remains flux_topology.cli:main."""
    from flux_topology.cli import main
    assert callable(main)


def shutil_rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path)