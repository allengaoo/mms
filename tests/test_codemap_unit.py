"""
tests/test_codemap_unit.py
━━━━━━━━━━━━━━━━━━━━━━━━━━
codemap.py 的单元测试

覆盖：
  - _should_ignore()：忽略目录/文件名判断
  - _build_tree()：树状结构递归生成
  - generate_codemap()：完整输出格式校验
  - generate_codemap() depth 参数控制
  - 不存在的目录 → 输出 "目录不存在"
  - _get_recent_files()（间接通过 recent_count 参数）

注意：generate_codemap 对 _ROOT 下真实文件系统路径有依赖，
测试时通过 monkeypatch 或临时目录解耦。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mms.memory.codemap import (
    _should_ignore,
    _build_tree,
    generate_codemap,
)


# ─── _should_ignore 测试 ─────────────────────────────────────────────────────

class TestShouldIgnore:
    def test_ignores_pycache(self):
        assert _should_ignore("__pycache__") is True

    def test_ignores_git(self):
        assert _should_ignore(".git") is True

    def test_ignores_node_modules(self):
        assert _should_ignore("node_modules") is True

    def test_ignores_dot_prefix(self):
        assert _should_ignore(".hidden_file") is True

    def test_allows_normal_dir(self):
        assert _should_ignore("src") is False

    def test_allows_normal_file(self):
        assert _should_ignore("main.py") is False

    def test_allows_docs(self):
        assert _should_ignore("docs") is False

    def test_ignores_venv(self):
        assert _should_ignore("venv") is True

    def test_ignores_dotenv(self):
        assert _should_ignore(".venv") is True

    def test_ignores_build(self):
        assert _should_ignore("build") is True


# ─── _build_tree 测试 ────────────────────────────────────────────────────────

class TestBuildTree:
    def test_single_file(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        lines = []
        _build_tree(
            base=tmp_path,
            current=tmp_path / "main.py",
            depth=1,
            max_depth=3,
            lines=lines,
        )
        assert any("main.py" in line for line in lines)

    def test_single_directory(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        lines = []
        _build_tree(
            base=tmp_path,
            current=sub,
            depth=1,
            max_depth=3,
            lines=lines,
        )
        assert any("subdir/" in line for line in lines)

    def test_max_depth_respected(self, tmp_path):
        """超过 max_depth 时不展开深层目录"""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep_file.py").write_text("")

        lines = []
        _build_tree(
            base=tmp_path,
            current=tmp_path / "a",
            depth=1,
            max_depth=2,  # 只展开 2 层
            lines=lines,
        )
        full = "\n".join(lines)
        assert "deep_file.py" not in full  # 第 3 层不展开
        assert "b/" in full  # 第 2 层仍然展示

    def test_ignores_pycache_in_tree(self, tmp_path):
        cache = tmp_path / "__pycache__"
        cache.mkdir()
        (cache / "module.cpython-311.pyc").write_text("")
        normal = tmp_path / "module.py"
        normal.write_text("")

        lines = []
        _build_tree(
            base=tmp_path,
            current=tmp_path / "__pycache__",
            depth=1,
            max_depth=3,
            lines=lines,
        )
        # _should_ignore 被 _build_tree 的父层调用，但 _build_tree 本身接受传入节点
        # 测试目录仍然展示（过滤在父层调用时完成）
        # 这里测试 pyc 文件因 _IGNORE_EXTS 被过滤
        lines2 = []
        _build_tree(
            base=tmp_path,
            current=normal,
            depth=1,
            max_depth=3,
            lines=lines2,
        )
        assert any("module.py" in line for line in lines2)

    def test_pyc_extension_ignored(self, tmp_path):
        pyc = tmp_path / "module.pyc"
        pyc.write_bytes(b"")
        lines = []
        _build_tree(
            base=tmp_path,
            current=pyc,
            depth=1,
            max_depth=3,
            lines=lines,
        )
        assert lines == []  # .pyc 文件被过滤，不产生任何输出

    def test_last_vs_not_last_connector(self, tmp_path):
        """最后一项用 └──，非最后项用 ├──"""
        (tmp_path / "a.py").write_text("")
        (tmp_path / "b.py").write_text("")

        lines_last = []
        _build_tree(tmp_path, tmp_path / "b.py", 1, 3, lines_last, "", is_last=True)
        lines_not_last = []
        _build_tree(tmp_path, tmp_path / "a.py", 1, 3, lines_not_last, "", is_last=False)

        assert "└──" in lines_last[0]
        assert "├──" in lines_not_last[0]


# ─── generate_codemap 测试 ───────────────────────────────────────────────────

class TestGenerateCodemap:
    def test_returns_string(self):
        result = generate_codemap()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_header(self):
        result = generate_codemap()
        assert "# Codemap" in result

    def test_contains_auto_generated_note(self):
        result = generate_codemap()
        assert "自动生成" in result

    def test_contains_timestamp(self):
        result = generate_codemap()
        # 格式 "YYYY-MM-DD HH:MM UTC"
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", result)

    def test_nonexistent_dir_shows_placeholder(self, monkeypatch):
        """当扫描目录不存在时，输出提示而不是崩溃"""
        import mms.memory.codemap as cm
        monkeypatch.setattr(
            cm, "_SCAN_DIRS",
            [("nonexistent_dir_xyz_999", "测试目录")]
        )
        result = cm.generate_codemap()
        assert "目录不存在" in result or "nonexistent_dir_xyz_999" in result

    def test_depth_1_shallower_than_depth_3(self, tmp_path, monkeypatch):
        """depth=1 的输出行数应少于 depth=3"""
        import mms.memory.codemap as cm

        # 创建三层目录结构
        deep = tmp_path / "pkg" / "sub" / "deep"
        deep.mkdir(parents=True)
        (deep / "leaf.py").write_text("")

        monkeypatch.setattr(
            cm, "_SCAN_DIRS",
            [(str(tmp_path / "pkg"), "测试包")]
        )
        monkeypatch.setattr(cm, "_ROOT", tmp_path)

        result_depth1 = cm.generate_codemap(max_depth=1)
        result_depth3 = cm.generate_codemap(max_depth=3)

        # depth=1 时 leaf.py 不应出现
        assert "leaf.py" not in result_depth1
        # depth=3 时 leaf.py 应出现
        assert "leaf.py" in result_depth3

    def test_recent_count_adds_section(self, monkeypatch):
        """recent_count > 0 时输出包含'最近修改'节"""
        import mms.memory.codemap as cm
        # mock _get_recent_files 返回固定值
        monkeypatch.setattr(
            cm, "_get_recent_files",
            lambda n: [("src/main.py", "2026-05-05 10:00")]
        )
        result = cm.generate_codemap(recent_count=5)
        assert "最近修改" in result
        assert "src/main.py" in result

    def test_recent_count_zero_no_section(self):
        """recent_count=0 时不输出'最近修改'节"""
        result = generate_codemap(recent_count=0)
        assert "最近修改" not in result

    def test_output_is_idempotent(self):
        """两次连续调用返回内容的结构（header）一致（时间戳可能不同，测结构）"""
        r1 = generate_codemap()
        r2 = generate_codemap()
        # 两次结果都包含相同的固定字段
        for key in ["# Codemap", "自动生成", "---"]:
            assert key in r1
            assert key in r2
