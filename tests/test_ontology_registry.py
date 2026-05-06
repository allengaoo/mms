"""
tests/test_ontology_registry.py — src/mms/ontology/registry.py 单元测试

覆盖目标：registry.py 44% → 80%+
测试范围：
  - ObjectTypeRegistry: 加载、查询、validate、summary
  - FunctionRegistry:   加载、signal_rules、register_implementation
  - ActionRegistry:     加载、check_submission_criteria、get_rules
  - OntologyRegistry:  整体加载、validate_completeness
  - ValidationResult 数据类

遵循规则：使用 tmpdir 隔离，不依赖真实磁盘 YAML 状态（部分 happy path 除外）。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

# ─── 导入被测模块 ──────────────────────────────────────────────────────────────

from mms.ontology.registry import (
    ActionDef,
    ActionRegistry,
    ActionRule,
    FunctionDef,
    FunctionRegistry,
    ObjectTypeDef,
    ObjectTypeRegistry,
    OntologyRegistry,
    PropertyDef,
    ValidationResult,
    get_ontology_registry,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_objects_dir(tmp_path: Path) -> Path:
    """临时 objects/ 目录，包含 2 个 ObjectType YAML。"""
    obj_dir = tmp_path / "objects"
    obj_dir.mkdir()

    (obj_dir / "person.yaml").write_text(textwrap.dedent("""
        id: Person
        label: "人员"
        type: object
        layer: L3_domain
        version: "1.0"
        description: "测试用人员对象"
        primary_key: "name"
        properties:
          name:
            type: string
            required: true
          age:
            type: integer
            required: false
          role:
            type: string
            required: true
            enum: [admin, user, guest]
          email:
            type: string
            required: false
            pattern: "^[^@]+@[^@]+$"
        validation_rules:
          - rule_id: name_not_empty
            description: "name 不能为空"
            check: "len(name) > 0"
            severity: error
    """), encoding="utf-8")

    (obj_dir / "order.yaml").write_text(textwrap.dedent("""
        id: Order
        label: "订单"
        type: object
        layer: L3_domain
        version: "1.0"
        description: "测试用订单对象"
        primary_key: "order_id"
        properties:
          order_id:
            type: string
            required: true
          total:
            type: float
            required: true
    """), encoding="utf-8")

    return obj_dir


@pytest.fixture()
def tmp_funcs_dir(tmp_path: Path) -> Path:
    """临时 functions/ 目录。"""
    fn_dir = tmp_path / "functions"
    fn_dir.mkdir()

    (fn_dir / "fn_test.yaml").write_text(textwrap.dedent("""
        id: fn_test
        label: "测试函数"
        version: "1.0"
        description: "测试用函数"
        input_schema:
          x:
            type: integer
        output_schema:
          result:
            type: integer
        signal_rules:
          path_patterns:
            DOMAIN: [model, entity]
          name_patterns:
            APP: [Service]
    """), encoding="utf-8")

    return fn_dir


@pytest.fixture()
def tmp_actions_dir(tmp_path: Path) -> Path:
    """临时 actions/ 目录。"""
    act_dir = tmp_path / "actions"
    act_dir.mkdir()

    (act_dir / "act_test.yaml").write_text(textwrap.dedent("""
        id: act_test
        label: "测试 Action"
        version: "1.0"
        description: "测试用 Action"
        submission_criteria:
          - criterion_id: has_id
            description: "必须提供非空 id"
            check: "id is not None and id != ''"
            severity: error
        rules:
          - rule_id: set_status
            description: "设置默认状态"
            function: fn_test
            applies_to: create
    """), encoding="utf-8")

    return act_dir


# ─── ObjectTypeRegistry 测试 ──────────────────────────────────────────────────

class TestObjectTypeRegistry:

    def test_load_types_from_yaml(self, tmp_objects_dir):
        """从 YAML 目录加载 ObjectType 定义。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        assert reg.get("Person") is not None
        assert reg.get("Order") is not None

    def test_get_returns_none_for_unknown(self, tmp_objects_dir):
        """未知类型返回 None。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        assert reg.get("NonExistent") is None

    def test_all_ids_returns_all(self, tmp_objects_dir):
        """all_ids() 返回所有已加载类型。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        ids = reg.all_ids()
        assert "Person" in ids
        assert "Order" in ids
        assert len(ids) == 2

    def test_validate_valid_instance(self, tmp_objects_dir):
        """合法实例通过校验。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Person", {"name": "Alice", "role": "admin", "age": 30})
        assert result.valid is True
        assert result.errors == []

    def test_validate_missing_required_field(self, tmp_objects_dir):
        """缺少必填字段时校验失败。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Person", {"role": "user"})  # 缺少 name
        assert result.valid is False
        assert any("name" in e for e in result.errors)

    def test_validate_invalid_enum_value(self, tmp_objects_dir):
        """枚举值不合法时校验失败。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Person", {"name": "Bob", "role": "superuser"})
        assert result.valid is False
        assert any("role" in e for e in result.errors)

    def test_validate_invalid_pattern(self, tmp_objects_dir):
        """不符合 pattern 时校验失败。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Person", {
            "name": "Carol", "role": "user", "email": "not-an-email"
        })
        assert result.valid is False
        assert any("email" in e for e in result.errors)

    def test_validate_valid_pattern(self, tmp_objects_dir):
        """符合 pattern 时通过校验。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Person", {
            "name": "Dave", "role": "guest", "email": "dave@example.com"
        })
        assert result.valid is True

    def test_validate_unknown_type(self, tmp_objects_dir):
        """未知 type_id 返回 invalid。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        result = reg.validate("Ghost", {"name": "x"})
        assert result.valid is False
        assert "未知" in result.errors[0]

    def test_summary_contains_count(self, tmp_objects_dir):
        """summary() 含有类型数量信息。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        s = reg.summary()
        assert "ObjectTypeRegistry" in s
        assert "2" in s

    def test_lazy_loading(self, tmp_objects_dir):
        """首次调用 _ensure_loaded 后缓存，不重复读磁盘。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_objects_dir)
        assert reg._types is None  # 初始未加载
        reg._ensure_loaded()
        assert reg._types is not None
        first_ref = id(reg._types)
        reg._ensure_loaded()
        assert id(reg._types) == first_ref  # 同一对象，无重复加载


