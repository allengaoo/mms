from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("benchmark_baseline", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_retrieval_queries_meet_coverage_contract() -> None:
    queries = yaml.safe_load(
        (ROOT / "benchmarks" / "retrieval_queries.yaml").read_text(encoding="utf-8")
    )
    layers = {
        layer
        for query in queries
        for layer in query.get("expected_layers", [])
    }
    object_types = {
        object_type
        for query in queries
        for object_type in query.get("expected_object_types", [])
    }

    assert len(queries) >= 20
    assert len(layers) >= 6
    assert {"Pattern", "Decision", "AntiPattern", "BusinessFlow"} <= object_types


def test_compare_ignores_only_volatile_fields(tmp_path: Path) -> None:
    module = _load_module()
    left = {
        "generated_at": "first",
        "git_revision": "a",
        "timings": {"ast_ms": 1},
        "result": {"count": 2, "latency_ms": 10},
    }
    right = {
        "generated_at": "second",
        "git_revision": "b",
        "timings": {"ast_ms": 999},
        "result": {"count": 2, "latency_ms": 20},
    }
    left_path = tmp_path / "left.json"
    right_path = tmp_path / "right.json"
    left_path.write_text(json.dumps(left), encoding="utf-8")
    right_path.write_text(json.dumps(right), encoding="utf-8")

    assert module.compare(left_path, right_path) == 0

    right["result"]["count"] = 3
    right_path.write_text(json.dumps(right), encoding="utf-8")
    assert module.compare(left_path, right_path) == 1
