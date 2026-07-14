#!/usr/bin/env python3
"""Collect and compare the MMS modernization baseline.

The collector is deliberately read-only: Bootstrap runs in ``dry_run`` mode,
AST indexes are kept in memory, and the injector's optional LLM enhancement is
disabled so repeated runs remain local and comparable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mms.analysis.ast_skeleton import build_ast_index
from mms.analysis.dep_sniffer import sniff
from mms.bootstrap.code_graph_builder import build_code_graph
from mms.bootstrap.ontology_populator import bootstrap_project
from mms.bootstrap.signal_fusion import infer_all
from mms.memory.graph_resolver import MemoryGraph
from mms.memory.injector import MemoryInjector

FIXTURES = {
    "python_fastapi": ROOT / "tests" / "fixtures" / "python-fastapi-demo",
    "go_gin": ROOT / "tests" / "fixtures" / "go-gin-demo",
    "java_spring_boot": ROOT / "tests" / "fixtures" / "spring-boot-demo",
    "typescript_nestjs": ROOT / "tests" / "fixtures" / "typescript-nestjs-demo",
}
QUERY_FILE = ROOT / "benchmarks" / "retrieval_queries.yaml"


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _ast_metrics(index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    classes = [cls for file_data in index.values() for cls in file_data.get("classes", [])]
    class_methods = [method for cls in classes for method in cls.get("methods", [])]
    top_level = [
        method
        for file_data in index.values()
        for method in file_data.get("top_level_functions", [])
    ]
    annotations = sum(len(cls.get("annotations", [])) for cls in classes)
    annotations += sum(
        len(method.get("annotations", method.get("decorators", [])))
        for method in class_methods + top_level
    )
    imports = sum(len(file_data.get("imports", [])) for file_data in index.values())
    languages: dict[str, int] = {}
    for file_data in index.values():
        language = str(file_data.get("lang", "unknown"))
        languages[language] = languages.get(language, 0) + 1
    return {
        "files": len(index),
        "classes": len(classes),
        "methods": len(class_methods) + len(top_level),
        "class_methods": len(class_methods),
        "top_level_functions": len(top_level),
        "annotations": annotations,
        "imports": imports,
        "files_by_language": dict(sorted(languages.items())),
    }


def collect_fixture(name: str, root: Path) -> dict[str, Any]:
    if not root.exists():
        raise FileNotFoundError(f"Fixture does not exist: {root}")

    started = time.perf_counter()
    ast_index = build_ast_index(root=root, dry_run=True)
    ast_ms = _elapsed_ms(started)

    started = time.perf_counter()
    graph = build_code_graph(ast_index=ast_index, project_root=root)
    graph_ms = _elapsed_ms(started)

    stack = sniff(root=root)
    started = time.perf_counter()
    inferences = infer_all(
        ast_index=ast_index,
        code_graph_in_degrees=graph.in_degree,
        min_confidence=0.5,
        project_root=root,
        detected_stacks=stack.detected_stacks,
    )
    inference_ms = _elapsed_ms(started)

    inferred_layers: dict[str, int] = {}
    unknown_count = 0
    ambiguous_count = 0
    for layer_inference, _object_mapping in inferences.values():
        layer = layer_inference.inferred_layer
        if layer == "UNKNOWN":
            unknown_count += 1
        else:
            inferred_layers[layer] = inferred_layers.get(layer, 0) + 1
        if (layer_inference.all_scores or {}).get("_ambiguous"):
            ambiguous_count += 1

    started = time.perf_counter()
    report = bootstrap_project(
        project_root=root,
        dry_run=True,
        skip_doc_absorb=True,
        verbose=False,
    )
    bootstrap_ms = _elapsed_ms(started)

    return {
        "fixture": name,
        "path": str(root.relative_to(ROOT)),
        "ast": _ast_metrics(ast_index),
        "code_graph": {
            "nodes": graph.stats.get("node_count", 0),
            "edges": graph.stats.get("edge_count", 0),
            "cycles": graph.stats.get("cycle_count", 0),
        },
        "inference": {
            "classes": len(inferences),
            "layer_distribution": dict(sorted(inferred_layers.items())),
            "unknown_count": unknown_count,
            "ambiguous_count": ambiguous_count,
        },
        "bootstrap_report": {
            key: value
            for key, value in asdict(report).items()
            if key not in {"project_root", "elapsed_s", "memory_files"}
        },
        "timings": {
            "ast_ms": ast_ms,
            "code_graph_ms": graph_ms,
            "inference_ms": inference_ms,
            "bootstrap_total_ms": bootstrap_ms,
        },
    }


def collect_retrieval() -> dict[str, Any]:
    queries = yaml.safe_load(QUERY_FILE.read_text(encoding="utf-8")) or []
    injector = MemoryInjector(project_root=ROOT)
    # Baselines must never depend on an external model or network availability.
    injector._enhance_with_llm = lambda _task, _nodes: None  # type: ignore[method-assign]

    results = []
    latencies = []
    for item in queries:
        started = time.perf_counter()
        result = injector.inject(str(item["query"]), top_k=5)
        elapsed = _elapsed_ms(started)
        latencies.append(elapsed)
        results.append(
            {
                "id": item["id"],
                "expected_layers": item.get("expected_layers", []),
                "expected_object_types": item.get("expected_object_types", []),
                "detected_layers": result.detected_layers,
                "memory_ids": [memory.memory_id for memory in result.memories],
                "latency_ms": elapsed,
            }
        )

    sorted_latencies = sorted(latencies)
    p95_index = max(0, int(len(sorted_latencies) * 0.95 + 0.999) - 1)
    return {
        "query_count": len(results),
        "covered_layers": sorted(
            {
                layer
                for item in queries
                for layer in item.get("expected_layers", [])
            }
        ),
        "covered_object_types": sorted(
            {
                object_type
                for item in queries
                for object_type in item.get("expected_object_types", [])
            }
        ),
        "latency_p95_ms": sorted_latencies[p95_index] if sorted_latencies else 0.0,
        "queries": results,
    }


def collect_graph() -> dict[str, Any]:
    started = time.perf_counter()
    stats = MemoryGraph(memory_root=ROOT / "docs" / "memory").stats()
    return {"stats": stats, "load_ms": _elapsed_ms(started)}


def _git_revision() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def collect() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": _git_revision(),
        "fixtures": {
            name: collect_fixture(name, path)
            for name, path in FIXTURES.items()
        },
        "retrieval": collect_retrieval(),
        "memory_graph": collect_graph(),
    }


def _without_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_volatile(child)
            for key, child in value.items()
            if key != "generated_at"
            and key != "git_revision"
            and key != "timings"
            and not key.endswith("_ms")
            and not key.endswith("_s")
        }
    if isinstance(value, list):
        return [_without_volatile(item) for item in value]
    return value


def compare(left_path: Path, right_path: Path) -> int:
    left = _without_volatile(json.loads(left_path.read_text(encoding="utf-8")))
    right = _without_volatile(json.loads(right_path.read_text(encoding="utf-8")))
    if left == right:
        print("Baseline comparison: deterministic fields are identical.")
        return 0
    print("Baseline comparison: deterministic fields differ.", file=sys.stderr)
    print(
        json.dumps({"left": left, "right": right}, ensure_ascii=False, indent=2),
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="Write a newly collected baseline JSON")
    parser.add_argument(
        "--diff",
        nargs=2,
        type=Path,
        metavar=("LEFT", "RIGHT"),
        help="Compare deterministic fields in two baseline files",
    )
    args = parser.parse_args()

    if args.diff:
        return compare(args.diff[0], args.diff[1])
    if not args.out:
        parser.error("one of --out or --diff is required")

    baseline = collect()
    output = args.out if args.out.is_absolute() else ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Baseline written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
