"""
test_edge_decay.py — 图谱边衰减与剪枝单元测试

覆盖：
  1. reinforce_edges()：正反馈权重增强（含上限控制）
  2. decay_edges()：LFU 衰减算法（含 dry_run 模式）
  3. 剪枝边界：weight < threshold 的边被物理删除
  4. EP 距离计算
  5. weights 文件读写健壮性（文件不存在/损坏时降级）
"""
from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Helper：隔离文件系统 ─────────────────────────────────────────────────────

@pytest.fixture
def isolated_weights(tmp_path, monkeypatch):
    """将 _WEIGHTS_FILE 重定向到 tmp_path，避免污染真实 docs/ 目录。"""
    import mms.memory.entropy_scan as es
    weights_path = tmp_path / "_graph_weights.yaml"
    monkeypatch.setattr(es, "_WEIGHTS_FILE", weights_path)
    return weights_path


# ── _ep_distance 测试 ─────────────────────────────────────────────────────────

class TestEpDistance:
    def test_normal_distance(self):
        from mms.memory.entropy_scan import _ep_distance
        assert _ep_distance("EP-100", "EP-120") == 20

    def test_same_ep(self):
        from mms.memory.entropy_scan import _ep_distance
        assert _ep_distance("EP-50", "EP-50") == 0

    def test_reverse_order(self):
        from mms.memory.entropy_scan import _ep_distance
        assert _ep_distance("EP-130", "EP-110") == 20

    def test_invalid_format(self):
        from mms.memory.entropy_scan import _ep_distance
        assert _ep_distance("invalid", "EP-100") == 0

    def test_no_ep_prefix(self):
        from mms.memory.entropy_scan import _ep_distance
        assert _ep_distance("EP-001", "EP-021") == 20


# ── reinforce_edges 测试 ─────────────────────────────────────────────────────

class TestReinforceEdges:
    def test_first_reinforcement(self, isolated_weights):
        from mms.memory.entropy_scan import reinforce_edges, _load_weights
        reinforce_edges("MN-001", "cites", ["src/foo.py"], "EP-100")
        weights = _load_weights()
        assert "MN-001" in weights
        assert "cites:src/foo.py" in weights["MN-001"]
        meta = weights["MN-001"]["cites:src/foo.py"]
        assert meta["weight"] == pytest.approx(1.2)  # 1.0 + 0.2
        assert meta["last_ep"] == "EP-100"
        assert meta["access_count"] == 1

    def test_multiple_reinforcements(self, isolated_weights):
        from mms.memory.entropy_scan import reinforce_edges, _load_weights
        for i in range(5):
            reinforce_edges("MN-001", "about", ["grpc"], f"EP-{100+i}")
        weights = _load_weights()
        meta = weights["MN-001"]["about:grpc"]
        # 1.0 + 5*0.2 = 2.0（上限）
        assert meta["weight"] == pytest.approx(2.0)
        assert meta["access_count"] == 5

    def test_weight_capped_at_2(self, isolated_weights):
        from mms.memory.entropy_scan import reinforce_edges, _load_weights
        for i in range(20):  # 远超上限
            reinforce_edges("MN-002", "impacts", ["MN-100"], "EP-100")
        weights = _load_weights()
        assert weights["MN-002"]["impacts:MN-100"]["weight"] == pytest.approx(2.0)

    def test_multiple_targets(self, isolated_weights):
        from mms.memory.entropy_scan import reinforce_edges, _load_weights
        reinforce_edges("MN-003", "cites", ["file_a.py", "file_b.py", "file_c.py"], "EP-100")
        weights = _load_weights()
        assert len(weights["MN-003"]) == 3


# ── decay_edges 测试 ─────────────────────────────────────────────────────────

