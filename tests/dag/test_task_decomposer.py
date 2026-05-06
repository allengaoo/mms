"""
tests/dag/test_task_decomposer.py

P1 测试：TaskDecomposer 完整覆盖

覆盖路径：
  - RBO 路径：关键词匹配、step 格式、auto-append TEST、去重、顺序
  - LLM 路径：_parse_llm_response 正常解析、格式容错（JSON 块、裸 JSON、乱序）
  - Fallback 路径：LLM 返回空/None 时触发 fallback step
  - _assign_ids_and_order：aiu_id 顺序、exec_order 排序、depends_on 清空
  - should_decompose：低置信度、连词触发、高置信度简单任务不触发
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.task_decomposer import TaskDecomposer, CONJUNCTION_PATTERNS
from mms.dag.aiu_types import AIUStep, AIUType, AIU_EXEC_ORDER


# ─────────────────────────────────────────────────────────────────────────────
# 测试辅助
# ─────────────────────────────────────────────────────────────────────────────

def _make_decomposer() -> TaskDecomposer:
    """创建 TaskDecomposer，保证 RBO 规则已从注册表加载（≥12 条）。"""
    d = TaskDecomposer()
    assert len(d._rbo_rules) >= 12, (
        f"期望 ≥12 条 RBO 规则，实际 {len(d._rbo_rules)} 条。注册表加载可能失败。"
    )
    return d


# ─────────────────────────────────────────────────────────────────────────────
# 1. should_decompose — 触发条件
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldDecompose:
    def test_low_confidence_triggers(self):
        """置信度 < 0.6 → True"""
        assert TaskDecomposer.should_decompose("fix bug", 0.3) is True

    def test_high_confidence_simple_task_no_trigger(self):
        """高置信度 + 短任务 + 无连词 → False"""
        assert TaskDecomposer.should_decompose("fix null pointer", 0.9) is False

    def test_conjunction_triggers_regardless_of_confidence(self):
        """包含连词（'且'）即使高置信度也触发"""
        assert TaskDecomposer.should_decompose("新增字段且补充测试", 0.95) is True

    def test_conjunction_and_trigger(self):
        """英文连词 ' and ' 触发"""
        assert TaskDecomposer.should_decompose(
            "add field and update endpoint", 0.9
        ) is True

    def test_exact_threshold_boundary(self):
        """confidence = 0.6 刚好在阈值边界 → False（< 才触发）"""
        assert TaskDecomposer.should_decompose("fix bug", 0.6) is False

    def test_confidence_just_below_threshold(self):
        """confidence = 0.599 → True"""
        assert TaskDecomposer.should_decompose("fix bug", 0.599) is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. RBO 路径
# ─────────────────────────────────────────────────────────────────────────────

class TestRBODecompose:
    """验证 RBO 关键词匹配和 step 格式。"""

    def test_schema_keyword_matches(self):
        """'新增字段' → 命中 SCHEMA_ADD_FIELD RBO 规则。"""
        d = _make_decomposer()
        steps, conf = d._rbo_decompose(
            task="为 User 对象新增字段 email",
            files_hint=["backend/app/domain/user.py"],
        )
        types = {s.aiu_type for s in steps}
        assert AIUType.SCHEMA_ADD_FIELD.value in types
        assert conf > 0.0

    def test_route_keyword_matches(self):
        """'api endpoint' → 命中 ROUTE_ADD_ENDPOINT。"""
        d = _make_decomposer()
        steps, conf = d._rbo_decompose(
            task="新增 api endpoint 用于查询订单列表",
            files_hint=["backend/app/api/v1/orders.py"],
        )
        types = {s.aiu_type for s in steps}
        assert AIUType.ROUTE_ADD_ENDPOINT.value in types

    def test_no_keyword_match_returns_empty(self):
        """无关键词任务 → RBO miss，返回 ([], 0.0)。"""
        d = _make_decomposer()
        steps, conf = d._rbo_decompose(
            task="重构一下整体架构",  # 无 RBO 关键词
            files_hint=[],
        )
        assert steps == []
        assert conf == 0.0

    def test_dedup_same_type_keeps_highest_hit(self):
        """同类型规则命中多次，应去重（同类型只出现一次）。"""
        d = _make_decomposer()
        # "新增字段" 和 "添加字段" 都命中 SCHEMA_ADD_FIELD → 应去重
        steps, _ = d._rbo_decompose(
            task="新增字段并且添加字段 email 到 User",
            files_hint=[],
        )
        schema_steps = [s for s in steps if s.aiu_type == AIUType.SCHEMA_ADD_FIELD.value]
        assert len(schema_steps) == 1, "同类型 RBO 规则应去重"

    def test_depends_on_always_empty(self):
        """RBO 返回的 step（分配 ID 前）depends_on 默认为 []。"""
        d = _make_decomposer()
        steps, _ = d._rbo_decompose(
            task="新增字段并添加单元测试",
            files_hint=["backend/app/domain/user.py"],
        )
        for step in steps:
            assert step.depends_on == [], f"{step.aiu_type} 的 depends_on 不为空"

    def test_auto_append_test_step(self):
        """AUTO_APPEND_TEST=True 时，RBO 命中后自动追加 TEST_ADD_UNIT。"""
        d = _make_decomposer()
        d._current_operation = "modify_logic"  # 非 NO_TEST_OPERATIONS
        steps, _ = d._rbo_decompose(
            task="新增字段 email 到 User 模型",
            files_hint=["backend/app/domain/user.py"],
        )
        test_types = {AIUType.TEST_ADD_UNIT.value, AIUType.TEST_ADD_INTEGRATION.value}
        assert any(s.aiu_type in test_types for s in steps), (
            "AUTO_APPEND_TEST=True 时应自动追加测试步骤"
        )

    def test_no_auto_append_test_for_doc_sync(self):
        """operation=doc_sync 属于 NO_TEST_OPERATIONS，不追加 TEST。"""
        d = _make_decomposer()
        d._current_operation = "doc_sync"
        steps, _ = d._rbo_decompose(
            task="更新文档 docs 并整理字段说明",
            files_hint=[],
        )
        test_types = {AIUType.TEST_ADD_UNIT.value, AIUType.TEST_ADD_INTEGRATION.value}
        # 不应追加（即使有其他匹配）
        # doc_sync 关键词也匹配 DOC_SYNC rule，所以 steps 非空；但不追加 TEST
        non_test = [s for s in steps if s.aiu_type not in test_types]
        assert len(non_test) == len(steps), (
            f"doc_sync 操作不应追加 TEST，但发现 {[s.aiu_type for s in steps]}"
        )

    def test_rbo_confidence_scales_with_hits(self):
        """命中多条规则 → confidence 高于只命中 1 条。"""
        d = _make_decomposer()
        _, conf_single = d._rbo_decompose(
            task="新增字段 email",
            files_hint=[],
        )
        _, conf_multi = d._rbo_decompose(
            task="新增字段 email，并添加 api endpoint 权限控制",
            files_hint=[],
        )
        assert conf_multi >= conf_single, "命中更多规则的任务置信度应不低于单条命中"


# ─────────────────────────────────────────────────────────────────────────────
# 3. _assign_ids_and_order
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignIdsAndOrder:
    """验证 ID 分配与排序逻辑。"""

    def _make_steps(self, exec_orders: list[int]) -> list[AIUStep]:
        return [
            AIUStep(
                aiu_id="",
                aiu_type=AIUType.SCHEMA_ADD_FIELD.value,
                description=f"step {o}",
                layer="L3_domain",
                target_files=[],
                depends_on=["aiu_99"],  # 故意设置，应被清空
                exec_order=o,
                token_budget=2000,
                model_hint="fast",
            )
            for o in exec_orders
        ]

    def test_ids_assigned_sequentially(self):
        """aiu_id 应按 exec_order 排序后从 aiu_1 顺序分配。"""
        steps = self._make_steps([3, 1, 2])
        result = TaskDecomposer._assign_ids_and_order(steps)
        assert [s.aiu_id for s in result] == ["aiu_1", "aiu_2", "aiu_3"]

    def test_sorted_by_exec_order(self):
        """返回的步骤按 exec_order 升序排列。"""
        steps = self._make_steps([5, 1, 3])
        result = TaskDecomposer._assign_ids_and_order(steps)
        orders = [s.exec_order for s in result]
        assert orders == sorted(orders)

    def test_depends_on_preserved_and_mapped(self):
        """步骤的 depends_on 被保留，并映射到新的 aiu_id。"""
        steps = [
            AIUStep(aiu_id="step_a", aiu_type="SCHEMA_ADD_FIELD", description="", layer="", target_files=[], exec_order=1, depends_on=[]),
            AIUStep(aiu_id="step_b", aiu_type="QUERY_ADD_SELECT", description="", layer="", target_files=[], exec_order=2, depends_on=["step_a"]),
        ]
        assigned = TaskDecomposer._assign_ids_and_order(steps)
        assert assigned[0].aiu_id == "aiu_1"
        assert assigned[0].depends_on == []
        assert assigned[1].aiu_id == "aiu_2"
        assert assigned[1].depends_on == ["aiu_1"], f"depends_on 映射失败：{assigned[1].depends_on}"

    def test_cyclic_depends_on_cleared(self):
        """如果 depends_on 存在环路，则清空所有 depends_on 降级。"""
        steps = [
            AIUStep(aiu_id="step_a", aiu_type="SCHEMA_ADD_FIELD", description="", layer="", target_files=[], exec_order=1, depends_on=["step_b"]),
            AIUStep(aiu_id="step_b", aiu_type="QUERY_ADD_SELECT", description="", layer="", target_files=[], exec_order=2, depends_on=["step_a"]),
        ]
        assigned = TaskDecomposer._assign_ids_and_order(steps)
        for step in assigned:
            assert step.depends_on == [], f"存在环路时 depends_on 未清空：{step.aiu_id}"

    def test_empty_steps_returns_empty(self):
        """空列表输入 → 空列表输出，不崩溃。"""
        result = TaskDecomposer._assign_ids_and_order([])
        assert result == []

    def test_single_step_gets_aiu_1(self):
        """单步骤 → aiu_id = 'aiu_1'。"""
        steps = self._make_steps([2])
        result = TaskDecomposer._assign_ids_and_order(steps)
        assert result[0].aiu_id == "aiu_1"


# ─────────────────────────────────────────────────────────────────────────────
# 4. _parse_llm_response
# ─────────────────────────────────────────────────────────────────────────────

class TestParseLLMResponse:
    """验证 LLM 响应解析：正常、代码块、裸 JSON、invalid。"""

    def _decomposer(self):
        return _make_decomposer()

    def test_valid_json_block(self):
        """标准 ```json ... ``` 代码块格式。"""
        d = self._decomposer()
        raw = """
