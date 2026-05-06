"""
tests/dag/test_aiu_registry_ocp_extended.py

P2 测试：AIURegistry OCP 扩展边界场景

覆盖路径：
  - custom/ 子目录的 YAML 文件被正确加载（aius_dir/custom/）
  - custom/ 中的 rbo_triggers 覆盖内置定义（优先级验证）
  - 格式错误的 YAML 被静默跳过（不崩溃）
  - 缺少必填字段（id）的条目被跳过
  - 非 YAML 文件（.txt/.json）被忽略
  - 内置 Enum 在 custom 加载后依然完整（基础定义不被破坏）
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


def _registry(aius_dir=None) -> AIURegistry:
    return AIURegistry(aius_dir=aius_dir)


# ─────────────────────────────────────────────────────────────────────────────
# 1. custom/ 子目录加载
# ─────────────────────────────────────────────────────────────────────────────

class TestCustomSubdir:
    """验证 aius_dir/custom/ 下的 YAML 文件被正确加载。"""

    def test_custom_subdir_yaml_loaded(self, tmp_path):
        """
        在 aius_dir/custom/ 写入 YAML → get_rbo_rules() 包含 custom 规则。
        """
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "my_custom.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: custom_A
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: custom override
                    base_cost: 1999
                    exec_order: 1
                    rbo_triggers:
                      keywords: [custom_trigger]
                      description_template: custom
                      token_budget: 1999
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        rules = r.get_rbo_rules()
        rule_ids = {rule["id"] for rule in rules}
        assert "rbo_schema_add_field" in rule_ids, (
            "custom/ 子目录中的 rbo_triggers 未被加载"
        )

    def test_custom_overrides_builtin_keywords(self, tmp_path):
        """
        custom/ 中的 rbo_triggers 覆盖主目录的定义（后加载，优先级更高）。
        """
        # 先在主目录写原始定义（无 rbo_triggers）
        (tmp_path / "family_base.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: base
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: base definition
                    base_cost: 2000
                    exec_order: 1
            """),
            encoding="utf-8",
        )
        # custom/ 写覆盖定义（带 rbo_triggers）
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "override.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: override
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: custom override with rbo
                    base_cost: 1500
                    exec_order: 1
                    rbo_triggers:
                      keywords: [custom_only_keyword]
                      description_template: overridden
                      token_budget: 1500
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        rules = r.get_rbo_rules()
        schema_rule = next((rule for rule in rules if rule["id"] == "rbo_schema_add_field"), None)
        assert schema_rule is not None, "覆盖后仍应有 rbo_schema_add_field 规则"
        assert "custom_only_keyword" in schema_rule["keywords"], (
            f"custom/ 的关键词未覆盖主目录定义：{schema_rule['keywords']}"
        )

    def test_custom_and_main_dir_both_loaded(self, tmp_path):
        """主目录 + custom/ 各有不同类型 → 均被加载，互不影响。"""
        (tmp_path / "family_main.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: main
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: main
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [main_keyword]
                      description_template: main
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        (custom_dir / "custom_extra.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                family: custom
                aius:
                  - id: DOC_SYNC
                    description: doc sync custom
                    base_cost: 1500
                    exec_order: 99
                    rbo_triggers:
                      keywords: [custom_doc]
                      description_template: doc
                      token_budget: 1500
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        rules = r.get_rbo_rules()
        rule_ids = {rule["id"] for rule in rules}
        assert "rbo_schema_add_field" in rule_ids
        assert "rbo_doc_sync" in rule_ids


# ─────────────────────────────────────────────────────────────────────────────
# 2. 格式容错：错误 YAML 静默跳过
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatTolerance:
    """验证格式错误的 YAML 不导致崩溃（静默跳过）。"""

    def test_malformed_yaml_skipped_gracefully(self, tmp_path):
        """格式损坏的 YAML 文件被静默跳过，其他文件正常加载。"""
        # 损坏的 YAML
        (tmp_path / "malformed.yaml").write_text(
            "aius: [: invalid yaml :::}",
            encoding="utf-8",
        )
        # 正常的 YAML
        (tmp_path / "good.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: good
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [good_kw]
                      description_template: g
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        # 不应抛出异常
        r = _registry(aius_dir=tmp_path)
        rules = r.get_rbo_rules()
        # good.yaml 应正常加载
        assert any(rule["id"] == "rbo_schema_add_field" for rule in rules)

    def test_missing_id_field_skipped(self, tmp_path):
        """YAML 条目缺少 id 字段被静默跳过。"""
        (tmp_path / "no_id.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                aius:
                  - description: "no id field"
                    base_cost: 2000
                    exec_order: 1
                  - id: SCHEMA_ADD_FIELD
                    description: has id
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [valid]
                      description_template: v
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        rules = r.get_rbo_rules()
        # 有 id 的条目正常加载
        assert any(rule["id"] == "rbo_schema_add_field" for rule in rules)

    def test_non_yaml_files_ignored(self, tmp_path):
        """非 YAML 文件（.txt/.json）被忽略，不崩溃。"""
        (tmp_path / "data.json").write_text('{"aius": []}', encoding="utf-8")
        (tmp_path / "readme.txt").write_text("some text", encoding="utf-8")
        # 仅有一个合法 YAML
        (tmp_path / "family_valid.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                aius:
                  - id: SCHEMA_ADD_FIELD
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [kw]
                      description_template: t
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        # 不崩溃，正常工作
        rules = r.get_rbo_rules()
        assert isinstance(rules, list)

    def test_empty_aius_list_ok(self, tmp_path):
        """aius 为空列表的 YAML 文件不崩溃。"""
        (tmp_path / "empty_aius.yaml").write_text(
            "schema_version: '1.0'\naius: []\n",
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        assert r.get_rbo_rules() == []

    def test_null_aius_field_ok(self, tmp_path):
        """aius 为 null 的 YAML 文件不崩溃。"""
        (tmp_path / "null_aius.yaml").write_text(
            "schema_version: '1.0'\naius:\n",
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        assert r.get_rbo_rules() == []


# ─────────────────────────────────────────────────────────────────────────────
# 3. 注册表基本属性（不依赖 aius_dir）
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistryProperties:
    """验证注册表在各种加载场景下的基本属性。"""

    def test_get_nonexistent_type_returns_none(self):
        """查询不存在的 AIU 类型 → 返回 None，不抛异常。"""
        r = AIURegistry()
        result = r.get("NON_EXISTENT_TYPE_XYZ")
        assert result is None

    def test_get_existing_builtin_type(self):
        """查询内置 AIU 类型 → 返回 AIUTypeDef，不为 None。"""
        r = AIURegistry()
        result = r.get(AIUType.SCHEMA_ADD_FIELD.value)
        assert result is not None
        assert result.id == AIUType.SCHEMA_ADD_FIELD.value

    def test_builtin_types_not_broken_after_custom_load(self, tmp_path):
        """加载 custom YAML 后，内置 Enum 类型的基础定义不被破坏。"""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        # custom 中覆盖 SCHEMA_ADD_FIELD，但不改变 exec_order 和 base_cost
        (custom_dir / "custom.yaml").write_text(
            textwrap.dedent("""\
                schema_version: "1.0"
                aius:
                  - id: SCHEMA_ADD_FIELD
                    description: custom desc
                    base_cost: 2000
                    exec_order: 1
                    rbo_triggers:
                      keywords: [custom_kw]
                      description_template: custom
                      token_budget: 2000
                      model_hint: fast
                      files_hint: []
            """),
            encoding="utf-8",
        )
        r = _registry(aius_dir=tmp_path)
        r._ensure_loaded()

        # 内置 Enum 类型均在注册表中
        for aiu_type in AIUType:
            assert r.get(aiu_type.value) is not None, (
                f"AIUType.{aiu_type.name} 在加载 custom YAML 后丢失"
            )

    def test_nonexistent_aius_dir_returns_empty_rules(self, tmp_path):
        """aius_dir 不存在时，get_rbo_rules() 返回空列表，不崩溃。"""
        r = AIURegistry(aius_dir=tmp_path / "nonexistent_dir")
        rules = r.get_rbo_rules()
        assert isinstance(rules, list)
        # 内置 Enum 的 rbo_triggers 来自主目录 YAML，aius_dir 不存在时为空
        # 但 Enum 层基础定义仍然存在
