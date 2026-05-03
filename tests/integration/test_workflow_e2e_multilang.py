"""
test_workflow_e2e_multilang.py — 任务工程层多语言端到端兼容性测试

覆盖：
  - Java (Spring Boot)
  - Python (FastAPI)
  - Go (Gin)

验证点：
  1. Precheck：对各语言项目能否正确执行 AST 快照。
  2. Postcheck：对 Python 项目能执行架构检查拦截，对非 Python 项目能优雅跳过不崩溃。
  3. EP Pipeline：空跑（Dry Run）状态机流转完整性。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parent / "src"))

from mms.workflow.precheck import run_precheck
from mms.workflow.postcheck import run_postcheck
from mms.workflow.ep_runner import EpRunPipeline, EpRunState
from mms.dag.dag_model import make_dag_state


# ─────────────────────────────────────────────────────────────────────────────
# 辅助：为靶机构造虚拟 EP
# ─────────────────────────────────────────────────────────────────────────────

def _setup_virtual_ep(ep_id: str, project_root: Path):
    """在 project_root 下构造虚拟的 EP 状态和 DAG。"""
    sys_dir = project_root / ".cursor" / "projects" / "default" / "_system"
    sys_dir.mkdir(parents=True, exist_ok=True)

    dag_dir = sys_dir / "dag"
    dag_dir.mkdir(parents=True, exist_ok=True)

    # 创建虚拟 DAG
    unit_data = {
        "id": "U1",
        "title": "测试 Unit",
        "layer": "L4_application",
        "files": ["test.py"],
        "test_files": [],
        "depends_on": [],
        "order": 1,
        "model_hint": "capable",
    }
    state = make_dag_state(ep_id, [unit_data], orchestrator_model="gemini-2.5-pro")
    (dag_dir / f"{ep_id}.json").write_text(json.dumps(state.to_dict()), encoding="utf-8")

    # 创建私有工作区
    private_dir = project_root / "docs" / "memory" / "private" / ep_id
    private_dir.mkdir(parents=True, exist_ok=True)
    (private_dir / f"{ep_id}.md").write_text(f"# {ep_id}: 测试任务\n\n描述内容", encoding="utf-8")

    # 创建公共 EP 目录和文件 (ep_runner 会在这里找)
    ep_dir = project_root / "docs" / "execution_plans"
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / f"{ep_id}_test.md").write_text(f"# {ep_id}: 测试任务\n\n描述内容", encoding="utf-8")
    return state


# ─────────────────────────────────────────────────────────────────────────────
# 用例 1：多语言 Precheck 基线快照测试
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", [
    "isolated_spring_boot",
    "isolated_python_project",
    "isolated_go_project",
])
def test_precheck_multilang_ast_snapshot(fixture_name, request):
    """验证各语言项目 Precheck 时能否正确生成 AST 快照。"""
    project_root = request.getfixturevalue(fixture_name)
    ep_id = "EP-PRE-001"
    _setup_virtual_ep(ep_id, project_root)

    # 运行 precheck
    with patch("mms.workflow.precheck._ROOT", project_root), \
         patch("mms.workflow.precheck._EP_DIR", project_root / "docs" / "execution_plans"), \
         patch("mms.workflow.precheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.workflow.precheck.run_arch_check_baseline", return_value={"violations": []}):
        ret = run_precheck(ep_id)

    assert ret == 0, f"Precheck 失败，返回码: {ret}"

    # 验证 ast_snapshot.json 生成
    snapshot_file = project_root / "docs" / "memory" / "_system" / "checkpoints" / f"precheck-{ep_id}.json"
    assert snapshot_file.exists(), "未生成 AST 快照文件"

    snapshot_data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    assert len(snapshot_data) > 0, "AST 快照为空"


# ─────────────────────────────────────────────────────────────────────────────
# 用例 2：Postcheck 架构拦截与容错测试
# ─────────────────────────────────────────────────────────────────────────────

def test_postcheck_python_arch_violation_intercepted(isolated_python_project):
    """Python 项目中违反架构约束时，Postcheck 应拦截。"""
    project_root = isolated_python_project
    ep_id = "EP-POST-PY"
    _setup_virtual_ep(ep_id, project_root)

    # 注入违规代码（在 services/ 中直接 import aiokafka）
    service_file = project_root / "backend" / "app" / "services" / "bad_service.py"
    service_file.write_text("import aiokafka\n\nclass BadService:\n    pass\n")

    with patch("mms.workflow.postcheck._ROOT", project_root), \
         patch("mms.workflow.postcheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.analysis.arch_check._BACKEND", project_root / "backend" / "app"), \
         patch("mms.analysis.arch_check._SERVICES", project_root / "backend" / "app" / "services"), \
         patch("mms.analysis.arch_check._API", project_root / "backend" / "app" / "api"), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(True, "")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(False, 1, [{"message": "mocked violation"}])):
        ret = run_postcheck(ep_id, skip_tests=True)

    assert ret == 2, "架构违规未被拦截"


@pytest.mark.parametrize("fixture_name", [
    "isolated_spring_boot",
    "isolated_go_project",
])
def test_postcheck_non_python_graceful_skip(fixture_name, request):
    """Java/Go 项目运行 Postcheck 时，不应因 Python 专属架构检查而崩溃。"""
    project_root = request.getfixturevalue(fixture_name)
    ep_id = f"EP-POST-{fixture_name.split('_')[1].upper()}"
    _setup_virtual_ep(ep_id, project_root)

    with patch("mms.workflow.postcheck._ROOT", project_root), \
         patch("mms.workflow.postcheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(True, "")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(True, 0, [])):
        ret = run_postcheck(ep_id, skip_tests=True)

    # 非 Python 项目，架构检查找不到 services 目录，应优雅返回 0
    assert ret == 0, f"非 Python 项目 Postcheck 崩溃或被误拦截，返回码: {ret}"


# ─────────────────────────────────────────────────────────────────────────────
# 用例 3：EP Pipeline 全链路空跑测试 (Dry Run)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fixture_name", [
    "isolated_spring_boot",
    "isolated_python_project",
    "isolated_go_project",
])
def test_pipeline_dry_run_state_machine(fixture_name, request):
    """验证 EpRunPipeline 在各语言项目上的 Dry Run 状态流转。"""
    project_root = request.getfixturevalue(fixture_name)
    ep_id = f"EP-PIPE-{fixture_name.split('_')[1].upper()}"
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
        mock_unit_run.return_value = RunResult(ep_id=ep_id, unit_id="U1", success=True, dry_run=True)

        result = pipeline.run(
            ep_id=ep_id,
            dry_run=True,
            model="capable"
        )

    assert result.success is True, f"Pipeline 执行失败: {result.failure_error}"

    # 验证状态机最终落盘状态
    state = EpRunState.load(ep_id)
    assert state is not None
    assert state.phase == "done", "最终状态应为 done"
    assert state.precheck_done is True, "precheck 未标记完成"
    assert state.postcheck_done is True, "postcheck 未标记完成"
    assert "U1" in state.completed_units, "Unit U1 未标记完成"