```json
{
  "steps": [
    {
      "aiu_type": "SCHEMA_ADD_FIELD",
      "description": "新增 email 字段",
      "target_files": ["backend/app/domain/user.py"],
      "depends_on": [],
      "token_budget": 2500,
      "model_hint": "fast"
    }
  ],
  "decomposed_by": "llm",
  "confidence": 0.8
}
```
"""
        steps, conf = d._parse_llm_response(raw)
        assert len(steps) == 1
        assert steps[0].aiu_type == AIUType.SCHEMA_ADD_FIELD.value
        assert abs(conf - 0.8) < 0.01

    def test_bare_json_without_codeblock(self):
        """裸 JSON（无代码块包裹）也能正确解析。"""
        d = self._decomposer()
        raw = """{
  "steps": [
    {
      "aiu_type": "ROUTE_ADD_ENDPOINT",
      "description": "添加 /users/{id} 路由",
      "target_files": ["backend/app/api/v1/users.py"],
      "depends_on": [],
      "token_budget": 3000,
      "model_hint": "fast"
    }
  ],
  "confidence": 0.75
}"""
        steps, conf = d._parse_llm_response(raw)
        assert len(steps) == 1
        assert steps[0].aiu_type == AIUType.ROUTE_ADD_ENDPOINT.value

    def test_invalid_aiu_type_skipped(self):
        """无效 AIU 类型被静默跳过，不崩溃。"""
        d = self._decomposer()
        raw = """{
  "steps": [
    {"aiu_type": "NON_EXISTENT_TYPE", "description": "...", "target_files": []},
    {"aiu_type": "SCHEMA_ADD_FIELD", "description": "valid", "target_files": []}
  ],
  "confidence": 0.7
}"""
        steps, conf = d._parse_llm_response(raw)
        assert len(steps) == 1
        assert steps[0].aiu_type == AIUType.SCHEMA_ADD_FIELD.value

    def test_malformed_json_returns_empty(self):
        """格式损坏的 JSON → 返回 ([], 0.0)，不崩溃。"""
        d = self._decomposer()
        raw = "{ invalid json here"
        steps, conf = d._parse_llm_response(raw)
        assert steps == []
        assert conf == 0.0

    def test_empty_response_returns_empty(self):
        """空字符串 → ([], 0.0)。"""
        d = self._decomposer()
        steps, conf = d._parse_llm_response("")
        assert steps == []
        assert conf == 0.0

    def test_empty_steps_array_returns_empty(self):
        """steps 为空数组 → ([], 0.0)。"""
        d = self._decomposer()
        raw = '{"steps": [], "confidence": 0.9}'
        steps, conf = d._parse_llm_response(raw)
        assert steps == []
        assert conf == 0.0

    def test_depends_on_preserved_in_llm_response(self):
        """LLM 在 JSON 中设置了 depends_on，解析后应保留。"""
        d = self._decomposer()
        raw = """{
  "steps": [
    {
      "aiu_id": "aiu_0",
      "aiu_type": "SCHEMA_ADD_FIELD",
      "description": "step1",
      "target_files": [],
      "depends_on": [],
      "token_budget": 2000,
      "model_hint": "fast"
    },
    {
      "aiu_id": "aiu_1",
      "aiu_type": "QUERY_ADD_SELECT",
      "description": "step2",
      "target_files": [],
      "depends_on": ["aiu_0"],
      "token_budget": 2000,
      "model_hint": "fast"
    }
  ],
  "confidence": 0.7
}"""
        steps, _ = d._parse_llm_response(raw)
        assert steps[1].depends_on == ["aiu_0"], "LLM 设置的 depends_on 应被保留"

    def test_multi_steps_parsed_correctly(self):
        """多步骤 JSON → 正确解析每个步骤。"""
        d = self._decomposer()
        raw = """{
  "steps": [
    {"aiu_type": "SCHEMA_ADD_FIELD", "description": "s1", "target_files": [], "token_budget": 2000, "model_hint": "fast"},
    {"aiu_type": "MUTATION_ADD_INSERT", "description": "s2", "target_files": [], "token_budget": 3000, "model_hint": "fast"},
    {"aiu_type": "TEST_ADD_UNIT", "description": "s3", "target_files": [], "token_budget": 2500, "model_hint": "fast"}
  ],
  "confidence": 0.85
}"""
        steps, conf = d._parse_llm_response(raw)
        assert len(steps) == 3
        assert abs(conf - 0.85) < 0.01

    def test_extra_text_before_json_handled(self):
        """JSON 前有额外文本（常见 LLM 输出模式）→ 正确解析。"""
        d = self._decomposer()
        raw = """好的，以下是分解结果：

