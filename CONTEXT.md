# Flux Topology

An MCP server that builds a dependency and topology graph of a Kubernetes/FluxCD
GitOps repository by static analysis, so AI agents can reason about service
relationships without cluster access.

## Language

**App**:
The unit of deployment and dependency in the topology graph — one deployable
service (e.g. `hindsight`, `litellm`, `postgres`), composed of its HelmRelease
or raw workloads and the Services fronting them. An App is the leafmost
directory that owns deployment intent; everything beneath it belongs to that
App unless a child directory owns its own.
_Avoid_: service, workload, release, chart (each names only a part of an App)

**Domain**:
A directory grouping of related Apps under `flux/` (e.g. `ai`, `apps`,
`worldinmovies`) — organizational, not a node in the dependency graph. A Domain
may hold Apps directly or nest them at any depth.
_Avoid_: namespace, project

**Internal composition**:
The workloads, Services, ConfigMaps, and Secrets an App deploys as parts of
itself (including local chart templates). Never a node in the inter-App graph.
_Avoid_: component, sub-service

**App card**:
The human/agent-readable markdown file describing one App — its composition,
sources, and edges. Lives in the Topology cache; greppable like any repo file.
_Avoid_: node file, README

**Topology cache**:
The `.fluxtop/` folder written into the analyzed repository on build — App
cards plus the machine-readable wiring graph. A regenerable local cache,
never committed.
_Avoid_: index, database, graft folder

## Relationships

- An **App** lives inside exactly one **Domain**
- A **Domain** contains one or more **Apps**
- An **App** owns every resource beneath its directory that is not itself an App
- Edges exist only between distinct **Apps**; intra-App references are
  **internal composition**

## Flagged ambiguities

- "service" was used to mean both **App** (logical unit) and Kubernetes Service
  (endpoint object) — resolved: **App** is the node; Service objects are
  internal composition of an App.
- "workload count" was assumed to equal App count — resolved by counterexample:
  `deerflow` is one App containing two Deployments (gateway, frontend).
