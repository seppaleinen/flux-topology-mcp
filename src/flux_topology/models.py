"""Data models for the Flux Topology graph."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Workload:
    kind: str
    name: str
    replicas: int | None = None

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "name": self.name}
        if self.replicas is not None:
            d["replicas"] = self.replicas
        return d


@dataclass
class Service:
    name: str
    namespace: str | None = None
    port: str | None = None
    selector: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        d: dict = {"name": self.name}
        if self.namespace:
            d["namespace"] = self.namespace
        if self.port:
            d["port"] = self.port
        if self.selector:
            d["selector"] = self.selector
        return d


@dataclass
class FluxObject:
    kind: str
    name: str
    namespace: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"kind": self.kind, "name": self.name}
        if self.namespace:
            d["namespace"] = self.namespace
        return d


@dataclass
class Ref:
    raw: str
    kind: str  # dns-full, dns-short, external
    resolved_to: str | None = None
    file: str | None = None

    def to_dict(self) -> dict:
        d: dict = {"raw": self.raw, "kind": self.kind}
        if self.resolved_to:
            d["resolved_to"] = self.resolved_to
        if self.file:
            d["file"] = self.file
        return d


@dataclass
class App:
    id: str  # relative path from flux/ e.g. "arrs/radarr"
    name: str  # directory name
    domain: str  # top-level domain under flux/
    path: str  # relative path from flux/
    signals: list[str] = field(default_factory=list)
    workloads: list[Workload] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    ingress_hosts: list[str] = field(default_factory=list)
    flux_objects: list[FluxObject] = field(default_factory=list)
    encrypted: bool = False
    refs: list[Ref] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "path": self.path,
            "signals": self.signals,
            "workloads": [w.to_dict() for w in self.workloads],
            "services": [s.to_dict() for s in self.services],
            "ingress_hosts": self.ingress_hosts,
            "flux_objects": [f.to_dict() for f in self.flux_objects],
            "encrypted": self.encrypted,
            "refs": [r.to_dict() for r in self.refs],
        }


@dataclass
class Edge:
    from_app: str
    to_app: str
    type: str  # dependsOn, dns-ref, external-ref
    evidence: str

    def to_dict(self) -> dict:
        return {
            "from": self.from_app,
            "to": self.to_app,
            "type": self.type,
            "evidence": self.evidence,
        }


@dataclass
class Warning:
    app: str
    kind: str  # broken-ref, unresolved-dependsOn, etc.
    detail: str

    def to_dict(self) -> dict:
        return {"app": self.app, "kind": self.kind, "detail": self.detail}


@dataclass
class WiringGraph:
    schema_version: int = 1
    root: str = ""
    built_at: str = ""
    fingerprint: dict = field(default_factory=dict)
    domains: list[dict] = field(default_factory=list)
    apps: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "root": self.root,
            "built_at": self.built_at,
            "fingerprint": self.fingerprint,
            "domains": self.domains,
            "apps": self.apps,
            "edges": self.edges,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WiringGraph:
        g = cls()
        g.schema_version = d.get("schema_version", 1)
        g.root = d.get("root", "")
        g.built_at = d.get("built_at", "")
        g.fingerprint = d.get("fingerprint", {})
        g.domains = d.get("domains", [])
        g.apps = d.get("apps", [])
        g.edges = d.get("edges", [])
        g.warnings = d.get("warnings", [])
        return g

    @staticmethod
    def compute_fingerprint(yaml_files: list[str]) -> dict:
        """Compute fingerprint from sorted list of YAML file paths."""
        sha = hashlib.sha256()
        for f in sorted(yaml_files):
            sha.update(f.encode())
        return {"files": len(yaml_files), "sha256": sha.hexdigest()}
