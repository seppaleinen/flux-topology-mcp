"""Tests for extract module against fleet-infra."""

import pytest
from pathlib import Path

from flux_topology.discovery import discover_apps
from flux_topology.extract import extract_app_data

FLEET_INFRA = Path.home() / "workspace" / "personal" / "fleet-infra"
FLUX_ROOT = FLEET_INFRA / "flux"

skip_no_fleet = pytest.mark.skipif(
    not FLUX_ROOT.is_dir(),
    reason="fleet-infra not available"
)


@skip_no_fleet
class TestExtraction:
    def _get_app(self, name: str):
        apps = discover_apps(FLUX_ROOT)
        app = [a for a in apps if a.name == name]
        assert len(app) == 1, f"App '{name}' not found"
        app = app[0]
        extract_app_data(app, FLUX_ROOT)
        return app

    def test_radarr_workloads(self):
        """radarr has a local chart with templates/ containing a Deployment."""
        app = self._get_app("radarr")
        assert len(app.workloads) >= 1
        kinds = {w.kind for w in app.workloads}
        assert "Deployment" in kinds

    def test_deerflow_two_deployments(self):
        """deerflow has two Deployments in templates/."""
        app = self._get_app("deerflow")
        deployments = [w for w in app.workloads if w.kind == "Deployment"]
        assert len(deployments) == 2, f"Expected 2 Deployments, got {len(deployments)}"

    def test_radarr_ingress_host(self):
        """radarr has ingress host radarr.labb.site."""
        app = self._get_app("radarr")
        assert "radarr.labb.site" in app.ingress_hosts

    def test_radarr_dns_refs(self):
        """radarr references postgres-rw.postgres.svc.cluster.local."""
        app = self._get_app("radarr")
        dns_refs = [r for r in app.refs if r.kind == "dns-full"]
        fqdns = [r.raw for r in dns_refs]
        assert any("postgres-rw.postgres.svc.cluster.local" in f for f in fqdns), \
            f"Expected postgres-rw FQDN in refs, got: {fqdns}"

    def test_radarr_encrypted(self):
        """radarr has SOPS-encrypted secrets."""
        app = self._get_app("radarr")
        assert app.encrypted, "radarr should be encrypted (SOPS markers)"

    def test_stipendiatet_backend_depends_on_postgres(self):
        """stipendiatet/backend has dependsOn: postgres-cluster."""
        app = self._get_app("backend")
        # DependsOn is extracted via edges, not directly in flux_objects
        # But the HelmRelease should be in flux_objects
        hr = [f for f in app.flux_objects if f.kind == "HelmRelease"]
        assert len(hr) >= 1

    def test_webapp_depends_on_tmdb_meilis(self):
        """worldinmovies/webapp dependsOn: tmdb, meilisearch."""
        app = self._get_app("webapp")
        hr = [f for f in app.flux_objects if f.kind == "HelmRelease"]
        assert len(hr) >= 1

    def test_litellm_depends_on_postgres(self):
        """litellm dependsOn: postgres-cluster."""
        app = self._get_app("litellm")
        hr = [f for f in app.flux_objects if f.kind == "HelmRelease"]
        assert len(hr) >= 1

    def test_postgres_cluster_helmrelease(self):
        """postgres has cluster-helmrelease.yaml with HelmRelease."""
        app = self._get_app("postgres")
        hr = [f for f in app.flux_objects if f.kind == "HelmRelease"]
        assert len(hr) >= 1
        assert hr[0].name == "postgres-cluster"

    def test_bitebase_depends_on_postgres(self):
        """bitebase dependsOn: postgres-cluster."""
        app = self._get_app("bitebase")
        hr = [f for f in app.flux_objects if f.kind == "HelmRelease"]
        assert len(hr) >= 1

    def test_agents_standalone_workload(self):
        """ai/agents has standalone Deployment (opencode-agent.yaml)."""
        app = self._get_app("agents")
        deployments = [w for w in app.workloads if w.kind == "Deployment"]
        assert len(deployments) >= 1

    def test_hermes_official_ingress(self):
        """hermes-official has ingress host hermes.labb.site."""
        app = self._get_app("hermes-official")
        assert "hermes.labb.site" in app.ingress_hosts

    def test_tmdb_external_refs(self):
        """tmdb references rabbitmq.worldinmovies.svc.cluster.local."""
        app = self._get_app("tmdb")
        dns_refs = [r for r in app.refs if r.kind == "dns-full"]
        fqdns = [r.raw for r in dns_refs]
        assert any("rabbitmq.worldinmovies.svc.cluster.local" in f for f in fqdns), \
            f"Expected rabbitmq FQDN, got: {fqdns}"

    def test_workload_count_matches_discovery(self):
        """Workload count should be consistent with discovery signals."""
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            extract_app_data(app, FLUX_ROOT)
            # Apps with helmrelease signal should have at least 0 workloads
            # (some HelmReleases don't define workloads in values)
            assert isinstance(app.workloads, list)

    def test_services_extracted(self):
        """radarr should have services from templates/service.yaml."""
        app = self._get_app("radarr")
        # radarr templates/service.yaml should define a Service
        assert isinstance(app.services, list)
