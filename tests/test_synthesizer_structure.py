"""
test_synthesizer_structure.py — 验证 synthesizer.py 输出的结构完整性

核心防漏场景：
  - mms synthesize 生成的起手提示词必须包含 ## Scope 节（含表格格式说明）
  - mms synthesize 生成的起手提示词必须包含 ## Testing Plan 节
  - ep-devops 模板已正确注册到 SUPPORTED_TEMPLATES
  - 所有已注册模板的 .md 文件均存在于磁盘
  - _SYNTHESIS_USER prompt 中包含对 Scope/Testing Plan 的明确要求
  - ep_parser 能正确解析含 Scope + Testing Plan 节的 EP 文件

背景：
  EP-124 precheck 报告 ⚠️ 警告「未找到 Scope 文件列表」和「未找到 Testing Plan 声明」，
  根因是 synthesizer 的输出 Prompt 未要求 Scope 表格和 Testing Plan 节，
  导致 LLM 生成的 EP 文件缺失这两节，mms precheck 无法建立基线。
"""

from __future__ import annotations

import sys
import textwrap
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_MMS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_MMS_DIR))
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _MMS_DIR.parent.parent


# ══════════════════════════════════════════════════════════════════════════════
# synthesizer.py Prompt 结构检查
# ══════════════════════════════════════════════════════════════════════════════

class TestSynthesizerPromptStructure:
    """验证 _SYNTHESIS_USER prompt 包含对 Scope/Testing Plan 节的要求"""

    def test_synthesis_user_contains_scope_requirement(self):
        """_SYNTHESIS_USER 必须明确要求 EP 文件包含 ## Scope 节"""
        import mms.workflow.synthesizer as _s
        assert "## Scope" in _s._SYNTHESIS_USER, (
            "_SYNTHESIS_USER prompt 中缺少对 '## Scope' 节的要求，"
            "会导致 LLM 生成的 EP 文件缺失 Scope 表格，mms precheck 报 ⚠️"
        )

    def test_synthesis_user_contains_testing_plan_requirement(self):
        """_SYNTHESIS_USER 必须明确要求 EP 文件包含 ## Testing Plan 节"""
        import mms.workflow.synthesizer as _s
        assert "## Testing Plan" in _s._SYNTHESIS_USER, (
            "_SYNTHESIS_USER prompt 中缺少对 '## Testing Plan' 节的要求，"
            "会导致 LLM 生成的 EP 文件缺失测试声明，mms precheck 报 ⚠️"
        )

    def test_synthesis_user_contains_scope_table_format(self):
        """_SYNTHESIS_USER 应包含 Scope 表格格式示例（| Unit | 操作描述 | 涉及文件 |）"""
        import mms.workflow.synthesizer as _s
        # 表格必须有 Unit 列和文件列（引导 LLM 生成正确格式）
        assert "Unit" in _s._SYNTHESIS_USER and "涉及文件" in _s._SYNTHESIS_USER, (
            "_SYNTHESIS_USER 缺少 Scope 表格格式示例，LLM 可能生成非标准格式"
        )

    def test_synthesis_user_contains_precheck_warning(self):
        """_SYNTHESIS_USER 应提示 Scope/Testing Plan 是 precheck 必要结构"""
        import mms.workflow.synthesizer as _s
        assert "precheck" in _s._SYNTHESIS_USER or "mms precheck" in _s._SYNTHESIS_USER, (
            "_SYNTHESIS_USER 未说明 Scope/Testing Plan 是 precheck 必要结构，"
            "LLM 可能不理解为何要生成这两节"
        )


# ══════════════════════════════════════════════════════════════════════════════
# ep-devops 模板注册检查
# ══════════════════════════════════════════════════════════════════════════════

class TestEpDevopsTemplate:
    """验证 ep-devops 模板已注册且文件存在"""

    def test_ep_devops_in_supported_templates(self):
        """ep-devops 必须在 SUPPORTED_TEMPLATES 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-devops" in _s.SUPPORTED_TEMPLATES, (
            "ep-devops 未注册到 SUPPORTED_TEMPLATES，运维类任务无法使用 --template ep-devops"
        )

    def test_ep_devops_template_file_exists(self):
        """ep-devops.md 模板文件必须存在于磁盘"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-devops.md"
        assert template_path.exists(), (
            f"ep-devops.md 模板文件不存在：{template_path}"
        )

    def test_ep_devops_template_contains_scope_section(self):
        """ep-devops.md 必须包含 ## Scope 节（范例）"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-devops.md"
        if not template_path.exists():
            pytest.skip("ep-devops.md 不存在")
        content = template_path.read_text(encoding="utf-8")
        assert "## Scope" in content, "ep-devops.md 缺少 ## Scope 节范例"

    def test_ep_devops_template_contains_testing_plan_section(self):
        """ep-devops.md 必须包含 ## Testing Plan 节（范例）"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-devops.md"
        if not template_path.exists():
            pytest.skip("ep-devops.md 不存在")
        content = template_path.read_text(encoding="utf-8")
        assert "## Testing Plan" in content, "ep-devops.md 缺少 ## Testing Plan 节范例"

    def test_ep_devops_in_codemap_sections(self):
        """ep-devops 必须在 _TEMPLATE_CODEMAP_SECTIONS 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-devops" in _s._TEMPLATE_CODEMAP_SECTIONS, (
            "ep-devops 未注册到 _TEMPLATE_CODEMAP_SECTIONS，codemap 截取逻辑会跳过它"
        )

    def test_ep_devops_in_e2e_keywords(self):
        """ep-devops 必须在 _TEMPLATE_E2E_KEYWORDS 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-devops" in _s._TEMPLATE_E2E_KEYWORDS, (
            "ep-devops 未注册到 _TEMPLATE_E2E_KEYWORDS，e2e 追踪切片会跳过它"
        )


