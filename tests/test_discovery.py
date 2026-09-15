"""Tests for discovery module against fleet-infra."""

import pytest
from pathlib import Path

from flux_topology.discovery import discover_apps

FLEET_INFRA = Path.home() / "workspace" / "personal" / "fleet-infra"
FLUX_ROOT = FLEET_INFRA / "flux"

skip_no_fleet = pytest.mark.skipif(
    not FLUX_ROOT.is_dir(),
    reason="fleet-infra not available"
)


@skip_no_fleet
class TestDiscovery:
    def test_apps_discovered(self):
        apps = discover_apps(FLUX_ROOT)
        assert len(apps) >= 40, f"Expected 40+ apps, got {len(apps)}"

    def test_domains_discovered(self):
        apps = discover_apps(FLUX_ROOT)
        domains = {a.domain for a in apps}
        # fleet-infra has: ai, apps, arrs, bitebase, games, infrastructure,
        # monitoring, stipendiatet, worldinmovies, etc.
        assert len(domains) >= 8, f"Expected 8+ domains, got {len(domains)}"

    def test_radarr_local_chart_absorption(self):
        """radarr has Chart.yaml + templates/ with workloads → one App."""
        apps = discover_apps(FLUX_ROOT)
        radarr = [a for a in apps if a.name == "radarr"]
        assert len(radarr) == 1
        assert "local-chart" in radarr[0].signals

    def test_deerflow_one_app_two_deployments(self):
        """deerflow is one App, extraction should find 2 Deployments."""
        apps = discover_apps(FLUX_ROOT)
        deerflow = [a for a in apps if a.name == "deerflow"]
        assert len(deerflow) == 1

    def test_worldinmovies_six_apps(self):
        """worldinmovies domain should have multiple Apps (count fluctuates during ai/agents migration)."""
        apps = discover_apps(FLUX_ROOT)
        wim = [a for a in apps if a.domain == "worldinmovies"]
        assert len(wim) >= 4, f"Expected 4+ worldinmovies apps, got {len(wim)}: {[a.name for a in wim]}"

    def test_worldinmovies_one_domain(self):
        """All worldinmovies apps should share the same domain."""
        apps = discover_apps(FLUX_ROOT)
        wim = [a for a in apps if a.domain == "worldinmovies"]
        domains = {a.domain for a in wim}
        assert len(domains) == 1

    def test_ps3netsrv_pure_kustomization(self):
        """ps3netsrv has kustomization.yaml pointing at files → App signal."""
        apps = discover_apps(FLUX_ROOT)
        ps3 = [a for a in apps if a.name == "ps3netsrv"]
        assert len(ps3) == 1
        assert any("kustomization" in s for s in ps3[0].signals)

    def test_stipendiatet_three_sibling_apps(self):
        """stipendiatet domain should have at least backend, frontend, admin-frontend (may grow during migration)."""
        apps = discover_apps(FLUX_ROOT)
        stp = [a for a in apps if a.domain == "stipendiatet"]
        names = {a.name for a in stp}
        expected = {"backend", "frontend", "admin-frontend"}
        assert expected.issubset(names), f"Expected {expected} in stipendiatet apps, got: {names}"
        assert len(names) >= 3, f"Expected 3+ stipendiatet apps, got: {names}"

    def test_bitebase_domain_with_one_app(self):
        """bitebase = Domain (direct child of flux/) with 1 App."""
        apps = discover_apps(FLUX_ROOT)
        bitebase = [a for a in apps if a.name == "bitebase"]
        assert len(bitebase) == 1
        assert bitebase[0].domain == "bitebase"

    def test_monitoring_is_app(self):
        """monitoring/ has kustomization with file resources → App signal."""
        apps = discover_apps(FLUX_ROOT)
        monitoring = [a for a in apps if a.name == "monitoring"]
        assert len(monitoring) >= 1, "monitoring should be discovered as an App"
        assert any("kustomization" in s for s in monitoring[0].signals)

    def test_agents_nested_app(self):
        """ai/agents/ is an App with nested hermes-official child App."""
        apps = discover_apps(FLUX_ROOT)
        agents = [a for a in apps if a.name == "agents"]
        hermes = [a for a in apps if a.name == "hermes-official"]
        assert len(agents) == 1
        assert len(hermes) == 1
        assert agents[0].domain == "ai"
        assert hermes[0].domain == "ai"

    def test_app_ids_are_relative(self):
        """All app IDs should be relative to flux/."""
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            assert not app.id.startswith("/"), f"{app.id} starts with /"
            assert not app.id.startswith("flux/"), f"{app.id} starts with flux/"

    def test_app_domains_match_first_component(self):
        """Domain should be the first path component under flux/."""
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            # For apps that are direct children of flux/ (e.g. bitebase),
            # id == domain. For nested apps, id starts with domain/.
            assert app.id == app.domain or app.id.startswith(app.domain + "/"), \
                f"{app.id} domain={app.domain}"
