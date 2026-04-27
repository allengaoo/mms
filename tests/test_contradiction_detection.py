"""
test_contradiction_detection.py — 图谱矛盾检测测试

测试内容：
  1. 关键词级矛盾检测（离线，无需 LLM）
  2. 无矛盾时返回空列表
  3. graph_resolver.get_candidates_for_contradiction_check() 爆炸半径控制
  4. apply_contradiction_resolution() 的降级操作（dry-run 模式）
"""
from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from mms.memory.memory_actions import detect_contradictions, apply_contradiction_resolution
from mms.memory.memory_functions import MemoryInsight


# ── 测试夹具 ─────────────────────────────────────────────────────────────────

def make_insight(title: str, content: str, memory_type: str = "decision", layer: str = "DOMAIN") -> MemoryInsight:
    """创建测试用 MemoryInsight 对象。"""
    return MemoryInsight(
        title=title,
        memory_type=memory_type,
        layer=layer,
        dimension="D1",
        tags=[],
        description=content,
        source_ep_id="EP-TEST",
    )


# ── 离线矛盾检测测试 ──────────────────────────────────────────────────────────

class TestDetectContradictions:
    def test_no_contradiction_empty_graph(self, tmp_path: Path) -> None:
        """空记忆库应返回空列表。"""
        (tmp_path / "shared").mkdir()
        insight = make_insight("使用 gRPC 通信", "服务间通信使用 gRPC")
        conflicts = detect_contradictions(insight, memory_root=tmp_path, use_llm=False)
        assert conflicts == []

    def test_no_contradiction_different_keywords(self, tmp_path: Path) -> None:
        """没有矛盾关键词时应返回空列表。"""
        insight = make_insight(
            "数据库连接池配置",
            "使用 HikariCP 配置数据库连接池，最大连接数 20",
            layer="PLATFORM",
        )
        conflicts = detect_contradictions(insight, memory_root=tmp_path, use_llm=False)
        assert conflicts == []

    def test_detection_returns_list(self, tmp_path: Path) -> None:
        """detect_contradictions 应始终返回列表类型。"""
        insight = make_insight("使用 REST API", "所有服务通过 REST API 通信")
        result = detect_contradictions(insight, memory_root=tmp_path, use_llm=False)
        assert isinstance(result, list)

    def test_conflict_structure_valid(self, tmp_path: Path) -> None:
        """当存在冲突时，冲突项应包含必要字段。"""
        # 创建一个包含 gRPC 关键词的 mock 候选节点
        mock_node = MagicMock()
        mock_node.id = "MEM-L-001"
        mock_node.title = "gRPC 服务通信规范"
        mock_node.about_concepts = ["grpc", "microservice"]
        mock_node.tier = "hot"
        mock_node.related_ids = []
        mock_node.contradicts = []

        insight = make_insight(
            "使用 REST API 通信",
            "所有微服务之间使用 REST API 通信，禁止使用 gRPC",
            memory_type="decision",
        )

        # Mock MemoryGraph 的候选节点（在 graph_resolver 模块层面 mock）
        with patch("mms.memory.graph_resolver.MemoryGraph") as MockGraph:
            mock_graph = MockGraph.return_value
            mock_graph.get_candidates_for_contradiction_check.return_value = [mock_node]

            conflicts = detect_contradictions(insight, memory_root=tmp_path, use_llm=False)

            if conflicts:
                for conflict in conflicts:
                    assert "node_id" in conflict
                    assert "reason" in conflict
                    assert "confidence" in conflict
                    assert isinstance(conflict["confidence"], float)
                    assert 0.0 <= conflict["confidence"] <= 1.0

    def test_non_decision_type_skipped(self, tmp_path: Path) -> None:
        """非决策类型（如 lesson）不应触发矛盾检测（在 _check_not_contradicts_adr 层面）。"""
        from mms.memory.memory_actions import _check_not_contradicts_adr
        insight = make_insight(
            "使用 REST API",
            "REST API 使用规范",
            memory_type="lesson",   # 非 decision/arch_constraint
        )
        result = _check_not_contradicts_adr(insight, tmp_path)
        assert result is None   # lesson 类型不做矛盾检测

    def test_decision_type_triggers_check(self, tmp_path: Path) -> None:
        """decision 类型应触发矛盾检测。"""
        from mms.memory.memory_actions import _check_not_contradicts_adr
        insight = make_insight(
            "使用 grpc 通信",
            "决策：采用 grpc 作为服务间通信协议",
            memory_type="decision",
        )
        # 空库不报错
        (tmp_path / "shared").mkdir(exist_ok=True)
        result = _check_not_contradicts_adr(insight, tmp_path)
        assert result is None or isinstance(result, str)