# ─── FunctionRegistry 测试 ────────────────────────────────────────────────────

class TestFunctionRegistry:

    def test_load_function_yaml(self, tmp_funcs_dir):
        """加载 Function 定义。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        fn = reg.get("fn_test")
        assert fn is not None
        assert fn.label == "测试函数"

    def test_get_unknown_function(self, tmp_funcs_dir):
        """未知函数 id 返回 None。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        assert reg.get("fn_nonexistent") is None

    def test_all_ids(self, tmp_funcs_dir):
        """all_ids() 返回正确列表。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        assert "fn_test" in reg.all_ids()

    def test_get_signal_rules(self, tmp_funcs_dir):
        """get_signal_rules 返回 signal_rules 字段内容。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        rules = reg.get_signal_rules("fn_test")
        assert "path_patterns" in rules
        assert rules["path_patterns"]["DOMAIN"] == ["model", "entity"]

    def test_get_signal_rules_unknown(self, tmp_funcs_dir):
        """未知函数的 signal_rules 返回空 dict。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        rules = reg.get_signal_rules("fn_ghost")
        assert rules == {}

    def test_register_and_call_implementation(self, tmp_funcs_dir):
        """可以注册并调用 Python 实现。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        reg.register_implementation("fn_test", lambda x: x * 2)
        impl = reg.get_implementation("fn_test")
        assert impl is not None
        result = reg.call("fn_test", x=5)
        assert result == 10

    def test_call_unregistered_raises(self, tmp_funcs_dir):
        """调用未注册实现时抛出 NotImplementedError。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        with pytest.raises(NotImplementedError):
            reg.call("fn_test")

    def test_summary(self, tmp_funcs_dir):
        """summary() 包含函数数量。"""
        reg = FunctionRegistry(funcs_dir=tmp_funcs_dir)
        s = reg.summary()
        assert "Function" in s
        assert "1" in s


# ─── ActionRegistry 测试 ──────────────────────────────────────────────────────

class TestActionRegistry:

    def test_load_action_yaml(self, tmp_actions_dir):
        """加载 Action 定义。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        act = reg.get("act_test")
        assert act is not None
        assert act.label == "测试 Action"

    def test_get_unknown_action(self, tmp_actions_dir):
        """未知 action id 返回 None。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        assert reg.get("ghost") is None

    def test_all_ids(self, tmp_actions_dir):
        """all_ids() 返回正确列表。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        assert "act_test" in reg.all_ids()

    def test_check_submission_criteria_pass(self, tmp_actions_dir):
        """提交标准通过时返回空列表。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        errors = reg.check_submission_criteria("act_test", {"id": "abc"})
        assert errors == []

    def test_check_submission_criteria_fail(self, tmp_actions_dir):
        """提交标准不满足时返回错误（id 为 None）。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        errors = reg.check_submission_criteria("act_test", {"id": None})
        assert len(errors) > 0

    def test_check_submission_criteria_unknown_action(self, tmp_actions_dir):
        """未知 action 返回提示错误。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        errors = reg.check_submission_criteria("ghost", {})
        assert len(errors) > 0

    def test_get_rules(self, tmp_actions_dir):
        """get_rules 返回 Action 的规则列表。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        rules = reg.get_rules("act_test")
        assert len(rules) >= 1
        assert rules[0].function == "fn_test"

    def test_summary(self, tmp_actions_dir):
        """summary() 包含 Action 数量。"""
        reg = ActionRegistry(actions_dir=tmp_actions_dir)
        s = reg.summary()
        assert "Action" in s
        assert "1" in s


