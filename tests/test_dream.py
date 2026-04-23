"""
test_dream.py — autoDream 引擎单元测试

覆盖：
  - get_ep_sections：EP 文件章节提取
  - parse_dream_response：LLM 返回解析
  - save_draft：草稿文件保存格式
  - promote_draft：草稿提升逻辑（mock 用户输入）
  - run_dream：list / dry_run 模式（不调用 LLM）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── 路径常量 ──────────────────────────────────────────────────────────────────

_MMS_ROOT = Path(__file__).resolve().parents[1]  # scripts/mms/
_DREAM_MODULE = _MMS_ROOT / "src/mms/memory/dream.py"


def _import_dream():
    """动态 import dream.py（避免全局 import 时的路径问题）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dream", _DREAM_MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── get_ep_sections 测试 ──────────────────────────────────────────────────────

class TestGetEpSections:
    """测试 EP 文件章节提取"""

    def test_extracts_surprises(self, tmp_path):
        dream = _import_dream()
        ep_file = tmp_path / "EP-999_Test.md"
        ep_file.write_text(
            "# EP-999 · 测试\n\n"
            "## Surprises & Discoveries\n"
            "发现了一个 Python 前向引用的坑。\n\n"
            "## Decision Log\n"
            "决定使用 Strategy B 事务策略。\n\n"
            "## Other Section\n"
            "其他内容。\n",
            encoding="utf-8",
        )

        with patch.object(dream, "_EP_DIR", tmp_path):
            result = dream.get_ep_sections("EP-999")

        assert "Python 前向引用" in result["surprises"]
        assert "Strategy B" in result["decisions"]
        assert result["outcomes"] == ""

    def test_returns_empty_for_missing_ep(self, tmp_path):
        dream = _import_dream()
        with patch.object(dream, "_EP_DIR", tmp_path):
            result = dream.get_ep_sections("EP-000")

        assert result == {"surprises": "", "decisions": "", "outcomes": ""}

    def test_extracts_outcomes(self, tmp_path):
        dream = _import_dream()
        ep_file = tmp_path / "EP-999_Test.md"
        ep_file.write_text(
            "# EP-999\n\n"
            "## Outcomes & Retrospective\n"
            "本次 EP 顺利完成，所有测试通过。\n",
            encoding="utf-8",
        )

        with patch.object(dream, "_EP_DIR", tmp_path):
            result = dream.get_ep_sections("EP-999")

        assert "顺利完成" in result["outcomes"]

    def test_case_insensitive_match(self, tmp_path):
        dream = _import_dream()
        ep_file = tmp_path / "EP-999_Test.md"
        ep_file.write_text(
            "# EP-999\n\n"
            "## SURPRISES & DISCOVERIES\n"
            "大写标题也能匹配。\n",
            encoding="utf-8",
        )

        with patch.object(dream, "_EP_DIR", tmp_path):
            result = dream.get_ep_sections("EP-999")

        assert "大写标题也能匹配" in result["surprises"]


# ── parse_dream_response 测试 ─────────────────────────────────────────────────

class TestParseDreamResponse:
    """测试 LLM 返回内容的结构化解析"""

    def test_parses_single_draft(self):
        dream = _import_dream()
        raw = """
---MEMORY-DRAFT---
title: Python 模块级前向引用陷阱
type: anti-pattern
layer: L5_interface
dimension: D10
tags: [python, import, forward-reference]
description: Python 模块级字典引用未定义函数时抛出 NameError

## WHERE（适用场景）
在 cli.py 中定义命令映射字典时，函数定义顺序影响运行时加载。

## HOW（核心实现）
将 _COMMAND_HANDLERS 字典移到所有 cmd_* 函数定义之后。

## WHEN（触发条件/危险信号）
收到 NameError: name 'cmd_xxx' is not defined 时。
---MEMORY-DRAFT---
"""
        drafts = dream.parse_dream_response(raw)

        assert len(drafts) == 1
        d = drafts[0]
        assert d["title"] == "Python 模块级前向引用陷阱"
        assert d["type"] == "anti-pattern"
        assert d["layer"] == "L5_interface"
        assert "python" in d["tags"]
        assert "Python" in d["where"] or "cli.py" in d["where"]
        assert "NameError" in d["when"]

    def test_returns_empty_for_no_new_knowledge(self):
        dream = _import_dream()
        raw = "NO_NEW_KNOWLEDGE"
        drafts = dream.parse_dream_response(raw)
        assert drafts == []

    def test_returns_empty_for_empty_input(self):
        dream = _import_dream()
        assert dream.parse_dream_response("") == []

    def test_parses_multiple_drafts(self):
        dream = _import_dream()
        raw = """
---MEMORY-DRAFT---
title: 草稿一
type: lesson
layer: L4_application
dimension: D2
tags: [test]
description: 第一条

## WHERE（适用场景）
场景一

## HOW（核心实现）
做法一

## WHEN（触发条件/危险信号）
信号一
---MEMORY-DRAFT---
---MEMORY-DRAFT---
title: 草稿二
type: pattern
layer: L2_infrastructure
dimension: D4
tags: [test2]
description: 第二条

## WHERE（适用场景）
场景二

## HOW（核心实现）
做法二

## WHEN（触发条件/危险信号）
信号二
---MEMORY-DRAFT---
"""
        drafts = dream.parse_dream_response(raw)
        assert len(drafts) == 2
        assert drafts[0]["title"] == "草稿一"
        assert drafts[1]["title"] == "草稿二"

    def test_skips_blocks_without_title(self):
        dream = _import_dream()
        raw = """
---MEMORY-DRAFT---
type: lesson
layer: L4_application
dimension: D2
tags: []
description: 没有 title 字段

## WHERE
场景
## HOW
做法
## WHEN
信号
---MEMORY-DRAFT---
"""
        # 无 title 的块应被跳过
        drafts = dream.parse_dream_response(raw)
        assert len(drafts) == 0


