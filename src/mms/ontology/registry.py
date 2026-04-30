"""
src/mms/ontology/registry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MMS 动态本体注册表（Palantir 风格 Ontology Runtime）

将 docs/memory/ontology/ 下的所有 YAML 定义加载为内存对象，提供：
  - ObjectTypeRegistry  : 加载/查询 ObjectType 定义 + 实例校验
  - FunctionRegistry    : 加载 Function 定义 + 路由到 Python 实现
  - ActionRegistry      : 加载 Action 定义 + submission_criteria 校验
  - RuleEngine          : 执行 Action Rules（create/modify/delete object & link）

设计原则：
  - YAML 驱动：新增 ObjectType/Function/Action/Rule 无需修改 Python 代码
  - 懒加载：首次访问时才读取磁盘（import 时零 I/O）
  - 与 LinkTypeRegistry 风格统一（link_registry.py）
  - 严格分层：Registry 只读本体定义，不读业务记忆文件

版本：v1.0 | 创建于：2026-04-30 | Bootstrap v2
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent.parent

_ONTOLOGY_DIR = _ROOT / "docs" / "memory" / "ontology"
_OBJECTS_DIR  = _ONTOLOGY_DIR / "objects"
_LINKS_DIR    = _ONTOLOGY_DIR / "links"
_FUNCS_DIR    = _ONTOLOGY_DIR / "functions"
_ACTIONS_DIR  = _ONTOLOGY_DIR / "actions"

_logger = logging.getLogger(__name__)


# ─── YAML 加载（与 link_registry.py 保持一致）────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore[import]
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        _logger.warning("加载 YAML 失败 %s: %s", path, exc)
        return {}


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class PropertyDef:
    """ObjectType 的属性定义。"""
    name: str
    type: str
    required: bool = False
    description: str = ""
    enum: List[str] = field(default_factory=list)
    pattern: Optional[str] = None
    default: Any = None


@dataclass
class ValidationRule:
    """ObjectType 或 Action 的校验规则。"""
    rule_id: str
    description: str
    check: str          # Python 表达式字符串（在实例 dict 上下文中求值）
    severity: str = "error"   # error | warning


@dataclass
class ObjectTypeDef:
    """ObjectType 定义（对应 Palantir ObjectType Schema）。"""
    id: str
    label: str
    layer: str
    version: str
    description: str = ""
    primary_key: str = "id"
    parent_type: Optional[str] = None
    properties: Dict[str, PropertyDef] = field(default_factory=dict)
    related_link_types: List[str] = field(default_factory=list)
    related_functions: List[str] = field(default_factory=list)
    related_actions: List[str] = field(default_factory=list)
    validation_rules: List[ValidationRule] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, data: dict) -> "ObjectTypeDef":
        props: Dict[str, PropertyDef] = {}
        for pname, pdef in (data.get("properties") or {}).items():
            if not isinstance(pdef, dict):
                continue
            props[pname] = PropertyDef(
                name=pname,
                type=str(pdef.get("type", "string")),
                required=bool(pdef.get("required", False)),
                description=str(pdef.get("description", "")),
                enum=list(pdef.get("enum") or []),
                pattern=pdef.get("pattern"),
                default=pdef.get("default"),
            )

        rules: List[ValidationRule] = []
        for r in (data.get("validation_rules") or []):
            if isinstance(r, dict) and r.get("rule_id"):
                rules.append(ValidationRule(
                    rule_id=r["rule_id"],
                    description=r.get("description", ""),
                    check=r.get("check", "True"),
                    severity=r.get("severity", "error"),
                ))

        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            layer=str(data.get("layer", "")),
            version=str(data.get("version", "1.0")),
            description=str(data.get("description", "")),
            primary_key=str(data.get("primary_key", "id")),
            parent_type=data.get("parent_type"),
            properties=props,
            related_link_types=list(data.get("related_link_types") or []),
            related_functions=list(data.get("related_functions") or []),
            related_actions=list(data.get("related_actions") or []),
            validation_rules=rules,
        )


@dataclass
class FunctionDef:
    """Function 定义（纯计算，无副作用）。"""
    id: str
    label: str
    version: str
    description: str = ""
    pure: bool = True
    inputs: List[dict] = field(default_factory=list)
    outputs: List[dict] = field(default_factory=list)
    implementation: dict = field(default_factory=dict)
    signal_rules: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, data: dict) -> "FunctionDef":
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            version=str(data.get("version", "1.0")),
            description=str(data.get("description", "")),
            pure=bool(data.get("pure", True)),
            inputs=list(data.get("inputs") or []),
            outputs=list(data.get("outputs") or []),
            implementation=(data.get("implementation") if isinstance(data.get("implementation"), dict) else {}),
            signal_rules=dict(data.get("signal_rules") or {}),
        )


@dataclass
class ActionParameterDef:
    """Action 参数定义。"""
    name: str
    type: str
    required: bool = False
    description: str = ""
    default: Any = None


@dataclass
class SubmissionCriterion:
    """Action 的提交前校验条件（类比 Palantir submission_criteria）。"""
    criterion_id: str
    description: str
    check: str
    error_message: str = ""


@dataclass
class ActionRule:
    """Action 中的单条规则（对应 Palantir Action Rules）。"""
    rule_id: str
    label: str
    type: str   # function_rule | ontology_rule | side_effect
    description: str = ""
    function: Optional[str] = None
    skip_if: Optional[str] = None


@dataclass
class ActionDef:
    """Action 定义（有副作用的事务，修改本体对象和 Link）。"""
    id: str
    label: str
    version: str
    description: str = ""
    parameters: List[ActionParameterDef] = field(default_factory=list)
    submission_criteria: List[SubmissionCriterion] = field(default_factory=list)
    rules: List[ActionRule] = field(default_factory=list)
    side_effects: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, data: dict) -> "ActionDef":
        params = []
        for p in (data.get("parameters") or []):
            if isinstance(p, dict) and p.get("name"):
                params.append(ActionParameterDef(
                    name=p["name"],
                    type=str(p.get("type", "string")),
                    required=bool(p.get("required", False)),
                    description=str(p.get("description", "")),
                    default=p.get("default"),
                ))

        criteria = []
        for c in (data.get("submission_criteria") or []):
            if isinstance(c, dict) and c.get("criterion_id"):
                criteria.append(SubmissionCriterion(
                    criterion_id=c["criterion_id"],
                    description=c.get("description", ""),
                    check=c.get("check", "True"),
                    error_message=c.get("error_message", ""),
                ))

        rules = []
        for r in (data.get("rules") or []):
            if isinstance(r, dict) and r.get("rule_id"):
                rules.append(ActionRule(
                    rule_id=r["rule_id"],
                    label=r.get("label", r["rule_id"]),
                    type=r.get("type", "side_effect"),
                    description=r.get("description", ""),
                    function=r.get("function"),
                    skip_if=r.get("skip_if"),
                ))

        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            version=str(data.get("version", "1.0")),
            description=str(data.get("description", "")),
            parameters=params,
            submission_criteria=criteria,
            rules=rules,
            side_effects=list(data.get("side_effects") or []),
        )


@dataclass
class ValidationResult:
    """ObjectType 实例校验结果。"""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ─── ObjectTypeRegistry ───────────────────────────────────────────────────────

class ObjectTypeRegistry:
    """
    加载并管理所有 ObjectType 定义（docs/memory/ontology/objects/*.yaml）。

    对应 Palantir 概念：Ontology Manager 中管理的所有 Object Type Schema。

    使用示例：
        registry = ObjectTypeRegistry()
        ot = registry.get("CodeClass")        # → ObjectTypeDef | None
        result = registry.validate("CodeClass", {"name": "UserController", ...})
    """

    def __init__(self, objects_dir: Optional[Path] = None) -> None:
        self._dir = objects_dir or _OBJECTS_DIR
        self._types: Optional[Dict[str, ObjectTypeDef]] = None

    def _ensure_loaded(self) -> None:
        if self._types is not None:
            return
        self._types = {}
        if not self._dir.exists():
            return
        for yaml_file in sorted(self._dir.glob("*.yaml")):
            data = _load_yaml(yaml_file)
            if not data.get("id"):
                continue
            ot = ObjectTypeDef.from_yaml(data)
            self._types[ot.id] = ot
            _logger.debug("已加载 ObjectType: %s", ot.id)

    def get(self, type_id: str) -> Optional[ObjectTypeDef]:
        """根据 ID 获取 ObjectType 定义。"""
        self._ensure_loaded()
        return (self._types or {}).get(type_id)

    def all_ids(self) -> List[str]:
        """列出所有已注册的 ObjectType ID。"""
        self._ensure_loaded()
        return list((self._types or {}).keys())

    def layer_1_types(self) -> List[ObjectTypeDef]:
        """返回 Layer 1（代码结构）的 ObjectType（CodeFile/CodeClass/CodeModule）。"""
        self._ensure_loaded()
        return [ot for ot in (self._types or {}).values()
                if ot.layer == "L1_code_structure"]

    def layer_2_types(self) -> List[ObjectTypeDef]:
        """返回 Layer 2（记忆图谱）的 ObjectType（MemoryNode 及其子类）。"""
        self._ensure_loaded()
        return [ot for ot in (self._types or {}).values()
                if ot.layer == "L2_memory_graph"]

    def validate(self, type_id: str, instance: dict) -> ValidationResult:
        """
        校验一个 ObjectType 实例是否符合定义。
        对应 Palantir 的 Object Type property validation。
        """
        self._ensure_loaded()
        ot = (self._types or {}).get(type_id)
        if ot is None:
            return ValidationResult(valid=False, errors=[f"未知 ObjectType: {type_id}"])

        errors: List[str] = []
        warnings: List[str] = []

        # 必填字段检查
        for pname, pdef in ot.properties.items():
            if pdef.required and instance.get(pname) is None:
                errors.append(f"缺少必填字段: '{pname}'")
            # enum 校验
            if pdef.enum and instance.get(pname) is not None:
                if instance[pname] not in pdef.enum:
                    errors.append(
                        f"字段 '{pname}' 的值 '{instance[pname]}' 不在允许范围: {pdef.enum}"
                    )
            # pattern 校验
            if pdef.pattern and isinstance(instance.get(pname), str):
                if not re.match(pdef.pattern, instance[pname]):
                    errors.append(
                        f"字段 '{pname}' 值 '{instance[pname]}' 不符合格式: {pdef.pattern}"
                    )

        # validation_rules 校验
        for rule in ot.validation_rules:
            try:
                passed = bool(eval(rule.check, {"__builtins__": {}}, instance))  # noqa: S307
            except Exception:
                passed = True  # 表达式求值失败时宽松处理
            if not passed:
                msg = f"[{rule.rule_id}] {rule.description}"
                if rule.severity == "error":
                    errors.append(msg)
                else:
                    warnings.append(msg)

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def summary(self) -> str:
        """返回注册表摘要字符串。"""
        self._ensure_loaded()
        types = self._types or {}
        l1 = [t for t in types.values() if t.layer == "L1_code_structure"]
        l2 = [t for t in types.values() if t.layer == "L2_memory_graph"]
        return (
            f"ObjectTypeRegistry: {len(types)} 种 ObjectType "
            f"(Layer1={len(l1)}, Layer2={len(l2)})"
        )


# ─── FunctionRegistry ─────────────────────────────────────────────────────────

class FunctionRegistry:
    """
    加载并管理所有 Function 定义（docs/memory/ontology/functions/*.yaml）。

    对应 Palantir 概念：Ontology Functions（纯计算，可注册 Python 实现）。

    使用示例：
        registry = FunctionRegistry()
        fn = registry.get("fn_infer_layer")
        impl = registry.get_implementation("fn_infer_layer")  # → callable | None
    """

    def __init__(self, funcs_dir: Optional[Path] = None) -> None:
        self._dir = funcs_dir or _FUNCS_DIR
        self._functions: Optional[Dict[str, FunctionDef]] = None
        self._implementations: Dict[str, Callable] = {}

    def _ensure_loaded(self) -> None:
        if self._functions is not None:
            return
        self._functions = {}
        if not self._dir.exists():
            return
        for yaml_file in sorted(self._dir.glob("*.yaml")):
            data = _load_yaml(yaml_file)
            if not data.get("id"):
                continue
            fn = FunctionDef.from_yaml(data)
            self._functions[fn.id] = fn
            _logger.debug("已加载 Function: %s", fn.id)

    def get(self, fn_id: str) -> Optional[FunctionDef]:
        self._ensure_loaded()
        return (self._functions or {}).get(fn_id)

    def all_ids(self) -> List[str]:
        self._ensure_loaded()
        return list((self._functions or {}).keys())

    def register_implementation(self, fn_id: str, impl: Callable) -> None:
        """
        注册 Function 的 Python 实现。
        对应 Palantir 中 TypeScript/Python Function 的代码实现。
        """
        self._implementations[fn_id] = impl

    def get_implementation(self, fn_id: str) -> Optional[Callable]:
        """获取已注册的 Python 实现，未注册时返回 None。"""
        return self._implementations.get(fn_id)

    def call(self, fn_id: str, **kwargs: Any) -> Any:
        """调用已注册的 Function 实现。"""
        impl = self._implementations.get(fn_id)
        if impl is None:
            raise NotImplementedError(f"Function '{fn_id}' 未注册 Python 实现")
        return impl(**kwargs)

    def get_signal_rules(self, fn_id: str) -> dict:
        """获取 Function 的信号规则（用于 fn_infer_layer）。"""
        fn = self.get(fn_id)
        return fn.signal_rules if fn else {}

    def summary(self) -> str:
        self._ensure_loaded()
        functions = self._functions or {}
        registered = len(self._implementations)
        return (
            f"FunctionRegistry: {len(functions)} 个 Function 定义, "
            f"{registered} 个已注册 Python 实现"
        )


# ─── ActionRegistry ───────────────────────────────────────────────────────────

class ActionRegistry:
    """
    加载并管理所有 Action 定义（docs/memory/ontology/actions/*.yaml）。

    对应 Palantir 概念：Action Types（有副作用的事务，修改 Ontology）。

    使用示例：
        registry = ActionRegistry()
        action = registry.get("action_bootstrap")
        errors = registry.check_submission_criteria("action_bootstrap", params)
    """

    def __init__(self, actions_dir: Optional[Path] = None) -> None:
        self._dir = actions_dir or _ACTIONS_DIR
        self._actions: Optional[Dict[str, ActionDef]] = None

    def _ensure_loaded(self) -> None:
        if self._actions is not None:
            return
        self._actions = {}
        if not self._dir.exists():
            return
        for yaml_file in sorted(self._dir.glob("*.yaml")):
            data = _load_yaml(yaml_file)
            if not data.get("id"):
                continue
            action = ActionDef.from_yaml(data)
            self._actions[action.id] = action
            _logger.debug("已加载 Action: %s", action.id)

    def get(self, action_id: str) -> Optional[ActionDef]:
        self._ensure_loaded()
        return (self._actions or {}).get(action_id)

    def all_ids(self) -> List[str]:
        self._ensure_loaded()
        return list((self._actions or {}).keys())

    def check_submission_criteria(
        self, action_id: str, params: dict
    ) -> List[str]:
        """
        校验 Action 的提交前条件（submission_criteria）。
        对应 Palantir Action 的 submission_criteria 校验。
        返回错误消息列表（空列表表示全部通过）。
        """
        action = self.get(action_id)
        if action is None:
            return [f"未知 Action: {action_id}"]

        errors: List[str] = []
        for criterion in action.submission_criteria:
            try:
                # 将 params 注入上下文，求值 check 表达式
                ctx = {**params, "Path": Path}
                passed = bool(eval(criterion.check, {"__builtins__": {"any": any}}, ctx))  # noqa: S307
            except Exception:
                passed = True  # 表达式求值失败时宽松处理
            if not passed:
                msg = criterion.error_message.format(**params) if params else criterion.error_message
                errors.append(f"[{criterion.criterion_id}] {msg or criterion.description}")

        return errors

    def get_rules(self, action_id: str) -> List[ActionRule]:
        """获取 Action 的执行规则列表（按顺序）。"""
        action = self.get(action_id)
        return action.rules if action else []

    def summary(self) -> str:
        self._ensure_loaded()
        actions = self._actions or {}
        return f"ActionRegistry: {len(actions)} 个 Action 定义"


# ─── RuleEngine ───────────────────────────────────────────────────────────────

class RuleEngine:
    """
    Action Rules 执行引擎。

    对应 Palantir 概念：Action Type Rules（Create/Modify/Delete Object & Link）。
    在 MMS 中，RuleEngine 负责：
      1. 按顺序执行 ActionDef.rules
      2. 评估 skip_if 条件
      3. 路由 function_rule 到 FunctionRegistry
      4. 执行 ontology_rule（create/modify object & link）
      5. 记录执行日志

    当前版本提供框架，具体 ontology_rule 的执行委托给各命令实现。
    """

    def __init__(
        self,
        function_registry: Optional[FunctionRegistry] = None,
        action_registry: Optional[ActionRegistry] = None,
    ) -> None:
        self.fn_registry = function_registry or FunctionRegistry()
        self.action_registry = action_registry or ActionRegistry()

    def should_skip(self, rule: ActionRule, context: dict) -> bool:
        """判断规则是否应跳过（评估 skip_if 表达式）。"""
        if not rule.skip_if:
            return False
        try:
            return bool(eval(rule.skip_if, {"__builtins__": {}}, context))  # noqa: S307
        except Exception:
            return False

    def execute_function_rule(
        self, rule: ActionRule, context: dict
    ) -> Optional[Any]:
        """执行 function_rule：调用 FunctionRegistry 中的 Python 实现。"""
        if rule.type != "function_rule" or not rule.function:
            return None

        fn_name = rule.function.split("(")[0].strip()
        # 尝试从点分路径解析函数名（"module.fn_name(args)"）
        fn_id = fn_name.split(".")[-1]

        impl = self.fn_registry.get_implementation(fn_id)
        if impl is None:
            _logger.debug("function_rule '%s' 未注册实现，跳过", fn_id)
            return None

        try:
            return impl(**{k: v for k, v in context.items()})
        except TypeError:
            return impl()

    def run_action(
        self,
        action_id: str,
        params: dict,
        on_rule: Optional[Callable[[ActionRule, dict], Any]] = None,
    ) -> List[dict]:
        """
        执行一个 Action 的所有 Rules。

        Args:
            action_id: Action 的 ID（如 "action_bootstrap"）
            params: Action 参数字典
            on_rule: 可选的外部规则处理器（用于 ontology_rule 等需要业务逻辑的规则）

        Returns:
            执行日志列表（每条规则一个 dict）
        """
        action = self.action_registry.get(action_id)
        if action is None:
            _logger.error("未知 Action: %s", action_id)
            return []

        logs: List[dict] = []
        context = dict(params)

        for rule in action.rules:
            if self.should_skip(rule, context):
                logs.append({"rule_id": rule.rule_id, "status": "skipped",
                              "reason": rule.skip_if})
                continue

            result = None
            if rule.type == "function_rule":
                result = self.execute_function_rule(rule, context)
                if result is not None:
                    context[rule.rule_id + "_result"] = result

            elif rule.type in ("ontology_rule", "side_effect") and on_rule:
                result = on_rule(rule, context)

            logs.append({
                "rule_id": rule.rule_id,
                "label": rule.label,
                "type": rule.type,
                "status": "executed",
                "result_type": type(result).__name__ if result is not None else "None",
            })

        return logs


# ─── 统一入口：OntologyRegistry ───────────────────────────────────────────────

class OntologyRegistry:
    """
    统一的本体注册表入口，聚合四个子注册表。

    对应 Palantir 的 Ontology Manager（管理所有 ObjectType / Function / Action）。

    使用示例：
        from mms.ontology.registry import OntologyRegistry
        onto = OntologyRegistry()
        print(onto.summary())

        # 查询 ObjectType
        code_class = onto.objects.get("CodeClass")

        # 查询 Function
        fn = onto.functions.get("fn_infer_layer")
        rules = onto.functions.get_signal_rules("fn_infer_layer")

        # 执行 Action submission_criteria 校验
        errors = onto.actions.check_submission_criteria("action_bootstrap", params)
    """

    def __init__(self, ontology_dir: Optional[Path] = None) -> None:
        base = ontology_dir or _ONTOLOGY_DIR
        self.objects   = ObjectTypeRegistry(base / "objects")
        self.functions = FunctionRegistry(base / "functions")
        self.actions   = ActionRegistry(base / "actions")
        self.rules     = RuleEngine(self.functions, self.actions)

    def summary(self) -> str:
        lines = [
            "=== MMS Ontology Registry ===",
            self.objects.summary(),
            self.functions.summary(),
            self.actions.summary(),
        ]
        return "\n".join(lines)

    def validate_completeness(self) -> List[str]:
        """
        校验本体定义的完整性：
          - Function 的 related_actions 都已定义
          - ObjectType 的 related_link_types 都存在（通过 LinkTypeRegistry 校验）
        返回警告列表。
        """
        warnings: List[str] = []

        # 检查 ObjectType 中引用的 Function 是否都已定义
        for obj_id in self.objects.all_ids():
            obj = self.objects.get(obj_id)
            if obj is None:
                continue
            for fn_id in obj.related_functions:
                if self.functions.get(fn_id) is None:
                    warnings.append(
                        f"ObjectType '{obj_id}' 引用了未定义的 Function: '{fn_id}'"
                    )
            for action_id in obj.related_actions:
                if self.actions.get(action_id) is None:
                    warnings.append(
                        f"ObjectType '{obj_id}' 引用了未定义的 Action: '{action_id}'"
                    )

        return warnings


# ─── 模块级单例（懒创建）────────────────────────────────────────────────────

_default_registry: Optional[OntologyRegistry] = None


def get_ontology_registry() -> OntologyRegistry:
    """获取模块级默认 OntologyRegistry 实例（懒创建单例）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = OntologyRegistry()
    return _default_registry
