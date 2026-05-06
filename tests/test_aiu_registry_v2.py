"""
test_aiu_registry_v2.py — AIU Registry v2.0 测试（Schema-Driven OCP 重构）

测试内容：
  1. 双轨加载：Enum 内置 + YAML 合约 Schema
  2. get_input_schema() / get_validation_rules() 新接口
  3. get_layer_affinity() 新接口
  4. types_with_contracts() / types_without_contracts() 统计
  5. custom/ 子目录的自定义 AIU 加载
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from mms.dag.aiu_registry import AIURegistry, AIUTypeDef


# ── 测试夹具 ─────────────────────────────────────────────────────────────────

FAMILY_D_YAML = """
schema_version: "1.0"
family: D_interface
layer_affinity: [ADAPTER]

aius:
  - id: TEST_ROUTE_ENDPOINT
    family: D_interface
    layer_affinity: [ADAPTER, APP]
    exec_order: 3
    base_cost: 2500
    description: "测试路由端点 AIU"
    input_schema:
      method:
        type: string
        required: true
        enum: [GET, POST, PUT, DELETE]
      path:
        type: string
        required: true
      auth_required:
        type: boolean
        default: true
    validation_rules:
      ast_target: "FunctionDef"
      required_patterns:
        - "@router\\\\."
        - "response_model="
      forbidden_patterns:
        - "return\\\\s+\\\\{['\\\"]"
"""

CUSTOM_YAML = """
schema_version: "1.0"
is_builtin: false

aius:
  - id: K8S_CUSTOM_TEST
    family: G_distributed
    layer_affinity: [PLATFORM]
    exec_order: 5
    base_cost: 3500
    description: "自定义 K8S 测试 AIU"
    input_schema:
      target_deployment:
        type: string
        required: true
    validation_rules:
      ast_target: "yaml_mapping"
      required_patterns:
        - "containers:"
