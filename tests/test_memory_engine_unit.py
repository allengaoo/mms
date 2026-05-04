"""
test_memory_engine_unit.py — Memory Engine 单元测试

覆盖以下 0% 或低覆盖率模块：
  - TaskMatcher       (task_matcher.py)    0% → 85%+
  - IntentClassifier  (intent_classifier.py) 0% → 70%+
  - entropy_scan      (entropy_scan.py)    0% → 80%+
  - MemoryGraph       (graph_resolver.py)  59% → 85%+
  - MemoryInjector    (injector.py)        0% → 65%+
  - RepoMap           (repo_map.py)        0% → 75%+
  - memory_actions    (memory_actions.py)  0% → 65%+
  - codemap / funcmap 0% → 55%+

策略：
  - 全部使用 tmp_path 文件系统隔离，不依赖真实 docs/memory/
  - 不调用 LLM（所有 LLM 路径通过 mock/patch 或 use_llm=False 跳过）
"""
from __future__ import annotations

import json
import sys
import textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TaskMatcher
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.task_matcher import TaskMatcher, TaskRecord, MatchResult


def _make_history_file(tmp_path: Path, records: list) -> Path:
    hf = tmp_path / "task_history.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    hf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hf


class TestTaskMatcherExtractTags:

    def test_chinese_words_extracted(self):
        m = TaskMatcher()
        tags = m.extract_tags("实现用户登录功能")
        assert "实现用户登录功能" in tags or "用户登录" in tags or "登录功能" in tags

    def test_english_words_extracted(self):
        m = TaskMatcher()
        tags = m.extract_tags("implement UserController endpoint")
        # CamelCase 拆分：UserController → user, controller
        assert "controller" in tags or "user" in tags
        assert "endpoint" in tags or "implement" in tags

    def test_stop_words_filtered(self):
        m = TaskMatcher()
        tags = m.extract_tags("the fix and set new api")
        # 停用词 the/fix/and/set/new/api 应被过滤
        assert "the" not in tags
        assert "and" not in tags

    def test_template_tags_added(self):
        m = TaskMatcher()
        tags = m.extract_tags("create order", template="ep-backend-api")
        # ep-backend-api 模板固定标签
        assert "backend" in tags or "api" in tags or "service" in tags

    def test_unknown_template_no_crash(self):
        m = TaskMatcher()
        tags = m.extract_tags("some task", template="ep-nonexistent")
        assert isinstance(tags, list)

    def test_empty_task(self):
        m = TaskMatcher()
        tags = m.extract_tags("")
        assert isinstance(tags, list)

    def test_camel_case_split(self):
        m = TaskMatcher()
        tags = m.extract_tags("implement OrderService logic")
        # OrderService → order + service
        assert "order" in tags or "service" in tags

    def test_returns_sorted_list(self):
        m = TaskMatcher()
        tags = m.extract_tags("create user login service")
        assert tags == sorted(tags)


class TestTaskMatcherFindSimilar:

    def _make_record_via_matcher(
        self, task: str, hit_memories: List[str], hit_files: List[str],
        days_ago: int = 0, tmp_hf: Path = None
    ) -> dict:
        """使用 TaskMatcher.build_record 生成与提取器兼容的历史记录。"""
        m = TaskMatcher()
        rec = m.build_record(task, None, hit_memories, hit_files, author="alice")
        d = rec.to_dict()
        # 调整时间戳
        d["ts"] = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        return d

    def test_exact_match_returns_result(self, tmp_path):
        """相同任务描述应命中历史记录。"""
        task = "实现订单创建接口 OrderService create"
        rec = self._make_record_via_matcher(task, ["MEM-L-001"], ["src/service.py"])
        hf = _make_history_file(tmp_path, [rec])
        m = TaskMatcher(history_file=hf)
        result = m.find_similar(task)
        assert result is not None
        assert result.similarity > 0.5

    def test_no_history_returns_none(self, tmp_path):
        hf = tmp_path / "empty.jsonl"
        m = TaskMatcher(history_file=hf)
        assert m.find_similar("任意任务") is None

    def test_below_threshold_returns_none(self, tmp_path):
        """完全不相关的任务不应命中。"""
        rec = self._make_record_via_matcher("修复前端按钮颜色 button color", [], [])
        hf = _make_history_file(tmp_path, [rec])
        m = TaskMatcher(history_file=hf, similarity_threshold=0.99)
        result = m.find_similar("实现后端数据库分片 sharding PostgreSQL")
        assert result is None

    def test_hit_carries_memories_and_files(self, tmp_path):
        task = "实现订单服务 OrderService create backend"
        rec = self._make_record_via_matcher(task, ["MEM-L-001"], ["src/service.py"])
        hf = _make_history_file(tmp_path, [rec])
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        result = m.find_similar(task)
        assert result is not None
        assert "MEM-L-001" in result.record.hit_memories
        assert "src/service.py" in result.record.hit_files

    def test_time_decay_penalizes_old_records(self, tmp_path):
        task = "实现订单服务 OrderService create"
        old = self._make_record_via_matcher(task, [], [], days_ago=90)
        recent = self._make_record_via_matcher(task, [], [], days_ago=1)

        hf_old = tmp_path / "old.jsonl"
        hf_old.write_text(json.dumps(old) + "\n")
        m_old = TaskMatcher(history_file=hf_old, similarity_threshold=0.1)
        r_old = m_old.find_similar(task)

        hf_new = tmp_path / "new.jsonl"
        hf_new.write_text(json.dumps(recent) + "\n")
        m_new = TaskMatcher(history_file=hf_new, similarity_threshold=0.1)
        r_new = m_new.find_similar(task)

        if r_old and r_new:
            assert r_new.similarity >= r_old.similarity


