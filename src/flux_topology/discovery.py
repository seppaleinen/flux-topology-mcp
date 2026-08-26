"""Discover Apps and Domains in a FluxCD repository."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from .models import App, FluxObject
from .yamlsafe import read_yaml, read_yaml_all, read_text


# HelmRelease filename pattern (case-insensitive glob)
HR_GLOB = "*helmrelease*.yaml"

# Known Flux CRD kinds
FLUX_CRD_KINDS = {"HelmRelease", "Kustomization", "HelmRepository",
                  "GitRepository", "OCIRepository", "HelmChart",
                  "Alert", "Provider", "Receiver"}

# Kubernetes workload kinds
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob"}

# SOPS encryption markers
SOPS_MARKERS = ("ENC[AES256_GCM,", "sops:", "SOPS:")

# Flux CRD apiVersion prefixes
FLUX_API_PREFIXES = ("helm.toolkit.fluxcd.io", "kustomize.toolkit.fluxcd.io",
                     "source.toolkit.fluxcd.io", "notification.toolkit.fluxcd.io",
                     "image.toolkit.fluxcd.io")


def find_app_signals(directory: Path) -> tuple[bool, list[str]]:
    """Check if a directory is an App by examining its contents.

    Returns (is_app, list_of_signal_descriptions).
    """
    signals: list[str] = []

    # Signal 1: HelmRelease file(s)
    for f in directory.glob(HR_GLOB):
        signals.append(f"helmrelease:{f.name}")

    # Signal 2: Local Chart.yaml with templates/ containing workloads
    chart_yaml = directory / "Chart.yaml"
    templates_dir = directory / "templates"
    if chart_yaml.exists() and templates_dir.is_dir():
        has_workload = False
        for tf in templates_dir.iterdir():
            if tf.is_file() and tf.suffix in (".yaml", ".yml"):
                docs = read_yaml_all(tf)
                for doc in docs:
                    if isinstance(doc, dict) and doc.get("kind") in WORKLOAD_KINDS:
                        has_workload = True
                        break
            if has_workload:
                break
        if has_workload:
            signals.append("local-chart")

    # Signal 3: Kustomization with file resources (not only child dirs)
    kust_file = directory / "kustomization.yaml"
    if kust_file.exists():
        text = read_text(kust_file)
        if text:
            kust = read_yaml(kust_file)
            if isinstance(kust, dict):
                resources = kust.get("resources", [])
                if resources and isinstance(resources, list):
                    has_file_res = False
                    for r in resources:
                        if isinstance(r, str):
                            rpath = directory / r
                            if rpath.is_file():
                                has_file_res = True
                                break
                    if has_file_res:
                        signals.append("kustomization-files")

    # Signal 4: Standalone workload manifests
    for f in directory.iterdir():
        if f.is_file() and f.suffix in (".yaml", ".yml"):
            if any(g in f.name.lower() for g in ("helmrelease", "kustomization",
                                                   "kustomizeconfig", "secrets")):
                continue
            docs = read_yaml_all(f)
            for doc in docs:
                if isinstance(doc, dict):
                    if doc.get("apiVersion", "").startswith(FLUX_API_PREFIXES):
                        kind = doc.get("kind", "")
                        if kind in WORKLOAD_KINDS:
                            signals.append(f"standalone-workload:{f.name}")
                            break

    return bool(signals), signals


def discover_apps(flux_root: Path) -> list[App]:
    """Walk a flux/ directory tree and discover Apps via ownership-based detection.

    Returns a list of App objects with id, name, domain, path, signals.
    """
    all_apps: list[App] = []
    app_paths: set[Path] = set()

    def _walk(path: Path) -> None:
        if not path.is_dir():
            return

        is_app, signals = find_app_signals(path)

        if is_app:
            rel = path.relative_to(flux_root)
            parts = list(rel.parts)
            domain = parts[0] if parts else rel.name
            app = App(
                id=str(rel),
                name=path.name,
                domain=domain,
                path=str(rel),
                signals=signals,
            )
            all_apps.append(app)
            app_paths.add(path)

            # Recurse into children — nested Apps will be picked up
            for child in sorted(path.iterdir()):
                if child.is_dir() and child.name != ".git":
                    _walk(child)
            return

        # Not an App — recurse into children
        for child in sorted(path.iterdir()):
            if child.is_dir() and child.name != ".git":
                _walk(child)

    # Discover all apps
    _walk(flux_root)

    # Build ownership mapping: which directory is owned by which App
    owned: dict[Path, App] = {}
    for app in all_apps:
        app_dir = flux_root / app.path
        for child in sorted(app_dir.rglob("*")):
            if child.is_dir() and child not in app_paths:
                owned[child] = app

    # Assign domain to nested apps (owned by another app)
    for app in all_apps:
        if "/" in app.id:
            # Check if this app is nested inside another app
            parts = app.id.split("/")
            # Walk up to find the nearest ancestor app
            for i in range(len(parts) - 1, 0, -1):
                ancestor_path = flux_root / "/".join(parts[:i])
                if ancestor_path in app_paths:
                    # This app is nested — domain is the top-level component
                    app.domain = parts[0]
                    break

    return all_apps


def resolve_domain(app_path: str) -> str:
    """Extract the domain (top-level dir under flux/) from an app path."""
    parts = app_path.split("/")
    return parts[0] if parts else ""


def is_grouping_only_kustomization(directory: Path) -> bool:
    """Check if a kustomization.yaml at this path only references child directories.

    Used to distinguish domain-level grouping from app-level kustomizations.
    """
    kust_file = directory / "kustomization.yaml"
    if not kust_file.exists():
        return False
    text = read_text(kust_file)
    if not text:
        return False
    kust = read_yaml(kust_file)
    if not isinstance(kust, dict):
        return False
    resources = kust.get("resources", [])
    if not resources or not isinstance(resources, list):
        return False
    if not resources:
        return False
    for r in resources:
        if isinstance(r, str):
            rpath = directory / r
            if not rpath.is_dir():
                return False
    return True
