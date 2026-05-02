"""
src/mms/agent_tools/
━━━━━━━━━━━━━━━━━━━
Tool Abstraction Layer — 供 Autonomous Runner（Track B）使用的工具注册表。

每个工具对外暴露严格的 JSON Schema，供 LLM 调用时生成正确参数。
工具内部调用现有 MMS 模块（graph_resolver / ast_skeleton / sandbox / postcheck），
不引入新的业务逻辑。

用法（Autonomous Runner 内部）：
    from mms.agent_tools import get_tool_registry
    registry = get_tool_registry()
    schemas = registry.get_schemas()      # 传给 LLM 的工具描述列表
    result = registry.call("tool_query_ontology", keyword="gRPC")

版本：v1.0 | 创建于：2026-05-02 | Sprint 2
"""
from mms.agent_tools.registry import ToolRegistry, get_tool_registry  # noqa: F401