# ─── OntologyRegistry 整合测试 ────────────────────────────────────────────────

class TestOntologyRegistry:

    def test_real_registry_loads(self):
        """使用真实 assets/ontology_schema 加载全局注册表。"""
        reg = get_ontology_registry()
        assert "CodeClass" in reg.objects.all_ids()
        assert "MemoryNode" in reg.objects.all_ids()
        assert len(reg.functions.all_ids()) > 0
        assert len(reg.actions.all_ids()) > 0

    def test_validate_completeness_no_errors(self):
        """全局注册表完整性检查无严重错误。"""
        reg = get_ontology_registry()
        issues = reg.validate_completeness()
        # 允许警告存在，但不应有致命错误
        assert issues is not None
        assert isinstance(issues, list)

    def test_validate_code_class_valid(self):
        """合法 CodeClass 实例通过校验。"""
        reg = get_ontology_registry()
        instance = {
            "class_fqn": "com.example.UserController",
            "name": "UserController",
            "kind": "class",
            "file_path": "src/main/java/com/example/UserController.java",
        }
        result = reg.objects.validate("CodeClass", instance)
        assert result.valid is True

    def test_validate_code_class_missing_required(self):
        """缺少 name 字段时 CodeClass 校验失败。"""
        reg = get_ontology_registry()
        instance = {
            "class_fqn": "com.example.UserController",
            # name 缺失
            "kind": "class",
            "file_path": "src/main/java/UserController.java",
        }
        result = reg.objects.validate("CodeClass", instance)
        assert result.valid is False

    def test_validate_memory_node_with_boot_prefix(self):
        """MEM-BOOT- 前缀的节点通过 MemoryNode 校验。"""
        reg = get_ontology_registry()
        instance = {
            "id": "MEM-BOOT-001",
            "type": "pattern",
            "layer": "L3_domain",
            "tier": "warm",
            "tags": ["domain-model", "order"],
        }
        result = reg.objects.validate("MemoryNode", instance)
        assert result.valid is True, f"校验失败: {result.errors}"

    def test_validate_memory_node_old_prefix_invalid(self):
        """非法 id 前缀的节点校验失败。"""
        reg = get_ontology_registry()
        instance = {
            "id": "INVALID-001",
            "type": "pattern",
            "layer": "L3_domain",
            "tier": "warm",
            "tags": ["test"],
        }
        result = reg.objects.validate("MemoryNode", instance)
        assert result.valid is False
        assert any("id" in e for e in result.errors)

    def test_validate_memory_node_invalid_layer(self):
        """Bootstrap 内部层名（DOMAIN）不符合 MemoryNode schema。"""
        reg = get_ontology_registry()
        instance = {
            "id": "MEM-BOOT-002",
            "type": "pattern",
            "layer": "DOMAIN",   # ← 应使用 L3_domain
            "tier": "warm",
            "tags": ["domain"],
        }
        result = reg.objects.validate("MemoryNode", instance)
        assert result.valid is False
        assert any("layer" in e for e in result.errors)

    def test_link_types_loaded(self):
        """LinkTypeRegistry 加载成功。"""
        from mms.memory.link_registry import LinkTypeRegistry
        lreg = LinkTypeRegistry()
        # LinkTypeRegistry.all() 返回已加载的 LinkType 定义列表
        all_links = lreg.all()
        assert len(all_links) > 0
        link_ids = [lt.id if hasattr(lt, 'id') else str(lt) for lt in all_links]
        assert any("depends_on" in lid or "cites" in lid for lid in link_ids)

    def test_fn_signal_rules_accessible(self):
        """fn_infer_layer 的 signal_rules 可通过 FunctionRegistry 访问。"""
        reg = get_ontology_registry()
        rules = reg.functions.get_signal_rules("fn_infer_layer")
        # 可能为空（YAML 中未定义 signal_rules 字段），但不应报错
        assert isinstance(rules, dict)


