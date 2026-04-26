"""
tests/test_memory_functions.py — memory_functions.py 纯函数单元测试
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mms.memory.memory_functions import (
    MemoryInsight,
    Provenance,
    build_provenance,
    compute_content_fingerprint,
    detect_duplicate_insights,
    extract_insights_from_text,
    format_memory_content,
    score_memory_quality,
)


# ── score_memory_quality ──────────────────────────────────────────────────────

_GOOD_CONTENT = """---
id: MEM-L-001
title: Redis 缓存必须加 tenant_id 前缀
type: lesson
layer: PLATFORM
dimension: D7
tags: ["redis", "cache", "tenant"]
about_concepts: ["cache", "redis"]
access_count: 5
tier: hot
drift_suspected: false
version: 1
---

## WHERE（适用场景）
在多租户系统使用 Redis 缓存时。

## HOW（核心实现）
使用 {tenant_id}:{key} 格式，避免租户间数据泄漏。

## WHEN（触发条件）
每次新增 Redis 写入时检查 key 格式。
"""

_BAD_CONTENT = """---
id: MEM-L-002
title: 要写好代码
type: lesson
---

记得写测试，要写好代码，要注意边界条件。
"""


def test_good_content_score():
    score = score_memory_quality(_GOOD_CONTENT, "MEM-L-001")
    assert score.total_score > 0.6
    assert score.content_score >= 0.9


def test_bad_content_score_is_low():
    score = score_memory_quality(_BAD_CONTENT, "MEM-L-002")
    assert score.total_score < 0.5
    assert len(score.issues) > 0


def test_missing_sections_detected():
    content_no_when = _GOOD_CONTENT.replace("## WHEN", "## THEN")  # 故意破坏
    score = score_memory_quality(content_no_when)
    assert "缺少 WHEN 章节" in score.issues


# ── compute_content_fingerprint ──────────────────────────────────────────────

def test_fingerprint_is_deterministic():
    fp1 = compute_content_fingerprint(_GOOD_CONTENT)
    fp2 = compute_content_fingerprint(_GOOD_CONTENT)
    assert fp1 == fp2


def test_fingerprint_differs_for_different_content():
    fp1 = compute_content_fingerprint(_GOOD_CONTENT)
    fp2 = compute_content_fingerprint(_BAD_CONTENT)
    assert fp1 != fp2


def test_fingerprint_length():
    fp = compute_content_fingerprint(_GOOD_CONTENT)
    assert len(fp) == 16


# ── detect_duplicate_insights ─────────────────────────────────────────────────

def test_duplicate_detected():
    insight = MemoryInsight(
        title="Redis 缓存必须加 tenant_id 前缀",
        memory_type="lesson",
        layer="PLATFORM",
        dimension="D7",
        tags=["redis", "cache", "tenant"],
        description="",
    )
    existing = {"MEM-L-001": _GOOD_CONTENT}
    result = detect_duplicate_insights(insight, {}, existing, similarity_threshold=0.5)
    assert result == "MEM-L-001"


def test_no_duplicate_when_different():
    insight = MemoryInsight(
        title="Spring 事务传播机制",
        memory_type="lesson",
        layer="ADAPTER",
        dimension="D9",
        tags=["spring", "transaction", "propagation"],
        description="",
    )
    existing = {"MEM-L-001": _GOOD_CONTENT}
    result = detect_duplicate_insights(insight, {}, existing, similarity_threshold=0.5)
    assert result is None


# ── build_provenance ──────────────────────────────────────────────────────────

def test_build_provenance_fields():
    prov = build_provenance("EP-001", "aiu_3", "ep_postcheck_passed")
    assert prov.ep_id == "EP-001"
    assert prov.aiu_id == "aiu_3"
    assert prov.trigger_type == "ep_postcheck_passed"
    assert prov.timestamp  # 非空


# ── format_memory_content ─────────────────────────────────────────────────────

def test_format_memory_content_contains_provenance():
    insight = MemoryInsight(
        title="测试记忆",
        memory_type="lesson",
        layer="DOMAIN",
        dimension="D2",
        tags=["test"],
        description="",
        where="在测试时",
        how="这样做",
        when="触发时",
    )
    prov = build_provenance("EP-100")
    content = format_memory_content(insight, prov, "MEM-L-999")
    assert "MEM-L-999" in content
    assert "ep_id: EP-100" in content
    assert "## WHERE" in content
    assert "## HOW" in content
    assert "## WHEN" in content


# ── extract_insights_from_text ────────────────────────────────────────────────

_DRAFT_RESPONSE = """
Some preamble from LLM...

---MEMORY-DRAFT---
title: 分布式锁必须设置超时时间
type: anti-pattern
layer: ADAPTER
dimension: D5
tags: [distributed-lock, redis, timeout]
description: 无超时的分布式锁可能导致死锁

## WHERE（适用场景）
在使用 Redis SETNX 实现分布式锁时。

## HOW（核心实现）
使用 SET key value NX EX {ttl} 原子操作，ttl 建议 30 秒。

## WHEN（触发条件）
当看到 SETNX 命令而没有设置超时时。
---MEMORY-DRAFT---

---MEMORY-DRAFT---
title: 幂等键需要过期时间
type: lesson
layer: APP
dimension: D5
tags: [idempotency, redis, ttl]
description: 幂等键不设过期会导致 Redis 无限增长

## WHERE（适用场景）
API 幂等性实现时。

## HOW（核心实现）
幂等键 TTL = 请求重试窗口时间 × 2，建议 24 小时。

## WHEN（触发条件）
新增接口幂等保护时检查 TTL。
---MEMORY-DRAFT---
"""


def test_extract_multiple_insights():
    insights = extract_insights_from_text(_DRAFT_RESPONSE, "EP-050")
    assert len(insights) == 2
    assert insights[0].title == "分布式锁必须设置超时时间"
    assert insights[0].memory_type == "anti-pattern"
    assert insights[0].layer == "ADAPTER"
    assert "distributed-lock" in insights[0].tags


def test_extract_no_new_knowledge():
    insights = extract_insights_from_text("NO_NEW_KNOWLEDGE", "EP-051")
    assert insights == []


def test_extract_empty_response():
    insights = extract_insights_from_text("", "EP-052")
    assert insights == []