# ══════════════════════════════════════════════════════════════════════════════
# ep-others 模板注册检查
# ══════════════════════════════════════════════════════════════════════════════

class TestEpOthersTemplate:
    """验证 ep-others 模板已注册且文件存在"""

    def test_ep_others_in_supported_templates(self):
        """ep-others 必须在 SUPPORTED_TEMPLATES 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-others" in _s.SUPPORTED_TEMPLATES, (
            "ep-others 未注册到 SUPPORTED_TEMPLATES，通用兜底任务无法使用 --template ep-others"
        )

    def test_ep_others_template_file_exists(self):
        """ep-others.md 模板文件必须存在于磁盘"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-others.md"
        assert template_path.exists(), (
            f"ep-others.md 模板文件不存在：{template_path}"
        )

    def test_ep_others_template_contains_scope_section(self):
        """ep-others.md 必须包含 ## Scope 节（范例）"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-others.md"
        if not template_path.exists():
            pytest.skip("ep-others.md 不存在")
        content = template_path.read_text(encoding="utf-8")
        assert "## Scope" in content, "ep-others.md 缺少 ## Scope 节范例"

    def test_ep_others_template_contains_testing_plan_section(self):
        """ep-others.md 必须包含 ## Testing Plan 节（范例）"""
        template_path = _ROOT / "docs" / "memory" / "templates" / "ep-others.md"
        if not template_path.exists():
            pytest.skip("ep-others.md 不存在")
        content = template_path.read_text(encoding="utf-8")
        assert "## Testing Plan" in content, "ep-others.md 缺少 ## Testing Plan 节范例"

    def test_ep_others_in_codemap_sections(self):
        """ep-others 必须在 _TEMPLATE_CODEMAP_SECTIONS 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-others" in _s._TEMPLATE_CODEMAP_SECTIONS, (
            "ep-others 未注册到 _TEMPLATE_CODEMAP_SECTIONS，codemap 截取逻辑会跳过它"
        )

    def test_ep_others_in_e2e_keywords(self):
        """ep-others 必须在 _TEMPLATE_E2E_KEYWORDS 中注册"""
        import mms.workflow.synthesizer as _s
        assert "ep-others" in _s._TEMPLATE_E2E_KEYWORDS, (
            "ep-others 未注册到 _TEMPLATE_E2E_KEYWORDS，e2e 追踪切片会跳过它"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 所有模板的一致性检查
# ══════════════════════════════════════════════════════════════════════════════

class TestAllTemplatesConsistency:
    """验证所有已注册模板的 .md 文件存在且包含必要节"""

    def test_all_registered_templates_have_files(self):
        """所有 SUPPORTED_TEMPLATES 中的模板必须有对应的 .md 文件"""
        import mms.workflow.synthesizer as _s
        templates_dir = _ROOT / "docs" / "memory" / "templates"
        missing = []
        for name in _s.SUPPORTED_TEMPLATES:
            path = templates_dir / f"{name}.md"
            if not path.exists():
                missing.append(name)
        assert not missing, (
            f"以下已注册模板缺少对应 .md 文件：{missing}\n"
            f"模板目录：{templates_dir}"
        )

    def test_all_templates_contain_scope_section(self):
        """所有 EP 模板都应包含 ## Scope 节（引导 LLM 生成标准格式）"""
        import mms.workflow.synthesizer as _s
        templates_dir = _ROOT / "docs" / "memory" / "templates"
        missing_scope = []
        for name in _s.SUPPORTED_TEMPLATES:
            path = templates_dir / f"{name}.md"
            if path.exists():
                content = path.read_text(encoding="utf-8")
                if "## Scope" not in content:
                    missing_scope.append(name)
        assert not missing_scope, (
            f"以下模板缺少 ## Scope 节：{missing_scope}\n"
            "缺少此节会导致 LLM 生成的 EP 文件无 Scope 表格，mms precheck 报 ⚠️"
        )

    def test_all_templates_contain_testing_plan_section(self):
        """所有 EP 模板都应包含 ## Testing Plan 节（引导 LLM 生成标准格式）"""
        import mms.workflow.synthesizer as _s
        templates_dir = _ROOT / "docs" / "memory" / "templates"
        missing_testing = []
        for name in _s.SUPPORTED_TEMPLATES:
            path = templates_dir / f"{name}.md"
            if path.exists():
                content = path.read_text(encoding="utf-8")
                if "## Testing Plan" not in content:
                    missing_testing.append(name)
        assert not missing_testing, (
            f"以下模板缺少 ## Testing Plan 节：{missing_testing}\n"
            "缺少此节会导致 LLM 生成的 EP 文件无测试声明，mms precheck 报 ⚠️"
        )


