"""Edge extraction and resolution for the Flux Topology graph."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    # Build a resolution index once per call (exact Service index, fallback
    # name+namespace sets, exact + wildcard ingress indices).
    index = build_resolution_index(apps)

    # Resolve dns-ref edges
    for app in apps:
        for ref in app.refs:
            if ref.kind == "dns-full":
                target_id = _resolve_dns_ref(ref.raw, index)
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
                target_id = _resolve_external_ref(ref.raw, index)
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


@dataclass
class ResolutionIndex:
    """Precomputed index for DNS / external reference resolution.

    Built once per ``resolve_edges()`` call so that the (potentially large)
    app list is not re-scanned for every reference.
    """

    # Exact Service match: (service_name, namespace) -> app_id
    service_index: dict[tuple[str, str], str] = field(default_factory=dict)
    # Fallback: app_id -> set of candidate service names (app.name, HR names,
    # workload names). Used when no exact Service was extracted.
    app_service_names: dict[str, set[str]] = field(default_factory=dict)
    # Fallback: app_id -> set of candidate namespaces (HR metadata.namespace,
    # Service namespaces, app.domain). The domain is the fleet-infra default
    # namespace and is added as a last-resort fallback.
    app_namespaces: dict[str, set[str]] = field(default_factory=dict)
    # Exact ingress host -> app_id
    ingress_exact: dict[str, str] = field(default_factory=dict)
    # Wildcard suffix (e.g. "labb.site" from "*.labb.site") -> app_id
    ingress_wildcard: dict[str, str] = field(default_factory=dict)


def build_resolution_index(apps: list[App]) -> ResolutionIndex:
    """Build a ResolutionIndex from the extracted app data.

    The index is conservative: it only records facts that were actually
    extracted from the repo (Service manifests, HelmRelease metadata,
    ingress hosts). It never renders Helm templates or queries a cluster.
    """
    index = ResolutionIndex()

    for app in apps:
        # Candidate service names for fallback resolution.
        names: set[str] = set()
        names.add(app.name)
        for fo in app.flux_objects:
            if fo.kind in ("HelmRelease", "Kustomization"):
                names.add(fo.name)
        for wl in app.workloads:
            names.add(wl.name)
        index.app_service_names[app.id] = names

        # Candidate namespaces: HR metadata.namespace + Service namespaces +
        # the app's domain (fleet-infra default namespace).
        namespaces: set[str] = set()
        for fo in app.flux_objects:
            if fo.namespace:
                namespaces.add(fo.namespace)
        for svc in app.services:
            if svc.namespace:
                namespaces.add(svc.namespace)
        namespaces.add(app.domain)
        index.app_namespaces[app.id] = namespaces

        # Exact Service index.
        for svc in app.services:
            ns = svc.namespace if svc.namespace else "<unknown>"
            # First match wins; if a Service name is duplicated across apps
            # the earlier app in the list takes precedence.
            key = (svc.name, ns)
            if key not in index.service_index:
                index.service_index[key] = app.id

        # Ingress hosts: exact vs wildcard.
        for h in app.ingress_hosts:
            if h.startswith("*."):
                suffix = h[2:]
                if suffix and suffix not in index.ingress_wildcard:
                    index.ingress_wildcard[suffix] = app.id
            elif h and h not in index.ingress_exact:
                index.ingress_exact[h] = app.id

    return index


def _resolve_dns_ref(fqdn: str, index: ResolutionIndex) -> str | None:
    """Resolve a DNS FQDN to an app ID.

    FQDN format: ``service-name.namespace.svc.cluster.local``

    Resolution order:
      1. Exact Service match on ``(service_name, namespace)`` — only succeeds
         if a ``kind: Service`` manifest was actually extracted for that
         (name, namespace) pair.
      2. Fallback: ``service_name`` matches one of the app's known names AND
         ``namespace`` matches one of the app's known namespaces. This covers
         fleet-infra where the Kubernetes namespace equals the app's domain
         (top-level ``flux/`` dir) rather than the app's directory name, and
         where the Service is defined in Helm values (not extracted).
      3. Legacy fallback: ``namespace`` equals the app's directory name (last
         path segment of the app id). This covers operator-created Services
         (e.g. CloudNativePG creates ``postgres-rw`` from a HelmRelease named
         ``postgres-cluster``) where the service name matches neither the app
         name nor any HR/workload name, but the namespace still identifies
         the owning app directory.

    Returns the target app id, or ``None`` if unresolvable. A self-reference
    (target == caller) is a valid resolution — ``resolve_edges`` suppresses
    the edge and warning for intra-App composition.
    """
    parts = fqdn.split(".")
    if len(parts) < 3:
        return None

    # Find the "svc" label; the namespace is the label immediately before it.
    svc_idx = None
    for i, p in enumerate(parts):
        if p == "svc":
            svc_idx = i
            break
    if svc_idx is None or svc_idx < 2:
        return None

    service_name = parts[0]
    namespace = parts[svc_idx - 1]

    # 1. Exact Service match.
    for ns_key in (namespace, "<unknown>"):
        key = (service_name, ns_key)
        if key in index.service_index:
            return index.service_index[key]

    # 2. Fallback: service_name ∈ app's known names AND namespace ∈ app's
    #    known namespaces (HR namespace, Service namespace, or domain).
    for app_id, names in index.app_service_names.items():
        if service_name in names and namespace in index.app_namespaces.get(app_id, set()):
            return app_id

    # 3. Legacy fallback: namespace == app directory name (last path segment
    #    of the app id). First match in index insertion order wins.
    for app_id in index.app_service_names:
        if namespace == app_id.split("/")[-1]:
            return app_id

    return None


def _resolve_external_ref(host: str, index: ResolutionIndex) -> str | None:
    """Resolve an external hostname to an app by ingress host mapping.

    Resolution order:
      1. Exact host match (including self-references, which return the
         caller's own app id — ``resolve_edges`` suppresses those).
      2. Wildcard suffix match (e.g. ``foo.labb.site`` against an app that
         declares ``*.labb.site``).

    Returns the target app id, or ``None`` if unresolvable.
    """
    # 1. Exact match.
    if host in index.ingress_exact:
        return index.ingress_exact[host]

    # 2. Wildcard suffix match.
    for suffix, app_id in index.ingress_wildcard.items():
        # *.suffix matches foo.suffix, bar.baz.suffix, etc.
        # but NOT bare "suffix" (apex domain).
        if host.endswith("." + suffix):
            return app_id

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
