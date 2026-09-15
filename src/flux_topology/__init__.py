"""flux-topology: static topology graphs for FluxCD GitOps repos."""

__version__ = "0.3.0"

DOMAIN_VOCABULARY = {
    "App": "leafmost directory owning deployment intent; node of the inter-App graph",
    "Domain": "top-level grouping directory under flux/",
    "Internal composition": "workloads/services/config owned by an App; never an inter-App edge",
    "App card": "human-readable markdown description of one App, in the Topology cache",
    "Topology cache": ".fluxtop/ folder written into the analyzed repository on build",
}
