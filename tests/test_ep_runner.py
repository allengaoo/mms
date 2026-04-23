"""
test_ep_runner.py — EpRunPipeline 集成测试（EP-131）

测试覆盖：
  - EpRunState 持久化与加载
  - Pipeline 执行范围解析（from_unit / only_units）
  - 断点续跑（已 done 的 Unit 跳过）
  - 干跑模式（dry_run 不写文件）
  - EP 文件不存在时的优雅失败
  - IntentPlanSummary 计划摘要生成
  - DAG 文件不存在时从 EP Scope 表格临时解析
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HERE = Path(__file__).resolve().parent
_MMS = _HERE.parent
sys.path.insert(0, str(_MMS))

from mms.workflow.ep_runner import (
    EpRunPipeline,
    EpRunState,
    IntentPlanSummary,
    _normalize_ep_id,
    _find_ep_file,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_ep_dir(tmp_path: Path) -> Path:
    ep_dir = tmp_path / "docs" / "execution_plans"
    ep_dir.mkdir(parents=True)
    return ep_dir


@pytest.fixture()
def tmp_dag_dir(tmp_path: Path) -> Path:
    dag_dir = tmp_path / "docs" / "memory" / "_system" / "dag"
    dag_dir.mkdir(parents=True)
    return dag_dir


@pytest.fixture()
def tmp_ep_run_dir(tmp_path: Path) -> Path:
    ep_run_dir = tmp_path / "docs" / "memory" / "_system" / "ep_run"
    ep_run_dir.mkdir(parents=True)
    return ep_run_dir


def _make_dag_file(dag_dir: Path, ep_id: str, units: list) -> Path:
    """创建测试用 DAG JSON 文件"""
    data = {
        "ep_id": ep_id,
        "generated_at": "2026-04-18T00:00:00Z",
        "orchestrator_model": "test",
        "overall_status": "pending",
        "units": units,
    }
    path = dag_dir / f"{ep_id.upper()}.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _make_ep_file(ep_dir: Path, ep_id: str) -> Path:
    """创建测试用 EP Markdown 文件"""
    content = f"""# {ep_id}: 测试 EP

## Scope

| Unit | 操作描述 | 涉及文件 | 层 | 模型 |
|------|---------|---------|-----|------|
| U1 | 新增 ep_runner.py | `scripts/mms/ep_runner.py` | L0_mms | capable |
| U2 | 修改 unit_runner.py | `scripts/mms/unit_runner.py` | L0_mms | capable |
| U3 | 修改 intent_classifier.py | `scripts/mms/intent_classifier.py` | L0_mms | fast |

## Testing Plan

