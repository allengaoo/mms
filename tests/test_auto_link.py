"""
test_auto_link.py — Phase 3 测试

验证 dream.py 的 _auto_link() 纯函数和 _apply_auto_link_to_file 集成。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mms.memory.dream import (
    _auto_link,
    _apply_auto_link_to_file,
    _extract_file_paths,
    _match_domain_concepts,
)


# ─── _extract_file_paths 测试 ─────────────────────────────────────────────────

class TestExtractFilePaths:
    def test_extracts_python_paths(self) -> None:
        content = "修改了 backend/app/core/response.py 的 DTO 处理逻辑。"
        paths = _extract_file_paths(content)
        assert "backend/app/core/response.py" in paths

    def test_extracts_multiple_extensions(self) -> None:
        content = """
修改了以下文件：
- src/mms/memory/graph_resolver.py
- frontend/src/stores/auth.ts
- config/settings.yaml
        """
        paths = _extract_file_paths(content)
        assert "src/mms/memory/graph_resolver.py" in paths
        assert "frontend/src/stores/auth.ts" in paths
        assert "config/settings.yaml" in paths

    def test_no_paths_returns_empty(self) -> None:
        content = "这是一条没有任何文件路径引用的纯文本记忆。"
        paths = _extract_file_paths(content)
        assert paths == []

    def test_deduplicates_paths(self) -> None:
        content = "backend/app/core/response.py 出现了多次，backend/app/core/response.py 不应重复。"
        paths = _extract_file_paths(content)
        assert paths.count("backend/app/core/response.py") == 1

    def test_ignores_short_paths(self) -> None:
        """极短的路径不应被误提取。"""
        content = "查看 a.py 文件。"
        paths = _extract_file_paths(content)
        assert paths == []  # len("a.py") = 4，被过滤


# ─── _auto_link 纯函数测试 ────────────────────────────────────────────────────

class TestAutoLink:
    def test_returns_cites_files_when_paths_found(self) -> None:
        content = "修改了 backend/app/core/response.py 和 backend/app/services/user.py。"
        fm: dict = {"tags": [], "tier": "warm"}
        updates = _auto_link(content, fm)
        assert "cites_files" in updates
        assert "backend/app/core/response.py" in updates["cites_files"]

    def test_no_cites_when_no_paths(self) -> None:
        content = "这是一条没有文件路径的记忆。"
        fm: dict = {"tags": [], "tier": "warm"}
        updates = _auto_link(content, fm)
        assert "cites_files" not in updates

    def test_merges_with_existing_cites_files(self) -> None:
        content = "新增了 backend/new_file.py 的实现。"
        fm: dict = {
            "tags": [],
            "tier": "warm",
            "cites_files": ["backend/old_file.py"],
        }
        updates = _auto_link(content, fm)
        assert "cites_files" in updates
        assert "backend/old_file.py" in updates["cites_files"]
        assert "backend/new_file.py" in updates["cites_files"]

    def test_is_pure_function_does_not_modify_fm(self) -> None:
        """_auto_link 是纯函数：不修改传入的 fm。"""
        content = "修改了 backend/app/core/response.py。"
        fm: dict = {"tags": [], "tier": "warm"}
        original_fm = dict(fm)
        _auto_link(content, fm)
        assert fm == original_fm, "_auto_link 修改了传入的 fm（不应该！）"

    def test_no_duplicate_concepts(self) -> None:
        """返回的 about_concepts 不含重复项。"""
        content = "gRPC gRPC gRPC"  # 重复关键词
        fm: dict = {"tags": ["grpc"], "tier": "warm"}
        updates = _auto_link(content, fm)
        if "about_concepts" in updates:
            concepts = updates["about_concepts"]
            assert len(concepts) == len(set(concepts)), "about_concepts 含重复项"

    def test_auto_impacts_skipped_when_disabled(self) -> None:
        """enable_auto_impacts=False（默认）时不建立 impacts 边。"""
        content = "这是一个 hot 记忆。"
        fm: dict = {"tags": ["grpc", "service"], "tier": "hot"}
        updates = _auto_link(content, fm)
        # 默认情况下 impacts 边不被建立（_cfg.runner_enable_auto_impacts=False）
        assert "impacts" not in updates

    def test_updates_about_concepts_merges_correctly(self) -> None:
        """已有 about_concepts 时，新概念被合并而非覆盖。"""
        content = "gRPC 服务层实现"
        fm: dict = {
            "tags": ["grpc"],
            "tier": "warm",
            "about_concepts": ["existing-concept"],
        }
        updates = _auto_link(content, fm)
        if "about_concepts" in updates:
            assert "existing-concept" in updates["about_concepts"]


# ─── _apply_auto_link_to_file 集成测试 ───────────────────────────────────────

class TestApplyAutoLinkToFile:
    def _create_memory_file(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test_memory.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_adds_cites_files_to_frontmatter(self, tmp_path: Path) -> None:
        content = """---
id: TEST-001
tier: warm
layer: L3_domain
tags:
  - grpc
---

# 测试记忆

修改了 backend/app/core/response.py 文件。
"""
        p = self._create_memory_file(tmp_path, content)
        _apply_auto_link_to_file(p)

        result = p.read_text(encoding="utf-8")
        assert "cites_files:" in result
        assert "backend/app/core/response.py" in result

    def test_no_modification_when_no_updates(self, tmp_path: Path) -> None:
        """当没有文件路径且没有概念关键词时，cites_files 不应被添加。"""
        content = """---
id: TEST-002
tier: warm
layer: L3_domain
tags: []
---

# 无路径记忆

XYZZY_NO_KEYWORDS_HERE_RANDOM_CONTENT_42
"""
        p = self._create_memory_file(tmp_path, content)
        _apply_auto_link_to_file(p)
        result = p.read_text(encoding="utf-8")
        # 不应添加 cites_files（没有文件路径）
        assert "cites_files:" not in result

    def test_safe_on_missing_file(self, tmp_path: Path) -> None:
        """对不存在的文件不应抛异常。"""
        nonexistent = tmp_path / "nonexistent.md"
        _apply_auto_link_to_file(nonexistent)  # 不应抛异常

    def test_graph_resolver_reads_auto_linked_fields(self, tmp_path: Path) -> None:
        """auto_link 写入的字段可被 graph_resolver 正确读取（集成验证）。"""
        from mms.memory.graph_resolver import MemoryGraph

        mem_dir = tmp_path / "shared"
        mem_dir.mkdir(parents=True)

        content = """---
id: MEM-TEST-001
tier: warm
layer: L3_domain
tags:
  - grpc
---

# 测试记忆

修改了 backend/app/grpc_service.py 文件。
"""
        p = mem_dir / "MEM-TEST-001.md"
        p.write_text(content, encoding="utf-8")
        _apply_auto_link_to_file(p)

        # graph_resolver 应能读取新写入的 cites_files 字段
        graph = MemoryGraph(memory_root=tmp_path)
        nodes = graph.find_by_file("backend/app/grpc_service.py")
        node_ids = {n.id for n in nodes}
        assert "MEM-TEST-001" in node_ids, "auto_link 写入的 cites_files 未被 graph_resolver 读取"
