"""
entropy_scan.py — 记忆系统熵扫描器

检测记忆库中的"熵"（无序、过时、重复、冗余）并给出清理建议。

检查维度:
  1. 孤立记忆   — 存在文件但未在 MEMORY_INDEX.json 中索引
  2. 幽灵索引   — 索引中存在但文件已删除
  3. 过期热记忆 — tier=hot 但超过 N 天未访问（应降级为 warm）
  4. 零访问记忆 — access_count=0 且超过 M 天（可能是无价值记忆）
  5. 重复标题   — 不同记忆的标题相似度极高（可能是重复内容）
  6. 过大私有区 — EP 私有工作区超过 30 天未关闭

用法:
  python3 scripts/mms/entropy_scan.py                  # 扫描全部，默认阈值
  python3 scripts/mms/entropy_scan.py --threshold warn  # 只报告警告及以上
  python3 scripts/mms/entropy_scan.py --threshold error # 只报告错误级别
  python3 scripts/mms/entropy_scan.py --fix-orphans     # 自动将孤立文件加入索引待审列表
  python3 scripts/mms/entropy_scan.py --ci              # CI 模式（有 error 则 exit 1）

退出码:
  0 — 无问题
  1 — 有警告或错误（CI 模式下 error 级别才非 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_INDEX_PATH = _MEMORY_ROOT / "MEMORY_INDEX.json"
_PRIVATE_DIR = _MEMORY_ROOT / "private"
_ORPHAN_QUEUE = _MEMORY_ROOT / "_system" / "orphan_queue.jsonl"

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"

# ── 配置阈值 ─────────────────────────────────────────────────────────────────
HOT_STALE_DAYS = 30          # hot 记忆超过 N 天未访问 → 降级候选
ZERO_ACCESS_DAYS = 60        # 零访问超过 M 天 → 低价值候选
PRIVATE_STALE_DAYS = 30      # EP 私有区超过 N 天未关闭 → 警告
DUPLICATE_TITLE_PREFIX_LEN = 20  # 标题前缀相同长度认为是重复候选


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(s: str) -> datetime:
    """解析 YYYY-MM-DD 格式日期"""
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return _now()


def _collect_index_entries(tree: list) -> Dict[str, dict]:
    """递归收集所有索引记忆条目 id → entry"""
    result: Dict[str, dict] = {}
    for node in tree:
        for mem in node.get("memories", []):
            result[mem.get("id", "")] = mem
        result.update(_collect_index_entries(node.get("nodes", [])))
    return result


def _actual_memory_files() -> Set[Path]:
    return {
        md for md in _MEMORY_ROOT.rglob("*.md")
        if "_system" not in md.parts
        and "archive" not in md.parts
        and "templates" not in md.parts
        and "private" not in md.parts
        and md.name != "CONTRIBUTING.md"
    }


# ── 1. 孤立记忆 ──────────────────────────────────────────────────────────────

def scan_orphans(indexed: Dict[str, dict]) -> List[str]:
    """返回不在索引中的 .md 文件路径列表"""
    indexed_paths = {
        _MEMORY_ROOT / v.get("file", "")
        for v in indexed.values()
        if v.get("file")
    }
    orphans = []
    for md in _actual_memory_files():
        if md not in indexed_paths:
            orphans.append(str(md.relative_to(_MEMORY_ROOT)))
    return orphans


# ── 2. 幽灵索引 ──────────────────────────────────────────────────────────────

def scan_ghost_entries(indexed: Dict[str, dict]) -> List[str]:
    """返回索引中存在但文件已删除的条目"""
    ghosts = []
    for mid, entry in indexed.items():
        fpath = entry.get("file", "")
        if fpath and not (_MEMORY_ROOT / fpath).exists():
            ghosts.append(f"{mid} → {fpath}")
    return ghosts


# ── 3. 过期热记忆 ─────────────────────────────────────────────────────────────

def scan_stale_hot(indexed: Dict[str, dict]) -> List[Tuple[str, int]]:
    """返回 (mem_id, days_since_access) 的列表，超过 HOT_STALE_DAYS"""
    stale = []
    now = _now()
    for mid, entry in indexed.items():
        if entry.get("tier") != "hot":
            continue
        last_accessed = entry.get("last_accessed", "")
        if not last_accessed:
            continue
        days = (now - _parse_date(last_accessed)).days
        if days > HOT_STALE_DAYS:
            stale.append((mid, days))
    return stale


# ── 4. 零访问记忆 ─────────────────────────────────────────────────────────────

def scan_zero_access(indexed: Dict[str, dict]) -> List[Tuple[str, int]]:
    """返回 access_count=0 且超过 ZERO_ACCESS_DAYS 天的记忆"""
    result = []
    now = _now()
    for mid, entry in indexed.items():
        if entry.get("access_count", 0) > 0:
            continue
        created = entry.get("created_at", "")
        if not created:
            continue
        days = (now - _parse_date(created)).days
        if days > ZERO_ACCESS_DAYS:
            result.append((mid, days))
    return result


# ── 5. 重复标题检测 ───────────────────────────────────────────────────────────

def scan_duplicate_titles(indexed: Dict[str, dict]) -> List[Tuple[str, str, str]]:
    """
    返回 (id1, id2, common_prefix) 的列表，表示标题前 N 字相同的记忆对。
    简单的前缀匹配，不需要 NLP。
    """
    titles: List[Tuple[str, str]] = [
        (mid, entry.get("title", ""))
        for mid, entry in indexed.items()
        if entry.get("title")
    ]

    duplicates = []
    for i, (id1, t1) in enumerate(titles):
        prefix1 = t1[:DUPLICATE_TITLE_PREFIX_LEN].lower().strip()
        for id2, t2 in titles[i + 1:]:
            prefix2 = t2[:DUPLICATE_TITLE_PREFIX_LEN].lower().strip()
            if prefix1 and prefix1 == prefix2:
                duplicates.append((id1, id2, t1[:DUPLICATE_TITLE_PREFIX_LEN]))
    return duplicates


# ── 6. 过期私有工作区 ─────────────────────────────────────────────────────────

def scan_stale_private() -> List[Tuple[str, int]]:
    """返回超过 PRIVATE_STALE_DAYS 天未关闭的 EP 私有工作区"""
    stale = []
    if not _PRIVATE_DIR.exists():
        return stale
    now = _now()
    for ep_dir in _PRIVATE_DIR.iterdir():
        if not ep_dir.is_dir():
            continue
        meta_path = ep_dir / "_meta.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("status") == "closed":
            continue
        updated = meta.get("updated_at", meta.get("created_at", ""))
        days = (now - _parse_date(updated)).days
        if days > PRIVATE_STALE_DAYS:
            stale.append((ep_dir.name, days))
    return stale


# ── 孤立文件登记到待审队列 ────────────────────────────────────────────────────

def register_orphans_to_queue(orphans: List[str]) -> None:
    """将孤立文件写入 _system/orphan_queue.jsonl，供人工审查"""
    _ORPHAN_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if _ORPHAN_QUEUE.exists():
        for line in _ORPHAN_QUEUE.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line).get("file", ""))
            except json.JSONDecodeError:
                pass

    with _ORPHAN_QUEUE.open("a", encoding="utf-8") as f:
        for o in orphans:
            if o not in existing:
                entry = {
                    "file": o,
                    "detected_at": _now().isoformat(),
                    "status": "pending_review",
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── 主程序 ────────────────────────────────────────────────────────────────────

def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="mms.memory.entropy_scan.py — 记忆系统熵扫描器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/entropy_scan.py                   # 扫描全部
  python3 scripts/mms/entropy_scan.py --threshold warn   # 只报告警告及以上
  python3 scripts/mms/entropy_scan.py --fix-orphans      # 注册孤立文件到待审队列
  python3 scripts/mms/entropy_scan.py --ci               # CI 模式
""",
    )
    parser.add_argument(
        "--threshold",
        choices=["info", "warn", "error"],
        default="info",
        help="最低报告级别（info=全报，warn=跳过 info，error=只报错误）",
    )
    parser.add_argument(
        "--fix-orphans",
        action="store_true",
        help="将孤立文件注册到 orphan_queue.jsonl 待审",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI 模式：有 error 级别问题则 exit 1",
    )
    args = parser.parse_args()

    # 加载索引
    if not _INDEX_PATH.exists():
        print(f"{RED}MEMORY_INDEX.json 不存在{RESET}")
        return 1

    with open(_INDEX_PATH, encoding="utf-8") as f:
        idx = json.load(f)

    indexed = _collect_index_entries(idx.get("tree", []))

    error_count = 0
    warn_count = 0

    print(f"\n{BOLD}熵扫描报告{RESET}\n{'─' * 55}")

    # 1. 孤立记忆
    print("\n▶ 孤立记忆（存在但未索引）")
    orphans = scan_orphans(indexed)
    if not orphans:
        _ok("无孤立记忆")
    else:
        for o in orphans:
            _warn(f"孤立: {o}")
            warn_count += 1
        if args.fix_orphans:
            register_orphans_to_queue(orphans)
            _ok(f"已将 {len(orphans)} 条孤立文件写入 orphan_queue.jsonl")

    # 2. 幽灵索引
    print("\n▶ 幽灵索引（索引中存在但文件已删除）")
    ghosts = scan_ghost_entries(indexed)
    if not ghosts:
        _ok("无幽灵索引")
    else:
        for g in ghosts:
            _err(f"幽灵: {g}")
            error_count += 1

    # 3. 过期热记忆
    print(f"\n▶ 过期热记忆（>= {HOT_STALE_DAYS} 天未访问）")
    stale_hot = scan_stale_hot(indexed)
    if not stale_hot:
        _ok("无过期热记忆")
    else:
        for mid, days in stale_hot:
            if args.threshold in ("info", "warn"):
                _warn(f"{mid} — 已 {days} 天未访问，建议降级为 warm")
                warn_count += 1

    # 4. 零访问记忆
    print(f"\n▶ 零访问记忆（>= {ZERO_ACCESS_DAYS} 天从未被访问）")
    zero_access = scan_zero_access(indexed)
    if not zero_access:
        _ok("无零访问记忆")
    else:
        for mid, days in zero_access:
            if args.threshold == "info":
                _warn(f"{mid} — {days} 天零访问，可能是低价值记忆")
                warn_count += 1

    # 5. 重复标题
    print("\n▶ 重复标题检测")
    dupes = scan_duplicate_titles(indexed)
    if not dupes:
        _ok("无重复标题")
    else:
        for id1, id2, prefix in dupes:
            if args.threshold in ("info", "warn"):
                _warn(f"{id1} ≈ {id2}（标题前缀相同: {prefix!r}）")
                warn_count += 1

    # 6. 过期私有工作区
    print(f"\n▶ 过期私有工作区（>= {PRIVATE_STALE_DAYS} 天未关闭）")
    stale_private = scan_stale_private()
    if not stale_private:
        _ok("无过期私有工作区")
    else:
        for ep_id, days in stale_private:
            if args.threshold in ("info", "warn"):
                _warn(f"{ep_id} — 已 {days} 天未关闭，建议执行 mms private close {ep_id}")
                warn_count += 1

    # 汇总
    print(f"\n{'─' * 55}")
    if error_count > 0:
        print(f"{RED}{BOLD}✗ {error_count} 个错误，{warn_count} 个警告{RESET}")
        return 1 if args.ci else 0
    elif warn_count > 0:
        print(f"{YELLOW}{BOLD}⚠ 0 个错误，{warn_count} 个警告{RESET}")
        return 0
    else:
        print(f"{GREEN}{BOLD}✓ 记忆系统熵值正常{RESET}")
        return 0