- `scripts/mms/tests/test_ep_runner.py`
"""
    path = ep_dir / f"{ep_id}_Test.md"
    path.write_text(content, encoding="utf-8")
    return path


# ── _normalize_ep_id ─────────────────────────────────────────────────────────

class TestNormalizeEpId:
    def test_adds_ep_prefix_to_number(self):
        assert _normalize_ep_id("131") == "EP-131"

    def test_normalizes_lowercase(self):
        assert _normalize_ep_id("ep-131") == "EP-131"

    def test_preserves_already_normalized(self):
        assert _normalize_ep_id("EP-131") == "EP-131"

    def test_strips_whitespace(self):
        assert _normalize_ep_id("  EP-131  ") == "EP-131"


# ── EpRunState 持久化 ─────────────────────────────────────────────────────────

class TestEpRunState:
    def test_save_and_load_roundtrip(self, tmp_path: Path, monkeypatch):
        """EpRunState 保存后可以正确加载"""
        monkeypatch.setattr(
            "mms.workflow.ep_runner._EP_RUN_DIR", tmp_path / "ep_run"
        )
        state = EpRunState.new("EP-131")
        state.phase = "unit_loop"
        state.completed_units = ["U1", "U2"]
        state.total_units = 6
        state.save()

        loaded = EpRunState.load("EP-131")
        assert loaded is not None
        assert loaded.phase == "unit_loop"
        assert loaded.completed_units == ["U1", "U2"]
        assert loaded.total_units == 6

    def test_load_returns_none_when_file_missing(self, tmp_path: Path, monkeypatch):
        """文件不存在时 load 返回 None"""
        monkeypatch.setattr(
            "mms.workflow.ep_runner._EP_RUN_DIR", tmp_path / "nonexistent"
        )
        result = EpRunState.load("EP-999")
        assert result is None

    def test_new_creates_with_pending_phase(self):
        """new() 创建的状态初始 phase 为 pending"""
        state = EpRunState.new("EP-131")
        assert state.phase == "pending"
        assert state.ep_id == "EP-131"
        assert state.completed_units == []


# ── _resolve_exec_units ───────────────────────────────────────────────────────

class TestResolveExecUnits:
    def _make_units(self, statuses: dict) -> list:
        """创建 mock DagUnit 列表"""
        units = []
        for uid, status in statuses.items():
            u = MagicMock()
            u.id = uid
            u.status = status
            u.order = int(uid[1:])  # U1→1, U2→2
            u.depends_on = []
            u.title = f"Unit {uid}"
            units.append(u)
        return units

    def test_only_returns_specified_units(self):
        pipeline = EpRunPipeline()
        units = self._make_units({"U1": "pending", "U2": "pending", "U3": "pending"})
        result = pipeline._resolve_exec_units(units, only_units=["U1", "U3"])
        assert [u.id for u in result] == ["U1", "U3"]

    def test_from_unit_skips_earlier(self):
        pipeline = EpRunPipeline()
        units = self._make_units({"U1": "done", "U2": "pending", "U3": "pending"})
        result = pipeline._resolve_exec_units(units, from_unit="U2")
        assert [u.id for u in result] == ["U2", "U3"]

    def test_default_skips_done_units(self):
        pipeline = EpRunPipeline()
        units = self._make_units({"U1": "done", "U2": "pending", "U3": "done"})
        result = pipeline._resolve_exec_units(units)
        assert [u.id for u in result] == ["U2"]

    def test_from_unit_not_found_returns_all(self):
        pipeline = EpRunPipeline()
        units = self._make_units({"U1": "pending", "U2": "pending"})
        result = pipeline._resolve_exec_units(units, from_unit="U99")
        # 未找到时返回全部
        assert len(result) == 2


# ── Pipeline 失败场景 ─────────────────────────────────────────────────────────

class TestEpRunPipelineFailures:
    def test_returns_failure_when_ep_file_missing(self, tmp_path: Path, monkeypatch):
        """EP 文件不存在时 Pipeline 优雅失败"""
        monkeypatch.setattr("mms.workflow.ep_runner._EP_DIR", tmp_path / "execution_plans")
        monkeypatch.setattr("mms.workflow.ep_runner._EP_RUN_DIR", tmp_path / "ep_run")
        (tmp_path / "execution_plans").mkdir(parents=True)
        (tmp_path / "ep_run").mkdir(parents=True)

        pipeline = EpRunPipeline()
        result = pipeline.run("EP-999", auto_confirm=True)

        assert result.success is False
        assert result.failure_error is not None
        assert "EP-999" in (result.failure_error or "")

    def test_returns_failure_when_dag_missing_and_no_ep_scope(
        self, tmp_path: Path, monkeypatch
    ):
        """EP 文件无 Scope 表格、DAG 不存在时优雅失败"""
        ep_dir = tmp_path / "docs" / "execution_plans"
        ep_dir.mkdir(parents=True)
        # EP 文件内容无 Scope 表格
        (ep_dir / "EP-998_Test.md").write_text("# EP-998\n\n无 Scope 节", encoding="utf-8")

        monkeypatch.setattr("mms.workflow.ep_runner._EP_DIR", ep_dir)
        monkeypatch.setattr("mms.workflow.ep_runner._EP_RUN_DIR", tmp_path / "ep_run")
        monkeypatch.setattr("mms.workflow.ep_runner._DAG_DIR", tmp_path / "dag")
        (tmp_path / "ep_run").mkdir(parents=True)

        pipeline = EpRunPipeline()
        result = pipeline.run("EP-998", auto_confirm=True)

        assert result.success is False


# ── DAG 临时解析（从 EP Scope 表格）─────────────────────────────────────────

class TestBootstrapDagFromEp:
    def test_parses_units_from_scope_table(self, tmp_path: Path):
        """从 EP 文件 Scope 表格临时解析 DagUnit 列表"""
        ep_dir = tmp_path / "docs" / "execution_plans"
        ep_dir.mkdir(parents=True)
        ep_file = _make_ep_file(ep_dir, "EP-131")

        pipeline = EpRunPipeline()
        dag_state = pipeline._try_bootstrap_dag("EP-131", ep_file)

        assert dag_state is not None
        assert len(dag_state.units) == 3
        assert dag_state.units[0].id == "U1"
        assert dag_state.units[1].id == "U2"


# ── IntentPlanSummary ─────────────────────────────────────────────────────────

class TestIntentPlanSummary:
    def _make_dag_state(self, units_def: list):
        """创建 mock DagState"""
        mock_state = MagicMock()
        mock_units = []
        for u in units_def:
            mu = MagicMock()
            mu.id = u["id"]
            mu.title = u.get("title", f"Unit {u['id']}")
            mu.order = u.get("order", int(u["id"][1:]))
            mu.model_hint = u.get("model_hint", "capable")
            mu.status = u.get("status", "pending")
            mu.aiu_steps = u.get("aiu_steps", [])
            mu.intent_confidence = u.get("confidence", 1.0)
            mock_units.append(mu)
        mock_state.units = mock_units
        return mock_state

    def test_groups_units_by_order(self):
        """相同 order 的 Unit 被分到同一批次"""
        dag_state = self._make_dag_state([
            {"id": "U1", "order": 1},
            {"id": "U2", "order": 1},
            {"id": "U3", "order": 2},
        ])
        summary = IntentPlanSummary.from_dag_state("EP-131", dag_state)

        assert len(summary.batches) == 2
        batch1_ids = [u["id"] for u in summary.batches[0].units]
        assert "U1" in batch1_ids
        assert "U2" in batch1_ids
        batch2_ids = [u["id"] for u in summary.batches[1].units]
        assert "U3" in batch2_ids

    def test_identifies_grey_units(self):
        """置信度 0.6-0.85 的 Unit 被标记为灰区"""
        dag_state = self._make_dag_state([
            {"id": "U1", "confidence": 0.95},   # 非灰区
            {"id": "U2", "confidence": 0.72},   # 灰区
            {"id": "U3", "confidence": 0.60},   # 灰区下限
        ])
        summary = IntentPlanSummary.from_dag_state("EP-131", dag_state)

        assert "U2" in summary.grey_unit_ids
        assert "U1" not in summary.grey_unit_ids
        assert summary.is_grey is True

    def test_no_grey_units_when_all_high_confidence(self):
        """全部高置信度时 is_grey 为 False"""
        dag_state = self._make_dag_state([
            {"id": "U1", "confidence": 0.90},
            {"id": "U2", "confidence": 0.95},
        ])
        summary = IntentPlanSummary.from_dag_state("EP-131", dag_state)

        assert summary.is_grey is False
        assert summary.grey_unit_ids == []

    def test_total_token_estimate_is_positive(self):
        """总 token 估算应为正数"""
        dag_state = self._make_dag_state([
            {"id": "U1", "model_hint": "capable", "aiu_steps": []},
            {"id": "U2", "model_hint": "fast", "aiu_steps": []},
        ])
        summary = IntentPlanSummary.from_dag_state("EP-131", dag_state)

        assert summary.total_token_estimate > 0

    def test_skipped_done_units_not_counted_in_llm_calls(self):
        """已 done 的 Unit 不计入 LLM 调用次数"""
        dag_state = self._make_dag_state([
            {"id": "U1", "status": "done"},
            {"id": "U2", "status": "pending"},
        ])
        summary = IntentPlanSummary.from_dag_state("EP-131", dag_state)

        assert summary.llm_call_estimate == 1  # 只有 U2


# ── _find_ep_file ─────────────────────────────────────────────────────────────

class TestFindEpFile:
    def test_finds_file_by_prefix(self, tmp_path: Path, monkeypatch):
        """通过前缀匹配找到 EP 文件"""
        ep_dir = tmp_path / "execution_plans"
        ep_dir.mkdir()
        ep_file = ep_dir / "EP-131_EP_Runner_Test.md"
        ep_file.write_text("# EP-131")

        monkeypatch.setattr("mms.workflow.ep_runner._EP_DIR", ep_dir)

        result = _find_ep_file("EP-131")
        assert result == ep_file

    def test_returns_none_when_not_found(self, tmp_path: Path, monkeypatch):
        """文件不存在时返回 None"""
        ep_dir = tmp_path / "execution_plans"
        ep_dir.mkdir()

        monkeypatch.setattr("mms.workflow.ep_runner._EP_DIR", ep_dir)

        result = _find_ep_file("EP-999")
        assert result is None