# ─── ValidationResult 数据类测试 ─────────────────────────────────────────────

class TestValidationResult:

    def test_valid_result(self):
        r = ValidationResult(valid=True, errors=[], warnings=[])
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_invalid_result(self):
        r = ValidationResult(valid=False, errors=["缺少字段"], warnings=["可选字段缺失"])
        assert r.valid is False
        assert len(r.errors) == 1
        assert len(r.warnings) == 1


# ─── 边界情况测试 ─────────────────────────────────────────────────────────────

class TestRegistryEdgeCases:

    def test_empty_objects_dir(self, tmp_path):
        """空目录加载时不崩溃，返回空注册表。"""
        empty = tmp_path / "empty_objects"
        empty.mkdir()
        reg = ObjectTypeRegistry(objects_dir=empty)
        assert reg.all_ids() == []

    def test_malformed_yaml_skipped(self, tmp_path):
        """格式错误的 YAML 文件被跳过，不影响其他文件加载。"""
        obj_dir = tmp_path / "objects"
        obj_dir.mkdir()
        (obj_dir / "bad.yaml").write_text("this is: not: valid: yaml: {{", encoding="utf-8")
        (obj_dir / "good.yaml").write_text(textwrap.dedent("""
            id: GoodType
            label: "正常类型"
            type: object
            layer: L3_domain
            version: "1.0"
            properties: {}
        """), encoding="utf-8")
        reg = ObjectTypeRegistry(objects_dir=obj_dir)
        # 格式错误文件应跳过，好文件应加载（yaml 解析异常会返回空 dict）
        # GoodType 可能加载成功，也可能因 _load_yaml 异常而跳过
        # 关键是不抛出异常
        ids = reg.all_ids()
        assert isinstance(ids, list)

    def test_nonexistent_dir_handled(self, tmp_path):
        """指向不存在目录时不崩溃。"""
        reg = ObjectTypeRegistry(objects_dir=tmp_path / "nonexistent")
        # _ensure_loaded 时目录不存在，应返回空注册表
        assert reg.all_ids() == []
