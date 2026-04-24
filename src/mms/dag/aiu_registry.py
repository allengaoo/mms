#!/usr/bin/env python3
"""
aiu_registry.py — AIU 类型动态注册表（Phase 5，YAML 扩展层）

设计目标：
  不破坏现有 AIUType Enum（被大量代码引用），在其上叠加 YAML 驱动的扩展层。
  新增 AIU 类型：在 _system/schemas/aiu_types_extended.yaml 新增一行，不改 Python 源码。

架构：
  AIUType Enum（内置 28 种）→ 被 AIURegistry 包裹
  YAML 扩展文件 → 新增 AIU 类型，只存在于 AIURegistry，不在 Enum 中

查询路径：
  1. 优先查 YAML 扩展层（允许覆盖 Enum 内置配置）
  2. Fallback 到 Enum 内置 + 静态 Dict（AIU_LAYER_MAP, AIU_EXEC_ORDER）

使用示例：
  from mms.dag.aiu_registry import get_registry
  registry = get_registry()
  print(registry.get_family("SCHEMA_ADD_FIELD"))  # "A_schema"
  print(registry.all_types())                     # [..., "SCHEMA_ADD_INDEX", ...]
  print(registry.get_base_cost("SCHEMA_ADD_INDEX"))  # 1800（来自 YAML）

YAML 扩展文件格式（_system/schemas/aiu_types_extended.yaml）：
  extended_types:
    - id: SCHEMA_ADD_INDEX
      family: A_schema
      layer: L2_infrastructure
      exec_order: 1
      base_cost: 1800
      description: "新增数据库索引（不影响 Schema 字段）"

版本：v1.0 | 创建于：2026-04-25 | Phase 5
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

_EXTENDED_YAML = _ROOT / "docs" / "memory" / "_system" / "schemas" / "aiu_types_extended.yaml"


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class AIUTypeDef:
    """
    一个 AIU 类型的完整定义。
    来源：Enum 内置（is_builtin=True）或 YAML 扩展（is_builtin=False）。
    """
    id: str                          # 如 "SCHEMA_ADD_FIELD"
    family: str = ""                 # 如 "A_schema"
    layer: str = ""                  # 如 "L2_infrastructure"
    exec_order: int = 99             # 执行顺序（数字越小越早）
    base_cost: int = 3000            # 基础 Token 成本
    description: str = ""
    is_builtin: bool = True          # 来自 Enum = True；来自 YAML = False


# ── 注册表 ────────────────────────────────────────────────────────────────────

class AIURegistry:
    """
    AIU 类型注册表（YAML 扩展层 + Enum 兜底）。

    懒加载：首次访问时扫描 YAML 扩展文件 + 内置 Enum。
    扩展性：新增 AIU 类型只需在 YAML 文件添加一行，不改 Python 源码。
    """

    def __init__(self, extended_yaml: Optional[Path] = None) -> None:
        self._extended_yaml = extended_yaml or _EXTENDED_YAML
        self._registry: Dict[str, AIUTypeDef] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._load()
        self._loaded = True

    def _load(self) -> None:
        """加载内置 Enum + YAML 扩展层，建立统一注册表。"""
        # Step 1: 从 Enum 和静态 Dict 加载内置 AIU
        try:
            from mms.dag.aiu_types import (
                AIUType, AIU_TO_FAMILY, AIU_LAYER_MAP, AIU_EXEC_ORDER
            )
            try:
                from mms.dag.aiu_cost_estimator import AIU_BASE_COST
            except Exception:
                AIU_BASE_COST = {}

            for aiu_type in AIUType:
                type_id = aiu_type.value
                self._registry[type_id] = AIUTypeDef(
                    id=type_id,
                    family=AIU_TO_FAMILY.get(aiu_type, ""),
                    layer=AIU_LAYER_MAP.get(aiu_type, ""),
                    exec_order=AIU_EXEC_ORDER.get(aiu_type, 99),
                    base_cost=AIU_BASE_COST.get(type_id, 3000),
                    description="",
                    is_builtin=True,
                )
        except Exception:  # noqa: BLE001
            pass

        # Step 2: 从 YAML 扩展文件加载（覆盖 Enum 配置 or 新增）
        if self._extended_yaml.exists():
            try:
                import yaml  # type: ignore[import]
                data = yaml.safe_load(
                    self._extended_yaml.read_text(encoding="utf-8")
                ) or {}
                for item in (data.get("extended_types") or []):
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    type_id = item["id"]
                    existing = self._registry.get(type_id)
                    self._registry[type_id] = AIUTypeDef(
                        id=type_id,
                        family=item.get("family", existing.family if existing else ""),
                        layer=item.get("layer", existing.layer if existing else ""),
                        exec_order=int(item.get("exec_order", existing.exec_order if existing else 99)),
                        base_cost=int(item.get("base_cost", existing.base_cost if existing else 3000)),
                        description=item.get("description", ""),
                        is_builtin=False,  # YAML 扩展类型标记为非内置
                    )
            except Exception:  # noqa: BLE001
                pass

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


# ── 模块级单例 ────────────────────────────────────────────────────────────────

_default_registry: Optional[AIURegistry] = None


def get_registry() -> AIURegistry:
    """获取模块级默认 AIURegistry 单例（懒创建）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = AIURegistry()
    return _default_registry
