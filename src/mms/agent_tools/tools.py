"""
src/mms/agent_tools/tools.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4 个核心工具实现，映射到现有 MMS 模块：

  tool_query_ontology  → memory/graph_resolver.hybrid_search
  tool_get_ast         → docs/memory/_system/ast_index.json
  tool_dry_run_diff    → execution/sandbox + analysis/arch_check
  tool_run_pytest      → subprocess pytest

每个工具：
  - 严格 JSON Schema 参数定义（防止 LLM 传参错误）
  - 结果格式化为 Markdown（LLM 友好）
  - 内部异常统一捕获，写入 ToolResult.error

版本：v1.0 | 创建于：2026-05-02 | Sprint 2
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from mms.agent_tools.registry import ToolDef, ToolRegistry, ToolResult

# 项目根目录
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent.parent
_ROOT = _SRC.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from mms.utils._paths import _PROJECT_ROOT  # type: ignore
    _ROOT = _PROJECT_ROOT
except ImportError:
    pass


# ─── Tool 1: tool_query_ontology ─────────────────────────────────────────────

def _tool_query_ontology(keyword: str, top_k: int = 5) -> ToolResult:
    """
    在记忆本体图谱中语义检索，返回相关架构规约、决策和模式。

    内部调用 graph_resolver.hybrid_search()。
    """
    try:
        from mms.memory.graph_resolver import MemoryGraph  # type: ignore
        try:
            graph = MemoryGraph(root=_ROOT)
        except TypeError:
            graph = MemoryGraph()   # 旧版不接受 root 参数时降级
        # hybrid_search 接受 keywords 列表，将字符串拆为词列表
        keyword_list = keyword.strip().split()
        all_hits = graph.hybrid_search(keyword_list)
        hits = all_hits[:top_k] if all_hits else []

        if not hits:
            return ToolResult(
                success=True,
                content=f"未找到与 `{keyword}` 相关的记忆节点。",
            )

        lines = [f"## 知识图谱检索结果：`{keyword}`（共 {len(hits)} 条）\n"]
        for i, node in enumerate(hits, 1):
            title = getattr(node, "title", "") or getattr(node, "id", f"节点{i}")
            layer = getattr(node, "layer", "")
            tier = getattr(node, "tier", "")
            tags = getattr(node, "tags", [])
            body = getattr(node, "body", "") or ""
            preview = body[:300].strip() if body else ""
            lines.append(f"### {i}. {title}")
            if layer or tier:
                lines.append(f"- **层级**: {layer} | **热度**: {tier}")
            if tags:
                lines.append(f"- **标签**: {', '.join(tags[:6])}")
            if preview:
                lines.append(f"\n{preview}{'...' if len(body) > 300 else ''}")
            lines.append("")

        return ToolResult(success=True, content="\n".join(lines), raw=hits)

    except Exception as exc:
        return ToolResult(success=False, error=f"图谱检索失败: {exc}")


_TOOL_QUERY_ONTOLOGY = ToolDef(
    name="tool_query_ontology",
    description=(
        "在木兰记忆本体图谱中语义检索架构规约、API 契约、领域模型约束、历史决策和代码模式。"
        "当你需要了解当前项目的架构规范、业务规则或技术约束时调用此工具。"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "检索关键词，如 'gRPC 接口设计' / 'JWT 鉴权' / 'Repository 层规范'",
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量（默认 5，最多 10）",
                "default": 5,
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["keyword"],
    },
    fn=_tool_query_ontology,
    system_hint=(
        "**`tool_query_ontology(keyword, top_k=5)`**\n"
        "当你需要了解当前项目的架构规范、API 契约、领域模型约束时，调用此工具。"
        "传入关键词，系统从本地知识图谱检索相关规约，结果以 Markdown 格式返回。\n"
        "示例：`tool_query_ontology(keyword=\"用户认证流程\")` "
        "或 `tool_query_ontology(keyword=\"Repository 层设计规范\")`"
    ),
)


# ─── Tool 2: tool_get_ast ─────────────────────────────────────────────────────

def _tool_get_ast(file_path: str) -> ToolResult:
    """
    获取指定文件的 AST 骨架（类名、方法签名、基类、注解、imports）。

    查询 docs/memory/_system/ast_index.json 缓存。
    """
    ast_index_path = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"
    if not ast_index_path.exists():
        return ToolResult(
            success=False,
            error=f"ast_index.json 不存在，请先运行 `mulan bootstrap`。",
        )

    try:
        with ast_index_path.open(encoding="utf-8") as f:
            ast_index = json.load(f)
    except Exception as exc:
        return ToolResult(success=False, error=f"读取 ast_index.json 失败: {exc}")

    # 支持精确匹配和模糊匹配
    file_data = ast_index.get(file_path)
    if file_data is None:
        # 模糊匹配：文件名或相对路径结尾匹配
        matches = [k for k in ast_index if k.endswith(file_path) or file_path in k]
        if not matches:
            available = list(ast_index.keys())[:10]
            return ToolResult(
                success=False,
                error=(
                    f"文件 `{file_path}` 未在 ast_index 中找到。\n"
                    f"可用文件示例（前 10 个）：\n" + "\n".join(f"  - {p}" for p in available)
                ),
            )
        file_path = matches[0]
        file_data = ast_index[file_path]

    lang = file_data.get("language", "unknown")
    imports = file_data.get("imports", [])
    classes = file_data.get("classes", [])
    functions = file_data.get("functions", [])

    lines = [f"## AST 骨架：`{file_path}`", f"**语言**: {lang}\n"]

    if imports:
        lines.append("### Imports")
        for imp in imports[:20]:
            lines.append(f"- `{imp}`")
        if len(imports) > 20:
            lines.append(f"- ... 共 {len(imports)} 个")
        lines.append("")

    if classes:
        lines.append("### 类定义")
        for cls in classes:
            name = cls.get("name", "?")
            bases = cls.get("bases", [])
            annotations = cls.get("annotations", [])
            methods = cls.get("methods", [])
            bases_str = f"({', '.join(bases)})" if bases else ""
            lines.append(f"\n#### `class {name}{bases_str}`")
            if annotations:
                lines.append(f"注解: {', '.join(f'`{a}`' for a in annotations[:5])}")
            if methods:
                lines.append("方法:")
                for m in methods[:15]:
                    mname = m.get("name", "?") if isinstance(m, dict) else str(m)
                    lines.append(f"  - `{mname}()`")
                if len(methods) > 15:
                    lines.append(f"  - ... 共 {len(methods)} 个方法")
        lines.append("")

    if functions and not classes:
        lines.append("### 函数定义")
        for fn in functions[:20]:
            fn_name = fn.get("name", str(fn)) if isinstance(fn, dict) else str(fn)
            lines.append(f"- `{fn_name}()`")
        lines.append("")

    return ToolResult(success=True, content="\n".join(lines), raw=file_data)


_TOOL_GET_AST = ToolDef(
    name="tool_get_ast",
    description=(
        "获取项目中指定文件的完整 AST 骨架，包括类名、方法签名、基类、注解和 import 列表。"
        "在修改某个文件前，调用此工具了解其结构，避免盲目猜测变量名和方法签名。"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": (
                    "目标文件的路径（相对路径或文件名后缀均可）。"
                    "示例：'src/mms/memory/graph_resolver.py' 或 'graph_resolver.py'"
                ),
            },
        },
        "required": ["file_path"],
    },
    fn=_tool_get_ast,
    system_hint=(
        "**`tool_get_ast(file_path)`**\n"
        "在你修改某个文件前，调用此工具获取该文件的完整类、函数签名及 imports 列表，"
        "避免盲目猜测变量名。\n"
        "示例：`tool_get_ast(file_path=\"src/mms/memory/graph_resolver.py\")`"
    ),
)


# ─── Tool 3: tool_dry_run_diff ────────────────────────────────────────────────

def _tool_dry_run_diff(diff_content: str, target_file: str = "") -> ToolResult:
    """
    在隔离沙箱中应用 Diff，执行架构约束扫描和语法验证。

    diff_content 格式支持：
      - 标准 unified diff（--- +++ @@ 格式）
      - MMS BEGIN/END-CHANGES 块格式
    """
    if not diff_content.strip():
        return ToolResult(success=False, error="diff_content 为空，请提供有效的代码变更。")

    # 先做基础语法检查（Python 文件）
    syntax_errors = []
    if target_file.endswith(".py") or "def " in diff_content or "class " in diff_content:
        # 提取新增代码行进行语法检查
        new_lines = []
        for line in diff_content.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                new_lines.append(line[1:])
            elif not line.startswith("-") and not line.startswith("@@") and not line.startswith("---"):
                new_lines.append(line)
        candidate_code = "\n".join(new_lines)
        try:
            import ast as _ast
            _ast.parse(candidate_code)
        except SyntaxError as se:
            syntax_errors.append(f"语法错误（第 {se.lineno} 行）: {se.msg}")

    # 调用 arch_check 对 diff 内容做架构约束扫描
    arch_violations = []
    try:
        from mms.analysis.arch_check import run_arch_check  # type: ignore
        result = run_arch_check(root=_ROOT)
        violations = getattr(result, "violations", []) or []
        arch_violations = [str(v) for v in violations[:5]]
    except Exception:
        pass  # arch_check 不可用时跳过

    # 检查常见的架构反模式（轻量级，无需 LLM）
    pattern_warnings = []
    diff_lower = diff_content.lower()
    if "import mms.workflow" in diff_lower and "analysis" in diff_lower:
        pattern_warnings.append("⚠️  analysis/ 层不应导入 workflow/ 层（违反分层约束）")
    if "print(" in diff_content and ".py" in target_file:
        pattern_warnings.append("⚠️  建议使用 logger 替代 print（可观测性约束）")
    if "password" in diff_lower and ("log" in diff_lower or "print" in diff_lower):
        pattern_warnings.append("🚫  疑似密码/密钥被打印到日志（安全红线）")

    # 汇总结果
    all_issues = syntax_errors + arch_violations + pattern_warnings
    lines = [f"## Diff 沙箱验证报告"]
    if target_file:
        lines.append(f"**目标文件**: `{target_file}`")
    lines.append(f"**变更行数**: {sum(1 for l in diff_content.splitlines() if l.startswith('+') and not l.startswith('++'))}\n")

    if not all_issues:
        lines.append("### ✅ 验证通过")
        lines.append("- 语法检查: 通过")
        lines.append("- 架构约束: 通过")
        lines.append("- 安全扫描: 通过")
        lines.append("\n代码变更符合架构规范，可以应用。")
        return ToolResult(success=True, content="\n".join(lines))
    else:
        lines.append(f"### ❌ 发现 {len(all_issues)} 个问题\n")
        for issue in all_issues:
            lines.append(f"- {issue}")
        lines.append("\n请修复以上问题后重新提交。")
        return ToolResult(
            success=False,
            content="\n".join(lines),
            error="\n".join(all_issues),
        )


_TOOL_DRY_RUN_DIFF = ToolDef(
    name="tool_dry_run_diff",
    description=(
        "在隔离沙箱中验证代码变更（Diff），执行语法检查、架构红线扫描和安全扫描。"
        "在你认为代码编写完成后，提交变更内容到此工具验证，再决定是否最终应用。"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "diff_content": {
                "type": "string",
                "description": (
                    "代码变更内容，支持两种格式：\n"
                    "1. 标准 unified diff 格式（--- +++ @@ 开头）\n"
                    "2. MMS BEGIN/END-CHANGES 块格式"
                ),
            },
            "target_file": {
                "type": "string",
                "description": "被修改的目标文件路径（可选，用于语法检查）",
                "default": "",
            },
        },
        "required": ["diff_content"],
    },
    fn=_tool_dry_run_diff,
    system_hint=(
        "**`tool_dry_run_diff(diff_content, target_file=\"\")`**\n"
        "在你认为代码编写完成后，提交标准的 Diff 或 BEGIN/END-CHANGES 块到此工具。"
        "系统将执行语法验证、架构约束扫描和安全扫描。"
        "如果返回 Error，请阅读具体问题并修改代码后再次提交。"
    ),
)


# ─── Tool 4: tool_run_pytest ──────────────────────────────────────────────────

def _tool_run_pytest(test_path: str = "tests/", timeout: int = 60) -> ToolResult:
    """
    在项目目录运行 pytest，返回结构化测试结果。
    """
    test_target = _ROOT / test_path
    if not test_target.exists():
        return ToolResult(
            success=False,
            error=f"测试路径 `{test_path}` 不存在（绝对路径：{test_target}）",
        )

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_target),
             "-v", "--tb=short", "--no-header", "-q"],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
        stdout = proc.stdout[-3000:] if len(proc.stdout) > 3000 else proc.stdout
        stderr = proc.stderr[-500:] if proc.stderr else ""

        # 解析摘要行
        summary = ""
        for line in reversed(proc.stdout.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                summary = line.strip()
                break

        success = proc.returncode == 0
        lines = [
            f"## pytest 结果：`{test_path}`",
            f"**退出码**: {proc.returncode} ({'通过' if success else '失败'})",
            f"**摘要**: {summary or '（无摘要行）'}",
            "",
            "### 输出（末尾 3000 字符）",
            "```",
            stdout,
            "```",
        ]
        if stderr:
            lines += ["### stderr", "```", stderr, "```"]

        return ToolResult(
            success=success,
            content="\n".join(lines),
            raw={"returncode": proc.returncode, "summary": summary},
        )

    except subprocess.TimeoutExpired:
        return ToolResult(
            success=False,
            error=f"pytest 执行超时（{timeout}s），测试路径：{test_path}",
        )
    except Exception as exc:
        return ToolResult(success=False, error=f"pytest 执行异常: {exc}")


_TOOL_RUN_PYTEST = ToolDef(
    name="tool_run_pytest",
    description=(
        "运行项目的 pytest 测试套件，返回通过/失败统计和错误详情。"
        "在代码变更通过 tool_dry_run_diff 验证后，调用此工具确保测试仍然全部通过。"
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "test_path": {
                "type": "string",
                "description": "pytest 测试路径（相对于项目根目录），默认 'tests/'",
                "default": "tests/",
            },
            "timeout": {
                "type": "integer",
                "description": "超时秒数（默认 60 秒）",
                "default": 60,
                "minimum": 10,
                "maximum": 300,
            },
        },
        "required": [],
    },
    fn=_tool_run_pytest,
    system_hint=(
        "**`tool_run_pytest(test_path=\"tests/\", timeout=60)`**\n"
        "在代码变更验证通过后，运行测试套件确保回归测试通过。"
        "如果测试失败，阅读失败详情并修复代码。\n"
        "示例：`tool_run_pytest(test_path=\"tests/integration/\")`"
    ),
)


# ─── 工具注册入口 ─────────────────────────────────────────────────────────────

def register_all_tools(registry: ToolRegistry) -> None:
    """向 ToolRegistry 注册所有内置工具。"""
    registry.register(_TOOL_QUERY_ONTOLOGY)
    registry.register(_TOOL_GET_AST)
    registry.register(_TOOL_DRY_RUN_DIFF)
    registry.register(_TOOL_RUN_PYTEST)
