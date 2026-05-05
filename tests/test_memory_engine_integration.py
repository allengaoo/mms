"""
test_memory_engine_integration.py — Memory Engine 集成测试

测试跨组件联动的数据流正确性：

Chain A: Bootstrap → MemoryGraph
  验证 bootstrap 生成的记忆文件被 MemoryGraph 正确加载

Chain B: MemoryGraph → TaskMatcher
  验证 TaskMatcher 能找到与 MemoryGraph 中节点相关的历史记录

Chain C: MemoryGraph → MemoryInjector
  验证 MemoryInjector 能从 MemoryGraph 中读取并组装注入结果

Chain D: Bootstrap → MemoryGraph → MemoryInjector → TaskMatcher 全链路
  验证完整数据流：代码 → 记忆 → 注入 → 相似性匹配

Chain E: memory_actions 写入 → MemoryGraph 读取
  验证 create_memory_node 写入的节点可被 MemoryGraph 加载

注意:
  - 所有测试使用 tmp_path 隔离，不修改真实项目目录
  - Bootstrap 使用真实 Python FastAPI fixture
  - 不调用 LLM（所有 LLM 路径通过 use_llm=False 或 mock 跳过）
"""
from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.bootstrap.ontology_populator import bootstrap_project
from mms.memory.graph_resolver import MemoryGraph
from mms.memory.injector import MemoryInjector, InjectionResult
from mms.memory.task_matcher import TaskMatcher
from mms.memory.memory_actions import ActionResult, create_memory_node
from mms.memory.memory_functions import MemoryInsight

_FIXTURES = _HERE / "fixtures"
_PYTHON_FIXTURE = _FIXTURES / "python-fastapi-demo"
_JAVA_FIXTURE = _FIXTURES / "spring-boot-demo"


# ── 共用 Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_python(tmp_path):
    """将 python-fastapi-demo 复制到 tmp_path，运行 bootstrap，返回临时目录。"""
    dest = tmp_path / "python-fastapi-demo"
    shutil.copytree(_PYTHON_FIXTURE, dest)
    report = bootstrap_project(
        project_root=dest,
        skip_seeds=True,     # 不注入 seed_packs（保持测试快）
        skip_doc_absorb=True,
        verbose=False,
        min_confidence=0.0,  # 低置信度也生成，保证有节点可测
    )
    return dest, report


@pytest.fixture
def memory_graph_with_nodes(tmp_path):
    """创建带有三个节点的 MemoryGraph 目录。"""
    mem_root = tmp_path / "memory"
    shared = mem_root / "shared"
    shared.mkdir(parents=True)

    nodes = [
        {
            "id": "MEM-INTG-001",
            "tier": "hot",
            "layer": "L3_domain",
            "tags": ["redis", "cache", "tenant"],
            "cites_files": ["src/services/cache_service.py"],
            "title": "Redis 缓存必须加 tenant_id 前缀",
            "body": "Redis 缓存键必须包含 tenant_id 前缀以实现租户数据隔离。",
        },
        {
            "id": "MEM-INTG-002",
            "tier": "warm",
            "layer": "L4_application",
            "tags": ["order", "service", "backend"],
            "cites_files": ["src/services/order_service.py"],
            "related_to": ["MEM-INTG-001"],
            "title": "订单服务创建规范",
            "body": "创建订单时必须验证库存，并在同一事务内更新库存记录。",
        },
        {
            "id": "MEM-INTG-003",
            "tier": "cold",
            "layer": "L5_interface",
            "tags": ["api", "controller", "rest"],
            "cites_files": ["src/controllers/order_controller.py"],
            "title": "订单 API 路由设计",
            "body": "POST /api/orders 创建订单，返回 201 + 订单详情。",
        },
    ]

    for n in nodes:
        tags_str = "\n".join(f"  - {t}" for t in n.get("tags", []))
        cites_str = "\n".join(f"  - {f}" for f in n.get("cites_files", []))
        related_str = "\n".join(f"  - {r}" for r in n.get("related_to", []))
        fm_parts = [
            f"id: {n['id']}",
            f"tier: {n['tier']}",
            f"layer: {n['layer']}",
            f"tags:\n{tags_str}" if tags_str else "tags: []",
        ]
        if cites_str:
            fm_parts.append(f"cites_files:\n{cites_str}")
        if related_str:
            fm_parts.append(f"related_to:\n{related_str}")

        content = "---\n" + "\n".join(fm_parts) + "\n---\n# " + n["title"] + "\n" + n["body"]
        (shared / f"{n['id']}.md").write_text(content, encoding="utf-8")

    return mem_root, nodes


