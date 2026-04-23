"""
test_ep_parser.py — EP Markdown 解析器测试

使用内嵌 fixture（避免依赖特定 EP 文件路径）。
"""
import textwrap
import tempfile
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mms.workflow.ep_parser import (
    parse_ep_file, _extract_sections, _parse_scope_table,
    _parse_testing_files, _extract_ep_id, _extract_title,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

SIMPLE_EP = textwrap.dedent("""\
# EP-117 · DAG 任务编排与 mms unit 命令实现

> 状态：IN PROGRESS | 创建：2026-04-17

## 背景与目标

实现 DAG-based 任务编排。

## Scope（影响范围）

| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | DAG 数据结构定义 | `scripts/mms/dag_model.py` |
| U2 | EP Markdown 解析器 | `scripts/mms/ep_parser.py` |
| U3 | 原子性验证器 | `scripts/mms/atomicity_check.py` |

## Testing Plan

- `scripts/mms/tests/test_dag_model.py`
- `scripts/mms/tests/test_ep_parser.py`

## DAG Sketch

```
U1(dag_model) → U3(atomicity) → U5(generate)
U2(ep_parser) → U4(context)  → U6(unit_cmd)
```

## Surprises & Discoveries

<!-- 未填写 -->
""")

EP_NO_TABLE = textwrap.dedent("""\
# EP-200 · 简单 Bug 修复

## Purpose

修复一个小 Bug。

### U1: 修复 foo.py
修改 foo 函数。

### U2: 添加测试
添加测试用例。
""")


# ── _extract_ep_id ────────────────────────────────────────────────────────────

class TestExtractEpId:
    def test_from_filename(self):
        assert _extract_ep_id("", "EP-117_foo_bar.md") == "EP-117"

    def test_from_content(self):
        content = "# EP-099 · Some Title\n..."
        assert _extract_ep_id(content, "unknown.md") == "EP-099"

    def test_fallback(self):
        assert _extract_ep_id("no ep here", "readme.md") == "EP-???"


# ── _extract_title ────────────────────────────────────────────────────────────

class TestExtractTitle:
    def test_strips_ep_prefix(self):
        content = "# EP-117 · DAG 任务编排\n..."
        assert "EP-" not in _extract_title(content)
        assert "DAG 任务编排" in _extract_title(content)

    def test_no_header_returns_empty(self):
        assert _extract_title("no header here") == ""


# ── _extract_sections ─────────────────────────────────────────────────────────

class TestExtractSections:
    def test_extracts_scope(self):
        sections = _extract_sections(SIMPLE_EP)
        assert "scope" in sections
        assert "| U1 |" in sections["scope"]

    def test_extracts_testing(self):
        sections = _extract_sections(SIMPLE_EP)
        assert "testing" in sections

    def test_extracts_dag_sketch(self):
        sections = _extract_sections(SIMPLE_EP)
        assert "dag_sketch" in sections
        assert "U1" in sections["dag_sketch"]


# ── _parse_scope_table ────────────────────────────────────────────────────────

class TestParseScopeTable:
    def test_parses_three_units(self):
        sections = _extract_sections(SIMPLE_EP)
        units = _parse_scope_table(sections["scope"])
        assert len(units) == 3

    def test_unit_ids_extracted(self):
        sections = _extract_sections(SIMPLE_EP)
        units = _parse_scope_table(sections["scope"])
        ids = [u.unit_id for u in units]
        assert "U1" in ids
        assert "U2" in ids
        assert "U3" in ids

    def test_files_extracted(self):
        sections = _extract_sections(SIMPLE_EP)
        units = _parse_scope_table(sections["scope"])
        u1 = next(u for u in units if u.unit_id == "U1")
        assert "scripts/mms/dag_model.py" in u1.files

    def test_descriptions_extracted(self):
        sections = _extract_sections(SIMPLE_EP)
        units = _parse_scope_table(sections["scope"])
        u1 = next(u for u in units if u.unit_id == "U1")
        assert "DAG" in u1.description or "数据" in u1.description


# ── _parse_testing_files ──────────────────────────────────────────────────────

class TestParseTestingFiles:
    def test_extracts_test_files(self):
        sections = _extract_sections(SIMPLE_EP)
        files = _parse_testing_files(sections["testing"])
        assert len(files) == 2
        assert "scripts/mms/tests/test_dag_model.py" in files
        assert "scripts/mms/tests/test_ep_parser.py" in files

    def test_no_duplicates(self):
        text = "`tests/foo.py`\n`tests/foo.py`\n`tests/bar.py`"
        files = _parse_testing_files(text)
        assert len(files) == len(set(files))


# ── parse_ep_file ─────────────────────────────────────────────────────────────

class TestParseEpFile:
    def test_full_parse(self, tmp_path):
        ep_file = tmp_path / "EP-117_test.md"
        ep_file.write_text(SIMPLE_EP, encoding="utf-8")
        parsed = parse_ep_file(ep_file)

        assert parsed.ep_id == "EP-117"
        assert "DAG" in parsed.title
        assert len(parsed.scope_units) == 3
        assert len(parsed.testing_files) == 2
        assert parsed.dag_sketch is not None
        assert "U1" in parsed.dag_sketch

    def test_fallback_no_table(self, tmp_path):
        ep_file = tmp_path / "EP-200_test.md"
        ep_file.write_text(EP_NO_TABLE, encoding="utf-8")
        parsed = parse_ep_file(ep_file)

        assert parsed.ep_id == "EP-200"
        # 回退解析应找到 U1, U2
        ids = [u.unit_id for u in parsed.scope_units]
        assert "U1" in ids
        assert "U2" in ids

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_ep_file(tmp_path / "nonexistent.md")
