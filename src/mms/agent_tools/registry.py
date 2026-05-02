"""
src/mms/agent_tools/registry.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ToolRegistry：工具注册、JSON Schema 描述、统一调用入口。

设计原则：
  - 每个工具以 @register_tool 装饰器注册，自动收集 name / description / schema
  - JSON Schema 描述与 OpenAI function-calling / 百炼 tools 格式兼容
  - 工具调用结果统一返回 ToolResult，包含 success / content / error 三字段
  - 工具内部异常不向上抛出，而是写入 ToolResult.error

版本：v1.0 | 创建于：2026-05-02 | Sprint 2
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """工具调用结果。"""
    success: bool
    content: str = ""          # 成功时的 Markdown 格式结果（供 LLM 阅读）
    error: str = ""            # 失败时的错误信息
    raw: Any = None            # 原始数据（可选，供上层代码使用）

    def to_message(self) -> str:
        """转为追加到 LLM 消息历史的 Observation 字符串。"""
        if self.success:
            return f"[TOOL RESULT]\n{self.content}"
        return f"[TOOL ERROR]\n{self.error}"


@dataclass
class ToolDef:
    """工具定义（注册表内部存储）。"""
    name: str
    description: str
    parameters_schema: Dict[str, Any]    # JSON Schema for parameters
    fn: Callable[..., ToolResult]
    system_hint: str = ""                # 写入 System Prompt 的使用说明


# ─── 注册表 ──────────────────────────────────────────────────────────────────

class ToolRegistry:
    """
    全局工具注册表。

    用法：
        registry = ToolRegistry()
        registry.register(tool_def)
        result = registry.call("tool_name", param1="v1")
        schemas = registry.get_schemas()  # → [{"type": "function", "function": {...}}]
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDef] = {}

    def register(self, tool_def: ToolDef) -> None:
        self._tools[tool_def.name] = tool_def

    def get(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        """调用工具，捕获所有异常，返回 ToolResult。"""
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False,
                error=f"工具 '{name}' 未注册。可用工具：{list(self._tools.keys())}",
            )
        try:
            return tool.fn(**kwargs)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"工具执行异常: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}",
            )

    def get_schemas(self) -> List[Dict[str, Any]]:
        """
        返回符合 OpenAI / 百炼 tools 格式的工具描述列表。

        格式：
            [
              {
                "type": "function",
                "function": {
                  "name": "tool_query_ontology",
                  "description": "...",
                  "parameters": { "type": "object", "properties": {...}, "required": [...] }
                }
              },
              ...
            ]
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                },
            })
        return schemas

    def get_system_prompt_section(self) -> str:
        """生成写入 System Prompt 的工具使用说明段落。"""
        lines = ["## 可用工具（Tools）", ""]
        for tool in self._tools.values():
            lines.append(f"### `{tool.name}`")
            lines.append(tool.system_hint or tool.description)
            lines.append("")
        return "\n".join(lines)

    def list_names(self) -> List[str]:
        return list(self._tools.keys())


# ─── 全局单例 ─────────────────────────────────────────────────────────────────

_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """
    获取全局 ToolRegistry 单例（懒加载，首次调用时注册所有工具）。
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        # 注册所有内置工具
        from mms.agent_tools.tools import register_all_tools  # noqa
        register_all_tools(_registry)
    return _registry
