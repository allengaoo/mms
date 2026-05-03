import pytest
from pathlib import Path
from unittest.mock import patch

from mms.workflow.postcheck import run_postcheck

def _setup_virtual_ep(ep_id: str, project_root: Path):
    sys_dir = project_root / "docs" / "memory" / "_system"
    sys_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建基线快照
    checkpoints_dir = sys_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    import json
    checkpoint_data = {
        "ep_id": ep_id,
        "scope_files": ["src/main.py"],
        "testing_files": ["tests/test_main.py"],
        "arch_violations_baseline": [],
        "arch_violations_count": 0
    }
    (checkpoints_dir / f"precheck-{ep_id}.json").write_text(json.dumps(checkpoint_data), encoding="utf-8")
    
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

@pytest.mark.parametrize("fixture_name", [
    "isolated_spring_boot",
    "isolated_python_project",
    "isolated_go_project"
])
def test_postcheck_pytest_failure_blocks(fixture_name, request):
    """测试多语言项目中，如果测试失败，postcheck 应该返回 FAIL (2)"""
    project_root = request.getfixturevalue(fixture_name)
    ep_id = f"EP-POST-FAIL-{fixture_name.split('_')[1].upper()}"
    _setup_virtual_ep(ep_id, project_root)
    
    with patch("mms.workflow.postcheck._ROOT", project_root), \
         patch("mms.workflow.postcheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.workflow.precheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(False, "1 failed")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(True, 0, [])):
        ret = run_postcheck(ep_id, skip_tests=False)
        
    assert ret == 2, "测试失败时应该返回 2 (FAIL)"

def test_postcheck_arch_check_error(isolated_python_project):
    """测试架构检查执行异常时，postcheck 应该返回 FAIL (2)"""
    project_root = isolated_python_project
    ep_id = "EP-POST-ARCH-ERR"
    _setup_virtual_ep(ep_id, project_root)
    
    with patch("mms.workflow.postcheck._ROOT", project_root), \
         patch("mms.workflow.postcheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.workflow.precheck._CHECKPOINTS_DIR", project_root / "docs" / "memory" / "_system" / "checkpoints"), \
         patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(True, "1 passed")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(False, -1, [{"message": "Exception"}])):
        ret = run_postcheck(ep_id, skip_tests=False)
        
    assert ret == 2, "架构检查异常时应该返回 2 (FAIL)"
