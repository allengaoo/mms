"""
mms verify — 记忆系统健康检查工具

检查项：
  --schema     : YAML front-matter 结构校验（调用 validate.py 逻辑）
  --index      : MEMORY_INDEX.json 与实际文件一致性
  --docs       : frontend_page_map.md / e2e_traceability.md 与代码的漂移检测
  --frontend   : 前端页面是否使用了正确的 React 组件（非 Amis JSON）
  --all        : 运行所有检查（默认）

退出码：
  0  — 全部通过
  1  — 有警告（warn 级别）
  2  — 有错误（error 级别），适合 CI 断言
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Set, Tuple

# ── 路径常量 ─────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_INDEX_PATH = _MEMORY_ROOT / "MEMORY_INDEX.json"
_DOCS_ARCH = _ROOT / "docs" / "architecture"
_FRONTEND_SRC = _ROOT / "frontend" / "src"
_BACKEND_SRC = _ROOT / "backend" / "app"

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


# ── 1. Schema 校验 ────────────────────────────────────────────────────────────

REQUIRED_FIELDS = {"id", "layer", "type", "tier", "tags", "source_ep", "created_at"}
VALID_TIERS = {"hot", "warm", "cold", "archive"}
VALID_TYPES = {
    "lesson", "pattern", "anti-pattern", "decision",
    # BIZ 层专属类型
    "business-flow", "actor-model", "constraint", "edge-case",
    # ENV 层专属类型（部署环境快照）
    "environment-snapshot", "datasource-config",
}


def _parse_frontmatter(path: Path) -> Tuple[dict, str]:
    """返回 (front_matter_dict, body)，解析失败时 dict 为空"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text
    fm_text = parts[1]
    body = parts[2]
    fm: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm, body


def check_schema() -> List[str]:
    """校验所有记忆文件的 YAML front-matter。返回错误列表。"""
    errors: List[str] = []
    candidates = [
        md for md in _MEMORY_ROOT.rglob("*.md")
        if "_system" not in md.parts
        and "archive" not in md.parts
        and "templates" not in md.parts
        and md.name != "CONTRIBUTING.md"
    ]
    for path in candidates:
        fm, _ = _parse_frontmatter(path)
        rel = path.relative_to(_MEMORY_ROOT)
        if not fm:
            errors.append(f"[schema] {rel} — 缺少 YAML front-matter")
            continue
        missing = REQUIRED_FIELDS - fm.keys()
        if missing:
            errors.append(f"[schema] {rel} — 缺少字段: {missing}")
        if fm.get("tier") and fm["tier"] not in VALID_TIERS:
            errors.append(f"[schema] {rel} — tier 无效: {fm['tier']!r}")
        if fm.get("type") and fm["type"] not in VALID_TYPES:
            errors.append(f"[schema] {rel} — type 无效: {fm['type']!r}")
    return errors


# ── 2. 索引一致性 ─────────────────────────────────────────────────────────────

def _collect_index_paths(tree: list) -> Set[str]:
    """递归收集索引树中所有 file_path（以路径为唯一键，避免重复 ID 覆盖问题）。"""
    paths: Set[str] = set()
    for node in tree:
        for mem in node.get("memories", []):
            fp = mem.get("file", "")
            if fp:
                paths.add(fp)
        paths.update(_collect_index_paths(node.get("nodes", [])))
    return paths


def check_index() -> List[str]:
    """校验 MEMORY_INDEX.json 与磁盘文件的一致性。"""
    errors: List[str] = []
    if not _INDEX_PATH.exists():
        return ["[index] MEMORY_INDEX.json 不存在"]

    with open(_INDEX_PATH, encoding="utf-8") as f:
        idx = json.load(f)

    indexed_paths = _collect_index_paths(idx.get("tree", []))
    stats = idx.get("stats", {})

    # 实际文件列表
    actual_files = {
        md.relative_to(_MEMORY_ROOT)
        for md in _MEMORY_ROOT.rglob("*.md")
        if "_system" not in md.parts
        and "archive" not in md.parts
        and "templates" not in md.parts
        and md.name != "CONTRIBUTING.md"
    }

    # 在索引中但文件不存在（用路径集合做反向校验）
    for fpath in sorted(indexed_paths):
        if not (_MEMORY_ROOT / fpath).exists():
            errors.append(f"[index] 索引条目指向不存在的文件: {fpath}")

    # 文件存在但不在索引中
    orphans = actual_files - {Path(v) for v in indexed_paths}
    if orphans:
        for o in sorted(orphans):
            errors.append(f"[index] 孤立文件（未在索引中）: {o}")

    # stats 字段校验
    actual_count = len(actual_files)
    if stats.get("total") != actual_count:
        errors.append(
            f"[index] stats.total={stats.get('total')} 与实际文件数 {actual_count} 不符"
        )

    return errors


# ── 3. 文档漂移检测（轻量版） ─────────────────────────────────────────────────