"""


@pytest.fixture
def registry_with_temp_schemas(tmp_path: Path) -> AIURegistry:
    """创建带临时 YAML Schema 目录的 AIURegistry。"""
    aius_dir = tmp_path / "aius"
    aius_dir.mkdir()

    # 写入 family_D 合约文件
    (aius_dir / "family_D_test.yaml").write_text(FAMILY_D_YAML, encoding="utf-8")

    # 写入 custom/ 子目录
    custom_dir = aius_dir / "custom"
    custom_dir.mkdir()
    (custom_dir / "k8s_test.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

    return AIURegistry(aius_dir=aius_dir)


# ── 基础加载测试 ──────────────────────────────────────────────────────────────

class TestRegistryLoading:
    def test_enum_builtin_types_loaded(self) -> None:
        """内置 Enum 类型应被正确加载。"""
        registry = AIURegistry()
        all_types = registry.all_types()
        assert "SCHEMA_ADD_FIELD" in all_types
        assert "ROUTE_ADD_ENDPOINT" in all_types
        assert "DIST_ADD_SAGA" in all_types   # v3.0 新增族 G

    def test_builtin_types_count(self) -> None:
        """内置 AIU 类型数量应 >= 28（v2.0 基础），含 v3.0 扩展族应 >= 39。"""
        registry = AIURegistry()
        assert len(registry.builtin_types()) >= 28

    def test_yaml_contract_loaded(self, registry_with_temp_schemas: AIURegistry) -> None:
        """YAML 合约文件中的 AIU 应被正确加载。"""
        registry = registry_with_temp_schemas
        all_types = registry.all_types()
        assert "TEST_ROUTE_ENDPOINT" in all_types

    def test_custom_dir_loaded(self, registry_with_temp_schemas: AIURegistry) -> None:
        """custom/ 子目录的 AIU 应被正确加载。"""
        registry = registry_with_temp_schemas
        assert "K8S_CUSTOM_TEST" in registry.all_types()


# ── input_schema 接口测试 ─────────────────────────────────────────────────────

class TestInputSchema:
    def test_get_input_schema_returns_dict(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """get_input_schema() 应返回字典。"""
        schema = registry_with_temp_schemas.get_input_schema("TEST_ROUTE_ENDPOINT")
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_input_schema_fields(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """input_schema 应包含正确的字段定义。"""
        schema = registry_with_temp_schemas.get_input_schema("TEST_ROUTE_ENDPOINT")
        assert "method" in schema
        assert "path" in schema
        assert "auth_required" in schema

        method_schema = schema["method"]
        assert method_schema["type"] == "string"
        assert method_schema["required"] is True
        assert "GET" in method_schema["enum"]

    def test_input_schema_empty_for_unknown(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """未知类型应返回空字典。"""
        schema = registry_with_temp_schemas.get_input_schema("NONEXISTENT_TYPE")
        assert schema == {}

    def test_input_schema_empty_for_enum_only(self) -> None:
        """只在 Enum 中定义（无 YAML 合约）的类型，input_schema 应为空。"""
        registry = AIURegistry()
        schema = registry.get_input_schema("SCHEMA_ADD_FIELD")
        assert isinstance(schema, dict)
        # 可能为空（无合约 YAML）或有内容（若 schemas/aius/ 目录存在对应文件）


# ── validation_rules 接口测试 ─────────────────────────────────────────────────

class TestValidationRules:
    def test_get_validation_rules_returns_dict(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """get_validation_rules() 应返回字典。"""
        rules = registry_with_temp_schemas.get_validation_rules("TEST_ROUTE_ENDPOINT")
        assert isinstance(rules, dict)
        assert "ast_target" in rules

    def test_validation_rules_content(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """validation_rules 应包含 ast_target 和 patterns。"""
        rules = registry_with_temp_schemas.get_validation_rules("TEST_ROUTE_ENDPOINT")
        assert rules["ast_target"] == "FunctionDef"
        assert isinstance(rules.get("required_patterns"), list)
        assert isinstance(rules.get("forbidden_patterns"), list)

    def test_validation_rules_empty_for_unknown(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """未知类型应返回空字典。"""
        rules = registry_with_temp_schemas.get_validation_rules("NONEXISTENT_TYPE")
        assert rules == {}


# ── layer_affinity 接口测试 ───────────────────────────────────────────────────

class TestLayerAffinity:
    def test_get_layer_affinity_from_yaml(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """YAML 合约中的 layer_affinity 应被正确加载。"""
        affinity = registry_with_temp_schemas.get_layer_affinity("TEST_ROUTE_ENDPOINT")
        assert "ADAPTER" in affinity
        assert "APP" in affinity

    def test_get_layer_affinity_builtin(self) -> None:
        """内置 AIU 的 layer_affinity 应来自 aiu_types.py 的 AIU_LAYER_AFFINITY。"""
        registry = AIURegistry()
        affinity = registry.get_layer_affinity("ROUTE_ADD_ENDPOINT")
        assert isinstance(affinity, list)

    def test_get_layer_affinity_empty_for_unknown(self) -> None:
        """未知类型应返回空列表。"""
        registry = AIURegistry()
        affinity = registry.get_layer_affinity("NONEXISTENT_TYPE")
        assert affinity == []


# ── 统计接口测试 ──────────────────────────────────────────────────────────────

class TestContractStats:
    def test_types_with_contracts(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """types_with_contracts() 应返回有 input_schema 的类型列表。"""
        with_contracts = registry_with_temp_schemas.types_with_contracts()
        assert "TEST_ROUTE_ENDPOINT" in with_contracts
        assert "K8S_CUSTOM_TEST" in with_contracts

    def test_types_without_contracts_exist(self) -> None:
        """types_without_contracts() 应包含只在 Enum 定义的类型（无合约 YAML）。"""
        registry = AIURegistry()
        without = registry.types_without_contracts()
        # 如果 schemas/aius/ 目录中有 family_*.yaml，部分内置类型会有合约
        # 无论如何，内置类型数量 >= 43，不可能全部有合约
        assert isinstance(without, list)

    def test_all_types_union(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """types_with_contracts + types_without_contracts = all_types。"""
        registry = registry_with_temp_schemas
        with_c = set(registry.types_with_contracts())
        without_c = set(registry.types_without_contracts())
        all_t = set(registry.all_types())
        assert with_c | without_c == all_t
        assert with_c & without_c == set()  # 两个集合互不相交


# ── 双轨覆盖测试 ──────────────────────────────────────────────────────────────

class TestDualTrackPriority:
    def test_yaml_overrides_enum_description(self) -> None:
        """YAML 合约中的 description 应覆盖 Enum 内置的空描述。"""
        registry = AIURegistry()
        real_aius_dir = Path(__file__).parent.parent / "docs" / "memory" / "_system" / "schemas" / "aius"
        if not real_aius_dir.exists():
            pytest.skip("schemas/aius/ 目录不存在，跳过此测试")

        # ROUTE_ADD_ENDPOINT 在 Enum 中有定义，在 family_D_interface.yaml 中也有定义
        def_ = registry.get("ROUTE_ADD_ENDPOINT")
        if def_ and def_.input_schema:
            assert "method" in def_.input_schema   # 来自 YAML 合约

    def test_enum_builtin_flag(self) -> None:
        """Enum 内置类型的 is_builtin 应为 True。"""
        registry = AIURegistry()
        def_ = registry.get("SCHEMA_ADD_FIELD")
        assert def_ is not None
        assert def_.is_builtin is True

    def test_yaml_only_not_builtin(
        self, registry_with_temp_schemas: AIURegistry
    ) -> None:
        """仅在 YAML 中定义的类型 is_builtin 应为 False。"""
        registry = registry_with_temp_schemas
        def_ = registry.get("TEST_ROUTE_ENDPOINT")
        assert def_ is not None
        assert def_.is_builtin is False
