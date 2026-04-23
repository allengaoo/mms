#!/usr/bin/env python3
"""
MMS Precheck — 代码修改前检查门控

在开始修改代码前执行：
  1. 解析 EP 文件的 Scope 节，提取涉及文件路径
  2. 运行 arch_check 基线扫描（仅针对 Scope 文件）
  3. 分析 e2e_traceability.md 影响路径
  4. 保存基线快照到 checkpoint（供 postcheck 对比用）
  5. 输出前置检查报告：PASS / WARN / BLOCKER

用法：
    python scripts/mms/cli.py precheck --ep EP-114
    python scripts/mms/cli.py precheck --ep EP-114 --strict
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_CHECKPOINTS_DIR = _MEMORY_ROOT / "_system" / "checkpoints"
_EP_DIR = _ROOT / "docs" / "execution_plans"

# ANSI 颜色
_G = "\033[92m"   # green
_Y = "\033[93m"   # yellow
_R = "\033[91m"   # red
_C = "\033[96m"   # cyan
_B = "\033[1m"    # bold
_D = "\033[2m"    # dim
_X = "\033[0m"    # reset


def _ok(msg: str)   -> None: print(f"  {_G}✅{_X} {msg}")
def _warn(msg: str) -> None: print(f"  {_Y}⚠️ {_X} {msg}")
def _err(msg: str)  -> None: print(f"  {_R}❌{_X} {msg}")
def _info(msg: str) -> None: print(f"  {_D}ℹ️  {msg}{_X}")


# ── EP 文件解析 ──────────────────────────────────────────────────────────────

def find_ep_file(ep_id: str) -> Optional[Path]:
    """在 docs/execution_plans/ 中查找 EP 文件"""
    ep_norm = ep_id.upper()
    for f in _EP_DIR.glob("*.md"):
        if ep_norm in f.name.upper():
            return f
    return None


def parse_scope_files(ep_file: Path) -> List[str]:
    """
    从 EP 文件的 Scope 节解析涉及文件路径列表。
    支持格式：
      - `path/to/file.py`（新建）
      - - path/to/file.py
      - `path/to/file.py`（MODIFY）
    """
    text = ep_file.read_text(encoding="utf-8")
    paths: List[str] = []

    # 找到 Scope 节（## Scope 或 ## 1. 需求摘要 中的涉及文件行）
    scope_pattern = re.compile(
        r"(?:##\s*Scope.*?|涉及文件.*?)\n(.*?)(?:\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    scope_match = scope_pattern.search(text)
    if not scope_match:
        return []

    scope_text = scope_match.group(1)

    # 提取反引号包裹的路径
    for m in re.finditer(r"`([^`]+\.[a-zA-Z0-9]+)`", scope_text):
        candidate = m.group(1)
        # 过滤非文件路径（如命令行参数）
        if "/" in candidate or candidate.endswith((".py", ".ts", ".tsx", ".md", ".json")):
            paths.append(candidate)

    # 提取 bullet list 中的路径
    for line in scope_text.splitlines():
        stripped = line.strip().lstrip("- ").strip()
        if stripped.startswith(("backend/", "frontend/", "scripts/", "docs/", "deploy/")):
            # 去掉注释（如"（新建）"）
            path_part = stripped.split("（")[0].split("#")[0].strip()
            if path_part:
                paths.append(path_part)

    # 去重，保持顺序
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def parse_testing_files(ep_file: Path) -> List[str]:
    """从 EP 文件的 Testing Plan 节解析测试文件路径"""
    text = ep_file.read_text(encoding="utf-8")
    paths: List[str] = []

    test_pattern = re.compile(
        r"##\s*2\.5\s*Testing Plan.*?\n(.*?)(?:\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    )
    match = test_pattern.search(text)
    if not match:
        return []

    for m in re.finditer(r"`([^`]*tests?[^`]*\.py)`", match.group(1)):
        paths.append(m.group(1))

    return paths


# ── arch_check 基线扫描 ──────────────────────────────────────────────────────

def run_arch_check_baseline(scope_files: List[str]) -> Dict:
    """
    运行 arch_check.py，返回违反列表字典。
    结构：{"violations": [{"check": "AC-1", "file": "...", "message": "..."}], "total": N}
    """
    arch_check = _HERE / "mms.analysis.arch_check.py"
    if not arch_check.exists():
        return {"violations": [], "total": 0, "error": "mms.analysis.arch_check.py 不存在"}

    try:
        result = subprocess.run(
            [sys.executable, str(arch_check), "--json"],
            capture_output=True, text=True, cwd=str(_ROOT),
        )
        # arch_check 可能不支持 --json，则解析文本输出
        if result.returncode not in (0, 1):
            output = result.stdout + result.stderr
            return _parse_arch_check_text(output)

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return _parse_arch_check_text(result.stdout + result.stderr)

    except Exception as exc:
        return {"violations": [], "total": 0, "error": str(exc)}


def _parse_arch_check_text(text: str) -> Dict:
    """解析 arch_check 文本输出，提取违反信息"""
    violations = []
    for line in text.splitlines():
        if "❌" in line or "FAIL" in line or "violation" in line.lower():
            violations.append({"message": line.strip()})
    return {"violations": violations, "total": len(violations)}


# ── 影响范围分析 ─────────────────────────────────────────────────────────────

def analyze_impact(scope_files: List[str]) -> Dict:
    """
    分析涉及文件对 e2e_traceability.md 和 frontend_page_map.md 的影响范围。
    返回：{"api_endpoints": [...], "pages": [...], "stores": [...]}
    """
    result: Dict[str, List[str]] = {"api_endpoints": [], "pages": [], "stores": []}

    traceability = _ROOT / "docs" / "architecture" / "e2e_traceability.md"
    page_map = _ROOT / "docs" / "architecture" / "frontend_page_map.md"

    for scope_file in scope_files:
        stem = Path(scope_file).stem

        # 在 e2e_traceability.md 中搜索文件名相关行
        if traceability.exists():
            text = traceability.read_text(encoding="utf-8")
            for line in text.splitlines():
                if stem in line and ("|" in line):
                    if "/api/" in scope_file or "endpoint" in scope_file:
                        endpoint = _extract_cell(line, 0)
                        if endpoint and endpoint not in result["api_endpoints"]:
                            result["api_endpoints"].append(endpoint)

        # 在 frontend_page_map.md 中搜索
        if page_map.exists():
            text = page_map.read_text(encoding="utf-8")
            for line in text.splitlines():
                if stem in line and ("|" in line):
                    page = _extract_cell(line, 0)
                    if page and page not in result["pages"]:
                        result["pages"].append(page)

    return result


def _extract_cell(table_row: str, col_idx: int) -> str:
    """从 Markdown 表格行提取第 col_idx 列内容"""
    cells = [c.strip() for c in table_row.split("|") if c.strip()]
    if len(cells) > col_idx:
        return cells[col_idx]
    return ""


# ── 快照保存 ─────────────────────────────────────────────────────────────────

def save_checkpoint(ep_id: str, data: Dict) -> Path:
    """保存 precheck 基线快照到 checkpoint 文件"""
    _CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_file = _CHECKPOINTS_DIR / f"precheck-{ep_id}.json"
    checkpoint_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return checkpoint_file


def load_checkpoint(ep_id: str) -> Optional[Dict]:
    """加载 precheck 基线快照（供 postcheck 使用）"""
    checkpoint_file = _CHECKPOINTS_DIR / f"precheck-{ep_id}.json"
    if not checkpoint_file.exists():
        return None
    try:
        return json.loads(checkpoint_file.read_text(encoding="utf-8"))
    except Exception:
        return None


# ── 主检查逻辑 ───────────────────────────────────────────────────────────────

def run_precheck(ep_id: str, strict: bool = False) -> int:
    """
    执行完整的前置检查流程。

    返回码：
      0 = PASS（可以开始修改代码）
      1 = WARN（有警告，可以继续但需注意）
      2 = BLOCKER（严重问题，必须先修复）
    """
    ep_norm = ep_id.upper()
    print(f"\n{_B}MMS 前置检查（precheck）· {ep_norm}{_X}")
    print("─" * 60)

    # ── 1. 找到 EP 文件 ──────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 1 · 解析 EP 文件{_X}")
    ep_file = find_ep_file(ep_norm)
    if not ep_file:
        _err(f"找不到 EP 文件：{ep_norm}（在 docs/execution_plans/ 中搜索）")
        return 2

    _ok(f"找到 EP 文件：{ep_file.name}")

    scope_files = parse_scope_files(ep_file)
    testing_files = parse_testing_files(ep_file)

    if scope_files:
        _info(f"Scope 文件（{len(scope_files)} 个）：")
        for f in scope_files:
            print(f"      {_D}{f}{_X}")
    else:
        _warn("未找到 Scope 文件列表（EP 文件中缺少 Scope 节）")

    if testing_files:
        _info(f"Testing Plan 文件（{len(testing_files)} 个）：")
        for f in testing_files:
            print(f"      {_D}{f}{_X}")
    else:
        _warn("未找到 Testing Plan 声明（postcheck 阶段将需要手动指定测试路径）")

    # ── 2. arch_check 基线 ───────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 2 · arch_check 基线扫描{_X}")
    arch_result = run_arch_check_baseline(scope_files)

    if "error" in arch_result:
        _warn(f"arch_check 运行异常：{arch_result['error']}")
        arch_violations = []
    else:
        arch_violations = arch_result.get("violations", [])

    if not arch_violations:
        _ok("arch_check 基线：无已知架构违反")
    else:
        total = arch_result.get("total", len(arch_violations))
        _warn(f"arch_check 基线：发现 {total} 处已有违反（将在 postcheck 中对比新增量）")
        for v in arch_violations[:5]:
            msg = v.get("message", str(v))
            print(f"    {_Y}→{_X} {msg}")
        if total > 5:
            _info(f"  ... 还有 {total - 5} 处（运行 arch_check.py 查看完整列表）")

    # ── 3. 影响范围分析 ──────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 3 · 影响范围分析{_X}")
    if scope_files:
        impact = analyze_impact(scope_files)
        if impact["api_endpoints"]:
            _info(f"关联 API Endpoint：{impact['api_endpoints']}")
        if impact["pages"]:
            _info(f"关联前端页面：{impact['pages']}")
        if not impact["api_endpoints"] and not impact["pages"]:
            _info("e2e_traceability.md / frontend_page_map.md 中未找到直接关联记录")
            _info("（如本次新增，记得在 postcheck 后同步更新这两份文档）")
    else:
        _warn("无 Scope 文件，跳过影响范围分析")
        impact = {}

    # ── 4. 保存基线快照 ──────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 4 · 保存基线快照{_X}")
    checkpoint_data = {
        "ep_id": ep_norm,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope_files": scope_files,
        "testing_files": testing_files,
        "arch_violations_baseline": arch_violations,
        "arch_violations_count": len(arch_violations),
        "impact": impact,
    }
    checkpoint_file = save_checkpoint(ep_norm, checkpoint_data)
    _ok(f"基线快照已保存：{checkpoint_file.relative_to(_ROOT)}")

    # ── 5. 综合评级 ──────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")

    has_blocker = False
    has_warn = len(arch_violations) > 10 or not scope_files

    if has_blocker:
        print(f"{_R}{_B}❌  BLOCKER — 存在严重问题，请先修复后再开始修改代码{_X}")
        return 2
    elif has_warn and strict:
        print(f"{_Y}{_B}⚠️   WARN（--strict 模式）— 有警告，建议处理后继续{_X}")
        return 1
    else:
        if arch_violations:
            print(f"{_Y}{_B}⚠️   WARN — 有 {len(arch_violations)} 处已有违反（非本次引入），可以继续{_X}")
        else:
            print(f"{_G}{_B}✅  PASS — 前置检查通过，可以开始修改代码{_X}")
        print(f"\n{_D}下一步：按 EP 的 Unit 顺序修改代码，完成后运行：{_X}")
        print(f"  {_C}mms postcheck --ep {ep_norm}{_X}\n")
        return 1 if (arch_violations and strict) else 0
