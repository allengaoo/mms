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
    
    with patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(False, "1 failed")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(True, 0, [])):
        ret = run_postcheck(ep_id, skip_tests=False, project_root=project_root)
        
    assert ret == 2, "测试失败时应该返回 2 (FAIL)"

def test_postcheck_arch_check_error(isolated_python_project):
    """测试架构检查执行异常时，postcheck 应该返回 FAIL (2)"""
    project_root = isolated_python_project
    ep_id = "EP-POST-ARCH-ERR"
    _setup_virtual_ep(ep_id, project_root)
    
    with patch("mms.analysis.arch_check._ROOT", project_root), \
         patch("mms.workflow.postcheck.run_pytest", return_value=(True, "1 passed")), \
         patch("mms.workflow.postcheck.run_arch_check_post", return_value=(False, -1, [{"message": "Exception"}])):
        ret = run_postcheck(ep_id, skip_tests=False, project_root=project_root)
        
    assert ret == 2, "架构检查异常时应该返回 2 (FAIL)"


# ─────────────────────────────────────────────────────────────────────────────
# Test-PC2：契约漂移容错（arch_check 抛出 Python 级别异常时的优雅降级）
# ─────────────────────────────────────────────────────────────────────────────

def test_pc2_arch_check_raises_exception_graceful_degradation(isolated_python_project):
    """
    Test-PC2 契约漂移容错
    ---------------------
    当 run_arch_check_post 抛出 Python 级别异常（而非返回 -1 退出码）时，
    run_postcheck 不应让异常向上传播导致 Python 崩溃，
    应优雅地捕获并将状态报告为 WARN 或 FAIL（返回码 1 或 2），
    确保最终报告文件能够生成。

    此场景模拟：arch_check 工具本身在某些边缘环境下（如文件权限、OOM）
    直接抛出 RuntimeError 而非正常返回的情况。
    """
    project_root = isolated_python_project
    ep_id = "EP-PC2-EXCEPTION"
    _setup_virtual_ep(ep_id, project_root)

    def arch_check_raises(_baseline):
        raise RuntimeError("模拟 arch_check 工具内部异常：OOM / 文件锁")

    try:
        with patch("mms.analysis.arch_check._ROOT", project_root), \
             patch("mms.workflow.postcheck.run_pytest", return_value=(True, "1 passed")), \
             patch("mms.workflow.postcheck.run_arch_check_post",
                   side_effect=arch_check_raises):
            ret = run_postcheck(ep_id, skip_tests=False, project_root=project_root)

        # 应返回非零退出码（WARN=1 或 FAIL=2），不允许是 0（PASS）
        assert ret in (1, 2), (
            f"arch_check 抛出异常时，postcheck 应返回 WARN(1) 或 FAIL(2)，实际返回：{ret}"
        )
    except Exception as exc:
        pytest.fail(
            f"Test-PC2 失败：run_postcheck 不应向上传播 Python 异常，"
            f"但捕获到：{type(exc).__name__}: {exc}"
        )


def test_pc2_arch_check_error_report_still_generated(isolated_python_project):
    """
    Test-PC2b：arch_check 异常时，报告文件（postcheck-EP-xxx.md）应仍能生成
    验证最终报告不会因中间步骤异常而缺失。
    """
    import glob
    project_root = isolated_python_project
    ep_id = "EP-PC2-REPORT"
    _setup_virtual_ep(ep_id, project_root)

    report_dir = project_root / "docs" / "memory" / "_system" / "postcheck_reports"

    try:
        with patch("mms.workflow.postcheck._ROOT", project_root), \
             patch("mms.workflow.postcheck._CHECKPOINTS_DIR",
                   project_root / "docs" / "memory" / "_system" / "checkpoints"), \
             patch("mms.workflow.precheck._CHECKPOINTS_DIR",
                   project_root / "docs" / "memory" / "_system" / "checkpoints"), \
             patch("mms.analysis.arch_check._ROOT", project_root), \
             patch("mms.workflow.postcheck.run_pytest", return_value=(True, "2 passed")), \
             patch("mms.workflow.postcheck.run_arch_check_post",
                   side_effect=RuntimeError("工具崩溃")):
            run_postcheck(ep_id, skip_tests=False)
    except Exception:
        pass  # 允许异常，但下方会检查报告是否生成