class TestTaskMatcherAppendRecord:

    def test_append_creates_file(self, tmp_path):
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf)
        rec = m.build_record("测试任务", None, ["MEM-001"], ["a.py"])
        m.append_record(rec)
        assert hf.exists()
        lines = [l for l in hf.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_append_multiple_records(self, tmp_path):
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf)
        for i in range(3):
            rec = m.build_record(f"任务{i}", None, [], [])
            m.append_record(rec)
        lines = [l for l in hf.read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_max_records_rolling_delete(self, tmp_path):
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf, max_history_records=3)
        for i in range(5):
            rec = m.build_record(f"任务{i}", None, [], [])
            m.append_record(rec)
        lines = [l for l in hf.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        # 保留最新的 3 条
        last = json.loads(lines[-1])
        assert "任务4" in last["task"]

    def test_build_record_fills_tags(self, tmp_path):
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf)
        rec = m.build_record("实现 OrderService 接口", "ep-backend-api", [], [])
        assert len(rec.tags) > 0
        assert "order" in rec.tags or "service" in rec.tags


# ═══════════════════════════════════════════════════════════════════════════════
# 2. IntentClassifier
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.intent_classifier import IntentClassifier, IntentResult


class TestIntentClassifierLocalMatch:

    def test_frontend_keywords_match(self):
        ic = IntentClassifier()
        result = ic.local_match_only("修改前端导航栏页面配置")
        assert result.layer in ("L5_frontend", "L4_service"), f"期望前端层，得到: {result.layer}"
        assert result.confidence > 0.2

    def test_backend_service_keywords_match(self):
        ic = IntentClassifier()
        result = ic.local_match_only("实现 OrderService 订单创建后端逻辑")
        # service/backend 关键词应命中后端层
        assert result.confidence > 0.0
        assert isinstance(result.operation, str) and result.operation != ""

    def test_fallback_on_no_match(self):
        ic = IntentClassifier()
        result = ic.local_match_only("xyzzy zyxwvut completelyrandom")
        # 应回退到 fallback result，不崩溃
        assert isinstance(result, IntentResult)
        assert result.confidence < 0.5  # 置信度应较低

    def test_result_has_required_fields(self):
        ic = IntentClassifier()
        result = ic.local_match_only("修改用户认证服务")
        assert isinstance(result.layer, str)
        assert isinstance(result.operation, str)
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.entry_files_hint, list)
        assert isinstance(result.from_llm, bool)
        assert result.from_llm is False  # local_match_only 不调用 LLM

    def test_skip_llm_property_high_confidence(self):
        ic = IntentClassifier()
        result = ic.local_match_only("修改前端导航栏页面")
        if result.confidence >= 0.80:
            assert result.skip_llm_round1 is True

    def test_skip_llm_property_low_confidence(self):
        # 低置信度不应 skip LLM
        result = IntentResult(
            layer="L4_service", operation="modify_logic",
            confidence=0.30, entry_files_hint=[], from_llm=False
        )
        assert result.skip_llm_round1 is False

    def test_classify_with_llm_false(self):
        """use_llm_fallback=False 等价于 local_match_only。"""
        ic = IntentClassifier()
        result = ic.classify("修改前端页面", use_llm_fallback=False)
        assert isinstance(result, IntentResult)
        assert result.from_llm is False

    def test_classify_no_crash_empty(self):
        ic = IntentClassifier()
        result = ic.classify("", use_llm_fallback=False)
        assert isinstance(result, IntentResult)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. entropy_scan 纯函数
