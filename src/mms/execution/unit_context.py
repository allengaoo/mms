"""
unit_context.py — Unit 上下文压缩器

为小模型（8B/16B）生成自包含、token 受限的 Unit 执行上下文。

上下文结构（按 token 预算分配优先级）：
  1. 任务描述（不压缩，约 200 tokens）
  2. 层边界契约（当前层摘要，约 500 tokens）
  3. 涉及文件（函数签名 + docstring，约 800-2000 tokens）
  4. 相关记忆（MEMORY.md 过滤 Top-3，约 300 tokens）
  5. 验证命令（固定，约 100 tokens）

用法：
  python3 scripts/mms/unit_context.py --ep EP-117 --unit U3 --model 8b
  mms unit context --ep EP-117 --unit U3
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_LAYER_CONTRACTS = _ROOT / "docs" / "context" / "layer_contracts.md"
_MEMORY_MD = _MEMORY_ROOT / "MEMORY.md"

# ── Token 预算（粗略估算：1 token ≈ 4 chars，保守系数 0.8）──────────────────

TOKEN_LIMITS = {
    "8b": 4000,
    "16b": 8000,
    "capable": 16000,
    "fast": 8000,
}

# 各区块 token 预算分配比例
BUDGET_RATIOS = {
    "header":    0.05,   # 任务描述头部
    "task":      0.10,   # 任务详情
    "contracts": 0.15,   # 层边界契约
    "files":     0.55,   # 文件内容摘要（最大头）
    "memories":  0.10,   # 记忆注入
    "verify":    0.05,   # 验证命令
}


def estimate_tokens(text: str) -> int:
    """粗略估算文本 token 数（字符数 // 4 × 0.8）"""
    return int(len(text) / 4 * 0.8)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """截断文本到 token 上限"""
    max_chars = int(max_tokens * 4 / 0.8)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [已截断，保留前 {max_tokens} tokens] ..."


# ── 文件内容摘要提取 ──────────────────────────────────────────────────────────

_FUNC_DEF_RE = re.compile(
    r"^((?:async\s+)?def\s+\w+\s*\([^)]*\)[^:]*:)\s*\n"
    r"(?:\s+[\"']{3}.*?[\"']{3}\s*\n)?",
    re.MULTILINE | re.DOTALL,
)

_CLASS_DEF_RE = re.compile(
    r"^(class\s+\w+[^:]*:)\s*\n"
    r"(?:\s+[\"']{3}.*?[\"']{3}\s*\n)?",
    re.MULTILINE | re.DOTALL,
)


def extract_file_summary(file_path: str, max_tokens: int = 800) -> str:
    """
    提取文件摘要（函数签名 + 类定义 + 文件头 docstring）。
    控制在 max_tokens 以内。
    """
    abs_path = _ROOT / file_path if not Path(file_path).is_absolute() else Path(file_path)

    if not abs_path.exists():
        return f"# {file_path}\n（文件不存在，可能是本 Unit 需要新建的文件）\n"

    content = abs_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()

    # TypeScript/JavaScript 文件：提取 export 声明
    if abs_path.suffix in (".ts", ".tsx", ".js", ".jsx"):
        return _extract_ts_summary(file_path, content, max_tokens)

    # Python 文件：提取 import + docstring + 函数/类签名
    sections = []

    # 文件级 docstring（前 3 行）
    docstring_lines = []
    for i, line in enumerate(lines[:20]):
        if '"""' in line or "'''" in line:
            docstring_lines.append(line)
            if i > 0:
                break
        elif docstring_lines:
            docstring_lines.append(line)
    if docstring_lines:
        sections.append("\n".join(docstring_lines[:5]))

    # 顶层 import（最多 15 行）
    import_lines = [l for l in lines[:30] if l.startswith(("import ", "from "))]
    if import_lines:
        sections.append("\n".join(import_lines[:15]))

    # 函数签名（def + 第一行 docstring）
    sig_lines: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("def ", "async def ", "class ")):
            sig_lines.append(line)
            # 读取后续的 docstring（若有）
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('"""') or next_line.startswith("'''"):
                    sig_lines.append(lines[i + 1])
                    # 单行 docstring
                    if next_line.count('"""') >= 2 or next_line.count("'''") >= 2:
                        pass
                    else:
                        # 多行 docstring：取第一行
                        pass
        i += 1

    if sig_lines:
        sections.append("\n".join(sig_lines[:60]))

    summary = f"### {file_path}\n```python\n" + "\n\n".join(sections) + "\n```\n"
    return truncate_to_tokens(summary, max_tokens)


