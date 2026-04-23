"""
test_dag_model.py — DagUnit/DagState 数据结构测试

覆盖：序列化/反序列化、next_executable 逻辑、mark_done、批次分组
"""
import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.dag.dag_model import DagUnit, DagState, make_dag_state, LAYER_ORDER


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_simple_dag() -> DagState:
    """构造一个 3 节点 DAG：U1 → U2 → U3"""
    return make_dag_state(
        ep_id="EP-TEST",
        units_data=[
            {"id": "U1", "title": "数据模型", "layer": "L3_domain",
             "files": ["backend/app/domain/foo.py"], "depends_on": [], "order": 1,
             "test_files": ["backend/tests/unit/test_foo.py"]},
            {"id": "U2", "title": "服务方法", "layer": "L4_application",
             "files": ["backend/app/services/control/foo_service.py"], "depends_on": ["U1"],
             "order": 2, "test_files": []},
            {"id": "U3", "title": "API Endpoint", "layer": "L5_interface",
             "files": ["backend/app/api/v1/endpoints/foo.py"], "depends_on": ["U2"],
             "order": 3, "test_files": []},
        ],
    )


# ── DagUnit 测试 ──────────────────────────────────────────────────────────────

class TestDagUnit:
    def test_is_executable_no_deps(self):
        u = DagUnit(id="U1", title="t", layer="L3_domain", files=[], depends_on=[], order=1)
        assert u.is_executable(done_ids=[]) is True

    def test_is_executable_with_deps_not_done(self):
        u = DagUnit(id="U2", title="t", layer="L4_application", files=[], depends_on=["U1"], order=2)
        assert u.is_executable(done_ids=[]) is False

    def test_is_executable_with_deps_done(self):
        u = DagUnit(id="U2", title="t", layer="L4_application", files=[], depends_on=["U1"], order=2)
        assert u.is_executable(done_ids=["U1"]) is True

    def test_is_atomic_for_model_8b(self):
        u = DagUnit(id="U1", title="t", layer="L3_domain", files=[], depends_on=[], order=1,
                    atomicity_score=0.9)
        assert u.is_atomic_for_model("8b") is True

    def test_is_not_atomic_for_8b(self):
        u = DagUnit(id="U1", title="t", layer="L3_domain", files=[], depends_on=[], order=1,
                    atomicity_score=0.5)
        assert u.is_atomic_for_model("8b") is False

    def test_is_atomic_for_capable(self):
        u = DagUnit(id="U1", title="t", layer="L3_domain", files=[], depends_on=[], order=1,
                    atomicity_score=0.0)
        assert u.is_atomic_for_model("capable") is True

    def test_to_dict_from_dict_roundtrip(self):
        u = DagUnit(id="U1", title="test", layer="L4_application",
                    files=["f.py"], depends_on=[], order=2, model_hint="8b",
                    atomicity_score=0.85)
        d = u.to_dict()
        u2 = DagUnit.from_dict(d)
        assert u2.id == u.id
        assert u2.title == u.title
        assert u2.atomicity_score == u.atomicity_score
        assert u2.model_hint == u.model_hint


# ── DagState 测试 ─────────────────────────────────────────────────────────────

class TestDagState:
    def test_progress_all_pending(self):
        dag = _make_simple_dag()
        done, total = dag.progress()
        assert done == 0
        assert total == 3

    def test_executable_units_no_deps_done(self):
        dag = _make_simple_dag()
        executable = dag.executable_units()
        assert len(executable) == 1
        assert executable[0].id == "U1"

    def test_executable_units_after_u1_done(self):
        dag = _make_simple_dag()
        dag.mark_done("U1", commit_hash="abc123")
        executable = dag.executable_units()
        assert len(executable) == 1
        assert executable[0].id == "U2"

    def test_next_executable(self):
        dag = _make_simple_dag()
        unit = dag.next_executable()
        assert unit is not None
        assert unit.id == "U1"

    def test_next_executable_returns_none_when_done(self):
        dag = _make_simple_dag()
        for uid in ["U1", "U2", "U3"]:
            dag.mark_done(uid)
        unit = dag.next_executable()
        assert unit is None

    def test_mark_done_updates_status(self):
        dag = _make_simple_dag()
        dag.mark_done("U1", commit_hash="abc123")
        u1 = dag._get_unit("U1")
        assert u1.status == "done"
        assert u1.git_commit == "abc123"
        assert u1.completed_at is not None

    def test_mark_done_updates_overall(self):
        dag = _make_simple_dag()
        assert dag.overall_status == "pending"
        dag.mark_done("U1")
        assert dag.overall_status == "in_progress"
        dag.mark_done("U2")
        dag.mark_done("U3")
        assert dag.overall_status == "done"

    def test_reset_unit(self):
        dag = _make_simple_dag()
        dag.mark_done("U1", commit_hash="abc123")
        dag.reset_unit("U1")
        u1 = dag._get_unit("U1")
        assert u1.status == "pending"
        assert u1.git_commit is None

    def test_get_batch_groups(self):
        dag = _make_simple_dag()
        batches = dag.get_batch_groups()
        assert len(batches) == 3
        assert batches[0][0].id == "U1"
        assert batches[1][0].id == "U2"
        assert batches[2][0].id == "U3"

    def test_parallel_units_in_same_batch(self):
        dag = make_dag_state(
            ep_id="EP-PAR",
            units_data=[
                {"id": "U1", "title": "模型A", "layer": "L3_domain",
                 "files": [], "depends_on": [], "order": 1},
                {"id": "U2", "title": "模型B", "layer": "L3_domain",
                 "files": [], "depends_on": [], "order": 1},
                {"id": "U3", "title": "服务", "layer": "L4_application",
                 "files": [], "depends_on": ["U1", "U2"], "order": 2},
            ],
        )
        batches = dag.get_batch_groups()
        assert len(batches[0]) == 2  # U1, U2 可并行
        assert len(batches[1]) == 1  # U3 单独

    def test_save_and_load(self, tmp_path, monkeypatch):
        """测试 save/load 序列化往返"""
        import dag_model as dm
        monkeypatch.setattr(dm, "_DAG_DIR", tmp_path)

        dag = _make_simple_dag()
        dag.mark_done("U1", commit_hash="abc123")
        saved_path = dag.save()
        assert saved_path.exists()

        loaded = DagState.load("EP-TEST")
        assert loaded.ep_id == "EP-TEST"
        assert loaded._get_unit("U1").status == "done"
        assert loaded._get_unit("U1").git_commit == "abc123"
        assert loaded._get_unit("U2").status == "pending"

    def test_get_unit_not_found_raises(self):
        dag = _make_simple_dag()
        with pytest.raises(ValueError, match="U99"):
            dag._get_unit("U99")


# ── make_dag_state 测试 ───────────────────────────────────────────────────────

class TestMakeDagState:
    def test_infers_order_from_layer(self):
        dag = make_dag_state(
            ep_id="EP-ORDER",
            units_data=[
                {"id": "U1", "title": "API", "layer": "L5_interface",
                 "files": [], "depends_on": []},
                {"id": "U2", "title": "Model", "layer": "L3_domain",
                 "files": [], "depends_on": []},
            ],
        )
        u1 = dag._get_unit("U1")
        u2 = dag._get_unit("U2")
        # L5_interface(order=3) > L3_domain(order=1)
        assert u1.order > u2.order

    def test_ep_id_normalized(self):
        dag = make_dag_state(ep_id="ep-123", units_data=[])
        assert dag.ep_id == "EP-123"