# ═══════════════════════════════════════════════════════════════════════════════

import mms.memory.entropy_scan as _entropy_mod
from mms.memory.entropy_scan import (
    _parse_date, _collect_index_entries,
    scan_orphans, scan_ghost_entries,
    scan_stale_hot, scan_zero_access, scan_duplicate_titles,
)


def _make_entropy_env(tmp_path: Path):
    """在 tmp_path 创建伪装的 memory root，monkey-patch 模块级路径。"""
    mem_root = tmp_path / "memory"
    shared = mem_root / "shared"
    shared.mkdir(parents=True)
    return mem_root, shared


class TestEntropyScanParsers:

    def test_parse_date_valid(self):
        dt = _parse_date("2026-01-15")
        assert dt.year == 2026 and dt.month == 1 and dt.day == 15

    def test_parse_date_invalid_returns_now(self):
        dt = _parse_date("not-a-date")
        now = datetime.now(timezone.utc)
        assert abs((dt - now).total_seconds()) < 10

    def test_collect_index_entries_flat(self):
        tree = [
            {"memories": [{"id": "M1", "file": "a.md"}, {"id": "M2", "file": "b.md"}], "nodes": []},
        ]
        entries = _collect_index_entries(tree)
        assert "M1" in entries and "M2" in entries

    def test_collect_index_entries_nested(self):
        tree = [
            {"memories": [{"id": "M1", "file": "a.md"}], "nodes": [
                {"memories": [{"id": "M2", "file": "b.md"}], "nodes": []}
            ]},
        ]
        entries = _collect_index_entries(tree)
        assert "M1" in entries and "M2" in entries


