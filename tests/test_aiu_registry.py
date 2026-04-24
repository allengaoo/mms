"""
test_aiu_registry.py — Phase 5 测试

验证 AIURegistry 的 YAML 扩展层 + Enum 兜底机制。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mms.dag.aiu_registry import AIURegistry, AIUTypeDef, get_registry


# ─── 测试 fixture ─────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_extended_yaml(tmp_path: Path) -> Path:
    """创建临时 YAML 扩展文件。"""
    yaml_file = tmp_path / "aiu_types_extended.yaml"
    yaml_file.write_text(
        """
extended_types:
  - id: SCHEMA_ADD_INDEX
    family: A_schema
    layer: L2_infrastructure
    exec_order: 1
    base_cost: 1800
    description: "新增数据库索引"

  - id: EVENT_ADD_SAGA
    family: E_infrastructure
    layer: L3_domain
    exec_order: 2
    base_cost: 4500
    description: "新增 Saga 协调器"
""",
        encoding="utf-8",
    )
    return yaml_file


@pytest.fixture
def registry_with_yaml(tmp_extended_yaml: Path) -> AIURegistry:
    """使用临时 YAML 创建 Registry。"""
    return AIURegistry(extended_yaml=tmp_extended_yaml)


# ─── Enum 内置类型测试 ────────────────────────────────────────────────────────

class TestBuiltinTypes:
    def test_builtin_type_accessible(self, registry_with_yaml: AIURegistry) -> None:
        """内置 Enum 类型可通过 Registry 查询。"""
        def_ = registry_with_yaml.get("SCHEMA_ADD_FIELD")
        assert def_ is not None
        assert def_.id == "SCHEMA_ADD_FIELD"
        assert def_.is_builtin is True

    def test_get_family_builtin(self, registry_with_yaml: AIURegistry) -> None:
        """内置类型正确返回 family。"""
        family = registry_with_yaml.get_family("SCHEMA_ADD_FIELD")
        assert family != "", "SCHEMA_ADD_FIELD 的 family 不应为空"

    def test_get_base_cost_builtin(self, registry_with_yaml: AIURegistry) -> None:
        """内置类型返回正确的基础成本。"""
        cost = registry_with_yaml.get_base_cost("SCHEMA_ADD_FIELD")
        assert cost > 0

    def test_builtin_types_in_all_types(self, registry_with_yaml: AIURegistry) -> None:
        """all_types() 包含内置 Enum 类型。"""
        all_types = registry_with_yaml.all_types()
        assert "SCHEMA_ADD_FIELD" in all_types
        assert "ROUTE_ADD_ENDPOINT" in all_types

    def test_builtin_types_method(self, registry_with_yaml: AIURegistry) -> None:
        """builtin_types() 只返回 Enum 内置类型。"""
        builtin = registry_with_yaml.builtin_types()
        assert "SCHEMA_ADD_FIELD" in builtin
        # YAML 扩展类型不应出现在 builtin_types
        assert "SCHEMA_ADD_INDEX" not in builtin


# ─── YAML 扩展类型测试 ────────────────────────────────────────────────────────

class TestExtendedTypes:
    def test_yaml_extended_type_accessible(self, registry_with_yaml: AIURegistry) -> None:
        """YAML 扩展的新类型可通过 Registry 查询。"""
        def_ = registry_with_yaml.get("SCHEMA_ADD_INDEX")
        assert def_ is not None
        assert def_.id == "SCHEMA_ADD_INDEX"
        assert def_.is_builtin is False

    def test_yaml_extended_type_properties(self, registry_with_yaml: AIURegistry) -> None:
        """YAML 扩展类型的属性正确解析。"""
        def_ = registry_with_yaml.get("SCHEMA_ADD_INDEX")
        assert def_ is not None
        assert def_.family == "A_schema"
        assert def_.layer == "L2_infrastructure"
        assert def_.exec_order == 1
        assert def_.base_cost == 1800

    def test_extended_types_in_all_types(self, registry_with_yaml: AIURegistry) -> None:
        """all_types() 包含 YAML 扩展类型。"""
        all_types = registry_with_yaml.all_types()
        assert "SCHEMA_ADD_INDEX" in all_types
        assert "EVENT_ADD_SAGA" in all_types

    def test_extended_types_method(self, registry_with_yaml: AIURegistry) -> None:
        """extended_types() 只返回 YAML 扩展类型。"""
        extended = registry_with_yaml.extended_types()
        assert "SCHEMA_ADD_INDEX" in extended
        assert "EVENT_ADD_SAGA" in extended
        # 内置类型不应出现在 extended_types
        assert "SCHEMA_ADD_FIELD" not in extended

    def test_unknown_type_returns_none(self, registry_with_yaml: AIURegistry) -> None:
        """未知类型返回 None，不抛异常。"""
        def_ = registry_with_yaml.get("NONEXISTENT_TYPE")
        assert def_ is None

    def test_unknown_type_family_returns_empty(self, registry_with_yaml: AIURegistry) -> None:
        """未知类型的 get_family 返回空字符串，不抛异常。"""
        family = registry_with_yaml.get_family("NONEXISTENT_TYPE")
        assert family == ""

    def test_unknown_type_base_cost_returns_default(self, registry_with_yaml: AIURegistry) -> None:
        """未知类型的 get_base_cost 返回默认值 3000。"""
        cost = registry_with_yaml.get_base_cost("NONEXISTENT_TYPE")
        assert cost == 3000


# ─── 扩展性验证 ───────────────────────────────────────────────────────────────

class TestExtensibility:
    def test_new_yaml_entry_recognized(self, tmp_path: Path) -> None:
        """新增 YAML 行后，新实例自动识别新 AIU 类型（不改 Python 源码）。"""
        yaml_file = tmp_path / "aiu_types_extended.yaml"
        yaml_file.write_text(
            """