# ══════════════════════════════════════════════════════════════════════════════
# ep_parser 解析能力回归测试
# ══════════════════════════════════════════════════════════════════════════════

class TestEpParserScopeAndTestingPlan:
    """验证 ep_parser 能正确解析含 Scope + Testing Plan 节的 EP 文件"""

    _DEVOPS_EP = textwrap.dedent("""\
        # EP-124: 本地调试环境配置

        ## 背景与目标

        在不构建新镜像的情况下，实现前后端本地热重载调试。

        ## Scope

        | Unit | 操作描述 | 涉及文件 |
        |------|---------|---------|
        | U1   | MySQL 端口转发 | `（kubectl 命令，无代码变更）` |
        | U2   | 本地后端启动 | `backend/.env.local` |
        | U3   | 快速启动脚本 | `scripts/dev-local.sh` |

        ## Testing Plan

        （本 EP 为运维/调试类，无新增自动化测试文件；验收通过手动验证清单完成）
    """)

    def test_parses_scope_units_from_devops_ep(self, tmp_path):
        """ep_parser 应能从运维类 EP 的 Scope 表格中解析出 Unit 列表"""
        from mms.workflow.ep_parser import parse_ep_file
        ep_file = tmp_path / "EP-124_test.md"
        ep_file.write_text(self._DEVOPS_EP, encoding="utf-8")
        parsed = parse_ep_file(ep_file)
        assert len(parsed.scope_units) >= 2, (
            f"应至少解析出 2 个 Unit，实际：{len(parsed.scope_units)}\n"
            f"解析结果：{parsed.scope_units}"
        )
        unit_ids = [u.unit_id for u in parsed.scope_units]
        assert "U1" in unit_ids and "U2" in unit_ids, (
            f"应包含 U1 和 U2，实际：{unit_ids}"
        )

    def test_parses_testing_plan_section_exists(self, tmp_path):
        """ep_parser 解析后 testing_files 即使为空，Testing Plan 节也应被识别"""
        from mms.workflow.ep_parser import parse_ep_file, _extract_sections
        ep_file = tmp_path / "EP-124_test.md"
        ep_file.write_text(self._DEVOPS_EP, encoding="utf-8")
        content = ep_file.read_text(encoding="utf-8")
        sections = _extract_sections(content)
        # Testing Plan 节应该被解析到（即使文件列表为空）
        assert "testing" in sections, (
            f"_extract_sections 未识别到 Testing Plan 节\n"
            f"实际 sections keys：{list(sections.keys())}"
        )

    def test_standard_ep_with_both_sections_parses_correctly(self, tmp_path):
        """含完整 Scope 表格和 Testing Plan 文件列表的 EP 应被正确解析"""
        full_ep = textwrap.dedent("""\
            # EP-999: 完整结构 EP 测试

            ## Scope

            | Unit | 操作描述 | 涉及文件 |
            |------|---------|---------|
            | U1   | 新增 Service | `backend/app/services/control/test_svc.py` |
            | U2   | 新增 API | `backend/app/api/v1/endpoints/test_api.py` |

            ## Testing Plan

            - `backend/tests/unit/services/test_svc.py` — Service 单元测试
            - `backend/tests/unit/api/test_api_endpoint.py` — API 单元测试
        """)
        from mms.workflow.ep_parser import parse_ep_file
        ep_file = tmp_path / "EP-999_full.md"
        ep_file.write_text(full_ep, encoding="utf-8")
        parsed = parse_ep_file(ep_file)

        assert len(parsed.scope_units) == 2, (
            f"应解析出 2 个 Unit，实际：{len(parsed.scope_units)}"
        )
        assert len(parsed.testing_files) == 2, (
            f"应解析出 2 个测试文件，实际：{parsed.testing_files}"
        )
        assert any("test_svc.py" in f for f in parsed.testing_files), (
            "应包含 test_svc.py 测试文件"
        )
