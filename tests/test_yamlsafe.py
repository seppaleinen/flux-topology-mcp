"""Tests for yamlsafe module."""

from flux_topology.yamlsafe import (
    safe_load, safe_load_all, strip_go_templates, read_yaml, read_yaml_all,
)
from pathlib import Path
import tempfile
import pytest


class TestStripGoTemplates:
    def test_empty(self):
        assert strip_go_templates("") == ""

    def test_no_templates(self):
        assert strip_go_templates("apiVersion: v1\n") == "apiVersion: v1\n"

    def test_single_template(self):
        result = strip_go_templates("value: {{ .Value }}")
        assert "{{" not in result
        assert "value:" in result

    def test_multiline_template(self):
        text = "before\n{{ range .Items }}\n{{ .Name }}\nafter"
        result = strip_go_templates(text)
        assert "{{" not in result
        assert "before" in result
        assert "after" in result

    def test_multiple_templates(self):
        text = "{{ .A }} and {{ .B }}"
        result = strip_go_templates(text)
        assert "{{" not in result
        assert "and" in result


class TestSafeLoad:
    def test_valid_yaml(self):
        doc = safe_load("apiVersion: v1\nkind: Pod\n")
        assert isinstance(doc, dict)
        assert doc["apiVersion"] == "v1"

    def test_go_templates_stripped(self):
        doc = safe_load("value: {{ .Chart.Name }}\nname: test\n")
        assert isinstance(doc, dict)
        assert doc["name"] == "test"

    def test_invalid_yaml(self):
        doc = safe_load("{{ invalid yaml }}:\n  - [\n")
        # Should not crash, returns None or parsed result
        assert doc is None or isinstance(doc, dict)

    def test_multi_doc(self):
        result = safe_load_all("apiVersion: v1\n---\napiVersion: v2\n")
        assert isinstance(result, list)
        assert len(result) == 2

    def test_empty(self):
        result = safe_load("")
        # Empty string returns [] (empty list from safe_load_all) or None
        assert result is None or result == []


class TestReadYaml:
    def test_read_valid(self, tmp_path):
        f = tmp_path / "test.yaml"
        f.write_text("apiVersion: v1\nkind: ConfigMap\n")
        doc = read_yaml(f)
        assert isinstance(doc, dict)
        assert doc["kind"] == "ConfigMap"

    def test_read_missing(self, tmp_path):
        doc = read_yaml(tmp_path / "nonexistent.yaml")
        assert doc is None

    def test_read_all(self, tmp_path):
        f = tmp_path / "multi.yaml"
        f.write_text("a: 1\n---\nb: 2\n")
        docs = read_yaml_all(f)
        assert len(docs) == 2