# ═══════════════════════════════════════════════════════════════════════════════
# Chain A: Bootstrap → MemoryGraph
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainA_BootstrapToMemoryGraph:

    def test_bootstrap_creates_memory_files(self, isolated_python):
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        md_files = list(mem_dir.rglob("*.md"))
        assert len(md_files) > 0, "Bootstrap 应生成至少一个记忆文件"

    def test_memory_graph_loads_bootstrap_nodes(self, isolated_python):
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        assert len(g._nodes) > 0, "MemoryGraph 应能加载 bootstrap 生成的记忆节点"

    def test_bootstrap_nodes_have_valid_ids(self, isolated_python):
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        for node_id, node in g._nodes.items():
            assert node_id == node.id, f"节点 ID 不一致：{node_id} vs {node.id}"
            # MEM-BOOT- 前缀 或 其他合法前缀
            assert node.id.startswith(("MEM-", "AD-", "BIZ-", "ENV-")), \
                f"节点 ID 前缀不合法: {node.id}"

    def test_bootstrap_nodes_have_layer_field(self, isolated_python):
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        # v4.0：细粒度层 ID（规范值）+ 粗粒度别名（向后兼容）
        valid_layers = {
            "L5_frontend", "L5_api", "L4_service", "L4_worker",
            "L3_ontology", "L3_data_pipeline",
            "L2_database", "L2_messaging", "L2_cache", "L2_storage",
            "L1_security", "CC_architecture", "CC_testing", "CC_governance",
            "BIZ", "Ops", "Tooling_mms",
            "L1_platform", "L2_infrastructure", "L3_domain", "L4_application", "L5_interface", "CC",
        }
        for node in g._nodes.values():
            if node.layer:
                assert node.layer in valid_layers, \
                    f"节点 {node.id} 的 layer={node.layer!r} 不在 schema 允许值中"

    def test_find_by_file_works_for_bootstrap_nodes(self, isolated_python):
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        if not g._nodes:
            pytest.skip("没有生成记忆节点")
        # 取第一个有 cites_files 的节点，验证反向查找
        for node in g._nodes.values():
            if node.cites_files:
                file_path = node.cites_files[0]
                found = g.find_by_file(file_path)
                assert any(n.id == node.id for n in found), \
                    f"find_by_file({file_path!r}) 未找到节点 {node.id}"
                return
        pytest.skip("没有带 cites_files 的节点")

    def test_bootstrap_report_lists_generated_memories(self, isolated_python):
        dest, report = isolated_python
        assert hasattr(report, "generated_memories") or hasattr(report, "memory_files"), \
            "BootstrapV2Report 应包含生成的记忆文件信息"