extended_types:
  - id: MY_CUSTOM_AIU
    family: A_schema
    layer: L3_domain
    exec_order: 5
    base_cost: 2200
    description: "自定义 AIU 类型（测试扩展性）"
""",
            encoding="utf-8",
        )
        registry = AIURegistry(extended_yaml=yaml_file)
        def_ = registry.get("MY_CUSTOM_AIU")
        assert def_ is not None
        assert def_.base_cost == 2200
        assert def_.is_builtin is False

    def test_yaml_overrides_builtin_cost(self, tmp_path: Path) -> None:
        """YAML 中使用内置类型 ID 时，可覆盖其配置（如 base_cost）。"""
        yaml_file = tmp_path / "aiu_types_extended.yaml"
        yaml_file.write_text(
            """
extended_types:
  - id: SCHEMA_ADD_FIELD
    family: A_schema
    layer: L2_infrastructure
    exec_order: 1
    base_cost: 9999
    description: "覆盖内置 SCHEMA_ADD_FIELD 的成本"
""",
            encoding="utf-8",
        )
        registry = AIURegistry(extended_yaml=yaml_file)
        cost = registry.get_base_cost("SCHEMA_ADD_FIELD")
        # YAML 优先（覆盖了 Enum 内置的成本）
        assert cost == 9999

    def test_no_yaml_file_falls_back_to_enum(self, tmp_path: Path) -> None:
        """YAML 扩展文件不存在时，Registry 依然可用（只有内置 Enum 类型）。"""
        nonexistent = tmp_path / "nonexistent.yaml"
        registry = AIURegistry(extended_yaml=nonexistent)
        # 内置类型仍然可用
        def_ = registry.get("SCHEMA_ADD_FIELD")
        assert def_ is not None
        # 扩展类型为空
        assert registry.extended_types() == []

    def test_all_types_count(self, registry_with_yaml: AIURegistry) -> None:
        """all_types() 返回内置 + 扩展的总数。"""
        all_types = registry_with_yaml.all_types()
        builtin = registry_with_yaml.builtin_types()
        extended = registry_with_yaml.extended_types()
        # 合集大小 = 内置 + 扩展（覆盖的 key 不重复计数）
        assert len(all_types) >= len(builtin)
        assert len(all_types) >= len(extended)


# ─── 生产环境 Registry 测试 ───────────────────────────────────────────────────

class TestProductionRegistry:
    def test_default_registry_loads_without_error(self) -> None:
        """默认 Registry 加载无异常。"""
        registry = get_registry()
        types = registry.all_types()
        assert isinstance(types, list)

    def test_builtin_28_types_present(self) -> None:
        """生产 Registry 应包含 28 个内置 AIU 类型。"""
        registry = get_registry()
        builtin = registry.builtin_types()
        assert len(builtin) >= 28, f"预期至少 28 个内置类型，实际 {len(builtin)}"

    def test_production_yaml_extensions_loaded(self) -> None:
        """生产 YAML 扩展文件中的类型被加载。"""
        registry = get_registry()
        extended = registry.extended_types()
        # aiu_types_extended.yaml 中定义了 SCHEMA_ADD_INDEX 等类型
        assert "SCHEMA_ADD_INDEX" in extended, "生产 YAML 中定义的 SCHEMA_ADD_INDEX 未被加载"

    def test_all_defs_sortable(self) -> None:
        """all_defs() 返回可排序的 AIUTypeDef 列表。"""
        registry = get_registry()
        defs = registry.all_defs()
        assert isinstance(defs, list)
        assert all(isinstance(d, AIUTypeDef) for d in defs)
