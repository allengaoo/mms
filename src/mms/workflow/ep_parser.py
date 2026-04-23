"""
ep_parser.py — EP Markdown 文件解析器

从标准 EP Markdown 格式中提取：
- EP ID 和标题
- Purpose（目标）
- Scope 表格（Unit 列表 + 文件路径）
- Testing Plan 节（测试文件路径）
- DAG Sketch 节（如已手写，优先于 LLM 生成）

支持的 EP Markdown 格式（来自 docs/memory/templates/ep-*.md）：
  # EP-NNN · 标题
  ## Scope / 范围  （含 | Unit | 操作 | 涉及文件 | 表格）
  ## Testing Plan  （含文件路径列表）
  ## DAG Sketch    （可选，含 DAG 依赖关系描述）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
_EP_DIR = _ROOT / "docs" / "execution_plans"


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class ScopeUnit:
    """Scope 表格中的一行（对应一个 Unit）"""
    unit_id: str           # "U1", "U2" 等（从操作/描述中提取）
    description: str       # 操作描述
    files: List[str]       # 涉及文件路径


@dataclass
class ParsedEP:
    """解析后的 EP 文件内容"""
    ep_id: str                               # "EP-116"
    title: str                               # "MMS 重构..."
    purpose: str                             # Purpose 节全文
    scope_units: List[ScopeUnit]             # Scope 表格解析结果
    testing_files: List[str]                 # Testing Plan 节文件列表
    dag_sketch: Optional[str] = None         # DAG Sketch 节原始文本（如存在）
    raw_path: Optional[Path] = None          # 原始文件路径


# ── 解析器 ────────────────────────────────────────────────────────────────────

# EP ID 模式：EP-116、EP-117 等（兼容文件名中的 EP-NNN_ 格式）
_EP_ID_RE = re.compile(r"EP-(\d+)(?:[_\s·:\.]|$)", re.IGNORECASE)

# 一级标题解析
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# 节标题解析（## 开头）
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Markdown 表格行（含 | 分隔）
_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$", re.MULTILINE)

# Unit ID：U1, U2, Unit 1, Unit 2 等
_UNIT_ID_RE = re.compile(r"\b(U\d+|Unit\s*\d+)\b", re.IGNORECASE)

# 文件路径：包含 / 或 . 的词
_FILE_PATH_RE = re.compile(
    r"(?:新建|修改|删除)?\s*`([^`]+(?:[/\\][^`]+|\.[a-z]{2,4}))`"
    r"|(?:^|\s)((?:backend|frontend|scripts|docs|tests)/[^\s,，`]+)"
    , re.MULTILINE
)

# 测试文件路径：以 test_ 或 _test 开头/结尾的 .py 文件
_TEST_FILE_RE = re.compile(r"[^\s`]+test[^\s`]*\.py|[^\s`]+\.spec\.[tj]sx?", re.IGNORECASE)


def _extract_sections(content: str) -> Dict[str, str]:
    """
    将 Markdown 按 ## 节标题拆分为 {节名: 内容} 字典。
    保留 # 级别的内容在 "__header__" 键下。
    """
    sections: Dict[str, str] = {}
    parts = re.split(r"^##\s+", content, flags=re.MULTILINE)

    # 第一部分是 ## 之前的内容（含 # 标题）
    sections["__header__"] = parts[0]

    for part in parts[1:]:
        lines = part.split("\n", 1)
        title = lines[0].strip().rstrip("（)()").strip()
        body = lines[1] if len(lines) > 1 else ""
        # 规范化节名（中英文、括号等）
        key = _normalize_section_key(title)
        sections[key] = body

    return sections


def _normalize_section_key(title: str) -> str:
    """将节标题规范化为小写英文 key，兼容中英文混写"""
    title_lower = title.lower()
    if any(k in title_lower for k in ("scope", "范围", "影响范围")):
        return "scope"
    if any(k in title_lower for k in ("testing", "测试", "test plan")):
        return "testing"
    if any(k in title_lower for k in ("dag sketch", "dag", "dag 草图")):
        return "dag_sketch"
    if any(k in title_lower for k in ("purpose", "目标", "背景", "background")):
        return "purpose"
    if any(k in title_lower for k in ("surprises", "意外")):
        return "surprises"
    if any(k in title_lower for k in ("decision log", "决策")):
        return "decision_log"
    if any(k in title_lower for k in ("outcomes", "retrospective", "总结")):
        return "retrospective"
    # 其他节：直接用原标题
    return title_lower.replace(" ", "_")


def _parse_scope_table(scope_text: str) -> List[ScopeUnit]:
    """
    解析 Scope 表格，提取 Unit ID、描述和文件路径。

    支持格式：
    | Unit | 操作 | 涉及文件 |
    |---|---|---|
    | U1 | 实现 xxx | `scripts/mms/foo.py` |
    """
    units: List[ScopeUnit] = []
    rows = _TABLE_ROW_RE.findall(scope_text)

    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        if not cells:
            continue
        # 跳过表头和分隔行
        if any(c.startswith("-") or c.lower() in ("unit", "操作", "#", "operation") for c in cells):
            continue
        if len(cells) < 2:
            continue

        # 从第一列提取 Unit ID
        first_cell = cells[0]
        uid_match = _UNIT_ID_RE.search(first_cell)
        if not uid_match:
            continue
        unit_id = uid_match.group(1).replace(" ", "").upper()
        if unit_id.startswith("UNIT"):
            unit_id = "U" + unit_id[4:]

        # 操作描述
        description = cells[1] if len(cells) > 1 else ""
        description = re.sub(r"`[^`]+`", "", description).strip()

        # 提取文件路径（所有列中的反引号内容）
        row_text = "|".join(cells)
        files = re.findall(r"`([^`]+)`", row_text)
        # 过滤掉非文件路径：
        #   合法路径 = 含 "/" 且无空格（排除 shell 命令如 "kubectl port-forward ..."）
        #              或 含 "." 且无空格且不以 "EP-" 开头（如 "config.yaml"）
        files = [
            f for f in files
            if (
                ("/" in f and " " not in f)
                or ("." in f and " " not in f and not f.startswith("EP-"))
            )
        ]

        units.append(ScopeUnit(unit_id=unit_id, description=description, files=files))

    return units


def _parse_testing_files(testing_text: str) -> List[str]:
    """从 Testing Plan 节提取测试文件路径"""
    files: List[str] = []
    # 匹配反引号内的路径
    backtick_files = re.findall(r"`([^`]+\.py)`", testing_text)
    files.extend(backtick_files)
    # 匹配裸路径（tests/ 开头）
    bare_files = re.findall(r"(?:^|\s)(tests?/[^\s,，]+\.py)", testing_text, re.MULTILINE)
    files.extend(bare_files)
    # 去重保序
    seen = set()
    result = []
    for f in files:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


def _extract_ep_id(content: str, filename: str) -> str:
    """从文件名或内容中提取 EP ID"""
    # 先从文件名提取
    m = _EP_ID_RE.search(filename)
    if m:
        return f"EP-{m.group(1)}"
    # 再从内容第一行提取
    first_line = content.split("\n")[0]
    m = _EP_ID_RE.search(first_line)
    if m:
        return f"EP-{m.group(1)}"
    return "EP-???"


def _extract_title(content: str) -> str:
    """从 # 标题行提取 EP 标题"""
    m = _H1_RE.search(content)
    if not m:
        return ""
    title = m.group(1).strip()
    # 去除 EP-NNN · 前缀
    title = re.sub(r"^EP-\d+\s*[·:·]\s*", "", title, flags=re.IGNORECASE)
    return title.strip()


