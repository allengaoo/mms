import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import json

from mms.workflow.ep_runner import EpRunPipeline, EpRunState
from mms.dag.dag_model import make_dag_state

def _setup_virtual_ep(ep_id: str, project_root: Path):
    sys_dir = project_root / "docs" / "memory" / "_system"
    sys_dir.mkdir(parents=True, exist_ok=True)

    dag_dir = sys_dir / "dag"
    dag_dir.mkdir(parents=True, exist_ok=True)

    # 创建虚拟 DAG，包含两个 Unit
    unit_data_1 = {
        "id": "U1",
        "title": "测试 Unit 1",
        "layer": "L4_service",
        "files": ["service.py"],
        "test_files": [],
        "depends_on": [],
        "order": 1,
        "model_hint": "capable",
    }
    unit_data_2 = {
        "id": "U2",
        "title": "测试 Unit 2",
        "layer": "L4_application",
        "files": ["api.py"],
        "test_files": [],
        "depends_on": ["U1"],
        "order": 2,
        "model_hint": "fast",
    }
    state = make_dag_state(ep_id, [unit_data_1, unit_data_2], orchestrator_model="gemini-2.5-pro")
    (dag_dir / f"{ep_id}.json").write_text(json.dumps(state.to_dict()), encoding="utf-8")

    ep_dir = project_root / "docs" / "execution_plans"
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / f"{ep_id}_test.md").write_text(f"# {ep_id}: 测试任务\n\n描述内容", encoding="utf-8")
    
    return state

@pytest.mark.parametrize("fixture_name", [
    "isolated_spring_boot",
    "isolated_python_project",
    "isolated_go_project"
])
def test_ep_runner_track_a_pipeline(fixture_name, request):
    """测试多语言项目下 Track A (Pipeline) 的执行流转"""
    project_root = request.getfixturevalue(fixture_name)
    ep_id = f"EP-RUN-A-{fixture_name.split('_')[1].upper()}"
    state = _setup_virtual_ep(ep_id, project_root)
    
    pipeline = EpRunPipeline()
    
    with patch("mms.workflow.ep_runner._ROOT", project_root), \
         patch("mms.workflow.ep_runner._EP_DIR", project_root / "docs" / "execution_plans"), \
         patch("mms.workflow.ep_runner._DAG_DIR", project_root / "docs" / "memory" / "_system" / "dag"), \
         patch("mms.dag.dag_model._DAG_DIR", project_root / "docs" / "memory" / "_system" / "dag"), \
         patch("mms.workflow.ep_runner._load_dag_state", return_value=state), \
         patch("mms.workflow.ep_runner._run_subprocess", return_value=(True, "mocked")), \
         patch("mms.execution.unit_runner.UnitRunner.run") as mock_unit_run:
        
        # Mock UnitRunner 让其直接成功
        from mms.execution.unit_runner import RunResult
        mock_unit_run.side_effect = [
            RunResult(ep_id=ep_id, unit_id="U1", success=True, dry_run=True),
            RunResult(ep_id=ep_id, unit_id="U2", success=True, dry_run=True)
        ]
        
        # 使用 qwen3-coder-plus 触发 Track A
        result = pipeline.run(ep_id=ep_id, dry_run=True, model="qwen3-coder-plus")
        
    assert result.success is True
    assert result.units_done == 2
    
    final_state = EpRunState.load(ep_id)
    assert final_state.phase == "done"
    assert "U1" in final_state.completed_units
    assert "U2" in final_state.completed_units

def test_ep_runner_track_b_autonomous(isolated_python_project):
    """测试 Track B (Autonomous) 的路由"""
    project_root = isolated_python_project
    ep_id = "EP-RUN-B-PY"
    _setup_virtual_ep(ep_id, project_root)
    
    pipeline = EpRunPipeline()
    
    with patch("mms.workflow.ep_runner._ROOT", project_root), \
         patch("mms.workflow.ep_runner._EP_DIR", project_root / "docs" / "execution_plans"), \
         patch("mms.workflow.ep_runner._resolve_execution_track", return_value="autonomous"), \
         patch("mms.workflow.ep_runner.EpRunPipeline._run_autonomous") as mock_auto_run:
        
        from mms.workflow.ep_runner import EpRunResult
        mock_auto_run.return_value = EpRunResult(ep_id=ep_id, success=True, dry_run=True)
        
        # 使用 claude 触发 Track B
        result = pipeline.run(ep_id=ep_id, dry_run=True, model="claude-opus-4")
        
    assert result.success is True
    mock_auto_run.assert_called_once()

def test_ep_runner_resume_from_unit(isolated_python_project):
    """测试从指定 Unit 断点续跑"""
    project_root = isolated_python_project
    ep_id = "EP-RUN-RESUME"
    state = _setup_virtual_ep(ep_id, project_root)
    
    pipeline = EpRunPipeline()
    
    with patch("mms.workflow.ep_runner._ROOT", project_root), \
         patch("mms.workflow.ep_runner._EP_DIR", project_root / "docs" / "execution_plans"), \
         patch("mms.workflow.ep_runner._DAG_DIR", project_root / "docs" / "memory" / "_system" / "dag"), \
         patch("mms.dag.dag_model._DAG_DIR", project_root / "docs" / "memory" / "_system" / "dag"), \
         patch("mms.workflow.ep_runner._load_dag_state", return_value=state), \
         patch("mms.workflow.ep_runner._run_subprocess", return_value=(True, "mocked")), \
         patch("mms.execution.unit_runner.UnitRunner.run") as mock_unit_run:
        
        from mms.execution.unit_runner import RunResult
        mock_unit_run.return_value = RunResult(ep_id=ep_id, unit_id="U2", success=True, dry_run=True)
        
        # 指定从 U2 开始跑
        result = pipeline.run(ep_id=ep_id, dry_run=True, model="qwen3-coder-plus", from_unit="U2")
        
    assert result.success is True
    assert result.units_done == 1  # 只跑了 U2
    assert result.units_skipped == 0  # U1 被过滤掉，不计入 skipped