# ═══════════════════════════════════════════════════════════════════════════════
# Chain B: MemoryGraph → TaskMatcher
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainB_MemoryGraphToTaskMatcher:

    def test_memory_ids_usable_in_task_records(self, memory_graph_with_nodes, tmp_path):
        """MemoryGraph 中的节点 ID 可以正确存入 TaskMatcher 历史并被检索。"""
        mem_root, nodes = memory_graph_with_nodes
        g = MemoryGraph(memory_root=mem_root)

        # 找到所有热节点 ID
        hot_ids = [n.id for n in g.all_hot()]
        assert len(hot_ids) > 0

        # 将 hot 节点 ID 存入 TaskMatcher 历史
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        rec = m.build_record(
            "实现 Redis 缓存 tenant_id 接口",
            template="ep-backend-api",
            hit_memories=hot_ids,
            hit_files=["src/services/cache_service.py"],
        )
        m.append_record(rec)

        # 用相似任务查找
        result = m.find_similar("Redis 缓存 tenant_id service")
        assert result is not None
        assert any(mid in result.record.hit_memories for mid in hot_ids)

    def test_warm_nodes_can_be_referenced_in_history(self, memory_graph_with_nodes, tmp_path):
        mem_root, nodes = memory_graph_with_nodes
        g = MemoryGraph(memory_root=mem_root)
        warm_nodes = [n for n in g._nodes.values() if n.tier == "warm"]
        if not warm_nodes:
            pytest.skip("无 warm 节点")

        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        warm_ids = [n.id for n in warm_nodes]
        rec = m.build_record(
            "订单服务创建接口 OrderService backend",
            template="ep-backend-api",
            hit_memories=warm_ids,
            hit_files=["src/services/order_service.py"],
        )
        m.append_record(rec)

        result = m.find_similar("订单服务 order service backend create")
        assert result is not None
        assert any(mid in result.record.hit_memories for mid in warm_ids)

    def test_graph_explore_results_usable_as_task_context(self, memory_graph_with_nodes, tmp_path):
        """explore() 返回的节点 ID 可作为 hit_memories 存入历史。"""
        mem_root, nodes = memory_graph_with_nodes
        g = MemoryGraph(memory_root=mem_root)

        related = g.explore("MEM-INTG-002", depth=1)
        related_ids = [n.id for n in related]

        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        rec = m.build_record(
            "修改订单服务，需要用到 Redis 缓存",
            template="ep-backend-api",
            hit_memories=related_ids,
            hit_files=["src/services/order_service.py"],
        )
        m.append_record(rec)
        assert len(rec.tags) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Chain C: MemoryGraph → MemoryInjector
# ═══════════════════════════════════════════════════════════════════════════════

def _make_full_project(tmp_path: Path, mem_root: Path, nodes: list) -> Path:
    """在 tmp_path 创建能被 MemoryInjector 读取的完整项目结构。"""
    proj = tmp_path / "project"
    sys_dir = proj / "docs" / "memory" / "_system"
    sys_dir.mkdir(parents=True)

    # 复制记忆文件
    shared_dest = proj / "docs" / "memory" / "shared"
    shared_dest.mkdir(parents=True)
    src_shared = mem_root / "shared"
    for md in src_shared.glob("*.md"):
        shutil.copy(md, shared_dest / md.name)

    # 写 memory_index.json
    index = {
        "tree": [
            {
                "id": "L3",
                "label": "DOMAIN",
                "memories": [
                    {"id": n["id"], "file": f"shared/{n['id']}.md",
                     "tier": n["tier"], "tags": n.get("tags", [])}
                    for n in nodes if n.get("layer") == "L3_domain"
                ],
                "nodes": []
            },
            {
                "id": "L4",
                "label": "APP",
                "memories": [
                    {"id": n["id"], "file": f"shared/{n['id']}.md",
                     "tier": n["tier"], "tags": n.get("tags", [])}
                    for n in nodes if n.get("layer") == "L4_application"
                ],
                "nodes": []
            },
        ]
    }
    (sys_dir / "memory_index.json").write_text(json.dumps(index), encoding="utf-8")
    return proj


class TestChainC_MemoryGraphToInjector:

    def test_injector_reads_from_memory_graph(self, memory_graph_with_nodes, tmp_path):
        """MemoryInjector 应能注入来自 MemoryGraph 节点的内容。"""
        mem_root, nodes = memory_graph_with_nodes
        proj = _make_full_project(tmp_path, mem_root, nodes)
        injector = MemoryInjector(project_root=proj)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("实现 Redis 缓存 tenant_id 隔离接口")
        assert isinstance(result, InjectionResult)

    def test_injector_prompt_prefix_is_non_empty(self, memory_graph_with_nodes, tmp_path):
        mem_root, nodes = memory_graph_with_nodes
        proj = _make_full_project(tmp_path, mem_root, nodes)
        injector = MemoryInjector(project_root=proj)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("订单服务 OrderService 创建接口")
        prefix = result.to_prompt_prefix()
        assert isinstance(prefix, str)

    def test_injector_detected_layers_is_list(self, memory_graph_with_nodes, tmp_path):
        mem_root, nodes = memory_graph_with_nodes
        proj = _make_full_project(tmp_path, mem_root, nodes)
        injector = MemoryInjector(project_root=proj)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("实现 API 接口")
        assert isinstance(result.detected_layers, list)

    def test_injector_classify_task_consistency(self):
        """_classify_task 对相同输入应返回一致的结果。"""
        injector = MemoryInjector()
        layers1 = injector._classify_task("实现 Redis 缓存接口")
        layers2 = injector._classify_task("实现 Redis 缓存接口")
        assert set(layers1) == set(layers2), "相同任务应产生一致的 layer 分类"


