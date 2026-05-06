#!/usr/bin/env python3
"""
scripts/migrate_memory_node_to_4_types.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MemoryNode God Object 拆分迁移脚本（Schema v4 → v5）

背景：
  v4.x 的 MemoryNode 使用 type 字段区分语义（pattern/decision/anti-pattern/business-flow 等），
  这是 God Object 反模式（违反 P4_focused_object_types 设计原则）。

  v5.0 将每种类型独立为单独的 ObjectType，前端接口向下不变：
    pattern       → Pattern ObjectType     (PAT-* / MEM-BOOT-*)
    decision      → Decision ObjectType    (AD-*)
    anti-pattern  → AntiPattern ObjectType (ANTI-*)
    business-flow → BusinessFlow ObjectType (BIZ-*)

迁移策略（Hard Switch，决策点 1:A）：
  1. 扫描所有 .md 文件的 YAML frontmatter
  2. 根据 type 字段确认旧 MemoryNode 语义
  3. 在 frontmatter 中添加 object_type 字段（用于 Schema v5 识别）
  4. 对于废弃字段（如 lesson.yaml 的 lesson type），设置 object_type=Pattern（最接近的）
  5. type 字段保持不变（向后兼容，validate.py 仍支持原有值）

用法：
  python3 scripts/migrate_memory_node_to_4_types.py               # 预览
  python3 scripts/migrate_memory_node_to_4_types.py --apply       # 执行
  python3 scripts/migrate_memory_node_to_4_types.py --path docs/  # 指定目录

注意：
  - 幂等：若 frontmatter 已有 object_type 字段，跳过
  - 迁移只在 frontmatter 中添加 object_type 字段，不修改 type 字段（保持兼容）
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_PATHS = [
    _ROOT / "docs" / "memory",
    _ROOT / "tests",
    _ROOT / "benchmark",
]

# 旧 type 字段值 → 新 object_type 字段值
_TYPE_TO_OBJECT_TYPE: dict[str, str] = {
    "pattern":      "Pattern",
    "skill":        "Pattern",       # 技能记忆 = 可复用模式
    "error":        "Pattern",       # 错误模式 = 一种反模式记忆
    "decision":     "Decision",
    "anti-pattern": "AntiPattern",
    "business-flow": "BusinessFlow",
    "actor-model":  "BusinessFlow",  # 角色模型 ≈ 业务流相关
    "constraint":   "BusinessFlow",
    "edge-case":    "BusinessFlow",
    "lesson":       "Pattern",       # 已废弃类型，迁移到 Pattern
}

# frontmatter 中已有 object_type 的检测
_OBJECT_TYPE_RE = re.compile(r"^object_type\s*:", re.MULTILINE)
# type 字段提取
_TYPE_EXTRACT_RE = re.compile(r"^type:\s*(\S+)", re.MULTILINE)


def _get_frontmatter_bounds(text: str) -> tuple[int, int] | None:
    """返回 frontmatter 的字符串范围 (start, end)，包括两个 --- 行。"""
    if not text.startswith("---"):
        return None
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return (0, len(text))
    return (0, end_idx + 4)


def migrate_file(path: Path, apply: bool, stats: Counter) -> bool:
    """迁移单个文件，返回是否被修改（或 dry-run 时会修改）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    bounds = _get_frontmatter_bounds(text)
    if bounds is None:
        return False

    fm_text = text[bounds[0] : bounds[1]]
    body_text = text[bounds[1] :]

    # 已有 object_type，跳过
    if _OBJECT_TYPE_RE.search(fm_text):
        return False

    # 提取 type 字段
    m = _TYPE_EXTRACT_RE.search(fm_text)
    if not m:
        return False

    old_type = m.group(1).strip().strip('"').strip("'")
    new_object_type = _TYPE_TO_OBJECT_TYPE.get(old_type)
    if not new_object_type:
        return False

    # 在 type 字段后插入 object_type 字段
    new_fm = _TYPE_EXTRACT_RE.sub(
        lambda mo: mo.group(0) + f"\nobject_type: {new_object_type}",
        fm_text,
        count=1,
    )

    stats[f"type={old_type} → object_type={new_object_type}"] += 1

    if apply:
        new_text = new_fm + body_text
        path.write_text(new_text, encoding="utf-8")

    return True


def run(paths: list[Path], apply: bool) -> None:
    stats: Counter = Counter()
    modified = []
    scanned = 0

    all_md_files: list[Path] = []
    for base_path in paths:
        if base_path.is_file():
            all_md_files.append(base_path)
        else:
            all_md_files.extend(base_path.rglob("*.md"))

    for md_path in sorted(all_md_files):
        scanned += 1
        if migrate_file(md_path, apply=apply, stats=stats):
            rel = md_path.relative_to(_ROOT) if md_path.is_relative_to(_ROOT) else md_path
            modified.append(rel)

    print(f"\n{'=' * 64}")
    print(f"  MemoryNode → 4 ObjectType 迁移报告  ({'DRY-RUN' if not apply else '已应用'})")
    print(f"{'=' * 64}")
    print(f"  扫描文件数 : {scanned}")
    print(f"  受影响文件 : {len(modified)}")
    print()

    if stats:
        print("  迁移统计：")
        for mapping, count in sorted(stats.items()):
            print(f"    {mapping}: {count} 次")
    else:
        print("  无需迁移（所有文件已有 object_type 字段或无法识别）")

    if modified:
        print()
        print(f"  {'将被修改' if not apply else '已修改'}的文件：")
        for p in modified[:20]:
            print(f"    - {p}")
        if len(modified) > 20:
            print(f"    ... 以及另 {len(modified) - 20} 个文件")

    if not apply and modified:
        print()
        print("  ℹ️  以上为预览。使用 --apply 参数执行实际迁移。")

    print(f"{'=' * 64}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MemoryNode God Object 拆分迁移：添加 object_type 字段"
    )
    parser.add_argument("--apply", action="store_true", help="执行迁移（默认 dry-run）")
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        dest="paths",
        help="指定目录（可多次；默认: docs/memory + tests + benchmark）",
    )
    args = parser.parse_args()

    paths = args.paths if args.paths else _DEFAULT_PATHS
    paths = [p if p.is_absolute() else _ROOT / p for p in paths]

    run(paths=paths, apply=args.apply)


if __name__ == "__main__":
    main()