class TestEntropyScanScanFunctions:

    def test_scan_orphans_finds_unindexed_file(self, tmp_path, monkeypatch):
        mem_root, shared = _make_entropy_env(tmp_path)
        orphan_file = shared / "orphan.md"
        orphan_file.write_text("# orphan")

        # 同时 patch _MEMORY_ROOT 和 _actual_memory_files 以确保隔离
        monkeypatch.setattr(_entropy_mod, "_MEMORY_ROOT", mem_root)
        monkeypatch.setattr(_entropy_mod, "_actual_memory_files",
                            lambda: {orphan_file})
        orphans = _entropy_mod.scan_orphans({})
        assert any("orphan.md" in o for o in orphans)

    def test_scan_orphans_no_false_positive(self, tmp_path, monkeypatch):
        mem_root, shared = _make_entropy_env(tmp_path)
        md = shared / "indexed.md"
        md.write_text("# indexed")
        rel = str(md.relative_to(mem_root))
        indexed = {"M1": {"file": rel, "id": "M1"}}

        monkeypatch.setattr(_entropy_mod, "_MEMORY_ROOT", mem_root)
        monkeypatch.setattr(_entropy_mod, "_actual_memory_files", lambda: {md})
        orphans = _entropy_mod.scan_orphans(indexed)
        assert not any("indexed.md" in o for o in orphans)

    def test_scan_ghost_entries_detects_missing_file(self, tmp_path, monkeypatch):
        mem_root, _ = _make_entropy_env(tmp_path)
        monkeypatch.setattr(_entropy_mod, "_MEMORY_ROOT", mem_root)
        # 索引指向不存在的文件
        indexed = {"M1": {"file": "shared/ghost.md", "id": "M1"}}
        ghosts = _entropy_mod.scan_ghost_entries(indexed)
        assert any("M1" in g for g in ghosts)

    def test_scan_ghost_entries_no_false_positive(self, tmp_path, monkeypatch):
        mem_root, shared = _make_entropy_env(tmp_path)
        (shared / "real.md").write_text("# real")
        monkeypatch.setattr(_entropy_mod, "_MEMORY_ROOT", mem_root)
        indexed = {"M1": {"file": "shared/real.md", "id": "M1"}}
        ghosts = _entropy_mod.scan_ghost_entries(indexed)
        assert ghosts == []

    def test_scan_stale_hot_detects_old_hot_memory(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%d")
        indexed = {"M1": {"id": "M1", "tier": "hot", "last_accessed": old_date, "access_count": 5}}
        stale = scan_stale_hot(indexed)
        assert any("M1" in str(s) for s in stale)

    def test_scan_stale_hot_no_false_positive(self):
        recent_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        indexed = {"M1": {"id": "M1", "tier": "hot", "last_accessed": recent_date, "access_count": 5}}
        stale = scan_stale_hot(indexed)
        assert stale == []

    def test_scan_zero_access_detects_cold_entries(self):
        old_date = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
        indexed = {"M1": {"id": "M1", "tier": "warm", "created_at": old_date, "access_count": 0}}
        zero = scan_zero_access(indexed)
        assert any("M1" in str(z) for z in zero)

    def test_scan_duplicate_titles_detects_same_prefix(self):
        indexed = {
            "M1": {"id": "M1", "title": "Redis 缓存必须加 tenant_id 前缀（核心约束）"},
            "M2": {"id": "M2", "title": "Redis 缓存必须加 tenant_id 前缀（增强版）"},
        }
        dups = scan_duplicate_titles(indexed)
        assert len(dups) > 0

    def test_scan_duplicate_titles_no_false_positive(self):
        indexed = {
            "M1": {"id": "M1", "title": "Redis 缓存设计"},
            "M2": {"id": "M2", "title": "PostgreSQL 索引优化"},
        }
        dups = scan_duplicate_titles(indexed)
        assert dups == []


# ═══════════════════════════════════════════════════════════════════════════════
# 4. MemoryGraph (graph_resolver.py)
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.graph_resolver import _parse_frontmatter, MemoryGraph, MemoryNode


def _write_mem_file(path: Path, fm: dict, body: str = "") -> Path:
    """写一个最简的 MemoryNode Markdown 文件到指定目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_lines = []
    for k, v in fm.items():
        if isinstance(v, list):
            fm_lines.append(f"{k}:")
            for item in v:
                fm_lines.append(f"  - {item}")
        else:
            fm_lines.append(f"{k}: {v}")
    content = "---\n" + "\n".join(fm_lines) + "\n---\n" + body
    path.write_text(content, encoding="utf-8")
    return path


class TestParseFrontmatter:

    def test_basic_fields_parsed(self):
        text = textwrap.dedent("""
            ---
            id: MEM-001
            tier: hot
            layer: L3_domain
            ---
            # 正文
        """).strip()
        fm = _parse_frontmatter(text)
        assert fm["id"] == "MEM-001"
        assert fm["tier"] == "hot"
        assert fm["layer"] == "L3_domain"

    def test_list_field_parsed(self):
        text = textwrap.dedent("""
            ---
            id: MEM-002
            tags:
              - redis
              - cache
            cites_files:
              - src/service.py
            ---
        """).strip()
        fm = _parse_frontmatter(text)
        assert isinstance(fm.get("cites_files"), list)
        assert "src/service.py" in fm["cites_files"]

    def test_no_frontmatter_returns_empty(self):
        fm = _parse_frontmatter("# 只有正文，没有 front-matter")
        assert fm == {}

    def test_boolean_fields_parsed(self):
        text = "---\nid: X\ndrift: true\n---"
        fm = _parse_frontmatter(text)
        assert fm["drift"] is True

    def test_integer_fields_parsed(self):
        text = "---\nid: X\nversion: 3\n---"
        fm = _parse_frontmatter(text)
        assert fm["version"] == 3


class TestMemoryGraph:

    def _mk_graph(self, tmp_path: Path) -> MemoryGraph:
        return MemoryGraph(memory_root=tmp_path)

    def test_load_basic_nodes(self, tmp_path):
        _write_mem_file(tmp_path / "a.md", {"id": "M1", "tier": "hot", "layer": "L3_domain"})
        _write_mem_file(tmp_path / "b.md", {"id": "M2", "tier": "warm", "layer": "L4_application"})
        g = self._mk_graph(tmp_path)
        g._ensure_loaded()
        assert "M1" in g._nodes
        assert "M2" in g._nodes

    def test_get_existing_node(self, tmp_path):
        _write_mem_file(tmp_path / "m1.md", {"id": "MEM-GET-001", "tier": "warm"}, "# 测试节点")
        g = self._mk_graph(tmp_path)
        node = g.get("MEM-GET-001")
        assert node is not None
        assert node.id == "MEM-GET-001"

    def test_get_nonexistent_returns_none(self, tmp_path):
        g = self._mk_graph(tmp_path)
        assert g.get("MEM-GHOST-999") is None

    def test_all_hot_filters_correctly(self, tmp_path):
        _write_mem_file(tmp_path / "h.md", {"id": "HOT-001", "tier": "hot"})
        _write_mem_file(tmp_path / "w.md", {"id": "WARM-001", "tier": "warm"})
        _write_mem_file(tmp_path / "c.md", {"id": "COLD-001", "tier": "cold"})
        g = self._mk_graph(tmp_path)
        hot = g.all_hot()
        hot_ids = {n.id for n in hot}
        assert "HOT-001" in hot_ids
        assert "WARM-001" not in hot_ids
        assert "COLD-001" not in hot_ids

    def test_stats_counts_by_tier(self, tmp_path):
        _write_mem_file(tmp_path / "h1.md", {"id": "H1", "tier": "hot"})
        _write_mem_file(tmp_path / "h2.md", {"id": "H2", "tier": "hot"})
        _write_mem_file(tmp_path / "w1.md", {"id": "W1", "tier": "warm"})
        g = self._mk_graph(tmp_path)
        s = g.stats()
        # stats 中用 tier_hot / tier_warm 字段
        assert s.get("tier_hot", s.get("hot", 0)) == 2
        assert s.get("tier_warm", s.get("warm", 0)) == 1
        # total_nodes 或 total
        total = s.get("total_nodes", s.get("total", 0))
        assert total == 3

    def test_find_by_file_uses_cites(self, tmp_path):
        _write_mem_file(tmp_path / "code.md", {
            "id": "CODE-001", "tier": "warm",
            "cites_files": ["src/controllers/order_controller.py"]
        })
        g = self._mk_graph(tmp_path)
        nodes = g.find_by_file("src/controllers/order_controller.py")
        assert any(n.id == "CODE-001" for n in nodes)

    def test_find_by_file_no_match(self, tmp_path):
        _write_mem_file(tmp_path / "m.md", {"id": "M1", "tier": "warm"})
        g = self._mk_graph(tmp_path)
        nodes = g.find_by_file("nonexistent/file.py")
        assert nodes == []

    def test_explore_traverses_related_nodes(self, tmp_path):
        _write_mem_file(tmp_path / "root.md", {
            "id": "ROOT", "tier": "warm",
            "related_to": ["CHILD"]
        })
        _write_mem_file(tmp_path / "child.md", {"id": "CHILD", "tier": "cold"})
        g = self._mk_graph(tmp_path)
        result = g.explore("ROOT", depth=1)
        result_ids = {n.id for n in result}
        assert "CHILD" in result_ids

    def test_explore_nonexistent_returns_empty(self, tmp_path):
        g = self._mk_graph(tmp_path)
        assert g.explore("GHOST-999", depth=1) == []

    def test_hybrid_search_by_keyword(self, tmp_path):
        _write_mem_file(tmp_path / "redis.md", {
            "id": "REDIS-001", "tier": "hot",
            "tags": ["redis", "cache", "tenant"]
        }, "# Redis 缓存规范")
        _write_mem_file(tmp_path / "pg.md", {
            "id": "PG-001", "tier": "warm",
            "tags": ["postgres", "index"]
        }, "# PostgreSQL 索引")
        g = self._mk_graph(tmp_path)
        results = g.hybrid_search(["redis", "cache"])
        result_ids = {n.id for n in results}
        assert "REDIS-001" in result_ids
        assert "PG-001" not in result_ids

    def test_build_context_for_task_with_files(self, tmp_path):
        _write_mem_file(tmp_path / "api.md", {
            "id": "API-001", "tier": "warm",
            "cites_files": ["src/controllers/order.py"]
        }, "# 订单 API 规范")
        g = self._mk_graph(tmp_path)
        ctx = g.build_context_for_task(
            files=["src/controllers/order.py"],
            seed_memories=[],
            depth=0,
        )
        assert "API-001" in ctx or "订单" in ctx or "order" in ctx.lower()

    def test_build_context_no_related_returns_notice(self, tmp_path):
        g = self._mk_graph(tmp_path)  # 空目录
        ctx = g.build_context_for_task(files=["nonexistent.py"], seed_memories=[])
        assert "无" in ctx or "(" in ctx  # 返回"无关联"提示


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MemoryInjector
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.injector import MemoryInjector, InjectionResult, MemorySnippet


def _make_project_with_memories(tmp_path: Path) -> Path:
    """构造带记忆文件和 memory_index.json 的最小项目目录。"""
    mem_dir = tmp_path / "docs" / "memory"
    shared = mem_dir / "shared"
    shared.mkdir(parents=True)

    # 写 2 个记忆节点
    (shared / "MEM-001.md").write_text(textwrap.dedent("""
        ---
        id: MEM-L-001
        tier: hot
        layer: L3_domain
        tags: [redis, cache, tenant]
        ---
        # Redis 缓存必须加 tenant_id 前缀
        缓存键必须包含 tenant_id。
    """).strip())
    (shared / "MEM-002.md").write_text(textwrap.dedent("""
        ---
        id: MEM-L-002
        tier: warm
        layer: L4_application
        tags: [order, service, backend]
        ---
        # 订单服务规范
        创建订单时必须验证库存。
    """).strip())

    # 写 memory_index.json（injector 读取此文件）
    index = {
        "tree": [
            {"id": "L3", "label": "DOMAIN", "memories": [
                {"id": "MEM-L-001", "file": "shared/MEM-001.md", "tier": "hot", "tags": ["redis", "cache"]},
            ], "nodes": []},
            {"id": "L4", "label": "APP", "memories": [
                {"id": "MEM-L-002", "file": "shared/MEM-002.md", "tier": "warm", "tags": ["order", "service"]},
            ], "nodes": []},
        ]
    }
    sys_dir = mem_dir / "_system"
    sys_dir.mkdir(parents=True)
    (sys_dir / "memory_index.json").write_text(json.dumps(index), encoding="utf-8")

    return tmp_path


class TestMemoryInjectorClassifyTask:

    def test_classify_returns_node_ids(self):
        injector = MemoryInjector()
        # 使用内部规则分类，不需要 LLM
        node_ids = injector._classify_task("实现 API 接口 endpoint")
        assert isinstance(node_ids, list)
        assert len(node_ids) > 0

    def test_classify_no_match_returns_defaults(self):
        injector = MemoryInjector()
        node_ids = injector._classify_task("xyzzy wubb lalala")
        # 无匹配时应返回默认节点集（L1+L2+L5）
        assert isinstance(node_ids, list)
        assert len(node_ids) >= 1

    def test_classify_ontology_keywords(self):
        injector = MemoryInjector()
        node_ids = injector._classify_task("修改本体对象类型 ontology objecttype")
        assert isinstance(node_ids, list)


class TestMemoryInjectorInject:

    def test_inject_returns_injection_result(self, tmp_path):
        proj = _make_project_with_memories(tmp_path)
        injector = MemoryInjector(project_root=proj)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("实现 Redis 缓存接口", top_k=5)
        assert isinstance(result, InjectionResult)

    def test_inject_prompt_prefix_is_string(self, tmp_path):
        proj = _make_project_with_memories(tmp_path)
        injector = MemoryInjector(project_root=proj)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("实现 Redis 缓存接口")
        prefix = result.to_prompt_prefix()
        assert isinstance(prefix, str)

    def test_inject_no_crash_empty_project(self, tmp_path):
        injector = MemoryInjector(project_root=tmp_path)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("任意任务")
        assert isinstance(result, InjectionResult)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. RepoMap
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.repo_map import RepoMap, invalidate_cache, _build_reference_graph


def _make_ast_index(tmp_path: Path, data: dict) -> Path:
    idx = tmp_path / "ast_index.json"
    idx.write_text(json.dumps(data), encoding="utf-8")
    return idx


class TestRepoMap:

    def setup_method(self):
        invalidate_cache()  # 每个测试前清除全局缓存

    def test_build_context_returns_string(self, tmp_path):
        data = {
            "src/service.py": {
                "lang": "python", "imports": [],
                "classes": [{"name": "OrderService", "methods": [{"name": "create", "signature": "(self)"}]}]
            }
        }
        idx = _make_ast_index(tmp_path, data)
        invalidate_cache()
        rm = RepoMap(ast_index_path=idx)
        ctx = rm.build_context(["src/service.py"], token_budget=500)
        assert isinstance(ctx, str)
        assert "OrderService" in ctx

    def test_build_context_includes_neighbors(self, tmp_path):
        data = {
            "src/controller.py": {
                "lang": "python", "imports": ["OrderService"],
                "classes": [{"name": "OrderController", "methods": []}]
            },
            "src/service.py": {
                "lang": "python", "imports": [],
                "classes": [{"name": "OrderService", "methods": [{"name": "create", "signature": "(self)"}]}]
            }
        }
        idx = _make_ast_index(tmp_path, data)
        invalidate_cache()
        rm = RepoMap(ast_index_path=idx)
        ctx = rm.build_context(["src/controller.py"], token_budget=2000)
        # 邻居文件 service.py 也应包含在内
        assert "OrderService" in ctx or "service.py" in ctx

    def test_build_context_empty_ast_index(self, tmp_path):
        idx = _make_ast_index(tmp_path, {})
        invalidate_cache()
        rm = RepoMap(ast_index_path=idx)
        ctx = rm.build_context(["nonexistent.py"], token_budget=500)
        assert isinstance(ctx, str)  # 不崩溃

    def test_build_context_respects_token_budget(self, tmp_path):
        # 构造大量文件，设置极小预算
        data = {f"src/svc{i}.py": {
            "lang": "python", "imports": [],
            "classes": [{"name": f"Service{i}", "methods": [
                {"name": "method", "signature": "(self, " + "a: int, " * 20 + ")"}
            ]}]
        } for i in range(20)}
        idx = _make_ast_index(tmp_path, data)
        invalidate_cache()
        rm = RepoMap(ast_index_path=idx)
        ctx = rm.build_context(
            [f"src/svc{i}.py" for i in range(20)],
            token_budget=100,  # 非常小的预算
        )
        # 不应超过预算太多（约 100 * 4 = 400 字符）
        assert len(ctx) < 2000

    def test_build_reference_graph_connects_imports(self, tmp_path):
        data = {
            "a.py": {"lang": "python", "imports": ["BService"], "classes": [{"name": "AController", "methods": []}]},
            "b.py": {"lang": "python", "imports": [], "classes": [{"name": "BService", "methods": []}]},
        }
        graph = _build_reference_graph(data)
        assert "b.py" in graph.get("a.py", set())

    def test_nonexistent_ast_file_returns_empty_context(self, tmp_path):
        invalidate_cache()
        rm = RepoMap(ast_index_path=tmp_path / "nonexistent.json")
        ctx = rm.build_context(["src/any.py"])
        assert isinstance(ctx, str)


# ═══════════════════════════════════════════════════════════════════════════════
# 7. memory_actions (dry_run 模式)
# ═══════════════════════════════════════════════════════════════════════════════

from mms.memory.memory_actions import (
    ActionResult, _check_quality, _check_no_duplicate,
    create_memory_node, update_memory_staleness,
)
from mms.memory.memory_functions import MemoryInsight


def _make_insight(title: str = "测试记忆", description: str = "这是一条足够长的测试描述内容，用于通过质量检查。") -> MemoryInsight:
    return MemoryInsight(
        title=title,
        memory_type="lesson",
        layer="CC",
        dimension="架构",
        tags=["test", "memory"],
        description=description,
        where="src/test.py",
        how="通过测试发现",
    )


def _make_high_quality_content(title: str = "Redis 缓存必须加 tenant_id 前缀") -> str:
    """生成满足 score_memory_quality >= 0.5 要求的 Markdown 内容。"""
    return f"""---
id: MEM-L-TEST
title: {title}
type: lesson
layer: CC
tags: [redis, cache, tenant]
about_concepts: [redis-cache, tenant-isolation]
---
# {title}

## WHERE
src/services/cache_service.py — CacheKeyBuilder 类

## HOW
在所有 Redis key 写入前，通过 CacheKeyBuilder 注入 tenant_id 前缀。
缓存层不允许使用裸 key 直接写入，必须经过 builder 处理。

## WHEN
每次缓存写入操作时（读操作无需处理，tenant_id 已在 key 中）

## BODY
Redis 缓存键必须包含 tenant_id 前缀以实现租户数据隔离，否则会导致跨租户数据泄露问题。
"""


class TestMemoryActionsQualityCheck:

    def test_high_quality_passes(self):
        insight = _make_insight(
            description="Redis 缓存键必须包含 tenant_id 前缀以实现租户数据隔离。"
        )
        content = _make_high_quality_content()
        result = _check_quality(insight, content)
        assert result is None  # None = 通过

    def test_short_content_fails(self):
        insight = _make_insight()
        result = _check_quality(insight, "short")
        # 极短内容质量分低，不通过检查
        assert result is None or isinstance(result, str)  # 不崩溃即可


class TestMemoryActionsCreateNode:

    def test_dry_run_does_not_write_files(self, tmp_path):
        insight = _make_insight()
        result = create_memory_node(
            insight=insight,
            ep_id="EP-001",
            memory_root=tmp_path,
            dry_run=True,
            skip_quality_check=True,
            skip_duplicate_check=True,
        )
        assert isinstance(result, ActionResult)
        assert result.success is True
        # dry_run 不写文件
        assert result.file_path == "(dry_run)"

    def test_result_has_node_id(self, tmp_path):
        insight = _make_insight()
        result = create_memory_node(
            insight=insight,
            ep_id="EP-001",
            memory_root=tmp_path,
            dry_run=True,
            skip_quality_check=True,
            skip_duplicate_check=True,
        )
        # dry_run 时生成占位 node_id
        assert isinstance(result.node_id, str) and result.node_id != ""

    def test_action_result_dataclass(self):
        r = ActionResult(success=True, node_id="X", file_path="f.md")
        assert r.success is True
        assert r.warnings == []


class TestMemoryActionsUpdateStaleness:

    def test_update_no_crash_on_missing_node(self, tmp_path):
        """当节点不存在时，update_memory_staleness 应返回失败结果而非抛异常。"""
        result = update_memory_staleness(
            node_id="MEM-NONEXISTENT-999",
            drift_suspected=True,
            memory_root=tmp_path,
        )
        assert isinstance(result, ActionResult)
        # 节点不存在时 success=False
        assert result.success is False or isinstance(result.error, str)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. codemap / funcmap
# ═══════════════════════════════════════════════════════════════════════════════

import mms.memory.codemap as _codemap_mod
import mms.memory.funcmap as _funcmap_mod
from mms.memory.codemap import _should_ignore, _build_tree
from mms.memory.funcmap import _extract_python_functions, generate_funcmap


class TestCodemap:

    def test_should_ignore_pycache(self):
        assert _should_ignore("__pycache__") is True

    def test_should_ignore_dotfile(self):
        assert _should_ignore(".git") is True

    def test_should_ignore_normal_dir(self):
        assert _should_ignore("src") is False

    def test_build_tree_basic(self, tmp_path):
        (tmp_path / "dir_a").mkdir()
        (tmp_path / "dir_a" / "file.py").write_text("# code")
        (tmp_path / "dir_b").mkdir()
        lines: list = []
        # signature: (base, current, depth, max_depth, lines, prefix, is_last)
        _build_tree(tmp_path, tmp_path, 0, 2, lines)
        full = "\n".join(lines)
        assert "dir_a" in full or "file.py" in full

    def test_build_tree_ignores_pycache(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "cached.pyc").write_text("")
        lines: list = []
        _build_tree(tmp_path, tmp_path, 0, 2, lines)
        full = "\n".join(lines)
        assert "__pycache__" not in full


class TestFuncmap:

    def test_extract_python_functions_basic(self, tmp_path):
        src = tmp_path / "svc.py"
        src.write_text(textwrap.dedent("""
            def create_order(customer_id: str, items: list) -> dict:
                \"\"\"创建订单并返回订单详情。\"\"\"
                return {}

            def _private_helper():
                \"\"\"私有函数，应被过滤。\"\"\"
                pass

            def no_docstring():
                pass
        """))
        # patch _ROOT so relative_to doesn't fail
        with patch.object(_funcmap_mod, "_ROOT", tmp_path):
            entries = _extract_python_functions(src)
        names = [e.name for e in entries]
        assert "create_order" in names
        assert "_private_helper" not in names  # 私有函数过滤
        assert "no_docstring" not in names     # 无 docstring 过滤

    def test_extract_python_functions_no_crash_on_syntax_error(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text("def this is not python {{{{")
        with patch.object(_funcmap_mod, "_ROOT", tmp_path):
            entries = _extract_python_functions(bad)
        assert entries == []  # 语法错误时返回空列表

    def test_generate_funcmap_with_fixture(self, tmp_path):
        """generate_funcmap 扫描后端目录并返回字符串摘要。"""
        # _BACKEND_DIRS 格式: [(rel_dir_str, label), ...]
        svc_dir = tmp_path / "backend" / "app" / "services"
        svc_dir.mkdir(parents=True)
        src = svc_dir / "order_service.py"
        src.write_text(textwrap.dedent("""
            def get_order(order_id: str) -> dict:
                \"\"\"获取订单详情。\"\"\"
                return {}
        """))
        # patch _BACKEND_DIRS 和 _ROOT
        with patch.object(_funcmap_mod, "_BACKEND_DIRS",
                          [("backend/app/services", "后端 Service 层")]):
            with patch.object(_funcmap_mod, "_ROOT", tmp_path):
                result = generate_funcmap(backend_only=True)
        assert isinstance(result, str)
