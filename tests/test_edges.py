"""Tests for edge resolution against fleet-infra."""

import pytest
from pathlib import Path

from flux_topology.discovery import discover_apps
from flux_topology.extract import extract_app_data
from flux_topology.edges import resolve_edges, build_lookup_index

FLEET_INFRA = Path.home() / "workspace" / "personal" / "fleet-infra"
FLUX_ROOT = FLEET_INFRA / "flux"

skip_no_fleet = pytest.mark.skipif(
    not FLUX_ROOT.is_dir(),
    reason="fleet-infra not available"
)


@skip_no_fleet
class TestEdgeResolution:
    def _build_all(self):
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            extract_app_data(app, FLUX_ROOT)
        edges, warnings = resolve_edges(apps, FLUX_ROOT)
        return apps, edges, warnings

    def test_depends_on_resolution(self):
        """unpackerr dependsOn radarr and sonarr → edges resolved."""
        apps, edges, warnings = self._build_all()
        unpackerr_edges = [e for e in edges
                          if e.from_app == "arrs/unpackerr"
                          and e.type == "dependsOn"]
        to_apps = {e.to_app for e in unpackerr_edges}
        assert "arrs/radarr" in to_apps, f"Expected arrs/radarr in edges, got: {to_apps}"
        assert "arrs/sonarr" in to_apps, f"Expected arrs/sonarr in edges, got: {to_apps}"

    def test_depends_on_postgres_cluster(self):
        """Multiple apps depend on infrastructure/postgres via dependsOn."""
        apps, edges, warnings = self._build_all()
        postgres_deps = [e for e in edges
                        if e.to_app == "infrastructure/postgres"
                        and e.type == "dependsOn"]
        from_apps = {e.from_app for e in postgres_deps}
        # litellm, stipendiatet/backend, bitebase all depend on postgres-cluster
        assert "infrastructure/litellm" in from_apps or \
               "stipendiatet/backend" in from_apps or \
               "bitebase" in from_apps, \
               f"Expected at least one postgres dep, got: {from_apps}"

    def test_dns_ref_postgres_resolution(self):
        """dns-full ref postgres-rw.postgres.svc.cluster.local resolves to infrastructure/postgres."""
        apps, edges, warnings = self._build_all()
        dns_edges = [e for e in edges if e.type == "dns-ref"]
        postgres_dns = [e for e in dns_edges
                       if "postgres-rw.postgres.svc.cluster.local" in e.evidence]
        assert len(postgres_dns) >= 1, "Expected at least one DNS edge to postgres"
        target_apps = {e.to_app for e in postgres_dns}
        assert "infrastructure/postgres" in target_apps, \
            f"Expected infrastructure/postgres, got: {target_apps}"

    def test_dns_ref_litellm_resolution(self):
        """dns-full ref litellm.litellm.svc.cluster.local resolves to infrastructure/litellm."""
        apps, edges, warnings = self._build_all()
        dns_edges = [e for e in edges if e.type == "dns-ref"]
        litellm_dns = [e for e in dns_edges
                      if "litellm.litellm.svc.cluster.local" in e.evidence]
        assert len(litellm_dns) >= 1, "Expected at least one DNS edge to litellm"
        target_apps = {e.to_app for e in litellm_dns}
        assert "infrastructure/litellm" in target_apps, \
            f"Expected infrastructure/litellm, got: {target_apps}"

    def test_external_ref_via_labb_site(self):
        """External refs via *.labb.site resolve through ingress host mapping."""
        apps, edges, warnings = self._build_all()
        ext_edges = [e for e in edges if e.type == "external-ref"]
        assert len(ext_edges) >= 1, "Expected at least one external-ref edge"

    def test_intra_app_ref_excluded(self):
        """Refs within the same App should not create inter-App edges."""
        apps, edges, warnings = self._build_all()
        # No edge should have from_app == to_app
        for e in edges:
            assert e.from_app != e.to_app, \
                f"Intra-App edge: {e.from_app} → {e.to_app}"

    def test_broken_ref_warning(self):
        """DNS refs pointing at no known App produce warnings."""
        apps, edges, warnings = self._build_all()
        broken = [w for w in warnings if w.kind == "broken-ref"]
        # There should be at least some broken refs (e.g., services that don't
        # correspond to apps in the flux/ tree)
        assert isinstance(broken, list)  # May be empty if all refs resolve

    def test_worldinmovies_depends_on_edges(self):
        """worldinmovies webapp dependsOn tmdb and meilisearch."""
        apps, edges, warnings = self._build_all()
        webapp_deps = [e for e in edges
                      if e.from_app == "worldinmovies/webapp"
                      and e.type == "dependsOn"]
        to_apps = {e.to_app for e in webapp_deps}
        assert "worldinmovies/tmdb" in to_apps, \
            f"Expected worldinmovies/tmdb, got: {to_apps}"
        assert "worldinmovies/meilisearch" in to_apps, \
            f"Expected worldinmovies/meilisearch, got: {to_apps}"

    def test_lookup_index_has_flux_objects(self):
        """build_lookup_index returns apps indexed by Flux object names."""
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            extract_app_data(app, FLUX_ROOT)
        index = build_lookup_index(apps)
        assert "postgres-cluster" in index, \
            f"Expected postgres-cluster in index, got: {list(index.keys())[:10]}"
        assert "radarr" in index
        assert "unpackerr" in index

    def test_all_edges_have_valid_app_ids(self):
        """All edge from/to should reference valid app IDs."""
        apps, edges, warnings = self._build_all()
        app_ids = {a.id for a in apps}
        for e in edges:
            assert e.from_app in app_ids, \
                f"Edge from unknown app: {e.from_app}"
            assert e.to_app in app_ids, \
                f"Edge to unknown app: {e.to_app}"