def _extract_ts_summary(file_path: str, content: str, max_tokens: int) -> str:
    """提取 TypeScript/JavaScript 文件摘要"""
    lines = content.splitlines()
    summary_lines: List[str] = []

    for line in lines[:80]:
        stripped = line.strip()
        if any(stripped.startswith(kw) for kw in (
            "import ", "export ", "const ", "function ", "class ", "interface ",
            "type ", "async function", "export default",
        )):
            summary_lines.append(line)
        if len(summary_lines) > 40:
            break

    summary = f"### {file_path}\n```typescript\n" + "\n".join(summary_lines) + "\n```\n"
    return truncate_to_tokens(summary, max_tokens)


# ── 层边界契约摘要 ────────────────────────────────────────────────────────────

def extract_layer_contracts(layer: str, max_tokens: int = 500) -> str:
    """从 layer_contracts.md 提取指定层的契约摘要"""
    if not _LAYER_CONTRACTS.exists():
        return f"（layer_contracts.md 不存在，请参考 docs/context/layer_contracts.md）\n"

    content = _LAYER_CONTRACTS.read_text(encoding="utf-8")

    # 按层名查找对应节
    layer_aliases = {
        "L5_interface": ["## L5", "接口层", "API Endpoints"],
        "L4_application": ["## L4", "应用服务层", "Control Services"],
        "L3_domain": ["## L3", "领域层", "Domain"],
        "L2_infrastructure": ["## L2", "基础设施层", "Infrastructure"],
        "L1_platform": ["## L1", "平台层"],
        "testing": ["## L5", "## 测试层", "Tests", "test_"],  # 测试层：L5 接口层 + 测试目录
        "docs": [],
        "unknown": [],
    }

    aliases = layer_aliases.get(layer, [f"## {layer}"])

    # 查找匹配节
    sections = re.split(r"\n## ", content)
    matched_section = ""
    for section in sections:
        if any(alias.lstrip("# ").lower() in section[:50].lower() for alias in aliases):
            matched_section = section
            break

    if not matched_section:
        # 返回精简版（层依赖规则）
        dag_section = ""
        for section in sections:
            if "DAG" in section[:30]:
                dag_section = section[:800]
                break
        return truncate_to_tokens(
            f"### 层边界契约（{layer}）\n（未找到对应层节，请参考 docs/context/layer_contracts.md）\n\n"
            + ("### DAG 层依赖规则\n" + dag_section if dag_section else ""),
            max_tokens,
        )

    return truncate_to_tokens(
        f"### 层边界契约（{layer}）\n\n" + matched_section[:2000],
        max_tokens,
    )


# ── 记忆注入（MEMORY.md 过滤）────────────────────────────────────────────────

def inject_relevant_memories(layer: str, files: List[str], max_tokens: int = 300) -> str:
    """从 MEMORY.md 中过滤与当前层和文件相关的记忆"""
    if not _MEMORY_MD.exists():
        return ""

    content = _MEMORY_MD.read_text(encoding="utf-8")

    # 确定关键词
    layer_keywords = {
        "L5_interface": ["api", "endpoint", "response", "envelope", "前端", "react"],
        "L4_application": ["service", "security", "audit", "transaction", "session"],
        "L3_domain": ["ontology", "object", "本体", "domain"],
        "L2_infrastructure": ["kafka", "redis", "db", "transaction", "infra"],
        "L1_platform": ["security", "tenant", "log", "observe"],
        "testing": ["test", "pytest", "msw", "mock"],
    }

    keywords = layer_keywords.get(layer, [])
    # 加入文件名关键词
    for f in files:
        stem = Path(f).stem.replace("_", " ").lower()
        keywords.extend(stem.split())

    # 过滤 MEMORY.md 中的相关行
    relevant_lines: List[str] = []
    for line in content.splitlines():
        if not line.startswith("- ["):
            continue
        line_lower = line.lower()
        if any(kw.lower() in line_lower for kw in keywords):
            relevant_lines.append(line)
        if len(relevant_lines) >= 6:
            break

    if not relevant_lines:
        return ""

    result = "### 相关记忆约束（来自 docs/memory/MEMORY.md）\n\n"
    result += "\n".join(relevant_lines[:5])
    return truncate_to_tokens(result, max_tokens)


# ── 主生成函数 ────────────────────────────────────────────────────────────────

