#!/usr/bin/env python3
"""
freshness_checker.py — 记忆新鲜度检测器（Phase 4-A）

职责：
  当代码文件的 AST fingerprint 发生变更时，通过 cites 边的反向索引
  找到引用该文件的所有 MemoryNode，将其标记为 drift_suspected=True。
  同时沿 impacts 边传播一跳，标记间接受影响的记忆。

与 doc_drift.py 的区别：
  doc_drift.py : 代码实体（API/页面/Store）vs 架构文档（URL/名称级别的漂移）
  freshness_checker.py : 代码文件（AST fingerprint）vs 记忆内容（知识新鲜度）

使用场景：
  postcheck.py 在 AST diff 步骤后调用，输出 drift_suspected 记忆 ID 列表，
  追加到 postcheck 报告的"记忆新鲜度"章节。

独立可用：
  python3 -m mms.memory.freshness_checker check backend/app/core/response.py

版本：v1.0 | 创建于：2026-04-25 | Phase 4-A
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent.parent


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class FreshnessReport:
    """
    单次新鲜度检测报告。

    stale_ids         : 直接引用了变更文件的 MemoryNode ID 列表
    propagated_ids    : 通过 impacts 边间接受影响的 MemoryNode ID 列表
    changed_files     : 触发本次检测的文件列表
    total_checked     : 检查了多少个 MemoryNode
    """
    stale_ids: List[str] = field(default_factory=list)
    propagated_ids: List[str] = field(default_factory=list)
    changed_files: List[str] = field(default_factory=list)
    total_checked: int = 0

    @property
    def all_suspect_ids(self) -> List[str]:
        """stale + propagated 的合集（去重）。"""
        combined = set(self.stale_ids) | set(self.propagated_ids)
        return sorted(combined)

    @property
    def is_clean(self) -> bool:
        """无任何 stale 记忆。"""
        return len(self.stale_ids) == 0 and len(self.propagated_ids) == 0

    def summary_lines(self) -> List[str]:
        """格式化为 postcheck 报告可用的行列表。"""
        lines = []
        if self.is_clean:
            lines.append("  ✅ 所有记忆新鲜度正常（无 drift_suspected）")
        else:
            lines.append(f"  ⚠️  发现 {len(self.stale_ids)} 条记忆可能已过时（直接引用了变更文件）")
            for mid in self.stale_ids:
                lines.append(f"    - {mid}")
            if self.propagated_ids:
                lines.append(f"  ⚡ 通过 impacts 边传播：{len(self.propagated_ids)} 条间接受影响")
                for mid in self.propagated_ids:
                    lines.append(f"    - {mid}")
        lines.append(f"  📊 共检查 MemoryNode：{self.total_checked}")
        return lines


# ── 核心引擎 ──────────────────────────────────────────────────────────────────

class FreshnessChecker:
    """
    记忆新鲜度检测器。

    算法：
      1. 对每个变更文件，计算其当前内容的 SHA256（或读取 ast_index.json fingerprint）
      2. 通过 graph.find_by_file 找到所有引用该文件的 MemoryNode
      3. 与记忆的 ast_pointer.fingerprint 比较（若有）
      4. 无 ast_pointer 时，用 cites_files 本身判断（文件存在即视为关联）
      5. 沿 impacts 边传播一跳，标记间接受影响节点

    与 doc_drift.py 分离，职责清晰，互不干扰。
    """

    def __init__(self, memory_root: Optional[Path] = None) -> None:
        self._memory_root = memory_root
        self._graph = None

    def _get_graph(self):
        if self._graph is None:
            from mms.memory.graph_resolver import MemoryGraph
            self._graph = MemoryGraph(memory_root=self._memory_root)
        return self._graph

    def _file_fingerprint(self, file_path: str) -> Optional[str]:
        """计算文件内容的 SHA256 fingerprint（只取前 12 位）。"""
        try:
            abs_path = _ROOT / file_path
            if abs_path.exists():
                content = abs_path.read_bytes()
                return hashlib.sha256(content).hexdigest()[:12]
        except Exception:  # noqa: BLE001
            pass
        return None

    def _fingerprint_changed(self, file_path: str, node_fingerprint: Optional[str]) -> bool:
        """
        判断文件 fingerprint 是否发生变化。
        若 node 没有记录 fingerprint，保守判断为"可能已变"（返回 True）。
        """
        if not node_fingerprint:
            return True  # 保守：无记录时假设已变
        current = self._file_fingerprint(file_path)
        if current is None:
            return False  # 文件不存在，不触发告警
        return current != node_fingerprint

    def check(self, changed_files: List[str]) -> FreshnessReport:
        """
        对一组变更文件执行新鲜度检测。

        参数：
            changed_files: 变更的文件路径列表（相对项目根目录）

        返回：
            FreshnessReport，包含 stale_ids 和 propagated_ids
        """
        graph = self._get_graph()
        report = FreshnessReport(changed_files=list(changed_files))

        stale: Set[str] = set()
        propagated: Set[str] = set()

        for file_path in changed_files:
            affected_nodes = graph.find_by_file(file_path)
            report.total_checked += len(affected_nodes)

            for node in affected_nodes:
                # 从 ast_pointer 取 fingerprint（若有）
                node_fp = None
                try:
                    raw_content = node.path.read_text(encoding="utf-8", errors="ignore")
                    # 简单提取 ast_pointer.fingerprint 字段
                    import re
                    fp_match = re.search(r"fingerprint:\s*(\w+)", raw_content)
                    if fp_match:
                        node_fp = fp_match.group(1)
                except Exception:  # noqa: BLE001
                    pass

                if self._fingerprint_changed(file_path, node_fp):
                    stale.add(node.id)
                    # 沿 impacts 边传播一跳
                    for impact_id in node.impacts:
                        if impact_id and impact_id != node.id:
                            propagated.add(impact_id)

        # propagated 不包含已在 stale 中的节点（避免重复）
        propagated -= stale

        report.stale_ids = sorted(stale)
        report.propagated_ids = sorted(propagated)
        return report

    def check_files(self, changed_files: List[str]) -> List[str]:
        """
        便捷方法：返回所有 drift_suspected 记忆 ID 列表（stale + propagated）。
        """
        return self.check(changed_files).all_suspect_ids


# ── 模块级便捷函数 ────────────────────────────────────────────────────────────

def check_freshness(changed_files: List[str], memory_root: Optional[Path] = None) -> FreshnessReport:
    """
    模块级便捷函数，供 postcheck.py 调用。

    参数：
        changed_files : 变更文件路径列表
        memory_root   : 记忆根目录（测试用，默认 None=使用项目标准路径）

    返回：
        FreshnessReport
    """
    checker = FreshnessChecker(memory_root=memory_root)
    return checker.check(changed_files)


# ── CLI 入口（调试用）─────────────────────────────────────────────────────────

def _cli_main(args: List[str]) -> None:
    if not args:
        print("用法: python3 -m mms.memory.freshness_checker check <file1> [file2 ...]")
        return

    cmd = args[0]
    files = args[1:]

    if cmd == "check":
        if not files:
            print("请提供至少一个文件路径")
            return

        print(f"\n🔍 新鲜度检测：{len(files)} 个变更文件")
        for f in files:
            print(f"  - {f}")

        report = check_freshness(files)
        print("\n" + "\n".join(report.summary_lines()))
    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    _cli_main(sys.argv[1:])
