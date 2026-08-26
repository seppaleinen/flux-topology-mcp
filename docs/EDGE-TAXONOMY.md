# Edge Taxonomy

Relationship types the topology graph can express, tiered by detection
confidence and extraction cost. V1 ships Tier 1; Tiers 2–3 are documented for
later inspection and must not block v1 schema design (edges are typed and the
set of types is open-ended).

## Tier 1 — v1 scope

| Edge type | Direction | Detection |
|---|---|---|
| `dependsOn` | dependent → dependency | Flux `dependsOn` on Kustomizations and HelmReleases |
| `dns-ref` | caller → callee | `<service>.<namespace>.svc.cluster.local` (and short forms) in env vars, Helm values, config blobs, job scripts |
| `external-ref` | caller → callee | Cross-App calls via public hostnames (`*.labb.site`), resolved through ingress host mappings |

## Tier 2 — documented, deferred

| Type | Evidence in fleet-infra | Open policy question |
|---|---|---|
| Forward-auth middleware | Traefik middlewares → `ak-outpost-authentik-embedded-outpost.authentik` | Is every protected route an edge to authentik, or is auth modeled as a shared platform service? |
| Scrape/push targets | ServiceMonitors, Alloy push configs → `loki-gateway`, `prometheus` | Is monitoring→monitored a dependency edge or exposure metadata? Which direction? |
| DB-provisioning jobs | `database-jobs/*-job.yaml` create databases for named apps | Provisioning edge postgres→consumer: worth its own edge type vs `dependsOn`? |
| Ingress/host exposure | IngressRoutes mapping hosts → Services | Exposure metadata on the App node rather than an edge? |

## Tier 3 — deferred indefinitely

- NetworkPolicies (allowed-flow edges)
- PVC / storage dependencies
- Image & OCI provenance (who ships which image)

## Non-goals (per ADR 0001)

- Anything requiring cluster access or live state reconciliation.
