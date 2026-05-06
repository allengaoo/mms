"""
test_sandbox_bug1_regression.py — Bug 1 回归测试：sandbox commit() 精准 git add

验证修复：commit() 必须使用 `git add -- <精准文件列表>` 而非 `git add -A`。

Bug 根因：
  原实现在 commit() 中调用 `subprocess.run(["git", "add", "-A"])`.
  `-A` 会将整个工作区的所有 untracked 和 modified 文件（包括 .env、API Key、
  临时文件等）全部混入 EP commit，破坏沙箱隔离边界。

修复方案：
  改为 `["git", "add", "--"] + list(dict.fromkeys(self.files + self._new_files))`
  只 add 沙箱声明的文件，不污染其他工作区文件。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mms.execution.sandbox import GitSandbox, SandboxError


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_subprocess_mock(returncode=0, stdout="abc1234\n", stderr=""):
    """构造一个模拟 subprocess.run 的 side_effect，记录所有调用。"""
    called_cmds = []

    def mock_run(cmd, **kwargs):
        called_cmds.append(cmd)
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    mock_run.called_cmds = called_cmds
    return mock_run


@pytest.fixture()
def tmp_root(tmp_path):
    return tmp_path


@pytest.fixture()
def txt_file(tmp_root):
    f = tmp_root / "service.py"
    f.write_text("def hello(): pass\n", encoding="utf-8")
    return f


# ── 核心回归测试：精准 add ────────────────────────────────────────────────────

class TestCommitNeverUsesGitAddA:
    """
    Bug 1 核心回归：commit() 绝对不允许出现 `git add -A`。
    任何包含 '-A' 的 git add 命令都是沙箱逃逸漏洞。
    """

    def test_commit_does_not_use_git_add_A(self, tmp_root, txt_file):
        """最基础的回归检查：`-A` 不能出现在任何 git add 调用中。"""
        sb = GitSandbox(["service.py"], root=tmp_root)
        sb.snapshot()

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: basic commit")

        for cmd in mock_run.called_cmds:
            if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add":
                assert "-A" not in cmd, (
                    f"沙箱逃逸漏洞！git add 命令包含 -A: {cmd}\n"
                    "这会将工作区所有文件混入 EP commit，破坏沙箱隔离。"
                )

    def test_commit_uses_double_dash_separator(self, tmp_root, txt_file):
        """git add 必须使用 `--` 分隔符，防止路径被解释为选项。"""
        sb = GitSandbox(["service.py"], root=tmp_root)
        sb.snapshot()

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: separator check")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add"]
        assert len(add_cmds) == 1, "commit() 应恰好调用一次 git add"
        assert "--" in add_cmds[0], f"git add 命令缺少 '--' 分隔符: {add_cmds[0]}"

    def test_commit_adds_only_declared_files(self, tmp_root):
        """git add 的参数必须精确匹配 files 声明列表，不能多也不能少。"""
        for name in ["a.py", "b.py", "unrelated.txt"]:
            (tmp_root / name).write_text("x", encoding="utf-8")

        # 只声明 a.py 和 b.py，unrelated.txt 不能被 add
        sb = GitSandbox(["a.py", "b.py"], root=tmp_root)
        sb.snapshot()

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: precise add")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add"]
        assert len(add_cmds) == 1
        added_files = set(add_cmds[0][add_cmds[0].index("--") + 1:])
        assert "a.py" in added_files
        assert "b.py" in added_files
        assert "unrelated.txt" not in added_files, (
            f"unrelated.txt 不应被 add！实际 add 了: {added_files}"
        )


class TestCommitIncludesNewFiles:
    """
    mark_new_file() 注册的沙箱外新文件也必须被精准 add，
    这些是 FileApplier 运行时创建的文件，需要进入 commit。
    """

    def test_commit_includes_mark_new_file_entries(self, tmp_root):
        """mark_new_file 注册的文件应出现在 git add 参数中。"""
        (tmp_root / "main.py").write_text("x", encoding="utf-8")

        sb = GitSandbox(["main.py"], root=tmp_root)
        sb.snapshot()
        sb.mark_new_file("new_module.py")

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: includes new files")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add"]
        added_files = set(add_cmds[0][add_cmds[0].index("--") + 1:])
        assert "main.py" in added_files
        assert "new_module.py" in added_files

    def test_commit_deduplicates_files_between_files_and_new_files(self, tmp_root):
        """如果同一文件同时出现在 files 和 _new_files 中，不应重复 add。"""
        (tmp_root / "shared.py").write_text("x", encoding="utf-8")

        sb = GitSandbox(["shared.py"], root=tmp_root)
        sb.snapshot()
        sb.mark_new_file("shared.py")  # 重复注册

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: dedup")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add"]
        added_files = add_cmds[0][add_cmds[0].index("--") + 1:]
        assert len(added_files) == len(set(added_files)), (
            f"存在重复文件！add 参数: {added_files}"
        )

    def test_commit_multiple_new_files_all_included(self, tmp_root):
        """多个 mark_new_file 注册的文件都应出现在 add 参数中。"""
        (tmp_root / "base.py").write_text("x", encoding="utf-8")

        sb = GitSandbox(["base.py"], root=tmp_root)
        sb.snapshot()
        for name in ["new1.py", "new2.py", "new3.py"]:
            sb.mark_new_file(name)

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("test: multiple new files")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "add"]
        added_files = set(add_cmds[0][add_cmds[0].index("--") + 1:])
        assert {"base.py", "new1.py", "new2.py", "new3.py"} == added_files


class TestCommitEdgeCases:
    """边缘情况：空文件列表、单文件、快照前调用等。"""

    def test_commit_returns_none_for_empty_file_list(self, tmp_root):
        """
        无文件声明时，精准 add 列表为空，应直接返回 None 而不执行 git add。
        这是额外的安全防线：无文件声明 → 无 git 操作。
        """
        sb = GitSandbox([], root=tmp_root)
        sb.snapshot()

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            result = sb.commit("empty commit")

        assert result is None
        # 不应调用任何 git 命令
        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and "add" in cmd]
        assert add_cmds == [], f"空文件列表不应触发 git add，但调用了: {add_cmds}"

    def test_commit_single_file_correct_add_args(self, tmp_root):
        """单文件时，git add 参数应为 ['git', 'add', '--', 'only_file.py']。"""
        (tmp_root / "only_file.py").write_text("x", encoding="utf-8")
        sb = GitSandbox(["only_file.py"], root=tmp_root)
        sb.snapshot()

        mock_run = _make_subprocess_mock()
        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            sb.commit("single file")

        add_cmds = [cmd for cmd in mock_run.called_cmds
                    if cmd[0] == "git" and "add" in cmd]
        assert len(add_cmds) == 1
        assert add_cmds[0] == ["git", "add", "--", "only_file.py"]

    def test_commit_nothing_to_commit_returns_none(self, tmp_root):
        """git commit 返回 'nothing to commit' 时，应优雅返回 None。"""
        (tmp_root / "a.py").write_text("x", encoding="utf-8")
        sb = GitSandbox(["a.py"], root=tmp_root)
        sb.snapshot()

        def mock_run(cmd, **kwargs):
            r = MagicMock()
            r.returncode = 1
            r.stdout = ""
            r.stderr = "nothing to commit, working tree clean"
            return r

        with patch("mms.execution.sandbox.subprocess.run", side_effect=mock_run):
            result = sb.commit("nothing to commit")
        assert result is None
