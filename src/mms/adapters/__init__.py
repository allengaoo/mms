"""Repository adapter factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from mms.ports.repository import MemoryRepository

from .markdown_repo import MarkdownRepository


def get_repository(
    *,
    project_root: Optional[Path] = None,
    memory_root: Optional[Path] = None,
    backend: Optional[str] = None,
) -> MemoryRepository:
    selected = (backend or os.environ.get("MMS_MEMORY_BACKEND", "markdown")).lower()
    if selected != "markdown":
        raise ValueError(
            f"unsupported memory backend {selected!r}; Phase 1 provides 'markdown'"
        )
    if memory_root is None:
        root = Path(project_root) if project_root is not None else Path.cwd()
        memory_root = root / "docs" / "memory"
    return MarkdownRepository(memory_root=memory_root)


__all__ = ["MarkdownRepository", "get_repository"]