# ── 边衰减与剪枝（Phase 2 新增） ─────────────────────────────────────────────

_WEIGHTS_FILE = _MEMORY_ROOT / "_system" / "_graph_weights.yaml"


def _load_weights() -> Dict[str, Dict[str, dict]]:
    """
    加载图谱边权重文件。
    格式：{node_id: {edge_key: {weight: float, last_ep: str, access_count: int}}}
    edge_key 格式："{link_type}:{target_id_or_path}"
    """
    if not _WEIGHTS_FILE.exists():
        return {}
    try:
        import yaml
        raw = yaml.safe_load(_WEIGHTS_FILE.read_text(encoding="utf-8")) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_weights(weights: Dict[str, Dict[str, dict]]) -> None:
    """持久化边权重文件。"""
    _WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        import yaml
        _WEIGHTS_FILE.write_text(
            yaml.dump(weights, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 写失败不影响主流程


def reinforce_edges(node_id: str, link_type: str, targets: List[str], ep_id: str) -> None:
    """
    隐式正反馈：记忆节点被 hybrid_search 命中后，增强相关边的权重。

    Args:
        node_id:   被命中的记忆 ID
        link_type: 边类型（"cites"、"about"、"impacts"）
        targets:   本次命中涉及的目标 ID/路径列表
        ep_id:     当前执行计划 ID（如 "EP-128"）

    权重上限：2.0；每次命中增量：0.2（来自 config.yaml）。
    """
    try:
        from mms.utils.mms_config import cfg
        increment = 0.2  # 每次命中的权重增量（可后续从 cfg 读取）
        max_weight = 2.0
    except Exception:
        increment = 0.2
        max_weight = 2.0

    weights = _load_weights()
    node_meta = weights.setdefault(node_id, {})

    for target in targets:
        edge_key = f"{link_type}:{target}"
        edge_meta = node_meta.setdefault(edge_key, {"weight": 1.0, "last_ep": ep_id, "access_count": 0})
        edge_meta["weight"] = min(edge_meta.get("weight", 1.0) + increment, max_weight)
        edge_meta["last_ep"] = ep_id
        edge_meta["access_count"] = edge_meta.get("access_count", 0) + 1

    _save_weights(weights)


def _ep_distance(ep_a: str, ep_b: str) -> int:
    """
    计算两个 EP ID 之间的距离（如 "EP-100" 和 "EP-120" 距离为 20）。
    无法解析时返回 0。
    """
    try:
        na = int(ep_a.split("-")[-1])
        nb = int(ep_b.split("-")[-1])
        return abs(na - nb)
    except (ValueError, IndexError):
        return 0


def decay_edges(
    current_ep: str,
    dry_run: bool = False,
    decay_factor: float | None = None,
    prune_threshold: float | None = None,
    decay_window: int | None = None,
) -> Dict[str, int]:
    """
    LFU 边衰减算法（集成到 mulan gc）。

    对所有边执行：
      1. 若距离上次访问超过 decay_window 个 EP → weight *= decay_factor
      2. 若 weight < prune_threshold → 标记为待剪枝

    Args:
        current_ep:      当前 EP ID（用于计算时间窗口距离）
        dry_run:         True 时只打印预览，不修改文件
        decay_factor:    权重衰减系数（默认从 config.yaml 读取，0.8）
        prune_threshold: 低于此权重则剪枝（默认 0.2）
        decay_window:    超过 N 个 EP 未访问才触发衰减（默认 20）

    Returns:
        {"decayed": N, "pruned": N, "total_edges": N}
    """
    try:
        from mms.utils.mms_config import cfg
        _decay_factor = decay_factor or cfg.gc_edge_decay_factor
        _threshold = prune_threshold or cfg.gc_edge_prune_threshold
        _window = decay_window or cfg.gc_edge_decay_window_eps
    except Exception:
        _decay_factor = decay_factor or 0.8
        _threshold = prune_threshold or 0.2
        _window = decay_window or 20

    weights = _load_weights()
    stats = {"decayed": 0, "pruned": 0, "total_edges": 0, "skipped": 0}
    to_delete: List[tuple] = []  # [(node_id, edge_key)]

    for node_id, edge_map in list(weights.items()):
        for edge_key, meta in list(edge_map.items()):
            stats["total_edges"] += 1
            last_ep = meta.get("last_ep", current_ep)
            dist = _ep_distance(last_ep, current_ep)

            if dist >= _window:
                new_weight = meta.get("weight", 1.0) * _decay_factor
                if not dry_run:
                    meta["weight"] = new_weight
                stats["decayed"] += 1

                if new_weight < _threshold:
                    to_delete.append((node_id, edge_key))
                    stats["pruned"] += 1
            else:
                stats["skipped"] += 1

    if not dry_run and (stats["decayed"] > 0 or to_delete):
        for node_id, edge_key in to_delete:
            weights.get(node_id, {}).pop(edge_key, None)
        # 清理空节点
        weights = {k: v for k, v in weights.items() if v}
        _save_weights(weights)

    return stats


if __name__ == "__main__":
    sys.exit(main())