def check_docs() -> List[str]:
    """
    检测 frontend_page_map.md 和 e2e_traceability.md 是否与代码同步。
    轻量规则：
    - 扫描 backend/app/api/v1/ 下的路由文件，提取 @router.xxx("/...") 的路径
    - 检查这些路径是否在 e2e_traceability.md 中有记录
    - 扫描 frontend/src/pages/ 下的 .tsx 文件，检查是否在 frontend_page_map.md 中有记录
    """
    errors: List[str] = []

    # 检查 e2e_traceability.md
    e2e_path = _DOCS_ARCH / "e2e_traceability.md"
    if not e2e_path.exists():
        errors.append("[docs] e2e_traceability.md 不存在")
    else:
        e2e_content = e2e_path.read_text(encoding="utf-8", errors="ignore")
        api_dir = _BACKEND_SRC / "api" / "v1"
        if api_dir.exists():
            route_pattern = re.compile(r'@router\.\w+\(\s*["\']([^"\']+)["\']')
            for py_file in api_dir.rglob("*.py"):
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                for m in route_pattern.finditer(text):
                    route = m.group(1)
                    # 只检查有实际路径（非占位符）的路由
                    if route and "{" not in route and route not in e2e_content:
                        errors.append(
                            f"[docs] 路由 {route!r}（{py_file.name}）未在 e2e_traceability.md 中记录"
                        )

    # 检查 frontend_page_map.md
    page_map_path = _DOCS_ARCH / "frontend_page_map.md"
    if not page_map_path.exists():
        errors.append("[docs] frontend_page_map.md 不存在")
    else:
        page_content = page_map_path.read_text(encoding="utf-8", errors="ignore")
        pages_dir = _FRONTEND_SRC / "pages"
        if pages_dir.exists():
            for tsx in pages_dir.rglob("*.tsx"):
                # 跳过 index、类型文件、测试文件
                if tsx.stem in ("index", "types", "utils") or "test" in tsx.stem.lower():
                    continue
                component_name = tsx.stem
                if component_name not in page_content:
                    errors.append(
                        f"[docs] 组件 {component_name}.tsx 未在 frontend_page_map.md 中记录"
                    )

    return errors


# ── 4. 前端规范检查 ───────────────────────────────────────────────────────────

def check_frontend() -> List[str]:
    """
    检查前端 Management 页面是否误用了 Amis JSON。
    规则：pages/ 下的 .tsx 文件中不应该出现 'amisMake' 或直接 import amis 的模式
    （Chat2App 模块除外，位于 pages/chat2app/ 或 components/chat2app/ 下）
    """
    errors: List[str] = []
    if not _FRONTEND_SRC.exists():
        return errors

    amis_import_pattern = re.compile(r"from\s+['\"]amis['\"]|import\s+.*amis")
    amis_make_pattern = re.compile(r"amisMake\(|createAmisEnv\(")

    for tsx in _FRONTEND_SRC.rglob("*.tsx"):
        # Chat2App 模块允许使用 Amis
        if "chat2app" in str(tsx).lower() or "chat_2_app" in str(tsx).lower():
            continue
        text = tsx.read_text(encoding="utf-8", errors="ignore")
        rel = tsx.relative_to(_FRONTEND_SRC)
        if amis_import_pattern.search(text) or amis_make_pattern.search(text):
            errors.append(
                f"[frontend] {rel} — Management 页面中检测到 Amis 导入（仅 Chat2App 允许使用）"
            )

    return errors


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="mms verify — 记忆系统与架构健康检查",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/verify.py                # 运行所有检查
  python3 scripts/mms/verify.py --schema       # 只检查 schema
  python3 scripts/mms/verify.py --index        # 只检查索引一致性
  python3 scripts/mms/verify.py --docs         # 只检查文档漂移
  python3 scripts/mms/verify.py --ci           # CI 模式（错误时返回 exit 2）
""",
    )
    parser.add_argument("--schema", action="store_true", help="校验 YAML front-matter")
    parser.add_argument("--index", action="store_true", help="校验索引一致性")
    parser.add_argument("--docs", action="store_true", help="检测文档漂移")
    parser.add_argument("--frontend", action="store_true", help="前端规范检查")
    parser.add_argument("--ci", action="store_true", help="CI 模式（有错误则 exit 2）")
    args = parser.parse_args()

    # 未指定任何子项则运行全部
    run_all = not any([args.schema, args.index, args.docs, args.frontend])

    all_errors: List[str] = []
    all_warnings: List[str] = []

    checks = [
        ("schema", check_schema, args.schema or run_all, "Schema 校验"),
        ("index", check_index, args.index or run_all, "索引一致性"),
        ("docs", check_docs, args.docs or run_all, "文档漂移检测"),
        ("frontend", check_frontend, args.frontend or run_all, "前端规范检查"),
    ]

    print(f"\n{BOLD}MMS 健康检查{RESET}\n{'─' * 50}")

    for _key, fn, enabled, label in checks:
        if not enabled:
            continue
        print(f"\n▶ {label}")
        issues = fn()
        if not issues:
            _ok("通过")
        else:
            for issue in issues:
                # 文档漂移只是警告，不阻断 CI
                if "[docs]" in issue or "[frontend]" in issue:
                    _warn(issue)
                    all_warnings.append(issue)
                else:
                    _err(issue)
                    all_errors.append(issue)

    print(f"\n{'─' * 50}")
    if all_errors:
        print(f"{RED}{BOLD}✗ {len(all_errors)} 个错误，{len(all_warnings)} 个警告{RESET}")
        if args.ci:
            return 2
        return 1
    elif all_warnings:
        print(f"{YELLOW}{BOLD}⚠ 0 个错误，{len(all_warnings)} 个警告（不阻断 CI）{RESET}")
        return 0
    else:
        print(f"{GREEN}{BOLD}✓ 全部检查通过{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