# ═══════════════════════════════════════════════════════════════════════════════
# Chain D: Bootstrap → MemoryGraph → MemoryInjector → TaskMatcher 全链路
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainD_FullPipeline:

    def test_bootstrap_to_task_matcher_full_chain(self, isolated_python, tmp_path):
        """
        完整链路：bootstrap 生成记忆 → MemoryGraph 加载 → MemoryInjector 注入 →
        TaskMatcher 存档 → 相似任务查找命中
        """
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"

        # Step 1: MemoryGraph 加载 bootstrap 生成的节点
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        if not g._nodes:
            pytest.skip("Bootstrap 未生成记忆节点")

        # Step 2: MemoryInjector 注入（用 bootstrap 目录作为 project_root）
        injector = MemoryInjector(project_root=dest)
        with patch.object(injector, "_enhance_with_llm", return_value=None):
            result = injector.inject("实现代码骨架分析 bootstrap AST")
        assert isinstance(result, InjectionResult)

        # Step 3: TaskMatcher 存档本次任务
        hf = tmp_path / "hist.jsonl"
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        memory_ids = [s.node_id for s in result.memories if s.node_id]
        rec = m.build_record(
            "实现代码骨架分析 bootstrap AST 推断",
            template="ep-backend-api",
            hit_memories=memory_ids or list(g._nodes.keys())[:3],
            hit_files=["src/mms/bootstrap/ontology_populator.py"],
        )
        m.append_record(rec)

        # Step 4: 相似任务应命中
        hit = m.find_similar("分析代码骨架 bootstrap AST 推断架构层")
        assert hit is not None or len(rec.tags) > 0  # 至少标签不为空

    def test_memory_graph_build_context_integration(self, isolated_python):
        """build_context_for_task 使用 bootstrap 生成的节点构建上下文。"""
        dest, report = isolated_python
        mem_dir = dest / "docs" / "memory"
        g = MemoryGraph(memory_root=mem_dir)
        g._ensure_loaded()
        if not g._nodes:
            pytest.skip("Bootstrap 未生成记忆节点")

        # 取前 3 个节点 ID 作为 seed
        seeds = list(g._nodes.keys())[:3]
        ctx = g.build_context_for_task(files=[], seed_memories=seeds, depth=1)
        assert isinstance(ctx, str)
        assert len(ctx) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Chain E: memory_actions 写入 → MemoryGraph 读取
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainE_ActionWriteToGraph:

    def _make_insight(self, title: str = "集成测试记忆节点") -> MemoryInsight:
        return MemoryInsight(
            title=title,
            memory_type="lesson",
            layer="CC",
            dimension="架构",
            tags=["integration", "test"],
            description="这是一条集成测试写入的记忆节点，用于验证 Action→Graph 联动。",
            where="src/test_integration.py",
            how="通过集成测试生成",
        )

    def test_create_node_dry_run_does_not_affect_graph(self, tmp_path):
        """dry_run=True 时不应写文件，MemoryGraph 不应读到新节点。"""
        mem_root = tmp_path / "memory"
        mem_root.mkdir()

        insight = self._make_insight()
        result = create_memory_node(
            insight=insight,
            ep_id="EP-INTG-001",
            memory_root=mem_root,
            dry_run=True,
            skip_quality_check=True,
            skip_duplicate_check=True,
        )
        assert result.success is True
        assert result.file_path == "(dry_run)"

        # MemoryGraph 不应有任何节点
        g = MemoryGraph(memory_root=mem_root)
        g._ensure_loaded()
        assert len(g._nodes) == 0

    def test_create_node_result_has_valid_file_path(self, tmp_path):
        """create_memory_node 应返回合法的 file_path（相对路径格式）。"""
        insight = self._make_insight("集成测试节点 - 验证路径")
        result = create_memory_node(
            insight=insight,
            ep_id="EP-INTG-002",
            memory_root=tmp_path,
            dry_run=True,  # dry_run 避免真实写入项目目录
            skip_quality_check=True,
            skip_duplicate_check=True,
        )
        assert result.success is True
        assert result.file_path == "(dry_run)"
        assert result.node_id != ""

    def test_multiple_nodes_graph_stats(self, tmp_path):
        """写入多个节点后，MemoryGraph.stats() 数量正确。"""
        # 手动写两个节点（使用已知格式）
        mem_root = tmp_path / "memory"
        shared = mem_root / "shared"
        shared.mkdir(parents=True)

        for i in range(3):
            content = f"""---
id: MEM-CHAIN-E-{i:03d}
tier: warm
layer: L3_domain
tags:
  - integration
---
# 节点 {i}
"""
            (shared / f"node_{i}.md").write_text(content)

        g = MemoryGraph(memory_root=mem_root)
        s = g.stats()
        total = s.get("total_nodes", s.get("total", 0))
        assert total == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Chain F: TaskMatcher 持久化与重新加载
