from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from client import MemoriaClient, MemoriaHttpError
from test_roundtrip import MEMORY_ROOT, ROOT, _parse_memory

BASELINE = ROOT / "benchmarks" / "baseline.json"
QUERIES = ROOT / "benchmarks" / "retrieval_queries.yaml"


def _projected_content(envelope: dict[str, Any]) -> str:
    return "MMS_ONTOLOGY_V1\n" + json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
    )


def _mms_id(item: dict[str, Any]) -> Optional[str]:
    content = item.get("content", "")
    if not isinstance(content, str) or not content.startswith("MMS_ONTOLOGY_V1\n"):
        return None
    try:
        envelope = json.loads(content.split("\n", 1)[1])
        return str(envelope["front_matter"]["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def test_retrieval_latency_and_result_overlap(
    memoria_client: MemoriaClient,
) -> None:
    records = [
        record
        for path in sorted(MEMORY_ROOT.rglob("*.md"))
        if not {"_archived", "_system", "archive", "templates"} & set(path.parts)
        for record in [_parse_memory(path)]
        if record is not None
    ]
    imported = 0
    blocked = 0
    for record in records:
        try:
            memoria_client.store(_projected_content(record))
            imported += 1
        except MemoriaHttpError as error:
            if "contains sensitive content" not in str(error):
                raise
            blocked += 1

    queries = yaml.safe_load(QUERIES.read_text(encoding="utf-8")) or []
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline_queries = {
        item["id"]: set(item["memory_ids"])
        for item in baseline["retrieval"]["queries"]
    }

    latencies: list[float] = []
    overlaps: list[float] = []
    for query in queries:
        started = time.perf_counter()
        results = memoria_client.retrieve(str(query["query"]), top_k=5)
        latencies.append((time.perf_counter() - started) * 1000)
        actual_ids = {
            memory_id
            for item in results
            for memory_id in [_mms_id(item)]
            if memory_id
        }
        expected_ids = baseline_queries.get(query["id"], set())
        if expected_ids:
            overlaps.append(len(actual_ids & expected_ids) / len(expected_ids))

    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)]
    print(
        json.dumps(
            {
                "candidate_memories": len(records),
                "imported_memories": imported,
                "blocked_memories": blocked,
                "query_count": len(queries),
                "p95_ms": round(p95, 3),
                "mean_baseline_overlap": (
                    round(sum(overlaps) / len(overlaps), 3) if overlaps else None
                ),
                "embedding_note": (
                    "The deterministic local stub validates plumbing and latency only; "
                    "retrieval quality requires a real embedding model."
                ),
            },
            ensure_ascii=False,
        )
    )
    assert len(latencies) == len(queries)
    assert p95 < 500