# ── 主入口 ────────────────────────────────────────────────────────────────────

def parse_ep_file(ep_path: Path) -> ParsedEP:
    """
    解析 EP Markdown 文件，返回 ParsedEP 数据结构。

    Args:
        ep_path: EP 文件路径（绝对或相对于项目根）

    Returns:
        ParsedEP 实例
    """
    if not ep_path.is_absolute():
        ep_path = _ROOT / ep_path
    if not ep_path.exists():
        raise FileNotFoundError(f"EP 文件不存在：{ep_path}")

    content = ep_path.read_text(encoding="utf-8")
    filename = ep_path.name

    ep_id = _extract_ep_id(content, filename)
    title = _extract_title(content)
    sections = _extract_sections(content)

    purpose = sections.get("purpose", "")
    scope_text = sections.get("scope", "")
    testing_text = sections.get("testing", "")
    dag_sketch = sections.get("dag_sketch") or None

    scope_units = _parse_scope_table(scope_text)
    testing_files = _parse_testing_files(testing_text)

    # 若 Scope 表格未解析出 Unit，尝试从整个文档提取 Unit ID
    if not scope_units:
        scope_units = _parse_scope_fallback(content)

    return ParsedEP(
        ep_id=ep_id,
        title=title,
        purpose=purpose.strip(),
        scope_units=scope_units,
        testing_files=testing_files,
        dag_sketch=dag_sketch.strip() if dag_sketch else None,
        raw_path=ep_path,
    )


def _parse_scope_fallback(content: str) -> List[ScopeUnit]:
    """
    回退解析：当标准表格不存在时，尝试从文档中提取 Unit 定义。
    识别格式：### U1: 标题 或 **U1** 描述
    """
    units: List[ScopeUnit] = []
    # 匹配 ### U1: 标题 或 ## Unit 1:
    pattern = re.compile(r"^#{2,3}\s+(U\d+|Unit\s*\d+)[:\s·](.+)$", re.MULTILINE)
    for m in pattern.finditer(content):
        unit_id_raw = m.group(1).replace(" ", "").upper()
        if unit_id_raw.startswith("UNIT"):
            unit_id_raw = "U" + unit_id_raw[4:]
        description = m.group(2).strip()
        units.append(ScopeUnit(unit_id=unit_id_raw, description=description, files=[]))
    return units


def find_ep_file(ep_id: str) -> Optional[Path]:
    """
    在 docs/execution_plans/ 目录中查找匹配 EP ID 的文件。
    支持 "EP-116"、"ep-116"、"116" 等输入格式。
    """
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    if not _EP_DIR.exists():
        return None

    for f in _EP_DIR.glob("*.md"):
        if ep_norm in f.name.upper():
            return f
    return None


def parse_ep_by_id(ep_id: str) -> ParsedEP:
    """
    按 EP ID 查找并解析 EP 文件。
    ep_id 支持 "EP-116"、"116" 等格式。
    """
    path = find_ep_file(ep_id)
    if path is None:
        ep_norm = ep_id.upper()
        if not ep_norm.startswith("EP-"):
            ep_norm = f"EP-{ep_norm}"
        raise FileNotFoundError(
            f"未找到 {ep_norm} 的执行计划文件\n"
            f"请确认 docs/execution_plans/ 目录下存在对应文件"
        )
    return parse_ep_file(path)
