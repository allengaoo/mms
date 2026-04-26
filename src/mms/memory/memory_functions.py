"""
memory_functions.py — 记忆系统纯函数层（无副作用）

设计原则（Palantir Function 对标）：
  - 所有函数必须是纯函数：相同输入 → 相同输出，无外部状态变更
  - 不直接写文件、不调用 LLM（LLM 调用封装在 memory_actions.py 中）
  - 可以独立单元测试（不需要 mock 文件系统）

主要职责：
  1. 记忆内容质量评估（重复检测、质量分数计算）
  2. 图边分析（in-degree 计算、关联强度评分）
  3. 内容摘要提取（不需要 LLM 的纯文本处理）
  4. Provenance 元数据构建

与 memory_actions.py 的分工：
  - functions（此文件）: 计算 → 返回数据结构
  - actions（memory_actions.py）: 验证前置条件 → 调用 functions → 写入文件 + 副作用
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class MemoryInsight:
    """从 EP 执行结果提取的记忆知识点（纯数据，无副作用）"""
    title: str
    memory_type: str          # lesson | pattern | anti-pattern | decision
    layer: str                # CC | PLATFORM | DOMAIN | APP | ADAPTER
    dimension: str            # D1-D10
    tags: List[str]
    description: str
    where: str = ""
    how: str = ""
    when: str = ""
    source_ep_id: str = ""    # 来源 EP 编号
    source_aiu_id: str = ""   # 来源 AIU 步骤 ID（可选）
    confidence: float = 1.0   # 提取置信度（0.0-1.0）


@dataclass
class Provenance:
    """记忆来源追踪（Palantir Action Provenance 对标）"""
    ep_id: str
    aiu_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trigger_type: str = "ep_postcheck_passed"   # ep_postcheck_passed | file_change | manual
    created_by: str = "mulan_dream"


@dataclass
class MemoryQualityScore:
    """记忆质量评分（纯计算结果）"""
    node_id: str
    content_score: float       # 内容质量（0-1）：WHERE/HOW/WHEN 完整度
    uniqueness_score: float    # 唯一性（0-1）：与现有记忆的区分度
    structural_score: float    # 结构分（0-1）：front-matter 字段完整度
    total_score: float         # 综合分
    issues: List[str] = field(default_factory=list)   # 质量问题列表


# ── 内容质量评估函数 ─────────────────────────────────────────────────────────

def score_memory_quality(content: str, node_id: str = "") -> MemoryQualityScore:
    """
    评估单条记忆的内容质量（纯函数，无副作用）。

    评分维度：
      content_score:   WHERE/HOW/WHEN 三个章节的完整程度
      structural_score: front-matter 字段完整性（id/title/type/layer/tags/about_concepts）
    """
    issues: List[str] = []

    # ── 内容完整度 ──────────────────────────────────────────────────────────
    has_where = bool(re.search(r"##\s*WHERE", content, re.IGNORECASE))
    has_how = bool(re.search(r"##\s*HOW", content, re.IGNORECASE))
    has_when = bool(re.search(r"##\s*WHEN", content, re.IGNORECASE))

    if not has_where:
        issues.append("缺少 WHERE 章节")
    if not has_how:
        issues.append("缺少 HOW 章节")
    if not has_when:
        issues.append("缺少 WHEN 章节")

    content_score = (int(has_where) + int(has_how) + int(has_when)) / 3.0

    # ── 章节内容长度（过短视为无效）──────────────────────────────────────────
    for section in ["WHERE", "HOW", "WHEN"]:
        m = re.search(rf"##\s*{section}[^\n]*\n(.+?)(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE)
        if m and len(m.group(1).strip()) < 20:
            issues.append(f"{section} 内容过短（< 20 字符）")
            content_score -= 0.1

    # ── Front-matter 完整度 ─────────────────────────────────────────────────
    required_fields = ["id:", "title:", "type:", "layer:", "tags:", "about_concepts:"]
    fm_match = re.search(r"^---\n(.+?)\n---", content, re.DOTALL)
    fm_text = fm_match.group(1) if fm_match else ""
    present = sum(1 for f in required_fields if f in fm_text)
    structural_score = present / len(required_fields)

    if structural_score < 1.0:
        missing = [f for f in required_fields if f not in fm_text]
        issues.append(f"Front-matter 缺少字段: {', '.join(missing)}")

    # ── 无意义内容检测 ──────────────────────────────────────────────────────
    boilerplate_patterns = [
        r"要写测试",
        r"注意边界条件",
        r"代码要整洁",
        r"遵守规范",
    ]
    for pat in boilerplate_patterns:
        if re.search(pat, content):
            issues.append(f"包含通用废话内容（匹配：{pat}）")
            content_score -= 0.2

    content_score = max(0.0, min(1.0, content_score))
    total_score = (content_score * 0.6 + structural_score * 0.4)

    return MemoryQualityScore(
        node_id=node_id,
        content_score=round(content_score, 3),
        uniqueness_score=1.0,   # 唯一性需要与现有库对比，在 action 层计算
        structural_score=round(structural_score, 3),
        total_score=round(total_score, 3),
        issues=issues,
    )


def compute_content_fingerprint(content: str) -> str:
    """计算记忆内容的语义指纹（去除格式噪音，只对核心内容哈希）"""
    # 去除 front-matter
    stripped = re.sub(r"^---\n.+?\n---\n", "", content, flags=re.DOTALL).strip()
    # 去除 Markdown 标题符号，保留文字
    stripped = re.sub(r"^#+\s*", "", stripped, flags=re.MULTILINE)
    # 规范化空白
    stripped = " ".join(stripped.split())
    return hashlib.sha256(stripped.encode()).hexdigest()[:16]


def detect_duplicate_insights(
    new_insight: MemoryInsight,
    existing_fingerprints: Dict[str, str],   # {node_id: fingerprint}
    existing_contents: Dict[str, str],        # {node_id: full_content}
    similarity_threshold: float = 0.8,
) -> Optional[str]:
    """
    检测新记忆是否与现有记忆高度相似（纯函数，Jaccard 相似度）。
    返回最相似的现有记忆 ID，如果没有重复则返回 None。
    """
    new_tags = set(new_insight.tags)
    new_title_words = set(re.findall(r'\w+', new_insight.title.lower()))

    for node_id, content in existing_contents.items():
        # 提取现有记忆的标签
        tags_m = re.search(r'^tags:\s*\[(.+)\]', content, re.MULTILINE)
        if not tags_m:
            continue
        existing_tags = set(t.strip().strip("\"'") for t in tags_m.group(1).split(','))

        # Jaccard 相似度
        if new_tags and existing_tags:
            intersection = len(new_tags & existing_tags)
            union = len(new_tags | existing_tags)
            jaccard = intersection / union if union > 0 else 0.0

            # 标题词重叠检测
            title_m = re.search(r'^title:\s*(.+)$', content, re.MULTILINE)
            existing_title_words = set(re.findall(r'\w+', title_m.group(1).lower())) if title_m else set()
            title_overlap = len(new_title_words & existing_title_words) / max(len(new_title_words | existing_title_words), 1)

            combined_score = jaccard * 0.6 + title_overlap * 0.4
            if combined_score >= similarity_threshold:
                return node_id

    return None


def build_provenance(
    ep_id: str,
    aiu_id: str = "",
    trigger_type: str = "ep_postcheck_passed",
) -> Provenance:
    """构建记忆来源追踪元数据（纯函数）"""
    return Provenance(
        ep_id=ep_id,
        aiu_id=aiu_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        trigger_type=trigger_type,
    )


def format_memory_content(insight: MemoryInsight, provenance: Provenance, new_id: str) -> str:
    """
    将 MemoryInsight 格式化为标准 Markdown 记忆文件内容（纯函数）。
    返回完整的文件内容字符串，不写文件。
    """
    tags_str = ", ".join(f'"{t}"' for t in insight.tags)
    created_date = datetime.now().strftime("%Y-%m-%d")

    content = f"""---
