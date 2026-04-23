"""
test_unit_compare.py — EP-120 unit_compare.py 单元测试

覆盖范围：
  - save_sonnet_output：写入 sonnet.txt + header
  - _parse_changes_from_text：标准块、无块、多文件块
  - _file_diff：相同内容、不同内容、行数限制
  - compare()：缺 qwen.txt、缺 sonnet.txt、正常生成 report.md
  - apply()：source 无效、缺文件、解析失败
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 确保 scripts/mms 在 sys.path 首位
_MMS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MMS_DIR))

import unit_compare as _uc


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def compare_dir(tmp_path):
    """在 tmp_path 下模拟 compare/<EP>/<UNIT> 目录结构"""
    d = tmp_path / "EP-120" / "U1"
    d.mkdir(parents=True)
    return d


@pytest.fixture()
def patch_compare_root(tmp_path):
    """将 unit_compare._COMPARE_ROOT 重定向到 tmp_path"""
    with patch.object(_uc, "_COMPARE_ROOT", tmp_path):
        yield tmp_path


QWEN_RAW = """\
# qwen 输出 — EP-120 U1
# 生成时间：2026-04-18T00:00:00+00:00
# 涉及文件：backend/app/test.py

===BEGIN-CHANGES===
FILE: backend/app/test.py
ACTION: create
CONTENT:
def hello():
    return "hello from qwen"
===END-FILE===
===END-CHANGES===
"""

SONNET_RAW = """\
# sonnet 输出 — EP-120 U1
# 生成时间：2026-04-18T00:01:00+00:00

===BEGIN-CHANGES===
FILE: backend/app/test.py
ACTION: create
CONTENT:
def hello():
    return "hello from sonnet"