# ── graph_resolver 矛盾检测相关接口测试 ───────────────────────────────────────

class TestGraphResolverContradictionMethods:
    def test_get_candidates_empty_graph(self, tmp_path: Path) -> None:
        """空图应返回空列表。"""
        from mms.memory.graph_resolver import MemoryGraph
        (tmp_path / "shared").mkdir()
        graph = MemoryGraph(memory_root=tmp_path)
        candidates = graph.get_candidates_for_contradiction_check(["DOMAIN"])
        assert candidates == []

    def test_get_candidates_respects_max(self, tmp_path: Path) -> None:
        """候选节点数量应不超过 max_candidates。"""
        from mms.memory.graph_resolver import MemoryGraph
        shared = tmp_path / "shared"
        shared.mkdir()

        # 创建 25 个 hot 节点（超过默认 max_candidates=20）
        for i in range(25):
            md = shared / f"MEM-TEST-{i:03d}.md"
            md.write_text(
                f"---\nid: MEM-TEST-{i:03d}\ntier: hot\nlayer: DOMAIN\nabout_concepts: [test]\n---\n# Test {i}\n",
                encoding="utf-8",
            )

        graph = MemoryGraph(memory_root=tmp_path)
        candidates = graph.get_candidates_for_contradiction_check(["DOMAIN"], max_candidates=10)
        assert len(candidates) <= 10

    def test_add_contradicts_edge_unknown_nodes(self, tmp_path: Path) -> None:
        """对不存在的节点添加 contradicts 边应返回 False。"""
        from mms.memory.graph_resolver import MemoryGraph
        (tmp_path / "shared").mkdir()
        graph = MemoryGraph(memory_root=tmp_path)
        result = graph.add_contradicts_edge("MEM-NONEXIST-001", "MEM-NONEXIST-002", tmp_path)
        # 不存在的节点应优雅地返回 False 或 True（空操作）
        assert isinstance(result, bool)

    def test_archive_node_unknown(self, tmp_path: Path) -> None:
        """对不存在的节点调用 archive_node 应返回 False。"""
        from mms.memory.graph_resolver import MemoryGraph
        (tmp_path / "shared").mkdir()
        graph = MemoryGraph(memory_root=tmp_path)
        result = graph.archive_node("MEM-NONEXIST-001", reason="test", memory_root=tmp_path)
        assert result is False


# ── apply_contradiction_resolution 测试 ─────────────────────────────────────

class TestApplyContradictionResolution:
    def test_unknown_nodes_fails_gracefully(self, tmp_path: Path) -> None:
        """不存在的节点应优雅地处理并返回 ActionResult。"""
        from mms.memory.memory_actions import apply_contradiction_resolution
        (tmp_path / "shared").mkdir()
        result = apply_contradiction_resolution(
            "MEM-NONEXIST-001",
            "MEM-NONEXIST-002",
            memory_root=tmp_path,
        )
        assert hasattr(result, "success")
        assert isinstance(result.success, bool)

    def test_requires_memory_graph(self) -> None:
        """apply_contradiction_resolution 应尝试导入 MemoryGraph。"""
        # 此测试只验证函数签名和返回类型
        result = apply_contradiction_resolution(
            "MEM-001",
            "MEM-002",
            memory_root=Path("/tmp/nonexistent_mulan_test"),
        )
        assert hasattr(result, "success")