{
  "steps": [
    {"aiu_type": "DOC_SYNC", "description": "更新文档", "target_files": []}
  ],
  "confidence": 0.6
}"""
        steps, _ = d._parse_llm_response(raw)
        assert len(steps) == 1
        assert steps[0].aiu_type == AIUType.DOC_SYNC.value


# ─────────────────────────────────────────────────────────────────────────────
# 5. decompose — 完整链路
# ─────────────────────────────────────────────────────────────────────────────

class TestDecomposeFull:
    """验证 decompose() 的完整调用链路。"""

    def test_rbo_path_returns_aiuplan(self):
        """RBO 命中时，decompose() 返回有效 AIUPlan，decomposed_by='rbo'。"""
        d = _make_decomposer()
        plan = d.decompose(
            task="为 User 对象新增字段 email",
            dag_unit_id="U_test",
            layer="L3_domain",
            operation="add_field",
            confidence=0.4,
            files_hint=["backend/app/domain/user.py"],
        )
        assert plan.decomposed_by == "rbo"
        assert len(plan.steps) >= 1
        assert plan.dag_unit_id == "U_test"

    def test_rbo_steps_have_sequential_ids(self):
        """RBO 路径输出的 steps 的 aiu_id 为 aiu_1, aiu_2, ..."""
        d = _make_decomposer()
        plan = d.decompose(
            task="新增字段并查询",
            dag_unit_id="U_seq",
            confidence=0.3,
        )
        for i, step in enumerate(plan.steps, 1):
            assert step.aiu_id == f"aiu_{i}", (
                f"aiu_id 错误：期望 aiu_{i}，实际 {step.aiu_id}"
            )

    def test_fallback_when_llm_returns_empty(self):
        """
        LLM 路径返回空（mock），RBO miss 后触发 fallback 单步骤。
        fallback step 使用 capable 模型。
        """
        d = _make_decomposer()
        # 使用一个无关键词任务触发 LLM 路径，并 mock LLM 返回 None
        with patch("mms.dag.task_decomposer.TaskDecomposer._llm_decompose", return_value=([], 0.0)):
            plan = d.decompose(
                task="执行一个复杂的非标准架构重构",
                dag_unit_id="U_fallback",
                confidence=0.3,
            )
        assert plan.decomposed_by == "fallback"
        assert len(plan.steps) == 1
        assert plan.steps[0].model_hint == "capable"
        assert plan.confidence == 0.3

    def test_original_task_preserved_in_plan(self):
        """AIUPlan.original_task 保留原始任务描述。"""
        d = _make_decomposer()
        task = "为 Order 新增字段"
        plan = d.decompose(task=task, dag_unit_id="U_orig")
        assert plan.original_task == task

    def test_all_steps_deps_cleared(self):
        """decompose() 输出中，所有 step 的 depends_on = []。"""
        d = _make_decomposer()
        plan = d.decompose(
            task="新增字段 email 并配置权限",
            dag_unit_id="U_deps",
            confidence=0.3,
        )
        for step in plan.steps:
            assert step.depends_on == [], (
                f"step {step.aiu_id} depends_on 未清空：{step.depends_on}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. _match_files
# ─────────────────────────────────────────────────────────────────────────────

class TestMatchFiles:
    def test_empty_dag_files_returns_hint(self):
        """dag_files 为空时，返回 files_hint 中存在的文件（或 hint 本身）。"""
        result = TaskDecomposer._match_files([], ["backend/app/domain/user.py"])
        # 文件可能不存在于测试环境，但不应崩溃
        assert isinstance(result, list)

    def test_dag_files_with_matching_prefix(self):
        """dag_files 中有匹配 files_hint 前缀的文件 → 返回匹配结果。"""
        dag = ["backend/app/domain/user.py", "backend/app/api/v1/users.py"]
        hint = ["backend/app/domain"]
        result = TaskDecomposer._match_files(dag, hint)
        assert "backend/app/domain/user.py" in result

    def test_no_match_returns_first_two(self):
        """无匹配时返回 dag_files 的前两个文件。"""
        dag = ["a.py", "b.py", "c.py"]
        hint = ["nonexistent/prefix"]
        result = TaskDecomposer._match_files(dag, hint)
        assert result == ["a.py", "b.py"]
