# flux-topology

[![skills.sh](https://skills.sh/b/seppaleinen/flux-topology-mcp)](https://skills.sh/seppaleinen/flux-topology-mcp)

An MCP server that builds a dependency and topology graph of a Kubernetes/FluxCD
GitOps repository by static analysis, so AI agents can reason about service
relationships without cluster access.

## Install

```bash
pip install flux-topology
```

## Configure MCP

Add to your `opencode.json`:

```json
{
  "mcp": {
    "flux-topology": {
      "type": "local",
      "command": ["flux-topology", "mcp"],
      "enabled": true
    }
  }
}
```

The server reads from `flux/` in the working directory. Run opencode from your
GitOps repo root.

## Agent Skill

The bundled agent skill teaches AI agents when and how to use the MCP tools.
Install it from [skills.sh](https://skills.sh/seppaleinen/flux-topology-mcp):

```bash
npx skills add seppaleinen/flux-topology-mcp
```

This gives your agent a workflow: start with `fluxtop_map` for an overview,
drill down with `fluxtop_app_card`, check blast radius with `fluxtop_trace`,
and find shared references with `fluxtop_find_refs`.

## Tools

| Tool | Description |
|------|-------------|
| `fluxtop_map` | Top-level view: domains, hub apps by edge count, warnings |
| `fluxtop_trace` | BFS blast radius from any app with typed edges |
| `fluxtop_find_refs` | Regex search for references across all apps |
| `fluxtop_app_card` | Full card for one app: workloads, services, edges |
| `fluxtop_check_freshness` | Check if the topology cache is up to date |

## CLI

```bash
# Build the topology cache (.fluxtop/)
flux-topology build

# Run the MCP server (for AI agents)
flux-topology mcp
```

## How it works

1. **Discovers** apps by walking `flux/` and finding ownership signals
   (HelmReleases, Kustomizations, Deployments, Services)
2. **Extracts** workloads, services, ingress hosts, and refs per app
3. **Resolves** edges between apps from cross-references
4. **Caches** everything in `.fluxtop/` — rebuilt only when source files change

No cluster access required. Pure static analysis of YAML files.

## Development

```bash
git clone https://github.com/seppaleinen/flux-topology-mcp.git
cd flux-topology-mcp
pip install -e ".[dev]"
pytest
```

## License

MIT
