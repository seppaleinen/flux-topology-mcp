"""Self-contained unit tests for DNS / external reference resolution.

These tests construct App objects directly — no fleet-infra dependency.
"""

from __future__ import annotations

from flux_topology.models import App, Service, FluxObject, Workload, Ref, Edge, Warning
from flux_topology.edges import build_resolution_index, _resolve_dns_ref, _resolve_external_ref, resolve_edges
from pathlib import Path


def _make_app(app_id: str, name: str, domain: str, **kwargs) -> App:
    """Factory for test Apps with minimal boilerplate."""
    return App(
        id=app_id,
        name=name,
        domain=domain,
        path=app_id,
        **kwargs,
    )


class TestDNSResolution:
    """Tests for _resolve_dns_ref behavior via ResolutionIndex."""

    def test_namespace_is_domain_not_dir(self):
        """
        Fleet-infra pattern: Kubernetes namespace = domain (top-level flux/ dir),
        not the app's directory name. Multiple apps share a namespace.

        Example: worldinmovies/rabbitmq, worldinmovies/tmdb both deploy to
        namespace "worldinmovies". A ref to "rabbitmq.worldinmovies.svc.cluster.local"
        should resolve to worldinmovies/rabbitmq via fallback (service_name matches
        app.name/HR name, namespace matches HR namespace/domain).
        """
        # Two apps in the same domain, different dir names
        rabbitmq = _make_app(
            "worldinmovies/rabbitmq",
            name="rabbitmq",
            domain="worldinmovies",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="rabbitmq", namespace="worldinmovies"),
            ],
        )
        tmdb = _make_app(
            "worldinmovies/tmdb",
            name="tmdb",
            domain="worldinmovies",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="tmdb", namespace="worldinmovies"),
            ],
        )
        webapp = _make_app(
            "worldinmovies/webapp",
            name="webapp",
            domain="worldinmovies",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="webapp", namespace="worldinmovies"),
            ],
        )
        apps = [rabbitmq, tmdb, webapp]
        index = build_resolution_index(apps)

        # Ref from webapp to rabbitmq's service
        target = _resolve_dns_ref("rabbitmq.worldinmovies.svc.cluster.local", index)
        assert target == "worldinmovies/rabbitmq", f"Expected worldinmovies/rabbitmq, got {target}"

        # Ref from rabbitmq to tmdb's service
        target = _resolve_dns_ref("tmdb.worldinmovies.svc.cluster.local", index)
        assert target == "worldinmovies/tmdb", f"Expected worldinmovies/tmdb, got {target}"

    def test_self_reference_no_warning(self):
        """
        When an app references its own Service (intra-App composition),
        the resolver returns the caller's own app_id. resolve_edges then
        suppresses the edge and warning (no broken-ref).
        """
        monitoring = _make_app(
            "monitoring",
            name="monitoring",
            domain="monitoring",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="loki-gateway", namespace="monitoring"),
            ],
            services=[
                Service(name="loki-gateway", namespace="monitoring"),
            ],
        )
        apps = [monitoring]
        index = build_resolution_index(apps)

        # Self-reference: monitoring calls its own loki-gateway
        target = _resolve_dns_ref("loki-gateway.monitoring.svc.cluster.local", index)
        assert target == "monitoring", f"Expected monitoring (self), got {target}"

        # In resolve_edges, this should produce no edge and no warning
        monitoring.refs.append(Ref(
            raw="loki-gateway.monitoring.svc.cluster.local",
            kind="dns-full",
            file="values.yaml",
        ))
        edges, warnings = resolve_edges(apps, Path("/tmp/flux"))
        dns_edges = [e for e in edges if e.type == "dns-ref"]
        broken = [w for w in warnings if w.kind == "broken-ref"]
        assert len(dns_edges) == 0, f"Self-ref should not create edge: {dns_edges}"
        assert len(broken) == 0, f"Self-ref should not create warning: {broken}"
        # The ref should be marked as resolved_to=self
        assert monitoring.refs[0].resolved_to == "monitoring"

    def test_exact_service_match_priority(self):
        """
        When an exact Service manifest exists, it takes priority over fallback.
        """
        backend = _make_app(
            "apps/backend",
            name="backend",
            domain="apps",
            services=[Service(name="backend", namespace="apps")],
        )
        frontend = _make_app(
            "apps/frontend",
            name="frontend",
            domain="apps",
        )
        apps = [backend, frontend]
        index = build_resolution_index(apps)

        target = _resolve_dns_ref("backend.apps.svc.cluster.local", index)
        assert target == "apps/backend", f"Expected apps/backend, got {target}"

    def test_short_fqdn_unresolvable(self):
        """Short-form FQDN (single label before .svc) returns None."""
        index = build_resolution_index([])
        assert _resolve_dns_ref("redis.svc.cluster.local", index) is None

    def test_namespace_dir_fallback_postgres(self):
        """
        Gap 1 regression: operator-created Service (CloudNativePG creates
        postgres-rw from HR postgres-cluster) matches neither app.name nor
        HR name. Legacy namespace==dir fallback must resolve it.
        """
        postgres = _make_app(
            "infrastructure/postgres",
            name="postgres",
            domain="infrastructure",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="postgres-cluster", namespace="postgres"),
            ],
        )
        other = _make_app(
            "infrastructure/other",
            name="other",
            domain="infrastructure",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="other", namespace="other"),
            ],
        )
        apps = [postgres, other]
        index = build_resolution_index(apps)

        target = _resolve_dns_ref("postgres-rw.postgres.svc.cluster.local", index)
        assert target == "infrastructure/postgres", f"Expected infrastructure/postgres, got {target}"

    def test_legacy_fallback_self_suppressed(self):
        """
        Legacy fallback self-ref (namespace == caller's own dir name) resolves
        to self; resolve_edges suppresses edge + warning.
        """
        monitoring = _make_app(
            "monitoring/loki",
            name="loki",
            domain="monitoring",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="loki-stack", namespace="monitoring"),
            ],
        )
        apps = [monitoring]
        index = build_resolution_index(apps)

        # loki-gateway.monitoring matches no app/workload/HR name, but
        # namespace 'monitoring' != dir 'loki'... use a matching self case:
        # daily-digest-api.daily-digest where app dir is daily-digest.
        digest = _make_app(
            "apps/daily-digest",
            name="daily-digest",
            domain="apps",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="digest-api", namespace="daily-digest"),
            ],
        )
        apps2 = [digest]
        index2 = build_resolution_index(apps2)
        target = _resolve_dns_ref("daily-digest-api.daily-digest.svc.cluster.local", index2)
        assert target == "apps/daily-digest", f"Expected apps/daily-digest, got {target}"

        digest.refs.append(Ref(
            raw="daily-digest-api.daily-digest.svc.cluster.local",
            kind="dns-full",
            file="values.yaml",
        ))
        edges, warnings = resolve_edges(apps2, Path("/tmp/flux"))
        assert not [e for e in edges if e.type == "dns-ref"]
        assert not [w for w in warnings if w.kind == "broken-ref"]
        assert digest.refs[0].resolved_to == "apps/daily-digest"

    def test_unmodeled_service_stays_broken(self):
        """
        Genuinely unmodeled service (no Service manifest, no name match,
        no dir match) must remain unresolvable → broken-ref.
        """
        stipendiatet = _make_app(
            "stipendiatet/backend",
            name="backend",
            domain="stipendiatet",
            flux_objects=[
                FluxObject(kind="HelmRelease", name="backend", namespace="stipendiatet"),
            ],
        )
        apps = [stipendiatet]
        index = build_resolution_index(apps)

        target = _resolve_dns_ref("browserless.stipendiatet.svc.cluster.local", index)
        assert target is None, f"Expected None (unmodeled), got {target}"

        stipendiatet.refs.append(Ref(
            raw="browserless.stipendiatet.svc.cluster.local",
            kind="dns-full",
            file="values.yaml",
        ))
        edges, warnings = resolve_edges(apps, Path("/tmp/flux"))
        broken = [w for w in warnings if w.kind == "broken-ref"]
        assert len(broken) == 1
        assert "browserless.stipendiatet.svc.cluster.local" in broken[0].detail

    def test_named_ingress_block_extraction(self):
        """
        Gap 2: bjw-s/common-chart named blocks (ingress.main.hosts[].host)
        must populate ingress_hosts.
        """
        from flux_topology.extract import _extract_ingress_from_helmrelease
        app = _make_app("ai/agent0", name="agent0", domain="ai")
        doc = {
            "spec": {
                "values": {
                    "ingress": {
                        "main": {
                            "enabled": True,
                            "hosts": [
                                {"host": "agentzero.labb.site"},
                                {"host": "agent-code.labb.site"},
                            ],
                        },
                        "className": "traefik",
                        "annotations": {"foo": "bar"},
                    }
                }
            }
        }
        _extract_ingress_from_helmrelease(app, doc)
        assert "agentzero.labb.site" in app.ingress_hosts
        assert "agent-code.labb.site" in app.ingress_hosts