def generate_unit_context(
    unit_id: str,
    title: str,
    layer: str,
    files: List[str],
    test_files: Optional[List[str]] = None,
    model: str = "capable",
    ep_id: str = "",
    description: str = "",
) -> str:
    """
    生成 Unit 的自包含执行上下文（Markdown 格式）。

    Args:
        unit_id: "U3" 等
        title: Unit 标题
        layer: 所属架构层（如 "L4_application"）
        files: 业务文件路径列表
        test_files: 测试文件路径列表
        model: 目标模型（"8b"|"16b"|"capable"）
        ep_id: EP 标识符（"EP-117" 等）
        description: 额外描述（来自 EP Scope）

    Returns:
        自包含 Markdown 字符串
    """
    token_limit = TOKEN_LIMITS.get(model, 8000)
    budgets = {k: int(token_limit * v) for k, v in BUDGET_RATIOS.items()}

    all_files = files + (test_files or [])

    # ── 组装各区块 ──────────────────────────────────────────────────────────

    header = (
        f"# Unit 执行上下文：{ep_id} {unit_id}\n"
        f"> token 预算：{token_limit:,} ({model}) | 文件：{len(all_files)} 个\n"
        f"> 架构层：{layer}\n\n"
    )

    task_block = f"## 任务\n\n**{title}**\n\n{description}\n\n"

    contracts_block = extract_layer_contracts(layer, budgets["contracts"])

    # 文件内容摘要（按预算平均分配给每个文件）
    per_file_budget = budgets["files"] // max(len(all_files), 1)
    file_summaries: List[str] = []
    for f in all_files:
        summary = extract_file_summary(f, per_file_budget)
        file_summaries.append(summary)
    files_block = "## 涉及文件摘要\n\n" + "\n".join(file_summaries)

    memories_block = inject_relevant_memories(layer, files, budgets["memories"])

    # 验证命令
    verify_cmds: List[str] = []
    if test_files or any("test" in f.lower() for f in all_files):
        test_paths = test_files or [f for f in all_files if "test" in f.lower()]
        if test_paths:
            verify_cmds.append(f"pytest {' '.join(test_paths[:2])} -v")
    verify_cmds.append("python3 scripts/mms/arch_check.py --ci")
    verify_block = "## 验证命令\n\n```bash\n" + "\n".join(verify_cmds) + "\n```\n"

    # ── 组装完整上下文 ──────────────────────────────────────────────────────
    parts = [header, task_block]
    if contracts_block.strip():
        parts.append(contracts_block)
    parts.append(files_block)
    if memories_block.strip():
        parts.append(memories_block)
    parts.append(verify_block)

    full_context = "\n".join(parts)

    # 最终 token 检查
    actual_tokens = estimate_tokens(full_context)
    if actual_tokens > token_limit * 1.1:
        # 超限时截断 files_block
        overage = actual_tokens - token_limit
        # 简单截断策略：减少每个文件的预算
        reduced_budget = max(200, per_file_budget - overage // max(len(all_files), 1))
        file_summaries = [extract_file_summary(f, reduced_budget) for f in all_files]
        files_block = "## 涉及文件摘要\n\n" + "\n".join(file_summaries)
        parts[parts.index(next(p for p in parts if "涉及文件摘要" in p))] = files_block
        full_context = "\n".join(parts)

    # 添加 token 使用统计尾注
    final_tokens = estimate_tokens(full_context)
    full_context += f"\n---\n*token 使用：~{final_tokens:,} / {token_limit:,} ({model})*\n"

    return full_context


def generate_from_dag(ep_id: str, unit_id: str, model: str = "capable") -> str:
    """从 DAG 状态文件读取 Unit 信息并生成上下文"""
    try:
        from mms.dag.dag_model import DagState  # type: ignore[import]
    except ImportError:
        from mms.dag.dag_model import DagState  # type: ignore[import]

    try:
        from mms.workflow.ep_parser import parse_ep_by_id  # type: ignore[import]
    except ImportError:
        from mms.workflow.ep_parser import parse_ep_by_id  # type: ignore[import]

    dag = DagState.load(ep_id)
    unit = dag._get_unit(unit_id)

    # 尝试从 EP 文件获取描述
    description = ""
    try:
        parsed = parse_ep_by_id(ep_id)
        for su in parsed.scope_units:
            if su.unit_id == unit_id:
                description = su.description
                break
    except Exception:
        pass

    return generate_unit_context(
        unit_id=unit.id,
        title=unit.title,
        layer=unit.layer,
        files=unit.files,
        test_files=unit.test_files,
        model=model,
        ep_id=ep_id,
        description=description,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="mms.execution.unit_context.py — 生成 Unit 执行上下文（token 受限）",
    )
    parser.add_argument("--ep", required=True, help="EP ID（如 EP-117）")
    parser.add_argument("--unit", required=True, help="Unit ID（如 U3）")
    parser.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="目标执行模型（影响 token 预算）",
    )
    parser.add_argument("--output", help="输出到文件（默认输出到 stdout）")
    args = parser.parse_args()

    try:
        context = generate_from_dag(args.ep, args.unit, args.model)
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ 生成上下文失败：{e}", file=sys.stderr)
        return 1

    if args.output:
        Path(args.output).write_text(context, encoding="utf-8")
        tokens = estimate_tokens(context)
        print(f"✅ 上下文已写入：{args.output}（~{tokens:,} tokens）")
    else:
        print(context)

    return 0


if __name__ == "__main__":
    sys.exit(main())
