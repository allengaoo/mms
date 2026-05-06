"""
tests/test_eviction_score.py — 三维度淘汰评分单元测试
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mms.memory.entropy_scan import compute_eviction_score


class TestEvictionScore:

    def test_cold_unused_adapter_node_high_score(self):
        """长期未访问 + 零频率 + 图边少 + ADAPTER 层 → 高淘汰分"""
        score = compute_eviction_score(
            node_id="MEM-L-001",
            access_count=0,
            days_since_access=180,
            layer="ADAPTER",
            graph_importance=0.0,
        )
        assert score > 0.7, f"Expected high score, got {score}"

    def test_cc_layer_protected(self):
        """CC 层节点受保护，即使低频也不应被淘汰"""
        score_cc = compute_eviction_score(
            node_id="AD-001",
            access_count=1,
            days_since_access=90,
            layer="CC",
            graph_importance=0.0,
        )
        score_adapter = compute_eviction_score(
            node_id="MEM-L-002",
            access_count=1,
            days_since_access=90,
            layer="ADAPTER",
            graph_importance=0.0,
        )
        assert score_cc < score_adapter, "CC 层保护机制失效"

    def test_domain_layer_higher_protection_than_adapter(self):
        """DOMAIN 层保护高于 ADAPTER 层"""
        base_params = dict(access_count=2, days_since_access=60, graph_importance=0.1)
        score_domain = compute_eviction_score("n1", layer="DOMAIN", **base_params)
        score_adapter = compute_eviction_score("n2", layer="ADAPTER", **base_params)
        assert score_domain < score_adapter

    def test_high_graph_importance_reduces_score(self):
        """被大量引用的节点（高 in-degree）应获得更低淘汰分"""
        score_low_importance = compute_eviction_score(
            node_id="n1",
            access_count=3,
            days_since_access=30,
            layer="APP",
            graph_importance=0.0,
        )
        score_high_importance = compute_eviction_score(
            node_id="n2",
            access_count=3,
            days_since_access=30,
            layer="APP",
            graph_importance=1.0,
        )
        assert score_high_importance < score_low_importance

    def test_drift_suspected_increases_score(self):
        """内容疑似过期的节点淘汰分应更高"""
        score_fresh = compute_eviction_score("n1", 5, 10, "APP", drift_suspected=False)
        score_stale = compute_eviction_score("n2", 5, 10, "APP", drift_suspected=True)
        assert score_stale > score_fresh

    def test_hot_frequently_accessed_node_low_score(self):
        """高频访问且刚访问过的节点应该有低淘汰分"""
        score = compute_eviction_score(
            node_id="MEM-L-HOT",
            access_count=50,
            days_since_access=1,
            layer="DOMAIN",
            max_access_in_corpus=50,
            graph_importance=0.8,
        )
        assert score < 0.3, f"Hot node score too high: {score}"

    def test_score_always_non_negative(self):
        """评分不应为负数"""
        for layer in ["CC", "PLATFORM", "DOMAIN", "APP", "ADAPTER"]:
            score = compute_eviction_score(
                node_id=f"n_{layer}",
                access_count=100,
                days_since_access=0,
                layer=layer,
                graph_importance=1.0,
            )
            assert score >= 0.0, f"Negative score for layer {layer}: {score}"

    def test_custom_weights(self):
        """自定义权重应该影响评分结果"""
        score_time_heavy = compute_eviction_score(
            "n1", 5, 60, "APP", alpha=0.9, beta=0.05, gamma=0.05
        )
        score_freq_heavy = compute_eviction_score(
            "n2", 5, 60, "APP", alpha=0.05, beta=0.9, gamma=0.05
        )
        # 这两个应该不同（权重不同）
        assert abs(score_time_heavy - score_freq_heavy) > 0.01