class TestExternalResolution:
    """Tests for _resolve_external_ref behavior via ResolutionIndex."""

    def test_wildcard_match(self):
        """
        App declares wildcard ingress host *.labb.site.
        Ref to foo.labb.site should resolve via wildcard suffix match.
        """
        ingress_controller = _make_app(
            "infra/traefik",
            name="traefik",
            domain="infra",
            ingress_hosts=["*.labb.site"],
        )
        app_a = _make_app(
            "apps/app-a",
            name="app-a",
            domain="apps",
        )
        apps = [ingress_controller, app_a]
        index = build_resolution_index(apps)

        target = _resolve_external_ref("agentzero.labb.site", index)
        assert target == "infra/traefik", f"Expected infra/traefik, got {target}"

        target = _resolve_external_ref("hermes.labb.site", index)
        assert target == "infra/traefik", f"Expected infra/traefik, got {target}"

    def test_self_reference_no_warning(self):
        """
        When an app references its own ingress host, the resolver returns
        the caller's own app_id. resolve_edges suppresses edge + warning.
        """
        agent0 = _make_app(
            "ai/agent0",
            name="agent0",
            domain="ai",
            ingress_hosts=["agentzero.labb.site"],
        )
        apps = [agent0]
        index = build_resolution_index(apps)

        target = _resolve_external_ref("agentzero.labb.site", index)
        assert target == "ai/agent0", f"Expected ai/agent0 (self), got {target}"

        agent0.refs.append(Ref(
            raw="agentzero.labb.site",
            kind="external",
            file="values.yaml",
        ))
        edges, warnings = resolve_edges(apps, Path("/tmp/flux"))
        ext_edges = [e for e in edges if e.type == "external-ref"]
        broken = [w for w in warnings if w.kind == "broken-ref"]
        assert len(ext_edges) == 0, f"Self-ref should not create edge: {ext_edges}"
        assert len(broken) == 0, f"Self-ref should not create warning: {broken}"
        assert agent0.refs[0].resolved_to == "ai/agent0"

    def test_cross_app_exact_match(self):
        """
        App A references App B's exact ingress host → external-ref edge.
        """
        app_a = _make_app(
            "apps/app-a",
            name="app-a",
            domain="apps",
            ingress_hosts=["app-a.labb.site"],
        )
        app_b = _make_app(
            "apps/app-b",
            name="app-b",
            domain="apps",
            ingress_hosts=["app-b.labb.site"],
        )
        apps = [app_a, app_b]
        index = build_resolution_index(apps)

        target = _resolve_external_ref("app-b.labb.site", index)
        assert target == "apps/app-b", f"Expected apps/app-b, got {target}"

        # Full resolve_edges flow
        app_a.refs.append(Ref(
            raw="app-b.labb.site",
            kind="external",
            file="values.yaml",
        ))
        edges, warnings = resolve_edges(apps, Path("/tmp/flux"))
        ext_edges = [e for e in edges if e.type == "external-ref"]
        assert len(ext_edges) == 1
        assert ext_edges[0].from_app == "apps/app-a"
        assert ext_edges[0].to_app == "apps/app-b"
        assert ext_edges[0].evidence == "External host: app-b.labb.site"

    def test_wildcard_fallback_when_exact_also_exists(self):
        """
        If an app has both exact and wildcard hosts, exact takes priority.
        (Order of iteration in build_resolution_index: exact first, then wildcard
        only if not already in exact.)
        """
        app_a = _make_app(
            "apps/app-a",
            name="app-a",
            domain="apps",
            ingress_hosts=["specific.labb.site", "*.labb.site"],
        )
        apps = [app_a]
        index = build_resolution_index(apps)

        # Exact host should match exact index
        target = _resolve_external_ref("specific.labb.site", index)
        assert target == "apps/app-a"

        # Other subdomain falls through to wildcard
        target = _resolve_external_ref("other.labb.site", index)
        assert target == "apps/app-a"

    def test_wildcard_no_match_bare_domain(self):
        """
        Wildcard *.labb.site should NOT match bare labb.site (no subdomain).
        """
        app = _make_app(
            "infra/traefik",
            name="traefik",
            domain="infra",
            ingress_hosts=["*.labb.site"],
        )
        apps = [app]
        index = build_resolution_index(apps)

        target = _resolve_external_ref("labb.site", index)
        assert target is None, "Bare domain should not match *.labb.site wildcard"


