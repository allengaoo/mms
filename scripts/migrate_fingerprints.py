#!/usr/bin/env python3
"""Migrate Bootstrap memories to parser-independent source fingerprints."""

from __future__ import annotations

import argparse
from pathlib import Path

from mms.adapters import MarkdownRepository
from mms.analysis.ast_skeleton import build_ast_index


def migrate(project_root: Path, *, dry_run: bool = False) -> int:
    root = project_root.resolve()
    memory_root = root / "docs" / "memory"
    repository = MarkdownRepository(memory_root)
    ast_index = build_ast_index(root=root, dry_run=True, use_tree_sitter=True)
    changed = 0
    for record in repository.load_all():
        if not record.id.startswith("MEM-BOOT-"):
            continue
        ast_pointer = record.metadata.get("ast_pointer", {})
        if not isinstance(ast_pointer, dict):
            continue
        file_path = str(ast_pointer.get("file_path") or "")
        fingerprint = str((ast_index.get(file_path) or {}).get("fingerprint") or "")
        if not fingerprint or ast_pointer.get("fingerprint") == fingerprint:
            continue
        changed += 1
        print(f"{record.id}: {ast_pointer.get('fingerprint', '')} -> {fingerprint}")
        if dry_run:
            continue
        metadata = dict(record.metadata)
        updated_pointer = dict(ast_pointer)
        updated_pointer["fingerprint"] = fingerprint
        metadata["ast_pointer"] = updated_pointer
        repository.put(record.copy(metadata=metadata))
    print(f"{'Would update' if dry_run else 'Updated'} {changed} memories")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(args.project_root, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