id: {new_id}
title: {insight.title}
type: {insight.memory_type}
layer: {insight.layer}
dimension: {insight.dimension}
tags: [{tags_str}]
about_concepts: [{tags_str}]
access_count: 0
last_accessed: "{created_date}"
tier: warm
drift_suspected: false
version: 1
provenance:
  ep_id: {provenance.ep_id}
  aiu_id: {provenance.aiu_id or 'null'}
  timestamp: {provenance.timestamp}
  trigger_type: {provenance.trigger_type}
---

## WHERE（适用场景）
{insight.where or '（待补充）'}

## HOW（核心实现/注意事项）
{insight.how or '（待补充）'}

## WHEN（触发条件/危险信号）
{insight.when or '（待补充）'}
"""
    return content


def extract_insights_from_text(raw_text: str, ep_id: str = "") -> List[MemoryInsight]:
    """
    从 LLM 返回的草稿文本中提取 MemoryInsight 列表（纯函数）。
    这是 dream.py::parse_dream_response 的纯函数版本。
    """
    if not raw_text or "NO_NEW_KNOWLEDGE" in raw_text:
        return []

    insights: List[MemoryInsight] = []
    blocks = re.split(r"---MEMORY-DRAFT---", raw_text)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        def _field(pat: str) -> str:
            m = re.search(pat, block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        title = _field(r"^title:\s*(.+)$")
        if not title:
            continue

        tags_raw = _field(r"^tags:\s*\[(.+)\]")
        tags = [t.strip().strip("\"'") for t in tags_raw.split(",") if t.strip()]

        where_m = re.search(r"##\s*WHERE[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)
        how_m = re.search(r"##\s*HOW[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)
        when_m = re.search(r"##\s*WHEN[^\n]*\n(.*?)(?=\n##|\Z)", block, re.DOTALL)

        insights.append(MemoryInsight(
            title=title,
            memory_type=_field(r"^type:\s*(.+)$") or "lesson",
            layer=_field(r"^layer:\s*(.+)$") or "CC",
            dimension=_field(r"^dimension:\s*(.+)$") or "D2",
            tags=tags,
            description=_field(r"^description:\s*(.+)$"),
            where=(where_m.group(1).strip() if where_m else ""),
            how=(how_m.group(1).strip() if how_m else ""),
            when=(when_m.group(1).strip() if when_m else ""),
            source_ep_id=ep_id,
        ))

    return insights
