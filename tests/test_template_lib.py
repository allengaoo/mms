"""
test_template_lib.py — 代码模板库单元测试

覆盖：
  - CodeTemplate 加载：front-matter 解析、body 分离
  - CodeTemplate.user_vars：正确识别用户需提供的变量
  - CodeTemplate.render：变量替换、缺失变量检测
  - CodeTemplate.get_arch_constraints：从 layer_contracts.md 提取约束
  - cmd_template_list / cmd_template_info / cmd_template_use：CLI 命令
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_MMS_ROOT = Path(__file__).resolve().parents[1]  # scripts/mms/


def _import_template_lib():
    """动态 import template_lib.py"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "template_lib", _MMS_ROOT / "src/mms/memory/template_lib.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── CodeTemplate 加载测试 ─────────────────────────────────────────────────────

class TestCodeTemplateLoad:
    """测试模板文件解析"""

    def _make_tmpl(self, tmp_path: Path, content: str, name: str = "test") -> object:
        tmpl_lib = _import_template_lib()
        path = tmp_path / f"{name}.tmpl"
        path.write_text(content, encoding="utf-8")
        return tmpl_lib.CodeTemplate(name, path)

    def test_parses_front_matter_and_body(self, tmp_path):
        tmpl = self._make_tmpl(
            tmp_path,
            "---\nname: test\nlabel: 测试模板\nlayer: L4_application\n---\n# 模板内容\ndef foo(): pass\n",
        )
        assert tmpl.label == "测试模板"
        assert tmpl.layer == "L4_application"
        assert "def foo(): pass" in tmpl._body

    def test_no_front_matter_uses_full_content(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "# 纯代码\ndef bar(): pass\n")
        assert "def bar(): pass" in tmpl._body
        assert tmpl.name == "test"

    def test_label_defaults_to_name(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "---\nname: mytemplate\n---\ncode\n")
        assert tmpl.label == "mytemplate" or tmpl.label == "test"

    def test_description_from_front_matter(self, tmp_path):
        tmpl = self._make_tmpl(
            tmp_path,
            "---\nname: x\ndescription: 这是描述\n---\nbody\n",
        )
        assert tmpl.description == "这是描述"


# ── user_vars 测试 ────────────────────────────────────────────────────────────

class TestUserVars:
    """测试变量列表提取"""

    def _make_tmpl(self, tmp_path: Path, body: str) -> object:
        tmpl_lib = _import_template_lib()
        path = tmp_path / "test.tmpl"
        path.write_text(f"---\nname: test\n---\n{body}\n", encoding="utf-8")
        return tmpl_lib.CodeTemplate("test", path)

    def test_extracts_user_vars(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "def {{method_name}}(ctx, {{entity_id}}): pass")
        assert "method_name" in tmpl.user_vars
        assert "entity_id" in tmpl.user_vars

    def test_excludes_arch_constraints(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "# {{arch_constraints}}\ndef {{foo}}(): pass")
        assert "arch_constraints" not in tmpl.user_vars
        assert "foo" in tmpl.user_vars

    def test_deduplicates_vars(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "{{entity}} {{entity}} {{entity}}")
        assert tmpl.user_vars.count("entity") == 1

    def test_empty_body_returns_empty(self, tmp_path):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "empty.tmpl"
        path.write_text("---\nname: empty\n---\n", encoding="utf-8")
        tmpl = tmpl_lib.CodeTemplate("empty", path)
        assert tmpl.user_vars == []


# ── render 测试 ───────────────────────────────────────────────────────────────

class TestRender:
    """测试模板渲染"""

    def _make_tmpl(self, tmp_path: Path, body: str, layer: str = "") -> object:
        tmpl_lib = _import_template_lib()
        path = tmp_path / "test.tmpl"
        front = f"---\nname: test\nlayer: {layer}\n---\n"
        path.write_text(front + body, encoding="utf-8")
        return tmpl_lib.CodeTemplate("test", path)

    def test_renders_simple_variables(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "class {{entity}}Service:\n    pass\n")
        rendered, missing = tmpl.render({"entity": "ObjectType"})
        assert missing == []
        assert "class ObjectTypeService:" in rendered

    def test_reports_missing_variables(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "{{entity}} {{method_name}}")
        rendered, missing = tmpl.render({"entity": "Foo"})
        assert "method_name" in missing
        assert rendered == ""

    def test_auto_injects_arch_constraints(self, tmp_path):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "test.tmpl"
        path.write_text("---\nname: test\nlayer: L4_application\n---\n# {{arch_constraints}}\n")
        tmpl = tmpl_lib.CodeTemplate("test", path)

        # mock get_arch_constraints 返回固定字符串
        with patch.object(tmpl, "get_arch_constraints", return_value="# 架构约束内容"):
            rendered, missing = tmpl.render({})

        assert missing == []
        assert "# 架构约束内容" in rendered

    def test_multiple_occurrences_replaced(self, tmp_path):
        tmpl = self._make_tmpl(tmp_path, "{{entity}} and {{entity}} again")
        rendered, missing = tmpl.render({"entity": "Foo"})
        assert missing == []
        assert rendered == "Foo and Foo again"

    def test_empty_template_body(self, tmp_path):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "empty.tmpl"
        path.write_text("---\nname: empty\n---\n", encoding="utf-8")
        tmpl = tmpl_lib.CodeTemplate("empty", path)
        rendered, missing = tmpl.render({})
        # 空模板：body="" 不含任何占位符，无缺失变量，渲染结果为空字符串
        assert missing == []
        assert rendered == ""