# ── save_draft 测试 ───────────────────────────────────────────────────────────

class TestSaveDraft:
    """测试草稿文件保存"""

    def test_saves_valid_draft_file(self, tmp_path):
        dream = _import_dream()
        draft_data = {
            "title": "测试草稿",
            "type": "lesson",
            "layer": "L4_application",
            "dimension": "D2",
            "tags": ["test", "mms"],
            "description": "这是一条测试草稿",
            "where": "在测试环境中",
            "how": "按照测试步骤操作",
            "when": "当测试失败时",
        }

        with patch.object(dream, "_DREAM_DIR", tmp_path):
            path = dream.save_draft("EP-999", draft_data)

        assert path.exists()
        content = path.read_text(encoding="utf-8")

        # 验证 front-matter 字段
        assert "source_ep: EP-999" in content
        assert "layer: L4_application" in content
        assert "type: lesson" in content
        assert "status: draft" in content
        assert "测试草稿" in content
        assert "## WHERE" in content
        assert "## HOW" in content
        assert "## WHEN" in content

    def test_increments_sequence_number(self, tmp_path):
        dream = _import_dream()
        draft_data = {
            "title": "草稿",
            "type": "lesson",
            "layer": "L4_application",
            "dimension": "D2",
            "tags": [],
            "description": "",
            "where": "",
            "how": "",
            "when": "",
        }

        with patch.object(dream, "_DREAM_DIR", tmp_path):
            path1 = dream.save_draft("EP-999", draft_data)
            path2 = dream.save_draft("EP-999", draft_data)

        # 两个文件名不同（序号递增）
        assert path1.name != path2.name
        assert path1.exists()
        assert path2.exists()


# ── run_dream 模式测试 ────────────────────────────────────────────────────────

class TestRunDreamModes:
    """测试 run_dream 的非 LLM 模式（list / dry_run）"""

    def test_list_mode_with_no_drafts(self, tmp_path, capsys):
        dream = _import_dream()

        with patch.object(dream, "_DREAM_DIR", tmp_path):
            rc = dream.run_dream(list_drafts=True)

        assert rc == 0
        out = capsys.readouterr().out
        assert "暂无草稿" in out

    def test_list_mode_with_drafts(self, tmp_path, capsys):
        dream = _import_dream()
        # 创建一个虚拟草稿文件
        draft = tmp_path / "DRAFT-2026-04-16-01.md"
        draft.write_text(
            "---\nsource_ep: EP-999\n---\n# 测试标题\n",
            encoding="utf-8",
        )

        with patch.object(dream, "_DREAM_DIR", tmp_path):
            rc = dream.run_dream(list_drafts=True)

        assert rc == 0
        out = capsys.readouterr().out
        assert "DRAFT-2026-04-16-01" in out

    def test_dry_run_mode_skips_llm(self, tmp_path, capsys):
        dream = _import_dream()
        # dry_run 不应调用 LLM，也不应保存文件
        with (
            patch.object(dream, "_DREAM_DIR", tmp_path),
            patch.object(dream, "_EP_DIR", tmp_path),
            patch.object(dream, "_call_llm", return_value="SHOULD_NOT_BE_CALLED") as mock_llm,
        ):
            # 创建虚假 EP 文件
            ep_file = tmp_path / "EP-999_Test.md"
            ep_file.write_text(
                "## Surprises & Discoveries\n有内容。\n",
                encoding="utf-8",
            )
            rc = dream.run_dream(ep_id="EP-999", dry_run=True)

        # dry_run 模式：LLM 不应被调用
        mock_llm.assert_not_called()
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_promote_mode_with_no_drafts(self, tmp_path, capsys):
        dream = _import_dream()

        with patch.object(dream, "_DREAM_DIR", tmp_path):
            rc = dream.run_dream(promote=True)

        assert rc == 0
        out = capsys.readouterr().out
        assert "暂无待审核草稿" in out
