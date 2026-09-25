"""Depth-B extraction per App: workloads, services, ingress hosts, refs."""

from __future__ import annotations

import re
from pathlib import Path

from .models import App, Workload, Service, FluxObject, Ref
from .yamlsafe import read_yaml, read_yaml_all, read_text


# Known Flux CRD kinds for flux_objects extraction
FLUX_CRD_KINDS = {"HelmRelease", "Kustomization", "HelmRepository",
                  "GitRepository", "OCIRepository", "HelmChart",
                  "Alert", "Provider", "Receiver"}

FLUX_API_PREFIXES = ("helm.toolkit.fluxcd.io", "kustomize.toolkit.fluxcd.io",
                     "source.toolkit.fluxcd.io", "notification.toolkit.fluxcd.io",
                     "image.toolkit.fluxcd.io")

SOPS_MARKERS = ("ENC[AES256_GCM,", "sops:", "SOPS:")

# Reference patterns
DNS_FULL_RE = re.compile(r"\w[\w.-]*\.svc\.cluster\.local")
EXTERNAL_HOST_RE = re.compile(r"[\w.-]+\.labb\.site")
GENERIC_HOST_RE = re.compile(r"\b[\w.-]+\.[\w.-]+\.[\w.-]+\b")

# Ingress host extraction patterns.
# Traefik IngressRoute `match` fields use the form `Host(\`...\`)`, which may
# include wildcards (e.g. `Host(\`*.labb.site\`)`). Capture both that form and
# the plain `host:` literal so wildcard hosts are not silently dropped.
INGRESSROUTE_HOST_RE = re.compile(
    r"Host\(`([^`]+)`\)|host:\s*['\"]?([^'\"\s,]+)['\"]?"
)
HOSTNAME_RE = re.compile(r"hostname:\s*['\"]?([^'\"\s,]+)['\"]?")


def extract_app_data(app: App, flux_root: Path) -> None:
    """Extract all depth-B data for an App in-place.

    Populates: workloads, services, ingress_hosts, flux_objects, encrypted, refs.
    """
    app_dir = flux_root / app.path

    # Collect all YAML-ish text for ref scanning and SOPS detection
    all_yaml_text: list[tuple[str, str]] = []  # (text, filename)

    # Process HelmRelease files
    for f in sorted(app_dir.glob("*helmrelease*.yaml")):
        docs = read_yaml_all(f)
        for doc in docs:
            if isinstance(doc, dict):
                _extract_flux_object(app, doc)
                _extract_workloads_from_helmrelease(app, doc)
                _extract_ingress_from_helmrelease(app, doc)
        text = read_text(f)
        if text:
            all_yaml_text.append((text, f.name))

    # Process values files
    for vf in ["values.yaml", "values.yml"]:
        vpath = app_dir / vf
        if vpath.exists():
            text = read_text(vpath)
            if text:
                all_yaml_text.append((text, vf))

    # Process configmap files
    for f in app_dir.glob("configmap*.yaml"):
        text = read_text(f)
        if text:
            all_yaml_text.append((text, f.name))

    # Process secrets files (for SOPS detection)
    for f in app_dir.glob("secrets*"):
        if f.is_file():
            text = read_text(f)
            if text:
                all_yaml_text.append((text, f.name))

    # Process template files (Helm chart templates)
    templates_dir = app_dir / "templates"
    if templates_dir.is_dir():
        for f in sorted(templates_dir.iterdir()):
            if f.is_file() and f.suffix in (".yaml", ".yml"):
                text = read_text(f)
                if text:
                    all_yaml_text.append((text, f.name))
                    # Parse after Go template stripping for workload/service/ingress
                    docs = read_yaml_all(f)
                    for doc in docs:
                        if isinstance(doc, dict):
                            _extract_workload_from_raw(app, doc)
                            _extract_service(app, doc)
                            _extract_ingress(app, doc)

    # Process raw workload manifests (non-HelmRelease, non-kustomization files)
    for f in sorted(app_dir.iterdir()):
        if f.is_file() and f.suffix in (".yaml", ".yml"):
            if any(g in f.name.lower() for g in ("helmrelease", "kustomization",
                                                   "kustomizeconfig", "secrets",
                                                   "values", "configmap")):
                continue
            docs = read_yaml_all(f)
            for doc in docs:
                if isinstance(doc, dict):
                    _extract_flux_object(app, doc)
                    _extract_workload_from_raw(app, doc)
                    _extract_service(app, doc)
                    _extract_ingress(app, doc)
            text = read_text(f)
            if text:
                all_yaml_text.append((text, f.name))

    # Check SOPS encryption
    for text, _ in all_yaml_text:
        if any(marker in text for marker in SOPS_MARKERS):
            app.encrypted = True
            break

    # Scan for refs
    _scan_refs(app, all_yaml_text, app_dir, flux_root)


