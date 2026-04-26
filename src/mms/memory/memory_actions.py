"""
memory_actions.py — 记忆系统有副作用的 Action 层（Palantir Action Type 对标）

设计原则：
  - 每个 Action 函数都有明确的前置条件（pre_conditions）
  - Action 执行前验证前置条件，不满足则拒绝执行并返回错误原因
  - Action 执行后记录 provenance（谁、何时、因何触发了此次写入）
  - 副作用与计算逻辑分离：所有计算调用 memory_functions.py 的纯函数

与 dream.py 的关系：
  dream.py 的 promote_draft() 函数是目前的主入口，
  本文件提供更规范的编程接口，供未来的自动化管道使用。
  两者可以并存，后续可逐步将 dream.py 中的写入逻辑迁移到本文件。

Palantir 对照：
  create_memory_node()  → Action Type: "创建记忆节点"
  update_memory_staleness() → Action Type: "标记记忆为待刷新"
  merge_duplicate_memories() → Action Type: "合并重复记忆"
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent.parent
_MEMORY_ROOT = _ROOT / "docs" / "memory"

try:
    from mms.memory.memory_functions import (  # type: ignore[import]
        MemoryInsight, Provenance,
        build_provenance, detect_duplicate_insights,
        format_memory_content, score_memory_quality,
    )
    from mms.memory.dream import _layer_to_dir, _get_next_mem_id  # type: ignore[import]
except ImportError:
    # 兜底导入（测试环境）
    MemoryInsight = None  # type: ignore[assignment,misc]
    Provenance = None  # type: ignore[assignment,misc]


# ── 前置条件检查结果 ─────────────────────────────────────────────────────────

@dataclass
class ActionResult:
    success: bool
    node_id: str = ""
    file_path: str = ""
    error: str = ""
    warnings: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.warnings is None:
            self.warnings = []


# ── Pre-condition 定义 ──────────────────────────────────────────────────────

_QUALITY_THRESHOLD = 0.5    # 总质量分低于此值时拒绝写入
_DUPLICATE_THRESHOLD = 0.8  # Jaccard 相似度高于此值时视为重复

def _check_quality(insight: "MemoryInsight", content: str) -> Optional[str]:
    """前置条件：内容质量评分 >= 阈值"""
    from mms.memory.memory_functions import score_memory_quality  # type: ignore[import]
    score = score_memory_quality(content)
    if score.total_score < _QUALITY_THRESHOLD:
        return (
            f"内容质量分 {score.total_score:.2f} 低于阈值 {_QUALITY_THRESHOLD}。"
            f"问题：{'; '.join(score.issues)}"
        )
    return None


def _check_no_duplicate(
    insight: "MemoryInsight",
    memory_root: Path,
) -> Tuple[Optional[str], Optional[str]]:
    """
    前置条件：与现有记忆不重复。
    返回 (error_msg, duplicate_id)
    """
    from mms.memory.memory_functions import detect_duplicate_insights  # type: ignore[import]

    existing_contents: Dict[str, str] = {}
    for md_file in memory_root.glob("**/*.md"):
        if "_system" in str(md_file) or "templates" in str(md_file):
            continue
        try:
            existing_contents[md_file.stem] = md_file.read_text(encoding="utf-8")
        except Exception:
            pass

    dup_id = detect_duplicate_insights(
        insight, {}, existing_contents, _DUPLICATE_THRESHOLD
    )
    if dup_id:
        return (
            f"与现有记忆 {dup_id} 高度相似（阈值 {_DUPLICATE_THRESHOLD}），建议更新现有记忆而非新建",
            dup_id,
        )
    return None, None


def _check_not_contradicts_adr(insight: "MemoryInsight", memory_root: Path) -> Optional[str]:
    """
    前置条件：新记忆不与现有架构决策（CC 层）矛盾（简单规则检测）。
    当前实现：只做关键词级的矛盾检测，完整版需要 LLM 语义判断。
    """
    if insight.memory_type not in ("anti-pattern", "decision"):
        return None   # 只对 decision/anti-pattern 类型做检查

    cc_dir = memory_root / "shared" / "CC"
    if not cc_dir.exists():
        return None

    # 简单检查：新记忆的 tags 是否与某个 CC 层记忆的 anti_tags（如果有）冲突
    # 当前仅警告，不强制拒绝
    return None   # TODO: 接入 LLM 语义矛盾检测


# ── Action 实现 ──────────────────────────────────────────────────────────────

def create_memory_node(
    insight: "MemoryInsight",
    ep_id: str,
    aiu_id: str = "",
    memory_root: Optional[Path] = None,
    dry_run: bool = False,
    skip_quality_check: bool = False,
    skip_duplicate_check: bool = False,
) -> ActionResult:
    """
    Action: 创建记忆节点

    前置条件：
      1. 内容质量分 >= QUALITY_THRESHOLD
      2. 与现有记忆不重复（Jaccard < DUPLICATE_THRESHOLD）
      3. 不与现有 ADR 矛盾（目前仅警告）

    副作用：
      - 在对应层级目录创建 MEM-*.md 文件
      - 写入 provenance 元数据
    """
    from mms.memory.memory_functions import (  # type: ignore[import]
        build_provenance, format_memory_content,
    )
    from mms.memory.dream import _layer_to_dir, _get_next_mem_id  # type: ignore[import]

    if memory_root is None:
        memory_root = _MEMORY_ROOT

    warnings: List[str] = []

    # 构建 provenance
    provenance = build_provenance(ep_id, aiu_id)
    new_id = _get_next_mem_id()
    content = format_memory_content(insight, provenance, new_id)

    # ── 前置条件检查 ──────────────────────────────────────────────────────
    if not skip_quality_check:
        err = _check_quality(insight, content)
        if err:
            return ActionResult(success=False, error=f"[质量检查失败] {err}")

    if not skip_duplicate_check:
        err, dup_id = _check_no_duplicate(insight, memory_root)
        if err:
            warnings.append(f"[重复检测] {err}")
            # 重复只警告，不强制拒绝（允许用户在 dry_run 模式下看到警告后决定）
            if not dry_run:
                return ActionResult(success=False, error=err, warnings=warnings)

    adr_warning = _check_not_contradicts_adr(insight, memory_root)
    if adr_warning:
        warnings.append(f"[ADR 矛盾警告] {adr_warning}")

    # ── 执行副作用（写文件）────────────────────────────────────────────────
    if dry_run:
        return ActionResult(
            success=True,
            node_id=new_id,
            file_path="(dry_run)",
            warnings=warnings,
        )

    target_dir = _layer_to_dir(insight.layer)
    target_dir.mkdir(parents=True, exist_ok=True)
    file_path = target_dir / f"{new_id}.md"
    file_path.write_text(content, encoding="utf-8")

    return ActionResult(
        success=True,
        node_id=new_id,
        file_path=str(file_path.relative_to(_ROOT)),
        warnings=warnings,
    )


def update_memory_staleness(
    node_id: str,
    drift_suspected: bool,
    memory_root: Optional[Path] = None,
    reason: str = "file_ast_fingerprint_changed",
) -> ActionResult:
    """
    Action: 更新记忆的新鲜度标记

    触发条件：代码文件的 AST 指纹发生变化时（由 freshness_checker 触发）
    副作用：修改目标记忆文件的 drift_suspected front-matter 字段
    """
    if memory_root is None:
        memory_root = _MEMORY_ROOT

    target_file: Optional[Path] = None
    for md_file in memory_root.glob("**/*.md"):
        if "_system" in str(md_file) or "templates" in str(md_file):
            continue
        content = md_file.read_text(encoding="utf-8")
        if re.search(rf"^id:\s*{re.escape(node_id)}\s*$", content, re.MULTILINE):
            target_file = md_file
            break

    if target_file is None:
        return ActionResult(success=False, error=f"记忆节点 {node_id} 不存在")

    content = target_file.read_text(encoding="utf-8")
    updated = re.sub(
        r"^drift_suspected:\s*.+$",
        f"drift_suspected: {str(drift_suspected).lower()}",
        content,
        flags=re.MULTILINE,
    )

    if updated == content:
        # drift_suspected 字段不存在，在 front-matter 中添加
        updated = re.sub(
            r"^(version:.*$)",
            rf"drift_suspected: {str(drift_suspected).lower()}\n\1",
            content,
            flags=re.MULTILINE,
            count=1,
        )

    target_file.write_text(updated, encoding="utf-8")
    return ActionResult(
        success=True,
        node_id=node_id,
        file_path=str(target_file.relative_to(_ROOT)),
    )