class TestResolveEdgesIntegration:
    """End-to-end resolve_edges tests combining DNS + external."""

    def test_mixed_refs_no_false_positives(self):
        """
        A realistic mix: cross-app DNS ref, self DNS ref, cross-app external,
        self external, genuinely broken ref.
        """
        backend = _make_app(
            "apps/backend",
            name="backend",
            domain="apps",
            services=[Service(name="backend", namespace="apps")],
            ingress_hosts=["backend.labb.site"],
        )
        frontend = _make_app(
            "apps/frontend",
            name="frontend",
            domain="apps",
            ingress_hosts=["frontend.labb.site"],
        )
        apps = [backend, frontend]

        # frontend refs:
        # 1. backend.apps.svc.cluster.local -> cross-app DNS (edge)
        # 2. frontend.apps.svc.cluster.local -> self DNS (no edge, no warning)
        # 3. backend.labb.site -> cross-app external (edge)
        # 4. frontend.labb.site -> self external (no edge, no warning)
        # 5. missing.apps.svc.cluster.local -> genuinely broken (warning)
        frontend.refs.extend([
            Ref(raw="backend.apps.svc.cluster.local", kind="dns-full", file="values.yaml"),
            Ref(raw="frontend.apps.svc.cluster.local", kind="dns-full", file="values.yaml"),
            Ref(raw="backend.labb.site", kind="external", file="values.yaml"),
            Ref(raw="frontend.labb.site", kind="external", file="values.yaml"),
            Ref(raw="missing.apps.svc.cluster.local", kind="dns-full", file="values.yaml"),
        ])

        edges, warnings = resolve_edges(apps, Path("/tmp/flux"))

        dns_edges = [e for e in edges if e.type == "dns-ref"]
        ext_edges = [e for e in edges if e.type == "external-ref"]
        broken = [w for w in warnings if w.kind == "broken-ref"]

        assert len(dns_edges) == 1, f"Expected 1 dns-ref edge, got {len(dns_edges)}"
        assert dns_edges[0].from_app == "apps/frontend"
        assert dns_edges[0].to_app == "apps/backend"

        assert len(ext_edges) == 1, f"Expected 1 external-ref edge, got {len(ext_edges)}"
        assert ext_edges[0].from_app == "apps/frontend"
        assert ext_edges[0].to_app == "apps/backend"

        assert len(broken) == 1, f"Expected 1 broken-ref warning, got {len(broken)}"
        assert "missing.apps.svc.cluster.local" in broken[0].detail

        # Self refs resolved but no edges/warnings
        self_dns_ref = next(r for r in frontend.refs if r.raw == "frontend.apps.svc.cluster.local")
        self_ext_ref = next(r for r in frontend.refs if r.raw == "frontend.labb.site")
        assert self_dns_ref.resolved_to == "apps/frontend"
        assert self_ext_ref.resolved_to == "apps/frontend"