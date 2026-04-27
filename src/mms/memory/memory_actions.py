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
    前置条件：新记忆不与现有架构决策（CC 层）矛盾。

    调用 detect_contradictions() 执行真实矛盾检测（爆炸半径控制 + 关键词级分析）。
    完整版 LLM 语义判断需要通过 detect_contradictions_with_llm() 触发。
    """
    if insight.memory_type not in ("anti-pattern", "decision", "arch_constraint"):
        return None   # 只对架构决策类型做检查

    try:
        conflicts = detect_contradictions(insight, memory_root, use_llm=False)
        if conflicts:
            conflict_ids = ", ".join(c["node_id"] for c in conflicts[:3])
            return f"检测到潜在矛盾（与 {conflict_ids} 冲突），建议人工确认"
    except Exception:  # noqa: BLE001
        pass
    return None


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


# ── 矛盾检测（Graph Contradiction Detection）────────────────────────────────

_CONTRADICTION_KEYWORDS: List[Tuple[str, str]] = [
    # (关键词A, 关键词B)：出现 A 的记忆与出现 B 的记忆可能互斥
    ("grpc", "rest"),
    ("graphql", "rest"),
    ("microservice", "monolith"),
    ("redis", "memcached"),
    ("kafka", "rabbitmq"),
    ("postgresql", "mysql"),
    ("jwt", "session"),
    ("sync", "async"),
    ("eager_loading", "lazy_loading"),
    ("optimistic_lock", "pessimistic_lock"),
]


def detect_contradictions(
    insight: "MemoryInsight",
    memory_root: Optional[Path] = None,
    use_llm: bool = False,
    max_candidates: int = 20,
) -> List[Dict]:
    """
    矛盾检测：检查新记忆是否与现有图谱中的记忆存在逻辑互斥。

    实现策略（两阶段）：
      阶段 1（离线，始终执行）：关键词级矛盾检测
        - 从新记忆内容中提取矛盾关键词对
        - 检查候选节点中是否存在与之互斥的关键词
      阶段 2（在线，use_llm=True 时执行）：LLM 语义矛盾检测
        - 调用 qwen3-32b，注入"架构仲裁者"系统提示词
        - 输出包含冲突节点 ID 的 JSON 数组

    爆炸半径控制：
      - 仅检查与新节点相同 layer_affinity 的现有节点
      - 仅检查 tier=hot/warm 节点
      - 最多检查 max_candidates 个节点

    Args:
        insight: 新的记忆内容（MemoryInsight 对象）
        memory_root: 记忆根目录
        use_llm: 是否使用 LLM 语义检测（默认 False，不消耗 Token）
        max_candidates: 最大候选节点数

    Returns:
        List[Dict]：检测到的冲突列表，每项包含：
          - node_id: 冲突节点 ID
          - reason: 冲突原因
          - confidence: 置信度（0.0-1.0）
    """
    if memory_root is None:
        memory_root = _MEMORY_ROOT

    try:
        from mms.memory.graph_resolver import MemoryGraph  # type: ignore[import]
    except ImportError:
        return []

    graph = MemoryGraph(memory_root=memory_root)

    # 爆炸半径控制：获取候选节点
    layer_affinity = [insight.layer] if insight.layer else []
    candidates = graph.get_candidates_for_contradiction_check(
        new_layer_affinity=layer_affinity,
        max_candidates=max_candidates,
    )
    if not candidates:
        return []

    insight_text = insight.title + " " + getattr(insight, "description", "") + " " + getattr(insight, "content", "")
    new_content_lower = insight_text.lower()
    conflicts: List[Dict] = []

    # ── 阶段 1：关键词级矛盾检测（离线）──────────────────────────────────────
    new_keywords = {kw for pair in _CONTRADICTION_KEYWORDS for kw in pair if kw in new_content_lower}

    for candidate in candidates:
        candidate_content_lower = (candidate.title + " " + " ".join(candidate.about_concepts or [])).lower()

        for kw_a, kw_b in _CONTRADICTION_KEYWORDS:
            new_has_a = kw_a in new_content_lower
            new_has_b = kw_b in new_content_lower
            cand_has_a = kw_a in candidate_content_lower
            cand_has_b = kw_b in candidate_content_lower

            # 新记忆有 A，候选有 B（或反之）→ 潜在矛盾
            if (new_has_a and cand_has_b) or (new_has_b and cand_has_a):
                conflict_word_new = kw_a if new_has_a else kw_b
                conflict_word_old = kw_b if new_has_a else kw_a
                conflicts.append({
                    "node_id": candidate.id,
                    "reason": f"新记忆使用 '{conflict_word_new}'，现有记忆 {candidate.id} 使用 '{conflict_word_old}'（可能互斥）",
                    "confidence": 0.6,
                    "detection_method": "keyword",
                })
                break   # 每个候选节点只报告一次冲突

    # ── 阶段 2：LLM 语义矛盾检测（在线，可选）─────────────────────────────────
    if use_llm and conflicts:
        llm_conflicts = _detect_contradictions_with_llm(
            insight=insight,
            candidates=candidates,
            preliminary_conflicts=conflicts,
        )
        if llm_conflicts:
            # LLM 结果覆盖关键词检测结果（更高精度）
            conflicts = llm_conflicts

    return conflicts


def _detect_contradictions_with_llm(
    insight: "MemoryInsight",
    candidates: List,
    preliminary_conflicts: List[Dict],
) -> List[Dict]:
    """
    使用 qwen3-32b 进行语义级矛盾检测（对抗性 LLM 审查）。

    系统提示词模板（架构仲裁者角色）：
      "你是架构仲裁者。对比【新规则 A】与【旧规则集 B】。
       若发现互斥（如 A 要求使用 gRPC，B 要求使用 REST），
       请输出包含冲突节点 ID 的 JSON 数组及理由。"
    """
    try:
        import json as _json
        from mms.llm.client import call_qwen  # type: ignore[import]

        # 只对初步检测有冲突的候选节点做 LLM 验证
        candidate_ids = {c["node_id"] for c in preliminary_conflicts}
        candidate_texts = []
        for cand in candidates:
            if cand.id in candidate_ids:
                candidate_texts.append(f"[{cand.id}] {cand.title}: {' '.join(cand.about_concepts or [])}")

        system_prompt = (
            "你是架构仲裁者。你的任务是检测架构规则之间的逻辑矛盾。\n"
            "对比【新规则 A】与【旧规则集 B】。若发现互斥（例如：A 要求使用 gRPC，"
            "B 要求使用 REST；或 A 要求无状态，B 要求有状态 Session），\n"
            "请输出 JSON 数组，每项包含 {\"node_id\": \"...\", \"reason\": \"...\", \"confidence\": 0.0-1.0}。\n"
            "若无矛盾，输出空数组 []。只输出 JSON，不输出其他内容。"
        )
        user_prompt = (
            f"新规则 A:\n标题: {insight.title}\n内容: {getattr(insight, 'description', '')[:500]}\n\n"
            f"旧规则集 B:\n" + "\n".join(candidate_texts)
        )

        response = call_qwen(
            system=system_prompt,
            user=user_prompt,
            model="qwen-max",
            temperature=0.1,
        )
        result = _json.loads(response.strip())
        if isinstance(result, list):
            for item in result:
                item["detection_method"] = "llm"
            return result
    except Exception:  # noqa: BLE001
        pass
    return []


def apply_contradiction_resolution(
    new_node_id: str,
    conflicting_node_id: str,
    memory_root: Optional[Path] = None,
) -> ActionResult:
    """
    Action: 矛盾解消 — 在图谱中建立 contradicts 边，并将冲突旧节点降级为 archive。

    操作步骤：
      1. 在 new_node_id ↔ conflicting_node_id 之间建立 contradicts 边
      2. 将 conflicting_node_id 的 tier 降级为 archive（切断入边，hybrid_search 永久忽略）
      3. 记录 archive_reason（为何被降级）

    注意：
      - 此操作不可逆（节点降级为 archive 后需手动恢复）
      - 建议先通过 detect_contradictions() 确认冲突，再调用此函数

    Args:
        new_node_id: 新记忆节点 ID（胜出方，保持 hot/warm）
        conflicting_node_id: 冲突旧节点 ID（降级为 archive）
        memory_root: 记忆根目录

    Returns:
        ActionResult（success=True 表示操作成功）
    """
    if memory_root is None:
        memory_root = _MEMORY_ROOT

    try:
        from mms.memory.graph_resolver import MemoryGraph  # type: ignore[import]
    except ImportError:
        return ActionResult(success=False, error="无法导入 MemoryGraph")

    graph = MemoryGraph(memory_root=memory_root)

    # 步骤 1：建立 contradicts 边
    edge_ok = graph.add_contradicts_edge(new_node_id, conflicting_node_id, memory_root)

    # 步骤 2：将冲突旧节点降级为 archive
    archive_reason = (
        f"矛盾检测：与 {new_node_id} 存在逻辑互斥，已由木兰矛盾检测系统自动降级"
    )
    archive_ok = graph.archive_node(conflicting_node_id, reason=archive_reason, memory_root=memory_root)

    if edge_ok and archive_ok:
        return ActionResult(
            success=True,
            node_id=conflicting_node_id,
            file_path="(updated in-place)",
            warnings=[f"节点 {conflicting_node_id} 已被降级为 archive"],
        )
    else:
        return ActionResult(
            success=False,
            error=(
                f"部分操作失败：edge_ok={edge_ok}, archive_ok={archive_ok}。"
                f"可能是记忆文件不存在或无写入权限。"
            ),
        )
