"""
tests/test_aiu_expansion.py — AIU 扩展（G/H/I 族）单元测试
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mms.dag.aiu_types import (
    AIUType,
    AIU_FAMILY,
    AIU_LAYER_AFFINITY,
    AIU_LAYER_MAP,
    AIU_EXEC_ORDER,
    AIU_TO_FAMILY,
)


class TestAIUFamilyExpansion:

    def test_total_aiu_families(self):
        """应该有 9 大族"""
        assert len(AIU_FAMILY) == 9

    def test_g_family_exists(self):
        """G 族（分布式协调）应该存在"""
        assert "G_distributed" in AIU_FAMILY
        assert AIUType.SAGA_ADD_STEP in AIU_FAMILY["G_distributed"]
        assert AIUType.SAGA_ADD_COMPENSATOR in AIU_FAMILY["G_distributed"]
        assert AIUType.OUTBOX_ADD_MESSAGE in AIU_FAMILY["G_distributed"]
        assert AIUType.IDEMPOTENCY_ADD_KEY in AIU_FAMILY["G_distributed"]

    def test_h_family_exists(self):
        """H 族（治理与合规）应该存在"""
        assert "H_governance" in AIU_FAMILY
        assert AIUType.RBAC_ADD_PERMISSION in AIU_FAMILY["H_governance"]
        assert AIUType.RBAC_ADD_ROLE in AIU_FAMILY["H_governance"]
        assert AIUType.AUDIT_ADD_TRAIL in AIU_FAMILY["H_governance"]
        assert AIUType.TENANT_ADD_ISOLATION in AIU_FAMILY["H_governance"]

    def test_i_family_exists(self):
        """I 族（可观测性）应该存在"""
        assert "I_observability" in AIU_FAMILY
        assert AIUType.METRIC_ADD_COUNTER in AIU_FAMILY["I_observability"]
        assert AIUType.TRACE_ADD_SPAN in AIU_FAMILY["I_observability"]
        assert AIUType.ALERT_ADD_RULE in AIU_FAMILY["I_observability"]

    def test_all_aiu_types_in_family(self):
        """所有 AIUType 都应该在某个族中"""
        all_in_families: set = set()
        for aius in AIU_FAMILY.values():
            all_in_families.update(aius)
        for aiu_type in AIUType:
            assert aiu_type in all_in_families, f"{aiu_type} 不在任何族中"

    def test_aiu_to_family_reverse_index(self):
        """反向索引应该覆盖所有 AIU 类型"""
        for aiu_type in AIUType:
            assert aiu_type in AIU_TO_FAMILY, f"{aiu_type} 不在 AIU_TO_FAMILY 中"

    def test_all_aiu_have_layer_map(self):
        """所有 AIU 类型都应该有主层级映射"""
        for aiu_type in AIUType:
            assert aiu_type in AIU_LAYER_MAP, f"{aiu_type} 不在 AIU_LAYER_MAP 中"

    def test_all_aiu_have_exec_order(self):
        """所有 AIU 类型都应该有执行顺序"""
        for aiu_type in AIUType:
            assert aiu_type in AIU_EXEC_ORDER, f"{aiu_type} 不在 AIU_EXEC_ORDER 中"

    def test_all_aiu_have_layer_affinity(self):
        """所有 AIU 类型都应该有层级亲和性"""
        for aiu_type in AIUType:
            assert aiu_type in AIU_LAYER_AFFINITY, f"{aiu_type} 不在 AIU_LAYER_AFFINITY 中"

    def test_g_family_layer_affinity(self):
        """G 族应该亲和 APP/DOMAIN 层"""
        for aiu in AIU_FAMILY["G_distributed"]:
            affinity = AIU_LAYER_AFFINITY[aiu]
            assert any(l in ["APP", "DOMAIN"] for l in affinity), \
                f"{aiu} 应亲和 APP 或 DOMAIN 层"

    def test_h_family_layer_affinity(self):
        """H 族应该亲和 PLATFORM/CC 层"""
        for aiu in AIU_FAMILY["H_governance"]:
            affinity = AIU_LAYER_AFFINITY[aiu]
            assert any(l in ["PLATFORM", "CC", "DOMAIN"] for l in affinity), \
                f"{aiu} 应亲和 PLATFORM/CC/DOMAIN 层"

    def test_i_family_layer_map(self):
        """I 族的主层级应该是 PLATFORM"""
        for aiu in AIU_FAMILY["I_observability"]:
            assert AIU_LAYER_MAP[aiu] == "PLATFORM", \
                f"{aiu} 主层级应为 PLATFORM"

    def test_layer_names_are_universal(self):
        """所有 AIU_LAYER_MAP 中的层级名应使用通用 5 层名（不含 L1-L5）"""
        valid_layers = {"CC", "PLATFORM", "DOMAIN", "APP", "ADAPTER", "testing", "docs"}
        for aiu_type, layer in AIU_LAYER_MAP.items():
            assert layer in valid_layers, \
                f"{aiu_type} 使用了旧层级名: {layer}"