def _extract_flux_object(app: App, doc: dict) -> None:
    """Extract Flux CRD objects from a YAML doc."""
    api = doc.get("apiVersion", "")
    kind = doc.get("kind", "")
    if api.startswith(FLUX_API_PREFIXES) and kind in FLUX_CRD_KINDS:
        meta = doc.get("metadata", {})
        name = meta.get("name", "")
        namespace = meta.get("namespace")
        if name:
            app.flux_objects.append(FluxObject(
                kind=kind, name=name, namespace=namespace))


def _extract_workloads_from_helmrelease(app: App, doc: dict) -> None:
    """Extract workload info from HelmRelease spec.values."""
    spec = doc.get("spec", {})
    values = spec.get("values", {})
    if not isinstance(values, dict):
        return

    # Check for replica counts in values
    for kind in ("deployment", "statefulset", "daemonset"):
        block = values.get(kind, {})
        if isinstance(block, dict) and "replicas" in block:
            name = app.name
            if kind == "statefulset":
                name = f"{app.name}-statefulset"
            app.workloads.append(Workload(
                kind=kind.capitalize(),
                name=name,
                replicas=block["replicas"],
            ))


def _extract_ingress_from_helmrelease(app: App, doc: dict) -> None:
    """Extract ingress hosts from HelmRelease spec.values.ingress."""
    spec = doc.get("spec", {})
    values = spec.get("values", {})
    if not isinstance(values, dict):
        return

    ingress = values.get("ingress", {})
    if not isinstance(ingress, dict):
        return

    # Single host: ingress.host
    host = ingress.get("host", "")
    if isinstance(host, str) and host and host not in app.ingress_hosts:
        app.ingress_hosts.append(host)

    # Single hostname: ingress.hostname
    hostname = ingress.get("hostname", "")
    if isinstance(hostname, str) and hostname and hostname not in app.ingress_hosts:
        app.ingress_hosts.append(hostname)

    # Multiple hosts: ingress.hosts[].host
    hosts_list = ingress.get("hosts", [])
    if isinstance(hosts_list, list):
        for h in hosts_list:
            if isinstance(h, dict):
                h_host = h.get("host", "")
                if isinstance(h_host, str) and h_host and h_host not in app.ingress_hosts:
                    app.ingress_hosts.append(h_host)

    # ingress.hosts[].hostname (some charts use this)
    if isinstance(hosts_list, list):
        for h in hosts_list:
            if isinstance(h, dict):
                h_name = h.get("hostname", "")
                if isinstance(h_name, str) and h_name and h_name not in app.ingress_hosts:
                    app.ingress_hosts.append(h_name)

    # global.host (used by dify and similar charts)
    global_config = values.get("global", {})
    if isinstance(global_config, dict):
        g_host = global_config.get("host", "")
        if isinstance(g_host, str) and g_host and g_host not in app.ingress_hosts:
            app.ingress_hosts.append(g_host)

    # Named ingress blocks (bjw-s/common-chart style, one level deep):
    #   ingress:
    #     main:
    #       enabled: true
    #       hosts:
    #         - host: foo.labb.site
    # Skip non-dict values (enabled, className, annotations, etc.).
    for sub in ingress.values():
        if not isinstance(sub, dict):
            continue
        _extract_hosts_from_ingress_block(app, sub)


def _extract_hosts_from_ingress_block(app: App, block: dict) -> None:
    """Extract host/hostname/hosts[].host/hosts[].hostname from one ingress sub-block."""
    host = block.get("host", "")
    if isinstance(host, str) and host and host not in app.ingress_hosts:
        app.ingress_hosts.append(host)

    hostname = block.get("hostname", "")
    if isinstance(hostname, str) and hostname and hostname not in app.ingress_hosts:
        app.ingress_hosts.append(hostname)

    hosts_list = block.get("hosts", [])
    if isinstance(hosts_list, list):
        for h in hosts_list:
            if isinstance(h, dict):
                for key in ("host", "hostname"):
                    val = h.get(key, "")
                    if isinstance(val, str) and val and val not in app.ingress_hosts:
                        app.ingress_hosts.append(val)


