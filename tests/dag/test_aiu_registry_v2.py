"""
tests/dag/test_aiu_registry_v2.py

阶段二：OCP 动态 RBO 规则测试（Test 3 — OCP Dynamic RBO）

验证目标：
  3a. 内置 YAML 加载后 get_rbo_rules() 返回 ≥12 条核心规则
  3b. 每条规则的 dict key 与 TaskDecomposer._rbo_rules 预期格式完全兼容
  3c. 在 tmp_path 写入自定义 YAML → 扩展注册表 → get_rbo_rules() 自动包含新规则
       （OCP 扩展点验证：零 Python 源码修改，仅增加 YAML 文件）
  3d. 内置 Enum 类型在 YAML 加载后保持完整，无遗漏
  3e. 规则按 exec_order 排序（确定性保证）
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from mms.dag.aiu_registry import AIURegistry
from mms.dag.aiu_types import AIUType

# ─────────────────────────────────────────────────────────────────────────────
# 期望的核心 RBO 类型（每个 YAML family 文件中各自定义的 rbo_triggers 类型）
# ─────────────────────────────────────────────────────────────────────────────

EXPECTED_CORE_RBO_IDS = {
    "rbo_schema_add_field",
    "rbo_contract_add_request",
    "rbo_contract_add_response",
    "rbo_config_modify",
    "rbo_query_add_select",
    "rbo_mutation_add_insert",
    "rbo_mutation_add_update",
    "rbo_logic_add_guard",
    "rbo_route_add_endpoint",
    "rbo_route_add_permission",
    "rbo_test_add_unit",
    "rbo_doc_sync",
}

# TaskDecomposer 期望的 RBO 规则 dict key（来自 task_decomposer.py _rbo_rules 使用处）
REQUIRED_RULE_KEYS = {
    "id",
    "aiu_type",
    "keywords",
    "description_template",
    "token_budget",
    "model_hint",
    "files_hint",
}


# ─────────────────────────────────────────────────────────────────────────────
# 3a：内置核心 RBO 规则数量 ≥ 12
# ─────────────────────────────────────────────────────────────────────────────

class TestBuiltinRBORules:
    def _registry(self) -> AIURegistry:
        """每次测试使用新实例（避免单例状态污染）。"""
        r = AIURegistry()
        r._loaded = False  # 强制重新加载
        return r

    def test_get_rbo_rules_returns_at_least_12(self):
        """内置 YAML 加载后 RBO 规则数 ≥ 12（当前实现：12 条）。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        rule_ids = {r["id"] for r in rules}
        assert len(rules) >= 12, f"期望 ≥12 条规则，实际得到 {len(rules)} 条"
        assert EXPECTED_CORE_RBO_IDS.issubset(rule_ids), (
            f"缺少核心规则：{EXPECTED_CORE_RBO_IDS - rule_ids}"
        )

    def test_each_rule_has_required_keys(self):
        """每条规则都包含 TaskDecomposer 所需的全部 key。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        for rule in rules:
            missing = REQUIRED_RULE_KEYS - set(rule.keys())
            assert not missing, (
                f"规则 {rule.get('id', '?')} 缺少 key：{missing}"
            )

    def test_rule_aiu_type_is_valid_enum(self):
        """每条规则的 aiu_type 是合法的 AIUType Enum 实例。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        for rule in rules:
            assert isinstance(rule["aiu_type"], AIUType), (
                f"规则 {rule['id']} 的 aiu_type={rule['aiu_type']} 不是 AIUType 枚举"
            )

    def test_rule_keywords_is_non_empty_list(self):
        """每条规则的 keywords 是非空列表（至少 1 个关键词）。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        for rule in rules:
            kws = rule["keywords"]
            assert isinstance(kws, list) and len(kws) >= 1, (
                f"规则 {rule['id']} 的 keywords 为空：{kws}"
            )

    def test_rule_token_budget_is_positive_int(self):
        """每条规则的 token_budget > 0。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        for rule in rules:
            assert isinstance(rule["token_budget"], int) and rule["token_budget"] > 0, (
                f"规则 {rule['id']} 的 token_budget={rule['token_budget']} 不合法"
            )

    def test_rule_model_hint_is_valid(self):
        """每条规则的 model_hint 为 'fast' 或 'capable'。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        valid_hints = {"fast", "capable"}
        for rule in rules:
            assert rule["model_hint"] in valid_hints, (
                f"规则 {rule['id']} 的 model_hint={rule['model_hint']} 不合法"
            )

    def test_rules_sorted_by_exec_order(self):
        """规则按 exec_order 排序，保证 TaskDecomposer 匹配顺序的确定性。"""
        registry = self._registry()
        rules = registry.get_rbo_rules()
        # 通过检查规则的 aiu_type 对应的 exec_order 序列是否单调不减来验证
        exec_orders = [
            registry._registry[rule["aiu_type"].value].exec_order
            for rule in rules
        ]
        assert exec_orders == sorted(exec_orders), (
            f"规则未按 exec_order 排序：{exec_orders}"
        )

    def test_builtin_enum_types_all_present(self):
        """内置 AIUType Enum 值均已在注册表中注册（无遗漏）。"""
        registry = self._registry()
        registry._ensure_loaded()
        registered_ids = set(registry._registry.keys())
        for aiu_type in AIUType:
            assert aiu_type.value in registered_ids, (
                f"AIUType.{aiu_type.name} ({aiu_type.value}) 未在注册表中注册"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3c：OCP 扩展点验证 — 自定义 YAML 注入
# ─────────────────────────────────────────────────────────────────────────────

class TestOCPExtension:
    """
    验证"零 Python 修改，只增加 YAML 文件"的 OCP 扩展能力。

    由于 AIUType Enum 是静态的，新的自定义类型必须使用已有的 Enum 值，
    或通过 custom/ 目录扩展。本测试验证：
      1. 在 custom/ 目录写入带 rbo_triggers 的 YAML → 注册表包含新定义
      2. get_rbo_rules() 自动返回新规则
    """

    def _fresh_registry(self, aius_dir=None) -> AIURegistry:
        """新建注册表实例，可指定自定义 YAML 目录。"""
        return AIURegistry(aius_dir=aius_dir)

    def test_custom_yaml_with_existing_type_adds_rbo_rule(self, tmp_path):
        """
        在自定义 YAML 中为已有的 AIUType 追加/覆盖 rbo_triggers → get_rbo_rules 收录。

        策略：通过 aius_dir 参数将注册表 YAML 目录指向 tmp_path，
        验证 get_rbo_rules() 能正确读取自定义关键词。
        """
        custom_yaml = tmp_path / "family_custom_test.yaml"
        custom_yaml.write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: custom_test
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: 自定义 rbo_triggers 覆盖测试
                    base_cost: 2500
                    exec_order: 1
                    rbo_triggers:
                      keywords:
                        - 自定义字段
                        - custom_field
                      description_template: "自定义：在 {target_files} 中新增字段"
                      token_budget: 2500
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )

        registry = self._fresh_registry(aius_dir=tmp_path)
        rules = registry.get_rbo_rules()

        rule_ids = {r["id"] for r in rules}
        assert "rbo_schema_add_field" in rule_ids, (
            "自定义 YAML 中的 SCHEMA_ADD_FIELD rbo_triggers 未被 get_rbo_rules 收录"
        )
        schema_rule = next(r for r in rules if r["id"] == "rbo_schema_add_field")
        assert "自定义字段" in schema_rule["keywords"], (
            f"自定义关键词未被加载：{schema_rule['keywords']}"
        )

    def test_registry_reload_picks_up_new_yaml(self, tmp_path):
        """
        模拟运行时新增 YAML 文件：每次实例化新的 AIURegistry 重新加载 YAML。
        验证注册表隔离性（不同实例不共享状态）。
        """
        yaml_v1 = tmp_path / "family_test.yaml"
        yaml_v1.write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: test_v1
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: first
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [v1_keyword]
                      description_template: v1
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )

        r1 = self._fresh_registry(aius_dir=tmp_path)
        rules_v1 = r1.get_rbo_rules()
        assert len(rules_v1) == 1

        # 追加第二个 YAML 文件，模拟 OCP 扩展（新建实例来模拟重新加载）
        yaml_v2 = tmp_path / "family_test2.yaml"
        yaml_v2.write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: test_v2
                aius:
                  - id: DOC_SYNC
                    description: doc
                    base_cost: 1500
                    exec_order: 99
                    rbo_triggers:
                      keywords: [doc_sync_v2]
                      description_template: doc
                      token_budget: 1500
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )

        r2 = self._fresh_registry(aius_dir=tmp_path)
        rules_v2 = r2.get_rbo_rules()
        assert len(rules_v2) == 2, (
            f"新增 YAML 后应有 2 条规则，实际：{len(rules_v2)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3d：TaskDecomposer 与 AIURegistry 集成（RBO 规则格式兼容性）
# ─────────────────────────────────────────────────────────────────────────────

class TestDecomposerIntegration:
    """验证 TaskDecomposer 能正确消费 AIURegistry.get_rbo_rules() 的输出。"""

    def test_task_decomposer_loads_rbo_rules_from_registry(self):
        """TaskDecomposer 初始化后 _rbo_rules 非空（来自 YAML 注册表）。"""
        from mms.dag.task_decomposer import TaskDecomposer

        decomposer = TaskDecomposer()
        assert len(decomposer._rbo_rules) >= 12, (
            f"TaskDecomposer._rbo_rules 应 ≥12 条，实际：{len(decomposer._rbo_rules)}"
        )

    def test_should_decompose_rbo_triggers_correctly(self):
        """
        should_decompose(task, confidence) 对低置信度任务返回 True。
        _rbo_decompose(task, files_hint) 对 RBO 匹配任务返回非空 steps。
        """
        from mms.dag.task_decomposer import TaskDecomposer

        decomposer = TaskDecomposer()

        # 低置信度 → should_decompose=True
        should_low = TaskDecomposer.should_decompose(
            task="为 User 对象新增字段 email，需要同步更新 schema",
            confidence=0.3,   # 低于阈值
        )
        assert should_low is True, "低置信度任务应触发分解"

        # 高置信度、短任务 → should_decompose=False
        should_high = TaskDecomposer.should_decompose(
            task="fix bug",
            confidence=0.9,
        )
        assert should_high is False, "高置信度简单任务不应触发分解"

    def test_rbo_decompose_returns_valid_steps(self):
        """
        _rbo_decompose(task, files_hint) 对 RBO 关键词命中任务返回合法 AIUStep 列表，
        每个 step 的 depends_on=[]（half-preserve 策略）。
        """
        from mms.dag.task_decomposer import TaskDecomposer

        decomposer = TaskDecomposer()
        # "新增字段" 命中 SCHEMA_ADD_FIELD rule
        steps, confidence = decomposer._rbo_decompose(
            task="为 User 对象新增字段 email",
            files_hint=["backend/app/domain/user.py"],
        )
        assert isinstance(steps, list)
        assert len(steps) >= 1, f"RBO 应命中至少 1 条规则，实际 steps={steps}"
        assert confidence > 0.0, f"RBO 命中时置信度应 > 0，实际：{confidence}"
        for step in steps:
            assert step.depends_on == [], (
                f"half-preserve 策略要求 depends_on=[]，got {step.depends_on}"
            )
            # _rbo_decompose 返回的 step 尚未分配 aiu_id（由 _assign_ids_and_order 完成）
            # 只验证 aiu_type 和 layer 字段的合法性
            assert step.aiu_type is not None and step.aiu_type != ""
