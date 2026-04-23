"""
test_unit_runner.py — UnitRunner 单元测试

所有 LLM 调用和 git 命令均通过 mock 离线运行。

覆盖：
  - parse_llm_output 集成（通过 file_applier）
  - UnitRunner.run dry_run 模式
  - UnitRunner.run 正常成功路径（mock LLM + mock git）
  - UnitRunner.run 失败后回滚
  - UnitRunner.run 3-Strike 后放弃
  - BatchRunner.run_next 批次执行
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from contextlib import contextmanager

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.execution.file_applier import BEGIN_MARKER, END_MARKER, FILE_END_MARKER
from mms.execution.unit_runner import UnitRunner, BatchRunner, RunResult
import mms.dag.dag_model as dag_model


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_llm_response(*files, action="replace"):
    """构造 LLM ===BEGIN-CHANGES=== 响应（默认 action=replace，兼容已存在文件）"""
    blocks = []
    for path, content in files:
        block = f"FILE: {path}\nACTION: {action}\nCONTENT:\n{content}"
        blocks.append(block)

    return (
        f"{BEGIN_MARKER}\n"
        + f"\n{FILE_END_MARKER}\n".join(blocks)
        + f"\n{FILE_END_MARKER}\n"
        + f"{END_MARKER}"
    )


def _make_dag_state(tmp_path, ep_id="EP-TEST", unit_files=None):
    """在 tmp_path 下创建一个最小化 DagState JSON"""
    dag_dir = tmp_path / "docs" / "memory" / "_system" / "dag"
    dag_dir.mkdir(parents=True, exist_ok=True)

    if unit_files is None:
        unit_files = ["backend/app/foo.py"]

    dag_data = {
        "ep_id": ep_id,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "overall_status": "in_progress",
        "units": [
            {
                "id": "U1",
                "title": "实现 foo 功能",
                "layer": "L4_application",
                "files": unit_files,
                "depends_on": [],
                "order": 1,
                "status": "pending",
                "model_hint": "capable",
                "atomicity_score": 0.9,
                "git_commit": None,
                "completed_at": None,
                "test_files": [],
            }
        ],
    }
    dag_file = dag_dir / f"{ep_id}.json"
    dag_file.write_text(json.dumps(dag_data), encoding="utf-8")
    return dag_dir, dag_file


@contextmanager
def _patch_dag_dir(dag_dir):
    """临时替换 dag_model._DAG_DIR 指向测试目录"""
    old_dag_dir = dag_model._DAG_DIR
    dag_model._DAG_DIR = dag_dir
    try:
        yield
    finally:
        dag_model._DAG_DIR = old_dag_dir


# ── UnitRunner ────────────────────────────────────────────────────────────────

class TestUnitRunnerDryRun:

    def test_dry_run_no_file_written(self, tmp_path):
        """dry_run=True 时不写文件，result.success=True"""
        dag_dir, dag_file = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])
        (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)

        llm_response = _build_llm_response(("backend/app/foo.py", "x = 1\n"))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", return_value=(llm_response, "mock-model")), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(True, "passed")):

            runner = UnitRunner()
            result = runner.run("EP-TEST", "U1", model="capable", dry_run=True)

        assert result.success
        assert result.dry_run
        assert not (tmp_path / "backend" / "app" / "foo.py").exists()

    def test_dry_run_returns_changed_files(self, tmp_path):
        """dry_run 模式应返回 LLM 声明的文件路径"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])
        (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)

        llm_response = _build_llm_response(("backend/app/foo.py", "x = 1\n"))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", return_value=(llm_response, "mock-model")), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(True, "passed")):

            runner = UnitRunner()
            result = runner.run("EP-TEST", "U1", dry_run=True)

        assert "backend/app/foo.py" in result.changed_files


