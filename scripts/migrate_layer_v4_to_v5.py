#!/usr/bin/env python3
"""
scripts/migrate_layer_v4_to_v5.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 字段迁移脚本：v4.x 项目特化 ID → v5.0 通用 9 层 ID

背景：
  v4.x 的 MemoryNode.layer 使用项目特化的 17 个细粒度 ID
  （L5_api / L4_service / L3_ontology 等），这些 ID 与 MMS 项目紧密绑定，
  违反 P3_universal_schema_per_project_config 设计原则。

  v5.0 将 layer 字段收敛到 9 个通用层 ID（ADAPTER/APP/DOMAIN/PLATFORM/CC 等），
  项目特化的细分移至 docs/memory/_system/routing/project_layers.yaml。

迁移映射（来自 universal_layers.yaml 的 deprecated_aliases）：
  L5_api / L5_frontend  → ADAPTER
  L4_service / L4_worker → APP
  L3_ontology / L3_data_pipeline → DOMAIN
  L2_database / L2_messaging / L2_cache / L2_storage / L2_infrastructure → PLATFORM
  L1_security / L1_platform → PLATFORM
  CC_architecture / Tooling_mms → CC
  （CC_testing / CC_governance / BIZ / Ops 保持不变）

用法：
  python3 scripts/migrate_layer_v4_to_v5.py                        # 预览（dry-run）
  python3 scripts/migrate_layer_v4_to_v5.py --apply                # 执行迁移
  python3 scripts/migrate_layer_v4_to_v5.py --path docs/memory/shared  # 指定目录
  python3 scripts/migrate_layer_v4_to_v5.py --apply --path tests/fixtures

特性：
  - 幂等：多次运行结果一致
  - 精确替换：只替换 YAML frontmatter 中的 layer 字段，不影响正文
  - 统计报告：显示每个旧 ID 被迁移的次数
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

# v4.x 项目特化 ID → v5.0 通用层 ID
_MIGRATION_MAP: dict[str, str] = {
    # L5 适配层
    "L5_api":           "ADAPTER",
    "L5_frontend":      "ADAPTER",
    "L5_interface":     "ADAPTER",
    # L4 应用层
    "L4_service":       "APP",
    "L4_worker":        "APP",
    "L4_application":   "APP",
    # L3 领域层
    "L3_ontology":      "DOMAIN",
    "L3_data_pipeline": "DOMAIN",
    "L3_domain":        "DOMAIN",
    # L2/L1 平台层
    "L2_database":      "PLATFORM",
    "L2_messaging":     "PLATFORM",
    "L2_cache":         "PLATFORM",
    "L2_storage":       "PLATFORM",
    "L2_infrastructure": "PLATFORM",
    "L1_security":      "PLATFORM",
    "L1_platform":      "PLATFORM",
    "L1":               "PLATFORM",
    "L2":               "PLATFORM",
    # CC 横切
    "CC_architecture":  "CC",
    "Tooling_mms":      "CC",
    "cross_cutting":    "CC",
    # 短格式数字别名（非常旧的格式）
    "L3":               "DOMAIN",
    "L4":               "APP",
    "L5":               "ADAPTER",
}

# layer: <old_id> 的 frontmatter 模式（YAML front-matter 第一个 --- 块内）
_LAYER_PATTERN = re.compile(
    r"^(layer:\s*)(" + "|".join(re.escape(k) for k in _MIGRATION_MAP) + r")(\s*)$",
    re.MULTILINE,
)


def migrate_file(path: Path, apply: bool, stats: Counter) -> bool:
    """
    迁移单个文件的 layer 字段。

    Returns:
        True 若文件被修改（或在 dry-run 时会被修改）
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    # 快速过滤：无 frontmatter 的文件跳过
    if not text.startswith("---"):
        return False

    # 找 frontmatter 结束位置（第二个 --- 之前）
    end_fm = text.find("\n---", 3)
    if end_fm == -1:
        # 没有关闭标记，整个文件作为 frontmatter
        fm_text = text
        body_text = ""
    else:
        fm_text = text[: end_fm + 4]
        body_text = text[end_fm + 4 :]

    new_fm, count = _LAYER_PATTERN.subn(
        lambda m: m.group(1) + _MIGRATION_MAP[m.group(2)] + m.group(3),
        fm_text,
    )

    if count == 0:
        return False

    # 统计
    for old_id, new_id in _MIGRATION_MAP.items():
        old_count = len(re.findall(rf"^layer:\s*{re.escape(old_id)}\s*$", fm_text, re.MULTILINE))
        if old_count > 0:
            stats[f"{old_id} → {new_id}"] += old_count

    if apply:
        new_text = new_fm + body_text
        path.write_text(new_text, encoding="utf-8")

    return True


def run(paths: list[Path], apply: bool) -> None:
    stats: Counter = Counter()
    modified = []
    scanned = 0

    all_md_files = []
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

    print(f"\n{'=' * 60}")
    print(f"  Layer 迁移报告 v4→v5  ({'DRY-RUN' if not apply else '已应用'})")
    print(f"{'=' * 60}")
    print(f"  扫描文件数 : {scanned}")
    print(f"  受影响文件 : {len(modified)}")
    print()

    if stats:
        print("  迁移统计（旧 ID → 新 ID：出现次数）：")
        for mapping, count in sorted(stats.items()):
            print(f"    {mapping}: {count} 次")
    else:
        print("  无需迁移（所有 layer 字段已为 v5 通用层 ID）")

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

    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Layer 字段迁移：v4.x 项目特化 ID → v5.0 通用 9 层 ID"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际执行迁移（默认 dry-run 预览）",
    )
    parser.add_argument(
        "--path",
        type=Path,
        action="append",
        dest="paths",
        help="指定迁移目录或文件（可多次指定；默认: docs/memory + tests + benchmark）",
    )
    args = parser.parse_args()

    paths = args.paths if args.paths else _DEFAULT_PATHS
    paths = [p if p.is_absolute() else _ROOT / p for p in paths]

    run(paths=paths, apply=args.apply)


if __name__ == "__main__":
    main()
