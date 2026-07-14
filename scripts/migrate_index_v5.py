#!/usr/bin/env python3
"""Idempotently rebuild MEMORY_INDEX.json from active shared memories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.core.indexer import IncrementalIndexer
from mms.core.writer import atomic_write_json


def rebuild(project_root: Path) -> dict:
    memory_root = project_root.resolve() / "docs" / "memory"
    shared_root = memory_root / "shared"
    repository = MarkdownRepository(memory_root)
    records = [
        record
        for record in repository.load_all()
        if record.path is not None and shared_root in record.path.parents
    ]
    index_file = memory_root / "MEMORY_INDEX.json"
    index = IncrementalIndexer(index_file).rebuild(records, memory_root)

    legacy = memory_root / "_system" / "memory_index.json"
    if legacy.exists():
        legacy.unlink()
    atomic_write_json(
        memory_root / "_system" / "memory_index.deprecated.json",
        {
            "deprecated": True,
            "replacement": "../MEMORY_INDEX.json",
            "schema_version": "5.0",
        },
    )
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    index_path = args.project_root / "docs" / "memory" / "MEMORY_INDEX.json"
    before = index_path.read_bytes() if index_path.exists() else None
    index = rebuild(args.project_root)
    after = index_path.read_bytes()
    if args.check and before is not None and before != after:
        print("MEMORY_INDEX.json is not up to date")
        return 1
    print(
        json.dumps(
            {
                "schema_version": index["schema_version"],
                "entries": sum(
                    len(type_node.get("memories", []))
                    for layer in index["tree"]
                    for type_node in layer.get("nodes", [])
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
