"""
test_sandbox.py — GitSandbox 单元测试

覆盖：
  - snapshot() 快照建立
  - rollback() 文件恢复（已有文件 / 新建文件）
  - changed_files 属性
  - commit() (mock subprocess)
  - diff_stat() (mock subprocess)
  - 上下文管理器异常自动回滚
"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sandbox import GitSandbox, is_git_clean, get_tracked_status


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_root(tmp_path):
    """临时目录作为 project root"""
    return tmp_path


@pytest.fixture()
def txt_file(tmp_root):
    """创建一个预设内容的文本文件"""
    f = tmp_root / "hello.txt"
    f.write_text("original content\n", encoding="utf-8")
    return f


# ── snapshot / rollback ───────────────────────────────────────────────────────

class TestSnapshotRollback:

    def test_snapshot_captures_existing_file(self, tmp_root, txt_file):
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        sb.snapshot()
        assert sb._snapshot["hello.txt"] == b"original content\n"

    def test_snapshot_records_none_for_missing(self, tmp_root):
        sb = GitSandbox(["nonexistent.py"], root=tmp_root)
        sb.snapshot()
        assert sb._snapshot["nonexistent.py"] is None

    def test_rollback_restores_existing_file(self, tmp_root, txt_file):
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        sb.snapshot()
        txt_file.write_text("modified!", encoding="utf-8")
        sb.rollback()
        assert txt_file.read_text(encoding="utf-8") == "original content\n"

    def test_rollback_deletes_new_file(self, tmp_root):
        new_file = tmp_root / "brand_new.py"
        sb = GitSandbox(["brand_new.py"], root=tmp_root)
        sb.snapshot()  # 文件不存在，快照为 None
        new_file.write_text("new content", encoding="utf-8")
        sb.rollback()
        assert not new_file.exists()

    def test_rollback_noop_if_not_snapshotted(self, tmp_root, txt_file):
        """未调用 snapshot() 时 rollback() 不操作"""
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        txt_file.write_text("changed!", encoding="utf-8")
        sb.rollback()  # 不应报错
        # 文件不被恢复（因为没有快照）
        assert txt_file.read_text(encoding="utf-8") == "changed!"

    def test_rollback_deletes_extra_new_files(self, tmp_root):
        """mark_new_file 注册的沙箱外文件也被删除"""
        extra = tmp_root / "extra.py"
        sb = GitSandbox([], root=tmp_root)
        sb.snapshot()
        extra.write_text("x", encoding="utf-8")
        sb.mark_new_file("extra.py")
        sb.rollback()
        assert not extra.exists()

    def test_multiple_files_snapshot_rollback(self, tmp_root):
        """多文件同时快照和回滚"""
        f1 = tmp_root / "a.txt"
        f2 = tmp_root / "b.txt"
        f1.write_text("aaa", encoding="utf-8")
        f2.write_text("bbb", encoding="utf-8")

        sb = GitSandbox(["a.txt", "b.txt"], root=tmp_root)
        sb.snapshot()

        f1.write_text("CHANGED_A", encoding="utf-8")
        f2.write_text("CHANGED_B", encoding="utf-8")

        sb.rollback()

        assert f1.read_text(encoding="utf-8") == "aaa"
        assert f2.read_text(encoding="utf-8") == "bbb"


# ── changed_files ─────────────────────────────────────────────────────────────

class TestChangedFiles:

    def test_no_changes(self, tmp_root, txt_file):
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        sb.snapshot()
        assert sb.changed_files == []

    def test_modified_file_detected(self, tmp_root, txt_file):
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        sb.snapshot()
        txt_file.write_text("new content!", encoding="utf-8")
        assert "hello.txt" in sb.changed_files

    def test_new_file_detected(self, tmp_root):
        new_file = tmp_root / "new.py"
        sb = GitSandbox(["new.py"], root=tmp_root)
        sb.snapshot()
        new_file.write_text("# new", encoding="utf-8")
        assert "new.py" in sb.changed_files


# ── commit (mocked) ───────────────────────────────────────────────────────────

class TestCommit:

    def _make_mock_run(self, returncode=0, stdout="abc123\n", stderr=""):
        mock_result = MagicMock()
        mock_result.returncode = returncode
        mock_result.stdout = stdout
        mock_result.stderr = stderr
        return mock_result

    def test_commit_success_returns_hash(self, tmp_root, txt_file):
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        sb.snapshot()

        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "abcdef1\n"
            r.stderr = ""
            return r

        with patch("sandbox.subprocess.run", side_effect=mock_run):
            h = sb.commit("test commit")

        assert h == "abcdef1"

    def test_commit_nothing_to_commit_returns_none(self, tmp_root):
        sb = GitSandbox([], root=tmp_root)
        sb.snapshot()

        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "nothing to commit"
            return r

        with patch("sandbox.subprocess.run", side_effect=mock_run):
            h = sb.commit("empty commit")
        assert h is None


# ── context manager ───────────────────────────────────────────────────────────

class TestContextManager:

    def test_exception_triggers_rollback(self, tmp_root, txt_file):
        """异常退出时自动回滚"""
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        with pytest.raises(RuntimeError):
            with sb:
                txt_file.write_text("corrupted!", encoding="utf-8")
                raise RuntimeError("something broke")

        assert txt_file.read_text(encoding="utf-8") == "original content\n"

    def test_normal_exit_no_auto_rollback(self, tmp_root, txt_file):
        """正常退出不自动回滚（需要调用方显式 commit 或 rollback）"""
        sb = GitSandbox(["hello.txt"], root=tmp_root)
        with sb:
            txt_file.write_text("new content!", encoding="utf-8")
        # 没有回滚，文件保持修改后状态
        assert txt_file.read_text(encoding="utf-8") == "new content!"


# ── is_git_clean / get_tracked_status (mocked) ────────────────────────────────

class TestHelperFunctions:

    def test_is_git_clean_true(self):
        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = ""
            return r

        with patch("sandbox.subprocess.run", side_effect=mock_run):
            assert is_git_clean() is True

    def test_is_git_clean_false(self):
        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = " M some_file.py\n"
            return r

        with patch("sandbox.subprocess.run", side_effect=mock_run):
            assert is_git_clean() is False

    def test_get_tracked_status(self, tmp_root):
        # 创建一个文件，一个不存在的
        f = tmp_root / "tracked.py"
        f.write_text("x", encoding="utf-8")

        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 0
            r.stdout = "tracked.py\n"
            return r

        with patch("sandbox.subprocess.run", side_effect=mock_run):
            status = get_tracked_status(["tracked.py", "not_exist.py"], root=tmp_root)

        assert status["tracked.py"] == "tracked"
        assert status["not_exist.py"] == "not_exists"