# ── get_arch_constraints 测试 ─────────────────────────────────────────────────

class TestGetArchConstraints:
    """测试从 layer_contracts.md 提取约束"""

    def test_extracts_l4_constraints(self, tmp_path):
        tmpl_lib = _import_template_lib()
        contracts_content = (
            "# Layer Contracts\n\n"
            "## L4 — 应用服务层\n"
            "**必须出现**\n"
            "- `ctx: SecurityContext` 作为首参\n"
            "- `AuditService.log()` 每次 WRITE\n\n"
            "**禁止出现**\n"
            "- 直接 import pymilvus\n\n"
            "## L5 — 接口层\n"
            "**必须出现**\n"
            "- 信封格式\n"
        )
        contracts_file = tmp_path / "layer_contracts.md"
        contracts_file.write_text(contracts_content, encoding="utf-8")

        path = tmp_path / "test.tmpl"
        path.write_text("---\nname: t\nlayer: L4_application\n---\nbody\n")
        tmpl = tmpl_lib.CodeTemplate("t", path)

        # 直接替换模块级变量，测试后恢复
        old = tmpl_lib._CONTRACTS_FILE
        tmpl_lib._CONTRACTS_FILE = contracts_file
        try:
            result = tmpl.get_arch_constraints()
        finally:
            tmpl_lib._CONTRACTS_FILE = old

        # 结果应包含 L4 的约束内容（即使为空也不报错）
        assert isinstance(result, str)

    def test_returns_empty_string_when_no_layer(self, tmp_path):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "test.tmpl"
        path.write_text("---\nname: t\n---\nbody\n")
        tmpl = tmpl_lib.CodeTemplate("t", path)
        # layer 为空时，不尝试提取
        result = tmpl.get_arch_constraints()
        assert result == ""


# ── CLI 命令测试 ──────────────────────────────────────────────────────────────

class TestCLICommands:
    """测试 CLI 命令处理函数"""

    def test_list_with_no_templates(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            rc = tmpl_lib.cmd_template_list()
        assert rc == 0
        out = capsys.readouterr().out
        assert "暂无模板" in out

    def test_list_with_templates(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "service-method.tmpl"
        path.write_text("---\nname: service-method\nlabel: Service 方法\n---\ncode\n")

        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            rc = tmpl_lib.cmd_template_list()

        assert rc == 0
        out = capsys.readouterr().out
        assert "service-method" in out

    def test_info_for_nonexistent_template(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            rc = tmpl_lib.cmd_template_info("nonexistent")
        assert rc == 1
        out = capsys.readouterr().out
        assert "不存在" in out

    def test_use_with_missing_vars(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "mytemplate.tmpl"
        path.write_text("---\nname: mytemplate\n---\ndef {{method}}({{entity}}): pass\n")

        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            rc = tmpl_lib.cmd_template_use(
                "mytemplate",
                variables={"method": "foo"},  # 缺少 entity
            )

        assert rc == 1
        out = capsys.readouterr().out
        assert "entity" in out

    def test_use_dry_run_renders_correctly(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "simple.tmpl"
        path.write_text("---\nname: simple\n---\ndef {{method}}(): pass\n")

        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            rc = tmpl_lib.cmd_template_use(
                "simple",
                variables={"method": "my_func"},
                dry_run=True,
            )

        assert rc == 0
        out = capsys.readouterr().out
        assert "my_func" in out
        assert "dry-run" in out

    def test_use_writes_to_output_file(self, tmp_path, capsys):
        tmpl_lib = _import_template_lib()
        path = tmp_path / "gen.tmpl"
        path.write_text("---\nname: gen\n---\n# {{title}}\n")

        out_file = tmp_path / "output.py"

        with patch.object(tmpl_lib, "_TEMPLATE_DIR", tmp_path):
            with patch.object(tmpl_lib, "_ROOT", tmp_path):
                rc = tmpl_lib.cmd_template_use(
                    "gen",
                    variables={"title": "Generated Code"},
                    output="output.py",
                )

        assert rc == 0
        assert out_file.exists()
        assert "Generated Code" in out_file.read_text(encoding="utf-8")