===END-FILE===
===END-CHANGES===
"""


# ── save_sonnet_output ────────────────────────────────────────────────────────

class TestSaveSonnetOutput:
    def test_creates_sonnet_txt(self, patch_compare_root):
        out = _uc.save_sonnet_output("EP-120", "U1", "===BEGIN-CHANGES===\n===END-CHANGES===")
        path = Path(out)
        assert path.exists()
        assert path.name == "sonnet.txt"

    def test_header_injected(self, patch_compare_root):
        # MY_CONTENT 不含 BEGIN-CHANGES 标记，会触发 input() 确认，需 mock
        with patch("builtins.input", return_value="yes"):
            _uc.save_sonnet_output("EP-120", "U1", "MY_CONTENT")
        txt = (patch_compare_root / "EP-120" / "U1" / "sonnet.txt").read_text()
        assert "# sonnet 输出" in txt
        assert "MY_CONTENT" in txt

    def test_creates_parent_dirs(self, patch_compare_root):
        # body 不含 BEGIN-CHANGES 标记，会触发 input() 确认，需 mock
        with patch("builtins.input", return_value="yes"):
            _uc.save_sonnet_output("EP-999", "U99", "body")
        assert (patch_compare_root / "EP-999" / "U99" / "sonnet.txt").exists()


# ── _parse_changes_from_text ─────────────────────────────────────────────────

class TestParseChanges:
    def test_single_file(self):
        text = (
            "===BEGIN-CHANGES===\n"
            "FILE: foo/bar.py\n"
            "ACTION: create\n"
            "CONTENT:\n"
            "x = 1\n"
            "===END-FILE===\n"
            "===END-CHANGES===\n"
        )
        changes = _uc._parse_changes_from_text(text)
        assert len(changes) == 1
        path, action, content = changes[0]
        assert path == "foo/bar.py"
        assert action == "create"
        assert "x = 1" in content

    def test_no_begin_marker_returns_empty(self):
        assert _uc._parse_changes_from_text("no marker here") == []

    def test_multiple_files(self):
        text = (
            "===BEGIN-CHANGES===\n"
            "FILE: a.py\nACTION: create\nCONTENT:\na=1\n===END-FILE===\n"
            "FILE: b.py\nACTION: replace\nCONTENT:\nb=2\n===END-FILE===\n"
            "===END-CHANGES===\n"
        )
        changes = _uc._parse_changes_from_text(text)
        assert len(changes) == 2
        assert changes[0][0] == "a.py"
        assert changes[1][0] == "b.py"

    def test_action_defaults_to_replace(self):
        text = (
            "===BEGIN-CHANGES===\n"
            "FILE: c.py\n"
            "CONTENT:\nc=3\n"
            "===END-FILE===\n"
            "===END-CHANGES===\n"
        )
        changes = _uc._parse_changes_from_text(text)
        # action 行缺失时应保持默认值 replace
        assert changes[0][1] == "replace"


# ── _file_diff ────────────────────────────────────────────────────────────────

class TestFileDiff:
    def test_identical_contents(self):
        result = _uc._file_diff("x = 1\n", "x = 1\n", "test.py")
        assert "相同" in result or result == "（两版本内容相同，无 diff）"

    def test_different_contents(self):
        result = _uc._file_diff("x = 1\n", "x = 2\n", "test.py")
        assert "-x = 1" in result or "+x = 2" in result

    def test_truncation_at_max_lines(self):
        """超过 MAX_LINES=80 时应截断并提示"""
        long_a = "\n".join(f"line_{i}_a" for i in range(200))
        long_b = "\n".join(f"line_{i}_b" for i in range(200))
        result = _uc._file_diff(long_a, long_b, "big.py")
        assert "省略" in result


# ── compare() ─────────────────────────────────────────────────────────────────

class TestCompare:
    def test_missing_qwen_returns_1(self, patch_compare_root, capsys):
        code = _uc.compare("EP-120", "U1")
        assert code == 1
        out = capsys.readouterr().out
        assert "qwen.txt" in out

    def test_missing_sonnet_returns_1(self, patch_compare_root, capsys):
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        (d / "qwen.txt").write_text(QWEN_RAW)
        code = _uc.compare("EP-120", "U1")
        assert code == 1
        out = capsys.readouterr().out
        assert "sonnet.txt" in out

    def test_generates_report_md(self, patch_compare_root, capsys):
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        (d / "qwen.txt").write_text(QWEN_RAW)
        (d / "sonnet.txt").write_text(SONNET_RAW)

        with (
            patch.object(_uc, "_run_arch_check_summary", return_value=(True, "0 violations")),
            patch.object(_uc, "_run_test_summary", return_value=(True, "5 passed")),
        ):
            code = _uc.compare("EP-120", "U1")

        assert code == 0
        report = d / "report.md"
        assert report.exists()
        text = report.read_text()
        assert "双模型对比报告" in text
        assert "backend/app/test.py" in text
        assert "qwen" in text
        assert "sonnet" in text

    def test_report_contains_diff(self, patch_compare_root):
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        (d / "qwen.txt").write_text(QWEN_RAW)
        (d / "sonnet.txt").write_text(SONNET_RAW)

        with (
            patch.object(_uc, "_run_arch_check_summary", return_value=(True, "ok")),
            patch.object(_uc, "_run_test_summary", return_value=(True, "ok")),
        ):
            _uc.compare("EP-120", "U1")

        report_text = (d / "report.md").read_text()
        # qwen 有 "qwen"，sonnet 有 "sonnet"，diff 应体现差异
        assert "diff" in report_text or "```" in report_text


# ── apply() ───────────────────────────────────────────────────────────────────

class TestApply:
    def test_invalid_source_returns_1(self, patch_compare_root, capsys):
        code = _uc.apply("EP-120", "U1", source="invalid")
        assert code == 1

    def test_missing_source_file_returns_1(self, patch_compare_root, capsys):
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        code = _uc.apply("EP-120", "U1", source="qwen")
        assert code == 1
        out = capsys.readouterr().out
        assert "qwen.txt" in out

    def test_empty_changes_returns_1(self, patch_compare_root, capsys):
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        (d / "qwen.txt").write_text("no changes block here")
        code = _uc.apply("EP-120", "U1", source="qwen")
        assert code == 1
        out = capsys.readouterr().out
        assert "===BEGIN-CHANGES===" in out

    def test_apply_success_with_mocks(self, patch_compare_root, tmp_path):
        """通过 mock FileApplier 和 GitSandbox 验证成功路径"""
        d = patch_compare_root / "EP-120" / "U1"
        d.mkdir(parents=True)
        (d / "qwen.txt").write_text(QWEN_RAW)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.path = "backend/app/test.py"

        mock_applier_instance = MagicMock()
        mock_applier_instance.apply.return_value = [mock_result]
        mock_applier_cls = MagicMock(return_value=mock_applier_instance)

        mock_sandbox_instance = MagicMock()
        mock_sandbox_instance.commit.return_value = "abc1234"
        mock_sandbox_cls = MagicMock(return_value=mock_sandbox_instance)

        # GitSandbox/FileApplier 在函数内用 try/except lazy import，
        # 需要 patch 到 sandbox / file_applier 模块，而非 unit_compare 模块
        with (
            patch("mms.execution.sandbox.GitSandbox", mock_sandbox_cls),
            patch("mms.execution.file_applier.FileApplier", mock_applier_cls),
        ):
            # patch DagState 使其抛出 ImportError（测试 except 分支）
            import dag_model as _dm
            with patch.object(_dm, "DagState", side_effect=Exception("skip")):
                code = _uc.apply("EP-120", "U1", source="qwen")

        assert code == 0
        mock_applier_instance.apply.assert_called_once()
        mock_sandbox_instance.commit.assert_called_once()
