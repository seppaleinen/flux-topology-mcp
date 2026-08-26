"""Integration tests: full pipeline against fleet-infra."""

import json
import pytest
from pathlib import Path

from flux_topology.discovery import discover_apps
from flux_topology.extract import extract_app_data
from flux_topology.edges import resolve_edges, build_wiring_graph
from flux_topology.cache import (
    compute_fingerprint, write_cache, read_wiring_graph,
    is_cache_fresh, FLUXTOP_DIR,
)
from flux_topology.cards import render_card

FLEET_INFRA = Path.home() / "workspace" / "personal" / "fleet-infra"
FLUX_ROOT = FLEET_INFRA / "flux"

skip_no_fleet = pytest.mark.skipif(
    not FLUX_ROOT.is_dir(),
    reason="fleet-infra not available"
)


@skip_no_fleet
class TestFullPipeline:
    def _build_full(self):
        """Run the full pipeline: discover → extract → edges → graph."""
        apps = discover_apps(FLUX_ROOT)
        for app in apps:
            extract_app_data(app, FLUX_ROOT)
        edges, warnings = resolve_edges(apps, FLUX_ROOT)
        fingerprint = compute_fingerprint(FLUX_ROOT)
        graph = build_wiring_graph(apps, edges, warnings, FLUX_ROOT, fingerprint)
        return apps, edges, warnings, graph

    def test_graph_schema_version(self):
        """WiringGraph should have schema_version 1."""
        _, _, _, graph = self._build_full()
        assert graph.schema_version == 1

    def test_graph_has_root(self):
        """WiringGraph should have root pointing to flux dir."""
        _, _, _, graph = self._build_full()
        assert graph.root == str(FLUX_ROOT)

    def test_graph_has_fingerprint(self):
        """WiringGraph should have a fingerprint with files and sha256."""
        _, _, _, graph = self._build_full()
        assert "files" in graph.fingerprint
        assert "sha256" in graph.fingerprint
        assert graph.fingerprint["files"] > 0

    def test_graph_has_domains(self):
        """WiringGraph should list domains with apps."""
        _, _, _, graph = self._build_full()
        assert len(graph.domains) >= 8
        for d in graph.domains:
            assert "name" in d
            assert "apps" in d
            assert len(d["apps"]) >= 1

    def test_graph_has_apps(self):
        """WiringGraph should list all apps with required fields."""
        _, _, _, graph = self._build_full()
        assert len(graph.apps) >= 40
        for app in graph.apps:
            assert "id" in app
            assert "name" in app
            assert "domain" in app
            assert "path" in app

    def test_graph_has_edges(self):
        """WiringGraph should have edges."""
        _, _, _, graph = self._build_full()
        assert len(graph.edges) >= 5
        for e in graph.edges:
            assert "from" in e
            assert "to" in e
            assert "type" in e
            assert "evidence" in e

    def test_graph_edges_typed(self):
        """All edges should have valid types."""
        _, _, _, graph = self._build_full()
        valid_types = {"dependsOn", "dns-ref", "external-ref"}
        for e in graph.edges:
            assert e["type"] in valid_types, f"Invalid edge type: {e['type']}"

    def test_graph_json_roundtrip(self):
        """WiringGraph should survive JSON serialization roundtrip."""
        _, _, _, graph = self._build_full()
        d = graph.to_dict()
        json_str = json.dumps(d)
        loaded = json.loads(json_str)
        graph2 = type(graph).from_dict(loaded)
        assert graph2.schema_version == graph.schema_version
        assert len(graph2.apps) == len(graph.apps)
        assert len(graph2.edges) == len(graph.edges)

    def test_card_rendering(self):
        """App cards should render without errors."""
        apps, edges, warnings, _ = self._build_full()
        for app in apps:
            card = render_card(app, edges, warnings)
            assert isinstance(card, str)
            assert len(card) > 0
            assert f"# App: {app.name}" in card

    def test_cache_write_and_read(self, tmp_path):
        """Cache should write and read back correctly."""
        apps, edges, warnings, graph = self._build_full()

        # Use a temp dir as the flux root
        test_flux = tmp_path / "flux"
        test_flux.mkdir()
        write_cache(test_flux, apps, edges, warnings, graph)

        # Read back
        read_graph = read_wiring_graph(test_flux)
        assert read_graph is not None
        assert len(read_graph.apps) == len(graph.apps)
        assert len(read_graph.edges) == len(graph.edges)

    def test_app_count_matches_discovery(self):
        """Graph app count should match discovery count."""
        apps, _, _, graph = self._build_full()
        assert len(graph.apps) == len(apps)

    def test_domains_cover_all_apps(self):
        """Every app should appear in exactly one domain."""
        _, _, _, graph = self._build_full()
        all_domain_apps = set()
        for d in graph.domains:
            for app_id in d["apps"]:
                assert app_id not in all_domain_apps, \
                    f"{app_id} appears in multiple domains"
                all_domain_apps.add(app_id)
        assert len(all_domain_apps) == len(graph.apps)
