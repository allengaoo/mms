#!/usr/bin/env python3
"""
MDP Memory System — 垃圾回收器 v2.1（EP-108 重构）

功能：
  1. 扫描所有 MEM-*.md，读取 front-matter
  2. 基于 access_log.jsonl 更新 access_count
  3. 用 LFU + 时间衰减计算新的 tier（hot/warm/cold/archive）
  4. 超出 hot_max_count 的记忆降级到 warm
  5. 超过 cold_days 的记忆归档（移动到 archive/YYYY-MM/）
  6. 批量更新 MEMORY_INDEX.json（一次磁盘写入）
  7. 写入 GC 审计日志

用法：
  python scripts/memory_gc.py               # 完整 GC
  python scripts/memory_gc.py --dry-run     # 仅预览，不修改文件
  python scripts/memory_gc.py --update-index-only  # 只重建索引，不移动文件
"""
import argparse
import datetime
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from mms.core.indexer import IncrementalIndexer
from mms.core.writer import atomic_write
from mms.observability.audit import AuditLogger
from mms.observability.tracer import new_trace_id

# ─── 路径配置 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
MEMORY_ROOT = PROJECT_ROOT / "docs" / "memory"
ARCHIVE_ROOT = MEMORY_ROOT / "archive"
ACCESS_LOG = MEMORY_ROOT / "_system" / "access_log.jsonl"
GC_LOG = MEMORY_ROOT / "_system" / "gc_log.md"

