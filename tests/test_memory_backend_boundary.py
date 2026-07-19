"""Memory backend boundary — Memoria No-Go 锁定。

Memoria 稳定版 PoC 因自定义 metadata 无法原生往返判定 No-Go。
本文件锁定当前唯一后端为 markdown，防止误接 memoria。
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mms.adapters import get_repository
from mms.adapters.markdown_repo import MarkdownRepository


def test_default_backend_is_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MMS_MEMORY_BACKEND", raising=False)
    repo = get_repository(project_root=tmp_path)
    assert isinstance(repo, MarkdownRepository)


def test_explicit_markdown_backend(tmp_path: Path) -> None:
    repo = get_repository(project_root=tmp_path, backend="markdown")
    assert isinstance(repo, MarkdownRepository)


@pytest.mark.parametrize("backend", ["memoria", "MEMORIA", "matrixone", "sqlite"])
def test_non_markdown_backends_are_rejected(
    tmp_path: Path,
    backend: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MMS_MEMORY_BACKEND", backend)
    with pytest.raises(ValueError, match="unsupported memory backend"):
        get_repository(project_root=tmp_path)


def test_memoria_adapter_module_not_present() -> None:
    """No-Go：仓库不得存在可导入的 memoria 适配器。"""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mms.adapters.memoria_repo")
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("mms.adapters.memoria_client")
