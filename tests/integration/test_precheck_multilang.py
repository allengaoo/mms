import pytest
from pathlib import Path
from unittest.mock import patch
import json

from mms.workflow.precheck import run_precheck, run_arch_check_baseline

@pytest.fixture
def setup_ep_for_precheck(request):
    project_root = request.getfixturevalue(request.param)
    ep_id = f"EP-PRECHECK-{request.param.split('_')[1].upper()}"
    
    # 创建 EP 文件
    ep_dir = project_root / "docs" / "execution_plans"
    ep_dir.mkdir(parents=True, exist_ok=True)
    
    ep_content = f"""# {ep_id}: 测试任务

## Scope
- `src/main.py`

## Testing Plan
- `tests/test_main.py`
"""
    (ep_dir / f"{ep_id}_test.md").write_text(ep_content, encoding="utf-8")
    
    return project_root, ep_id

@pytest.mark.parametrize("setup_ep_for_precheck", [
    "isolated_spring_boot",
    "isolated_python_project",
    "isolated_go_project"
], indirect=True)
def test_precheck_normal_flow(setup_ep_for_precheck):
    """测试多语言项目下 precheck 的正常流程"""
    project_root, ep_id = setup_ep_for_precheck
    
    with patch("mms.workflow.precheck.run_arch_check_baseline", return_value={"violations": []}):
        ret = run_precheck(ep_id, project_root=project_root)
        
    assert ret == 0, "Precheck 应该返回 0 (PASS)"
    
    # 验证 Checkpoint 生成
    checkpoint_file = project_root / "docs" / "memory" / "_system" / "checkpoints" / f"precheck-{ep_id}.json"
    assert checkpoint_file.exists()
    
    data = json.loads(checkpoint_file.read_text(encoding="utf-8"))
    assert data["ep_id"] == ep_id
    assert "src/main.py" in data["scope_files"]

def test_precheck_missing_ep(isolated_python_project):
    """测试 EP 文件缺失的情况"""
    project_root = isolated_python_project
    ep_id = "EP-MISSING"
    
    ret = run_precheck(ep_id, project_root=project_root)
        
    assert ret == 2, "找不到 EP 文件应该返回 2 (BLOCKER)"

def test_precheck_missing_scope(isolated_python_project):
    """测试 EP 文件中缺少 Scope 的情况"""
    project_root = isolated_python_project
    ep_id = "EP-NO-SCOPE"
    
    ep_dir = project_root / "docs" / "execution_plans"
    ep_dir.mkdir(parents=True, exist_ok=True)
    (ep_dir / f"{ep_id}.md").write_text(f"# {ep_id}\n\n无 Scope 声明", encoding="utf-8")
    
    with patch("mms.workflow.precheck.run_arch_check_baseline", return_value={"violations": []}):
        ret = run_precheck(ep_id, strict=True, project_root=project_root)
        
    assert ret == 1, "缺少 Scope 且 strict=True 应该返回 1 (WARN)"
