"""
doc_drift.py — 文档漂移检测器

检测 frontend_page_map.md 和 e2e_traceability.md 是否与当前代码保持同步。
当后端 API 路由或前端页面新增/删除时，对应的架构文档应同步更新。

用法:
  python3 scripts/mms/doc_drift.py           # 检测全部漂移
  python3 scripts/mms/doc_drift.py --api     # 只检查后端 API 路由漂移
  python3 scripts/mms/doc_drift.py --pages   # 只检查前端页面漂移
  python3 scripts/mms/doc_drift.py --stores  # 只检查 Zustand Store 漂移
  python3 scripts/mms/doc_drift.py --ci      # CI 模式（有漂移则 exit 1）

输出:
  每条漂移结果包含：类型、位置、建议操作
  配合 mms verify --docs 使用，也可单独运行

退出码:
  0 — 无漂移
  1 — 有漂移（需人工同步文档）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Set

_ROOT = Path(__file__).resolve().parents[2]
_DOCS_ARCH = _ROOT / "docs" / "architecture"
_BACKEND = _ROOT / "backend" / "app"
_FRONTEND_SRC = _ROOT / "frontend" / "src"

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


# ── 1. API 路由漂移 ───────────────────────────────────────────────────────────

_ROUTE_PATTERN = re.compile(
    r'@router\.\w+\(\s*["\']([^"\']+)["\']'
)


def scan_api_routes() -> Set[str]:
    """扫描 backend/app/api/v1/ 中所有路由路径"""
    routes: Set[str] = set()
    api_dir = _BACKEND / "api" / "v1"
    if not api_dir.exists():
        return routes
    for py in api_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for m in _ROUTE_PATTERN.finditer(text):
            path = m.group(1)
            # 排除占位符路径和 root
            if "{" not in path and path not in ("/", ""):
                routes.add(path)
    return routes


def check_api_drift() -> List[str]:
    """检测 backend 新增路由是否未在 e2e_traceability.md 中记录"""
    drifts: List[str] = []
    e2e_path = _DOCS_ARCH / "e2e_traceability.md"
    if not e2e_path.exists():
        drifts.append("[drift-api] e2e_traceability.md 不存在，请创建")
        return drifts

    e2e_content = e2e_path.read_text(encoding="utf-8", errors="ignore")
    routes = scan_api_routes()

    for route in sorted(routes):
        if route not in e2e_content:
            drifts.append(
                f"[drift-api] 路由 {route!r} 未在 e2e_traceability.md 中记录"
                f"  → 建议：在对应模块表格中添加该路由行"
            )

    return drifts


# ── 2. 前端页面漂移 ───────────────────────────────────────────────────────────

_SKIP_COMPONENTS = {
    "index", "types", "utils", "constants", "hooks",
    "context", "App", "main", "router", "Layout",
    "NotFound", "ComingSoon",
}

# 子组件后缀（Drawer/Dialog/Modal/Widget/Tab/Panel/Toolbar/Bubble 等不是独立页面）
_SUB_COMPONENT_SUFFIXES = (
    "Drawer", "Dialog", "Modal", "Widget", "Tab", "Panel",
    "Toolbar", "Bubble", "Canvas", "Editor",
)


def scan_frontend_pages() -> Set[str]:
    """扫描 frontend/src/pages/ 中所有页面组件名"""
    pages: Set[str] = set()
    pages_dir = _FRONTEND_SRC / "pages"
    if not pages_dir.exists():
        return pages
    for tsx in pages_dir.rglob("*.tsx"):
        name = tsx.stem
        if name in _SKIP_COMPONENTS or name.startswith("_"):
            continue
        if "test" in name.lower() or "spec" in name.lower():
            continue
        # 子组件后缀（Drawer/Dialog/Modal/Tab/Widget 等）跳过，它们不是独立路由页面
        if any(name.endswith(suffix) for suffix in _SUB_COMPONENT_SUFFIXES):
            continue
        pages.add(name)
    return pages


def check_page_drift() -> List[str]:
    """检测前端页面组件是否未在 frontend_page_map.md 中记录"""
    drifts: List[str] = []
    page_map_path = _DOCS_ARCH / "frontend_page_map.md"
    if not page_map_path.exists():
        drifts.append("[drift-page] frontend_page_map.md 不存在，请创建")
        return drifts

    content = page_map_path.read_text(encoding="utf-8", errors="ignore")
    pages = scan_frontend_pages()

    for page in sorted(pages):
        if page not in content:
            drifts.append(
                f"[drift-page] 组件 {page}.tsx 未在 frontend_page_map.md 中记录"
                f"  → 建议：添加页面行（路由 / Store / 权限）"
            )

    return drifts


# ── 3. Zustand Store 漂移 ─────────────────────────────────────────────────────

_STORE_FILE_PATTERN = re.compile(r"use[A-Z]\w+Store")


def scan_stores() -> Set[str]:
    """扫描 frontend/src/stores/ 中的 Zustand Store 名称"""
    stores: Set[str] = set()
    stores_dir = _FRONTEND_SRC / "stores"
    if not stores_dir.exists():
        return stores
    for ts in stores_dir.rglob("*.ts"):
        text = ts.read_text(encoding="utf-8", errors="ignore")
        for m in _STORE_FILE_PATTERN.finditer(text):
            stores.add(m.group(0))
    return stores


def check_store_drift() -> List[str]:
    """检测 Zustand Store 是否未在 frontend_page_map.md 中记录"""
    drifts: List[str] = []
    page_map_path = _DOCS_ARCH / "frontend_page_map.md"
    if not page_map_path.exists():
        return drifts

    content = page_map_path.read_text(encoding="utf-8", errors="ignore")
    stores = scan_stores()

    for store in sorted(stores):
        if store not in content:
            drifts.append(
                f"[drift-store] Store {store} 未在 frontend_page_map.md 中记录"
                f"  → 建议：在 Store 总览节添加该 Store"
            )

    return drifts


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="doc_drift.py — 文档漂移检测器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/doc_drift.py           # 检测全部漂移
  python3 scripts/mms/doc_drift.py --api     # 只检查 API 路由漂移
  python3 scripts/mms/doc_drift.py --ci      # CI 模式
""",
    )
    parser.add_argument("--api",    action="store_true", help="只检查 API 路由漂移")
    parser.add_argument("--pages",  action="store_true", help="只检查前端页面漂移")
    parser.add_argument("--stores", action="store_true", help="只检查 Store 漂移")
    parser.add_argument("--ci",     action="store_true", help="CI 模式（有漂移则 exit 1）")
    args = parser.parse_args()

    run_all = not any([args.api, args.pages, args.stores])

    tasks = [
        ("API 路由漂移",      check_api_drift,    args.api    or run_all),
        ("前端页面漂移",      check_page_drift,   args.pages  or run_all),
        ("Zustand Store 漂移", check_store_drift, args.stores or run_all),
    ]

    all_drifts: List[str] = []

    print(f"\n{BOLD}文档漂移检测{RESET}\n{'─' * 55}")
    for label, fn, enabled in tasks:
        if not enabled:
            continue
        print(f"\n▶ {label}")
        issues = fn()
        if not issues:
            _ok("无漂移")
        else:
            for issue in issues:
                _warn(issue)
            all_drifts.extend(issues)

    print(f"\n{'─' * 55}")
    if all_drifts:
        print(
            f"{YELLOW}{BOLD}⚠ 发现 {len(all_drifts)} 处文档漂移，"
            f"建议手动同步 docs/architecture/ 后重新运行{RESET}"
        )
        if args.ci:
            return 1
        return 0  # 非 CI 模式下漂移不阻断，只警告
    else:
        print(f"{GREEN}{BOLD}✓ 文档与代码保持同步{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
