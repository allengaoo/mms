#!/usr/bin/env python3
"""
aiu_registry.py — AIU 类型动态注册表（Phase 5 + Schema-Driven OCP 扩展）

设计目标：
  不破坏现有 AIUType Enum（被大量代码引用），在其上叠加 YAML 驱动的扩展层。
  新增 AIU 类型：在 schemas/aius/ 添加 YAML 文件，不改 Python 源码。

架构（双轨并行）：
  AIUType Enum（内置 43 种）→ 被 AIURegistry 包裹（Enum 兜底）
  YAML 合约文件（schemas/aius/*.yaml）→ 提供完整 input_schema 和 validation_rules
  YAML 扩展文件（aiu_types_extended.yaml）→ 轻量扩展（向后兼容）

查询路径（三层优先级）：
  1. schemas/aius/ 合约 YAML（含 input_schema + validation_rules）
  2. aiu_types_extended.yaml（轻量扩展）
  3. Enum 内置 + 静态 Dict（AIU_LAYER_MAP, AIU_EXEC_ORDER）— 兜底

新接口：
  registry.get_input_schema(type_id)      → Dict（DAG 编排时 LLM 遵守的输入 Schema）
  registry.get_validation_rules(type_id) → Dict（代码审查时的 AST 验证规则）

使用示例：
  from mms.dag.aiu_registry import get_registry
  registry = get_registry()
  print(registry.get_family("SCHEMA_ADD_FIELD"))      # "A_schema"
  print(registry.get_input_schema("ROUTE_ADD_ENDPOINT"))  # {"method": ..., "path": ...}
  print(registry.all_types())                         # 43+ 种 AIU

版本：v2.0 | 2026-04-27 | Schema-Driven AIU（OCP 重构）
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent.parent

_SCHEMAS_DIR = _ROOT / "docs" / "memory" / "_system" / "schemas"
_EXTENDED_YAML = _SCHEMAS_DIR / "aiu_types_extended.yaml"
_AIUS_DIR = _SCHEMAS_DIR / "aius"   # Schema-Driven AIU 合约目录


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class AIUTypeDef:
    """
    一个 AIU 类型的完整定义。
    来源：Enum 内置（is_builtin=True）或 YAML 合约（is_builtin=False）。

    v2.0 新增：
      layer_affinity   — 架构层亲和性列表（如 ["ADAPTER", "DOMAIN"]）
      input_schema     — DAG 编排时 LLM 遵守的输入参数 Schema（JSON Schema 风格）
      validation_rules — 代码审查时的 AST 验证规则
    """
    id: str                              # 如 "SCHEMA_ADD_FIELD"
    family: str = ""                     # 如 "A_schema"
    layer: str = ""                      # 如 "ADAPTER"（主层，向后兼容）
    layer_affinity: List[str] = field(default_factory=list)  # 多层亲和性
    exec_order: int = 99                 # 执行顺序（数字越小越早）
    base_cost: int = 3000                # 基础 Token 成本
    description: str = ""
    input_schema: Dict = field(default_factory=dict)      # DAG 编排输入规范
    validation_rules: Dict = field(default_factory=dict)  # AST 验证规则
    is_builtin: bool = True              # 来自 Enum = True；来自 YAML = False


# ── 注册表 ────────────────────────────────────────────────────────────────────

class AIURegistry:
    """
    AIU 类型注册表（三层加载：Enum 兜底 → YAML 轻量扩展 → YAML 合约 Schema）。

    懒加载：首次访问时加载所有来源。
    扩展性：新增 AIU 类型只需在 schemas/aius/ 添加 YAML 文件，不改 Python 源码。

    v2.0 新增：
      - 从 schemas/aius/*.yaml 加载 input_schema 和 validation_rules
      - 支持 schemas/aius/custom/ 子目录（用户自定义扩展）
      - get_input_schema() / get_validation_rules() 新接口
    """

    def __init__(
        self,
        extended_yaml: Optional[Path] = None,
        aius_dir: Optional[Path] = None,
    ) -> None:
        self._extended_yaml = extended_yaml or _EXTENDED_YAML
        self._aius_dir = aius_dir or _AIUS_DIR
        self._registry: Dict[str, AIUTypeDef] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        """三阶段加载：Enum 内置 → YAML 轻量扩展 → YAML 合约 Schema（后者优先级更高）。"""
        # ── 阶段 1：从 Enum 和静态 Dict 加载内置 AIU（兜底层）────────────────────
        try:
            from mms.dag.aiu_types import (
                AIUType, AIU_TO_FAMILY, AIU_LAYER_MAP, AIU_EXEC_ORDER,
                AIU_LAYER_AFFINITY,
            )
            try:
                from mms.dag.aiu_cost_estimator import AIU_BASE_COST
            except Exception:
                AIU_BASE_COST = {}

            for aiu_type in AIUType:
                type_id = aiu_type.value
                affinity = AIU_LAYER_AFFINITY.get(aiu_type, [])
                self._registry[type_id] = AIUTypeDef(
                    id=type_id,
                    family=AIU_TO_FAMILY.get(aiu_type, ""),
                    layer=AIU_LAYER_MAP.get(aiu_type, ""),
                    layer_affinity=list(affinity) if affinity else [],
                    exec_order=AIU_EXEC_ORDER.get(aiu_type, 99),
                    base_cost=AIU_BASE_COST.get(type_id, 3000),
                    description="",
                    is_builtin=True,
                )
        except Exception:  # noqa: BLE001
            pass

        # ── 阶段 2：从 aiu_types_extended.yaml 加载轻量扩展（向后兼容）──────────
        if self._extended_yaml.exists():
            self._load_extended_yaml(self._extended_yaml)

        # ── 阶段 3：从 schemas/aius/*.yaml 加载合约 Schema（最高优先级）──────────
        if self._aius_dir.exists():
            self._load_contract_schemas(self._aius_dir)

    def _load_extended_yaml(self, yaml_path: Path) -> None:
        """加载 aiu_types_extended.yaml 格式（轻量扩展，向后兼容）。"""
        try:
            import yaml  # type: ignore[import]
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            for item in (data.get("extended_types") or []):
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                self._apply_item(item, is_builtin=False)
        except Exception:  # noqa: BLE001
            pass

    def _load_contract_schemas(self, aius_dir: Path) -> None:
        """
        加载 schemas/aius/ 目录下所有 YAML 合约文件（含 custom/ 子目录）。
        合约格式：family_*.yaml，包含 aius: 列表，每项有 input_schema + validation_rules。
        """
        try:
            import yaml  # type: ignore[import]
            # 收集主目录 + custom/ 子目录的所有 YAML 文件
            yaml_files: List[Path] = []
            for f in sorted(aius_dir.glob("*.yaml")):
                if f.name != "README.md":
                    yaml_files.append(f)
            custom_dir = aius_dir / "custom"
            if custom_dir.is_dir():
                yaml_files.extend(sorted(custom_dir.glob("*.yaml")))

            for yaml_file in yaml_files:
                try:
                    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
                    for item in (data.get("aius") or []):
                        if not isinstance(item, dict) or not item.get("id"):
                            continue
                        self._apply_contract_item(item)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass

    def _apply_item(self, item: dict, is_builtin: bool = False) -> None:
        """将轻量 YAML 条目合并到注册表（不含 input_schema/validation_rules）。"""
        type_id = item["id"]
        existing = self._registry.get(type_id)
        self._registry[type_id] = AIUTypeDef(
            id=type_id,
            family=item.get("family", existing.family if existing else ""),
            layer=item.get("layer", existing.layer if existing else ""),
            layer_affinity=item.get("layer_affinity", existing.layer_affinity if existing else []),
            exec_order=int(item.get("exec_order", existing.exec_order if existing else 99)),
            base_cost=int(item.get("base_cost", existing.base_cost if existing else 3000)),
            description=item.get("description", existing.description if existing else ""),
            input_schema=existing.input_schema if existing else {},
            validation_rules=existing.validation_rules if existing else {},
            is_builtin=is_builtin,
        )

    def _apply_contract_item(self, item: dict) -> None:
        """将合约 YAML 条目（含 input_schema + validation_rules）合并到注册表。"""
        type_id = item["id"]
        existing = self._registry.get(type_id)
        self._registry[type_id] = AIUTypeDef(
            id=type_id,
            family=item.get("family", existing.family if existing else ""),
            layer=item.get("layer", existing.layer if existing else ""),
            layer_affinity=item.get("layer_affinity", existing.layer_affinity if existing else []),
            exec_order=int(item.get("exec_order", existing.exec_order if existing else 99)),
            base_cost=int(item.get("base_cost", existing.base_cost if existing else 3000)),
            description=item.get("description", existing.description if existing else ""),
            input_schema=item.get("input_schema") or (existing.input_schema if existing else {}),
            validation_rules=item.get("validation_rules") or (existing.validation_rules if existing else {}),
            is_builtin=existing.is_builtin if existing else False,
        )

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def get(self, type_id: str) -> Optional[AIUTypeDef]:
        """
        获取 AIU 类型定义。
        未知类型返回 None（不抛异常）。
        """
        self._ensure_loaded()
        return self._registry.get(type_id)

    def get_family(self, type_id: str) -> str:
        """返回 AIU 所属族名（如 "A_schema"），未知时返回空字符串。"""
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.family if def_ else ""

    def get_layer(self, type_id: str) -> str:
        """返回 AIU 对应的代码层（如 "L2_infrastructure"），未知时返回空字符串。"""
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.layer if def_ else ""

    def get_base_cost(self, type_id: str) -> int:
        """返回 AIU 基础 Token 成本，未知时返回 3000（默认值）。"""
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.base_cost if def_ else 3000

    def get_exec_order(self, type_id: str) -> int:
        """返回 AIU 执行顺序（数字越小越先执行），未知时返回 99。"""
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.exec_order if def_ else 99

    def all_types(self) -> List[str]:
        """
        返回所有已注册 AIU 类型 ID 列表（内置 Enum + YAML 扩展）。
        新增 AIU = 在 YAML 添加一行，此方法自动包含新类型。
        """
        self._ensure_loaded()
        return sorted(self._registry.keys())

    def builtin_types(self) -> List[str]:
        """返回内置 AIU 类型（来自 Enum）的 ID 列表。"""
        self._ensure_loaded()
        return sorted(k for k, v in self._registry.items() if v.is_builtin)

    def extended_types(self) -> List[str]:
        """返回 YAML 扩展的 AIU 类型 ID 列表。"""
        self._ensure_loaded()
        return sorted(k for k, v in self._registry.items() if not v.is_builtin)

    def all_defs(self) -> List[AIUTypeDef]:
        """返回所有 AIUTypeDef 对象列表（按 ID 排序）。"""
        self._ensure_loaded()
        return sorted(self._registry.values(), key=lambda d: d.id)

    def get_input_schema(self, type_id: str) -> Dict:
        """
        返回 AIU 的输入参数 Schema（DAG 编排时 LLM 遵守的输入规范）。
        Schema 来自 schemas/aius/*.yaml 的 input_schema 字段。
        未定义时返回空字典。

        示例返回：
          {
            "method": {"type": "string", "required": True, "enum": ["GET", "POST"]},
            "path": {"type": "string", "required": True},
            "auth_required": {"type": "boolean", "default": True},
          }
        """
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.input_schema if def_ else {}

    def get_validation_rules(self, type_id: str) -> Dict:
        """
        返回 AIU 的代码验证规则（用于 arch_check 的 AST 静态分析）。
        规则来自 schemas/aius/*.yaml 的 validation_rules 字段。
        未定义时返回空字典。

        示例返回：
          {
            "ast_target": "FunctionDef",
            "required_patterns": ["@router\\.", "response_model="],
            "forbidden_patterns": ["return\\s+\\{['\"]"],
          }
        """
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.validation_rules if def_ else {}

    def get_layer_affinity(self, type_id: str) -> List[str]:
        """返回 AIU 的架构层亲和性列表（如 ["ADAPTER", "DOMAIN"]）。"""
        self._ensure_loaded()
        def_ = self._registry.get(type_id)
        return def_.layer_affinity if def_ else []

    def types_with_contracts(self) -> List[str]:
        """返回已定义 input_schema 的 AIU 类型列表（合约完备的 AIU）。"""
        self._ensure_loaded()
        return sorted(k for k, v in self._registry.items() if v.input_schema)

    def types_without_contracts(self) -> List[str]:
        """返回尚未定义 input_schema 的 AIU 类型列表（待完善合约）。"""
        self._ensure_loaded()
        return sorted(k for k, v in self._registry.items() if not v.input_schema)


# ── 模块级单例 ────────────────────────────────────────────────────────────────

_default_registry: Optional[AIURegistry] = None


def get_registry() -> AIURegistry:
    """获取模块级默认 AIURegistry 单例（懒创建）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = AIURegistry()
    return _default_registry
