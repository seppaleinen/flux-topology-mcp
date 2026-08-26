"""Edge extraction and resolution for the Flux Topology graph."""

from __future__ import annotations

from pathlib import Path

from .models import App, Edge, Warning, WiringGraph, FluxObject
from .yamlsafe import read_yaml, read_text


# Known Flux CRD kinds
FLUX_CRD_KINDS = {"HelmRelease", "Kustomization", "HelmRepository",
                  "GitRepository", "OCIRepository", "HelmChart"}

FLUX_API_PREFIXES = ("helm.toolkit.fluxcd.io", "kustomize.toolkit.fluxcd.io",
                     "source.toolkit.fluxcd.io", "notification.toolkit.fluxcd.io",
                     "image.toolkit.fluxcd.io")


def build_lookup_index(apps: list[App]) -> dict[str, App]:
    """Build a global name→App index from Flux CRD metadata.name.

    Maps Flux object names to their owning Apps for dependsOn resolution.
    """
    index: dict[str, App] = {}
    for app in apps:
        for fo in app.flux_objects:
            index[fo.name] = app
    return index


def resolve_edges(apps: list[App], flux_root: Path) -> tuple[list[Edge], list[Warning]]:
    """Resolve all edges and warnings from extracted app data.

    Returns (edges, warnings).
    """
    lookup = build_lookup_index(apps)
    app_by_id = {a.id: a for a in apps}
    edges: list[Edge] = []
    warnings: list[Warning] = []

    # Resolve dependsOn from HelmRelease and Kustomization metadata
    for app in apps:
        app_dir = flux_root / app.path

        # Check all YAML files for dependsOn
        for f in sorted(app_dir.rglob("*.yaml")):
            docs = _read_yaml_docs(f)
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                api = doc.get("apiVersion", "")
                kind = doc.get("kind", "")
                if not api.startswith(FLUX_API_PREFIXES):
                    continue
                if kind not in ("HelmRelease", "Kustomization"):
                    continue

                spec = doc.get("spec", {})
                depends_on = spec.get("dependsOn", [])
                if not isinstance(depends_on, list):
                    continue

                for dep in depends_on:
                    if not isinstance(dep, dict):
                        continue
                    dep_name = dep.get("name", "")
                    dep_namespace = dep.get("namespace", "")

                    if dep_name in lookup:
                        target_app = lookup[dep_name]
                        if target_app.id != app.id:
                            edges.append(Edge(
                                from_app=app.id,
                                to_app=target_app.id,
                                type="dependsOn",
                                evidence=f"dependsOn: {dep_name}",
                            ))
                    else:
                        warnings.append(Warning(
                            app=app.id,
                            kind="unresolved-dependsOn",
                            detail=f"dependsOn '{dep_name}' not found in flux/ tree",
                        ))

    # Resolve dns-ref edges
    for app in apps:
        for ref in app.refs:
            if ref.kind == "dns-full":
                target_id = _resolve_dns_ref(ref.raw, apps, app.id)
                if target_id:
                    ref.resolved_to = target_id
                    if target_id != app.id:
                        edges.append(Edge(
                            from_app=app.id,
                            to_app=target_id,
                            type="dns-ref",
                            evidence=f"DNS: {ref.raw}",
                        ))
                else:
                    warnings.append(Warning(
                        app=app.id,
                        kind="broken-ref",
                        detail=f"DNS ref '{ref.raw}' has no matching app",
                    ))

    # Resolve external-ref edges
    for app in apps:
        for ref in app.refs:
            if ref.kind == "external":
                target_id = _resolve_external_ref(ref.raw, apps, app.id)
                if target_id:
                    ref.resolved_to = target_id
                    if target_id != app.id:
                        edges.append(Edge(
                            from_app=app.id,
                            to_app=target_id,
                            type="external-ref",
                            evidence=f"External host: {ref.raw}",
                        ))
                else:
                    warnings.append(Warning(
                        app=app.id,
                        kind="broken-ref",
                        detail=f"External ref '{ref.raw}' has no matching app",
                    ))

    return edges, warnings


def _read_yaml_docs(path: Path) -> list[dict]:
    """Read all YAML docs from a file, tolerating errors."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []

    import re
    cleaned = re.sub(r"\{\{.*?\}\}", "", text, flags=re.DOTALL)

    import yaml
    try:
        docs = list(yaml.safe_load_all(cleaned))
        return [d for d in docs if isinstance(d, dict)]
    except yaml.YAMLError:
        return []


def _resolve_dns_ref(fqdn: str, apps: list[App], caller_id: str) -> str | None:
    """Resolve a DNS FQDN to an app ID.

    FQDN format: service-name.namespace.svc.cluster.local
    We extract the namespace and find the app whose last path segment matches.
    """
    # Extract namespace from FQDN
    parts = fqdn.split(".")
    if len(parts) < 3:
        return None

    # Find namespace: everything between first label and .svc
    svc_idx = None
    for i, p in enumerate(parts):
        if p == "svc":
            svc_idx = i
            break
    if svc_idx is None or svc_idx < 2:
        return None

    namespace = parts[svc_idx - 1]

    # Find app whose last path segment matches the namespace
    for app in apps:
        if app.id == caller_id:
            continue
        path_parts = app.path.split("/")
        if path_parts and path_parts[-1] == namespace:
            return app.id

    return None


def _resolve_external_ref(host: str, apps: list[App], caller_id: str) -> str | None:
    """Resolve an external hostname (*.labb.site) to an app by ingress host mapping."""
    for app in apps:
        if app.id == caller_id:
            continue
        if host in app.ingress_hosts:
            return app.id
    return None


def build_wiring_graph(apps: list[App], edges: list[Edge],
                       warnings: list[Warning], flux_root: Path,
                       fingerprint: dict) -> WiringGraph:
    """Build the complete WiringGraph from resolved data."""
    # Build domains
    domain_map: dict[str, list[str]] = {}
    for app in apps:
        if app.domain not in domain_map:
            domain_map[app.domain] = []
        domain_map[app.domain].append(app.id)

    domains = [{"name": d, "apps": sorted(app_ids)}
               for d, app_ids in sorted(domain_map.items())]

    return WiringGraph(
        root=str(flux_root),
        built_at=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        fingerprint=fingerprint,
        domains=domains,
        apps=[a.to_dict() for a in apps],
        edges=[e.to_dict() for e in edges],
        warnings=[w.to_dict() for w in warnings],
    )