def _extract_workload_from_raw(app: App, doc: dict) -> None:
    """Extract workloads from raw Kubernetes manifests."""
    kind = doc.get("kind", "")
    if kind in ("Deployment", "StatefulSet", "DaemonSet"):
        meta = doc.get("metadata", {})
        name = meta.get("name", "")
        spec = doc.get("spec", {})
        replicas = spec.get("replicas")

        # Extract from pod template
        template = spec.get("template", {})
        pod_meta = template.get("metadata", {})
        labels = pod_meta.get("labels", {})
        containers = template.get("spec", {}).get("containers", [])

        workload_name = name or app.name
        app.workloads.append(Workload(
            kind=kind,
            name=workload_name,
            replicas=replicas,
        ))

    elif kind == "CronJob":
        meta = doc.get("metadata", {})
        name = meta.get("name", "")
        app.workloads.append(Workload(
            kind="CronJob",
            name=name or f"{app.name}-cronjob",
        ))


def _extract_service(app: App, doc: dict) -> None:
    """Extract Service information from a Kubernetes Service manifest."""
    if doc.get("kind") != "Service":
        return
    meta = doc.get("metadata", {})
    spec = doc.get("spec", {})
    selector = spec.get("selector", {})
    ports = spec.get("ports", [])

    svc_name = meta.get("name", "")
    namespace = meta.get("namespace", "")
    port_str = ""
    if ports and isinstance(ports, list) and ports[0]:
        port_val = ports[0].get("port")
        port_str = str(port_val) if port_val else ""

    if svc_name:
        app.services.append(Service(
            name=svc_name,
            namespace=namespace or None,
            port=port_str or None,
            selector=selector if isinstance(selector, dict) else {},
        ))


def _extract_ingress(app: App, doc: dict) -> None:
    """Extract ingress hosts from IngressRoute/Ingress/HTTPRoute resources."""
    kind = doc.get("kind", "")

    if kind == "IngressRoute":
        spec = doc.get("spec", {})
        routes = spec.get("routes", [])
        for route in routes:
            if isinstance(route, dict):
                match = route.get("match", "")
                if isinstance(match, str):
                    m = INGRESSROUTE_HOST_RE.search(match)
                    if m:
                        # group(1): Host(`...`) form; group(2): host: literal
                        host = m.group(1) or m.group(2)
                        if host and host not in app.ingress_hosts:
                            app.ingress_hosts.append(host)

    elif kind == "Ingress":
        spec = doc.get("spec", {})
        rules = spec.get("rules", [])
        for rule in rules:
            if isinstance(rule, dict):
                host = rule.get("host", "")
                if host and host not in app.ingress_hosts:
                    app.ingress_hosts.append(host)

    elif kind == "HTTPRoute":
        spec = doc.get("spec", {})
        hostnames = spec.get("hostnames", [])
        for h in hostnames:
            if isinstance(h, str) and h not in app.ingress_hosts:
                app.ingress_hosts.append(h)


def _scan_refs(app: App, all_yaml_text: list[tuple[str, str]],
               app_dir: Path, flux_root: Path) -> None:
    """Scan all YAML-ish text for DNS and external references."""
    seen: set[str] = set()

    for text, filename in all_yaml_text:
        if not text:
            continue

        # DNS full references (FQDN)
        for m in DNS_FULL_RE.finditer(text):
            raw = m.group()
            if raw in seen:
                continue
            seen.add(raw)
            ref = Ref(raw=raw, kind="dns-full", file=filename)
            app.refs.append(ref)

        # External references (*.labb.site)
        for m in EXTERNAL_HOST_RE.finditer(text):
            raw = m.group()
            if raw in seen:
                continue
            seen.add(raw)
            ref = Ref(raw=raw, kind="external", file=filename)
            app.refs.append(ref)


def extract_app(app: App, flux_root: Path) -> None:
    """Convenience wrapper: extract data and resolve refs."""
    extract_app_data(app, flux_root)
