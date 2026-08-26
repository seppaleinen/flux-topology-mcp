"""Tolerant YAML parser: strips Go template blocks before parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


def strip_go_templates(text: str) -> str:
    """Replace Go template blocks {{ }} with empty strings for YAML parsing."""
    return re.sub(r"\{\{.*?\}\}", "", text, flags=re.DOTALL)


def safe_load(text: str) -> Any:
    """Parse YAML after stripping Go templates. Returns doc or None."""
    cleaned = strip_go_templates(text)
    try:
        docs = list(yaml.safe_load_all(cleaned))
        return docs[0] if len(docs) == 1 else docs
    except yaml.YAMLError:
        return None


def safe_load_all(text: str) -> list[Any]:
    """Parse all YAML docs after stripping Go templates."""
    cleaned = strip_go_templates(text)
    try:
        docs = list(yaml.safe_load_all(cleaned))
        return [d for d in docs if d is not None]
    except yaml.YAMLError:
        return []


def read_yaml(path: Path) -> Any:
    """Read and parse a YAML file, returning first doc or None."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return None
    return safe_load(text)


def read_yaml_all(path: Path) -> list[Any]:
    """Read and parse all YAML docs from a file."""
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []
    return safe_load_all(text)


def read_text(path: Path) -> str | None:
    """Read file content as text, returning None on error."""
    try:
        return path.read_text(errors="replace")
    except (OSError, UnicodeDecodeError):
        return None


def parse_kustomization(yaml_text: str) -> dict | None:
    """Parse a kustomization.yaml, returning the parsed dict or None."""
    return safe_load(yaml_text)
