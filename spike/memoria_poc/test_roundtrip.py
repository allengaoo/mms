from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml

from client import MemoriaClient, MemoriaHttpError

ROOT = Path(__file__).resolve().parents[2]
MEMORY_ROOT = ROOT / "docs" / "memory"
OBJECT_TYPES = {"Pattern", "Decision", "AntiPattern", "BusinessFlow"}


def _parse_memory(path: Path) -> Optional[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    front_matter = yaml.safe_load(parts[1]) or {}
    if not isinstance(front_matter, dict) or not front_matter.get("id"):
        return None
    front_matter = json.loads(json.dumps(front_matter, default=str))
    return {
        "front_matter": front_matter,
        "body": parts[2].lstrip("\n"),
        "source_path": str(path.relative_to(ROOT)),
    }


def _sample_real_memories(limit: int = 1000) -> list[dict[str, Any]]:
    records = [
        record
        for path in sorted(MEMORY_ROOT.rglob("*.md"))
        if not {"_archived", "_system", "archive", "templates"} & set(path.parts)
        for record in [_parse_memory(path)]
        if record is not None
    ]
    selected: list[dict[str, Any]] = []
    for object_type in sorted(OBJECT_TYPES):
        match = next(
            (
                record
                for record in records
                if record["front_matter"].get(
                    "object_type",
                    record["front_matter"].get("type"),
                )
                == object_type
            ),
            None,
        )
        if match and match not in selected:
            selected.append(match)
    selected.extend(record for record in records if record not in selected)
    return selected[:limit]


def _find_by_content(
    memories: list[dict[str, Any]],
    content: str,
) -> Optional[dict[str, Any]]:
    return next((item for item in memories if item.get("content") == content), None)


def test_twenty_real_memories_can_roundtrip_via_projection(
    memoria_client: MemoriaClient,
) -> None:
    """Measure native metadata support and verify the deterministic fallback.

    Memoria's public store contract currently documents only content,
    memory_type and session_id.  The first write probes whether arbitrary
    metadata is nevertheless preserved.  The second write uses the candidate
    OntologyProjection fallback: a versioned JSON envelope in ``content``.
    """

    samples = _sample_real_memories()
    assert len(samples) >= 20, "PoC requires at least 20 real memory nodes"

    native_supported = 0
    projected_roundtrips = 0
    blocked_ids: list[str] = []
    for index, envelope in enumerate(samples):
        projected_content = "MMS_ONTOLOGY_V1\n" + json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
        )
        try:
            memoria_client.store(projected_content)
        except MemoriaHttpError as error:
            if "contains sensitive content" not in str(error):
                raise
            blocked_ids.append(str(envelope["front_matter"]["id"]))
            continue
        projected_item = _find_by_content(
            memoria_client.list_memories(limit=100),
            projected_content,
        )
        assert projected_item is not None
        decoded = json.loads(projected_item["content"].split("\n", 1)[1])
        assert decoded == envelope
        projected_roundtrips += 1

        marker = f"MMS_NATIVE_METADATA_PROBE_{index}_{envelope['front_matter']['id']}"
        memoria_client.store(marker, metadata=envelope)
        native_item = _find_by_content(memoria_client.list_memories(), marker)
        if native_item and (
            native_item.get("metadata") == envelope
            or native_item.get("extra_metadata") == envelope
        ):
            native_supported += 1
        if projected_roundtrips == 20:
            break

    print(
        json.dumps(
            {
                "sample_count": projected_roundtrips,
                "native_metadata_roundtrips": native_supported,
                "projected_content_roundtrips": projected_roundtrips,
                "blocked_ids": blocked_ids,
            },
            ensure_ascii=False,
        )
    )
    assert projected_roundtrips == 20