# tier 阈值（与 config.yaml 保持一致）
HOT_MIN_ACCESS = 3
HOT_MAX_DAYS = 30
HOT_MAX_COUNT = 20
WARM_MIN_ACCESS = 1
WARM_MAX_DAYS = 90
COLD_MAX_DAYS = 180


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def parse_frontmatter(content: str) -> Optional[Dict]:
    """提取并解析 YAML front-matter"""
    if not content.startswith("---"):
        return None
    lines = content.split("\n")
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    fm: Dict = {}
    for line in lines[1:end_idx]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        raw_val = raw_val.strip()
        if raw_val.startswith("[") and raw_val.endswith("]"):
            inner = raw_val[1:-1]
            fm[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
        elif raw_val.lower() in ("true", "false"):
            fm[key] = raw_val.lower() == "true"
        elif raw_val.lstrip("-").isdigit():
            fm[key] = int(raw_val)
        else:
            fm[key] = raw_val.strip("\"'")
    return fm


def days_since(date_str: str) -> int:
    """计算距今天数"""
    try:
        d = datetime.date.fromisoformat(date_str)
        return (datetime.date.today() - d).days
    except (ValueError, TypeError):
        return 999


def load_access_counts() -> Dict[str, int]:
    """从 access_log.jsonl 统计每条记忆的访问次数（增量，叠加到 front-matter 原有值）"""
    counts: Dict[str, int] = {}
    if not ACCESS_LOG.exists():
        return counts
    for line in ACCESS_LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            mid = record.get("memory_id", "")
            if mid:
                counts[mid] = counts.get(mid, 0) + 1
        except json.JSONDecodeError:
            continue
    return counts


def calculate_tier(access_count: int, last_accessed_str: str) -> str:
    """LFU + 时间衰减计算 tier"""
    days = days_since(last_accessed_str)
    if access_count >= HOT_MIN_ACCESS and days <= HOT_MAX_DAYS:
        return "hot"
    if access_count >= WARM_MIN_ACCESS and days <= WARM_MAX_DAYS:
        return "warm"
    if days <= COLD_MAX_DAYS:
        return "cold"
    return "archive"


def find_all_memory_files() -> List[Path]:
    files = []
    for pattern in ("MEM-*.md", "AD-*.md", "PAT-*.md", "SKL-*.md"):
        files.extend(MEMORY_ROOT.rglob(pattern))
    return [f for f in files if "_system" not in f.parts and "archive" not in f.parts]


def update_frontmatter_field(content: str, field: str, value) -> str:
    """更新 front-matter 中指定字段的值"""
    if isinstance(value, str):
        new_line = f'{field}: "{value}"'
    else:
        new_line = f"{field}: {value}"
    pattern = re.compile(rf"^{re.escape(field)}:.*$", re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(new_line, content, count=1)
    # 字段不存在时，在 --- 闭合前插入
    return content.replace("\n---\n", f"\n{new_line}\n---\n", 1)


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def run_gc(dry_run: bool = False, update_index_only: bool = False) -> dict:
    """
    执行 GC 主流程。

    Returns:
        统计信息 dict（archived, downgraded, upgraded, total）
    """
    trace_id = new_trace_id()
    logger = AuditLogger()
    indexer = IncrementalIndexer()
    t_start = time.time()

    today = datetime.date.today().strftime("%Y-%m-%d")
    access_counts = load_access_counts()
    files = find_all_memory_files()

    stats = {
        "total": len(files),
        "archived": 0,
        "downgraded": 0,
        "upgraded": 0,
        "unchanged": 0,
        "errors": 0,
    }

    hot_candidates: List[Tuple[int, Path, Dict]] = []
    index_updates: List[Dict] = []

    for fpath in sorted(files):
        content = fpath.read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        if not fm:
            stats["errors"] += 1
            continue

        mem_id = fm.get("id", fpath.stem)
        old_access = fm.get("access_count", 0)
        new_access = old_access + access_counts.get(mem_id, 0)
        last_accessed = fm.get("last_accessed", fm.get("created_at", today))
        old_tier = fm.get("tier", "warm")
        new_tier = calculate_tier(new_access, last_accessed)

        if update_index_only:
            index_updates.append({"id": mem_id, "access_count": new_access, "tier": new_tier})
            continue

        if new_tier == "archive":
            if not dry_run:
                archive_dir = ARCHIVE_ROOT / today[:7]  # YYYY-MM
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(fpath), str(archive_dir / fpath.name))
                indexer.remove_memory(mem_id)
            print(f"  📦 归档: {mem_id}")
            stats["archived"] += 1
            continue

        if new_tier == old_tier and new_access == old_access:
            stats["unchanged"] += 1
            index_updates.append({"id": mem_id, "access_count": new_access, "tier": new_tier})
            continue

        # 更新 front-matter（tier + access_count + last_accessed）
        updated_content = content
        if new_access != old_access:
            updated_content = update_frontmatter_field(updated_content, "access_count", new_access)
            updated_content = update_frontmatter_field(updated_content, "last_accessed", today)

        if new_tier != old_tier:
            updated_content = update_frontmatter_field(updated_content, "tier", new_tier)
            action = "⬆️ 升级" if _tier_rank(new_tier) > _tier_rank(old_tier) else "⬇️ 降级"
            print(f"  {action}: {mem_id}  {old_tier} → {new_tier}  (access={new_access})")
            if new_tier == "hot":
                stats["upgraded"] += 1
                hot_candidates.append((new_access, fpath, fm))
            else:
                stats["downgraded"] += 1
        else:
            stats["unchanged"] += 1

        if not dry_run:
            atomic_write(fpath, updated_content)

        index_updates.append({"id": mem_id, "access_count": new_access, "tier": new_tier})

    # Hot 区溢出处理（保留 access_count 最高的 HOT_MAX_COUNT 条）
    if not dry_run and len(hot_candidates) > HOT_MAX_COUNT:
        hot_candidates.sort(key=lambda x: x[0], reverse=True)
        overflow = hot_candidates[HOT_MAX_COUNT:]
        for _, fpath, fm in overflow:
            mem_id = fm.get("id", fpath.stem)
            content = fpath.read_text(encoding="utf-8")
            content = update_frontmatter_field(content, "tier", "warm")
            atomic_write(fpath, content)
            print(f"  ⬇️  Hot 溢出降级: {mem_id}")
            for upd in index_updates:
                if upd["id"] == mem_id:
                    upd["tier"] = "warm"
            stats["downgraded"] += 1

    # 批量更新索引（一次磁盘写入）
    if not dry_run and index_updates:
        updated_count = indexer.batch_update_stats(index_updates)
        print(f"  📑 索引更新: {updated_count} 条")

    # 写入 GC 日志
    elapsed_ms = int((time.time() - t_start) * 1000)
    logger.log(trace_id, "gc", result="ok", elapsed_ms=elapsed_ms, **stats)
    _append_gc_log(today, stats, dry_run, elapsed_ms)

    return stats


def _tier_rank(tier: str) -> int:
    return {"archive": 0, "cold": 1, "warm": 2, "hot": 3}.get(tier, 1)


def _append_gc_log(date: str, stats: dict, dry_run: bool, elapsed_ms: int) -> None:
    mode = "[DRY-RUN] " if dry_run else ""
    entry = (
        f"\n## {mode}GC 运行记录 — {date}\n"
        f"- 总计: {stats['total']} 条 | 归档: {stats['archived']} | "
        f"升级: {stats['upgraded']} | 降级: {stats['downgraded']} | "
        f"不变: {stats['unchanged']} | 错误: {stats['errors']}\n"
        f"- 耗时: {elapsed_ms}ms\n"
    )
    GC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with GC_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="MDP Memory System — GC v2.1")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不修改文件")
    parser.add_argument("--update-index-only", action="store_true",
                        help="只更新索引，不移动文件")
    args = parser.parse_args()

    mode = "[DRY-RUN] " if args.dry_run else ""
    print(f"\n{'='*50}")
    print(f"  {mode}MMS GC v2.1  —  {datetime.date.today()}")
    print(f"{'='*50}")

    stats = run_gc(dry_run=args.dry_run, update_index_only=args.update_index_only)

    print(f"\n{'='*50}")
    print(f"  GC 完成 | 总计 {stats['total']} | "
          f"归档 {stats['archived']} | 升级 {stats['upgraded']} | "
          f"降级 {stats['downgraded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