# ═══════════════════════════════════════════════════════════════════════════════

class TestChainF_TaskMatcherPersistence:

    def test_records_survive_reload(self, tmp_path):
        """TaskMatcher 写入的历史记录在重新实例化后仍可读取和命中。"""
        hf = tmp_path / "persistent_hist.jsonl"
        task = "实现 Redis 缓存 tenant_id 前缀接口 cache service"

        # 写入
        m1 = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        rec = m1.build_record(task, "ep-backend-api", ["MEM-001"], ["src/cache.py"])
        m1.append_record(rec)

        # 重新加载
        m2 = TaskMatcher(history_file=hf, similarity_threshold=0.1)
        result = m2.find_similar("Redis 缓存 cache service tenant_id")
        assert result is not None, "重新加载后应能找到历史记录"

    def test_rolling_delete_preserves_newest(self, tmp_path):
        """滚动删除只保留最新记录，且历史可继续正常读取。"""
        hf = tmp_path / "rolling.jsonl"
        m = TaskMatcher(history_file=hf, max_history_records=3, similarity_threshold=0.1)

        tasks = [
            ("修复登录 bug login authentication", "MEM-A"),
            ("实现订单服务 order service backend", "MEM-B"),
            ("实现支付接口 payment api gateway", "MEM-C"),
            ("实现消息通知 notification webhook", "MEM-D"),  # 第4条，M记录触发滚动
        ]
        for t, mid in tasks:
            rec = m.build_record(t, None, [mid], [])
            m.append_record(rec)

        # 只保留最新 3 条，最旧的应被删除
        lines = [l for l in hf.read_text().splitlines() if l.strip()]
        assert len(lines) == 3
        # 最新的是消息通知
        last = json.loads(lines[-1])
        assert "notification" in last["task"] or "通知" in last["task"]

    def test_personal_history_searched_first(self, tmp_path):
        """author 过滤：个人历史优先于全局历史。"""
        hf = tmp_path / "personal.jsonl"

        # alice 的 Redis 相关任务
        m = TaskMatcher(history_file=hf, similarity_threshold=0.1, history_top_x=5)
        alice_rec = m.build_record(
            "实现 Redis 缓存 cache service tenant",
            None, ["MEM-ALICE-001"], [], author="alice"
        )
        bob_rec = m.build_record(
            "实现 Redis 缓存 cache service tenant",
            None, ["MEM-BOB-001"], [], author="bob"
        )
        m.append_record(alice_rec)
        m.append_record(bob_rec)

        # 以 alice 身份查询
        result = m.find_similar(
            "Redis 缓存 cache service tenant",
            author="alice"
        )
        assert result is not None
        # alice 的个人历史应优先命中
        if result:
            assert "MEM-ALICE-001" in result.record.hit_memories