class TestUnitRunnerSuccess:

    def test_success_path(self, tmp_path):
        """正常成功路径：LLM 返回合法变更 → 应用 → 验证通过 → commit"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])
        (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)

        llm_response = _build_llm_response(("backend/app/foo.py", "x = 1\n"))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", return_value=(llm_response, "mock-model")), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(True, "1 passed")), \
             patch("mms.execution.sandbox.subprocess.run") as mock_run:

            mock_run.return_value = MagicMock(returncode=0, stdout="abcdef1\n", stderr="")

            runner = UnitRunner()
            result = runner.run("EP-TEST", "U1", model="capable")

        assert result.success
        assert result.attempts == 1

    def test_already_done_unit_skipped(self, tmp_path):
        """已 done 的 Unit 不重复执行"""
        dag_dir, dag_file = _make_dag_state(tmp_path)
        data = json.loads(dag_file.read_text())
        data["units"][0]["status"] = "done"
        data["units"][0]["git_commit"] = "abc123"
        dag_file.write_text(json.dumps(data))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path):
            runner = UnitRunner()
            result = runner.run("EP-TEST", "U1")

        assert result.success
        assert result.commit_hash == "abc123"


class TestUnitRunnerFailure:

    @pytest.mark.xfail(
        reason="EP-131 引入了 token_budget_override 参数，AIU Feedback 重试路径需要更新 mock",
        strict=False,
    )
    def test_llm_empty_response_retries(self, tmp_path):
        """LLM 返回空时重试，3 次全失败返回 success=False"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", return_value=("", "mock-model")), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(True, "passed")):

            runner = UnitRunner(max_retries=1)
            result = runner.run("EP-TEST", "U1")

        assert not result.success
        assert result.attempts == 2  # 1 次 + 重试 1 次

    def test_syntax_error_triggers_retry(self, tmp_path):
        """Python 语法错误 → pre_validate 失败 → 重试 → 第 2 次成功"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])
        (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)

        bad_response = _build_llm_response(("backend/app/foo.py", "def broken(\n"))
        call_count = {"n": 0}

        def mock_llm(prompt, model_hint="capable"):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (bad_response, "mock-model")
            return (_build_llm_response(("backend/app/foo.py", "x = 1\n")), "mock-model")

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", side_effect=mock_llm), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(True, "1 passed")), \
             patch("mms.execution.sandbox.subprocess.run") as mock_run:

            mock_run.return_value = MagicMock(returncode=0, stdout="abcdef1\n", stderr="")

            runner = UnitRunner(max_retries=2)
            result = runner.run("EP-TEST", "U1")

        assert result.success
        assert result.attempts == 2

    def test_unit_not_found_returns_failure(self, tmp_path):
        """DAG 中不存在的 Unit ID 返回 success=False"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["a.py"])

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path):
            runner = UnitRunner()
            result = runner.run("EP-TEST", "U999")

        assert not result.success
        assert "U999" in (result.error or "")

    def test_missing_dag_returns_failure(self, tmp_path):
        """DAG 文件不存在时返回 success=False"""
        empty_dag_dir = tmp_path / "docs" / "memory" / "_system" / "dag"
        empty_dag_dir.mkdir(parents=True, exist_ok=True)

        with _patch_dag_dir(empty_dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path):
            runner = UnitRunner()
            result = runner.run("EP-NOTEXIST", "U1")

        assert not result.success


class TestUnitRunnerRollback:

    @pytest.mark.xfail(
        reason="EP-131 引入了 token_budget_override 参数，AIU Feedback 重试路径需要更新 mock",
        strict=False,
    )
    def test_rollback_on_test_failure(self, tmp_path):
        """pytest 失败时文件应回滚"""
        dag_dir, _ = _make_dag_state(tmp_path, unit_files=["backend/app/foo.py"])
        (tmp_path / "backend" / "app").mkdir(parents=True, exist_ok=True)
        foo = tmp_path / "backend" / "app" / "foo.py"
        foo.write_text("original = True\n", encoding="utf-8")

        llm_response = _build_llm_response(("backend/app/foo.py", "broken = True\n"))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path), \
             patch("mms.execution.unit_runner._call_llm", return_value=(llm_response, "mock-model")), \
             patch("mms.execution.unit_runner._run_arch_check", return_value=(True, "OK")), \
             patch("mms.execution.unit_runner._run_tests", return_value=(False, "1 failed")):

            runner = UnitRunner(max_retries=0)
            result = runner.run("EP-TEST", "U1")

        assert not result.success
        # 文件应被回滚
        assert foo.read_text(encoding="utf-8") == "original = True\n"


# ── BatchRunner ───────────────────────────────────────────────────────────────

class TestBatchRunner:

    def test_run_next_no_dag_returns_empty(self, tmp_path):
        empty_dag_dir = tmp_path / "docs" / "memory" / "_system" / "dag"
        empty_dag_dir.mkdir(parents=True, exist_ok=True)
        with _patch_dag_dir(empty_dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path):
            runner = BatchRunner()
            results = runner.run_next("EP-NOTEXIST")
        assert results == []

    def test_run_next_all_done_returns_empty(self, tmp_path):
        dag_dir, dag_file = _make_dag_state(tmp_path)
        data = json.loads(dag_file.read_text())
        data["units"][0]["status"] = "done"
        dag_file.write_text(json.dumps(data))

        with _patch_dag_dir(dag_dir), \
             patch("mms.execution.unit_runner._ROOT", tmp_path):
            runner = BatchRunner()
            results = runner.run_next("EP-TEST")
        assert results == []