class TestDecayEdges:
    def _make_weights(self, weights_path: Path, data: dict) -> None:
        import yaml
        weights_path.parent.mkdir(parents=True, exist_ok=True)
        weights_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

    def test_decay_old_edge(self, isolated_weights):
        """超过 window_eps 的边应被衰减。"""
        from mms.memory.entropy_scan import decay_edges, _load_weights
        self._make_weights(isolated_weights, {
            "MN-001": {"cites:old_file.py": {"weight": 1.0, "last_ep": "EP-50", "access_count": 1}}
        })
        stats = decay_edges("EP-100", dry_run=False, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["decayed"] == 1
        assert stats["pruned"] == 0
        weights = _load_weights()
        assert weights["MN-001"]["cites:old_file.py"]["weight"] == pytest.approx(0.8)

    def test_no_decay_recent_edge(self, isolated_weights):
        """未超过 window_eps 的边不应被衰减。"""
        from mms.memory.entropy_scan import decay_edges, _load_weights
        self._make_weights(isolated_weights, {
            "MN-001": {"about:grpc": {"weight": 1.5, "last_ep": "EP-95", "access_count": 3}}
        })
        stats = decay_edges("EP-100", dry_run=False, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["decayed"] == 0
        assert stats["skipped"] == 1
        weights = _load_weights()
        assert weights["MN-001"]["about:grpc"]["weight"] == pytest.approx(1.5)  # 不变

    def test_prune_below_threshold(self, isolated_weights):
        """权重低于 prune_threshold 的边应被物理删除。"""
        from mms.memory.entropy_scan import decay_edges, _load_weights
        self._make_weights(isolated_weights, {
            "MN-001": {"cites:stale.py": {"weight": 0.22, "last_ep": "EP-50", "access_count": 0}}
        })
        # 衰减后: 0.22 * 0.8 = 0.176 < 0.2 → 剪枝
        stats = decay_edges("EP-100", dry_run=False, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["pruned"] == 1
        weights = _load_weights()
        # 边被删除后节点也应清理
        assert "MN-001" not in weights or "cites:stale.py" not in weights.get("MN-001", {})

    def test_dry_run_no_modification(self, isolated_weights):
        """dry_run=True 时文件不应被修改。"""
        from mms.memory.entropy_scan import decay_edges, _load_weights
        self._make_weights(isolated_weights, {
            "MN-001": {"cites:old.py": {"weight": 1.0, "last_ep": "EP-50", "access_count": 1}}
        })
        original_mtime = isolated_weights.stat().st_mtime
        stats = decay_edges("EP-100", dry_run=True, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["decayed"] == 1
        # 文件修改时间不变（dry_run 不写入）
        assert isolated_weights.stat().st_mtime == original_mtime

    def test_empty_weights_no_crash(self, isolated_weights):
        """weights 文件不存在时不应崩溃。"""
        from mms.memory.entropy_scan import decay_edges
        stats = decay_edges("EP-100", dry_run=False, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["total_edges"] == 0
        assert stats["decayed"] == 0

    def test_mixed_edges(self, isolated_weights):
        """新旧边并存时，只衰减旧边。"""
        from mms.memory.entropy_scan import decay_edges
        self._make_weights(isolated_weights, {
            "MN-001": {
                "cites:old.py": {"weight": 1.0, "last_ep": "EP-50", "access_count": 0},  # 旧，距离 50
                "about:grpc":   {"weight": 1.5, "last_ep": "EP-98", "access_count": 5},  # 新，距离 2
            }
        })
        stats = decay_edges("EP-100", dry_run=False, decay_factor=0.8, prune_threshold=0.2, decay_window=20)
        assert stats["decayed"] == 1
        assert stats["skipped"] == 1
        assert stats["total_edges"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Phase 6 TDD：mulan gc 触发衰减 + 物理剪枝验证
# ─────────────────────────────────────────────────────────────────────────────

class TestGcTriggeredDecay:
    """
    验证：经过 gc 触发的衰减后，低权重边被物理删除（从 weights 文件中移除）。
    """

    @staticmethod
    def _make_weights(path: Path, data: dict) -> None:
        import yaml
        path.write_text(yaml.dump(data, allow_unicode=True))

    @staticmethod
    def _load_weights(path: Path) -> dict:
        import yaml
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text()) or {}

    def test_gc_physically_removes_pruned_edges(self, isolated_weights):
        """
        gc 运行后，weight < prune_threshold 的边必须从 weights 文件中物理删除，
        不只是标记为过期。
        """
        from mms.memory.entropy_scan import decay_edges
        self._make_weights(isolated_weights, {
            "MN-GC-001": {
                "cites:stale_file.py": {"weight": 0.1, "last_ep": "EP-10", "access_count": 0},
                "about:concept_alive": {"weight": 1.5, "last_ep": "EP-98", "access_count": 5},
            }
        })
        stats = decay_edges(
            "EP-100",
            dry_run=False,
            decay_factor=0.5,
            prune_threshold=0.2,  # 0.1 < 0.2，应被剪枝
            decay_window=20,
        )
        weights_after = self._load_weights(isolated_weights)
        node_edges = weights_after.get("MN-GC-001", {})
        assert "cites:stale_file.py" not in node_edges, (
            "低权重边应被物理删除，不应保留在 weights 文件中"
        )
        assert "about:concept_alive" in node_edges, (
            "高权重边不应被删除"
        )
        assert stats["pruned"] >= 1

    def test_gc_dry_run_does_not_physically_delete(self, isolated_weights):
        """dry_run 模式下，pruned 边不写入磁盘（文件保持原始状态）。"""
        from mms.memory.entropy_scan import decay_edges
        self._make_weights(isolated_weights, {
            "MN-GC-002": {
                "cites:old.py": {"weight": 0.05, "last_ep": "EP-10", "access_count": 0},
            }
        })
        content_before = isolated_weights.read_text()
        stats = decay_edges(
            "EP-100",
            dry_run=True,
            prune_threshold=0.1,
            decay_window=20,
        )
        content_after = isolated_weights.read_text()
        assert content_before == content_after, (
            "dry_run 模式不应修改磁盘上的 weights 文件"
        )

    def test_gc_all_edges_pruned_removes_node(self, isolated_weights):
        """节点所有边都被剪枝后，节点本身也应从 weights 文件中删除。"""
        from mms.memory.entropy_scan import decay_edges
        self._make_weights(isolated_weights, {
            "MN-EMPTY-001": {
                "cites:dead_ref.py": {"weight": 0.01, "last_ep": "EP-01", "access_count": 0},
            }
        })
        decay_edges(
            "EP-100",
            dry_run=False,
            prune_threshold=0.05,
            decay_window=5,
        )
        weights_after = self._load_weights(isolated_weights)
        assert "MN-EMPTY-001" not in weights_after, (
            "所有边被剪枝后，空节点应从 weights 文件中删除"
        )

    def test_gc_stats_total_edges_is_positive(self, isolated_weights):
        """stats 中 total_edges 应等于处理的边总数（大于 0）。"""
        from mms.memory.entropy_scan import decay_edges
        self._make_weights(isolated_weights, {
            "MN-STATS-001": {
                "e1": {"weight": 0.05, "last_ep": "EP-10", "access_count": 0},
                "e2": {"weight": 0.5,  "last_ep": "EP-10", "access_count": 0},
                "e3": {"weight": 1.5,  "last_ep": "EP-98", "access_count": 5},
            }
        })
        stats = decay_edges(
            "EP-100",
            dry_run=False,
            decay_factor=0.8,
            prune_threshold=0.1,
            decay_window=20,
        )
        assert stats.get("total_edges", 0) == 3, "3 条边应全部被统计"
        assert stats.get("skipped", 0) >= 1, "至少 1 条新边被跳过"
