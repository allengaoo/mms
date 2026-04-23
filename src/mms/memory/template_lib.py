#!/usr/bin/env python3
"""
template_lib.py — MMS 代码模板库

为小模型提供「填空式」代码骨架，降低幻觉率。
模板使用 {{variable_name}} 占位符，arch_constraints 自动从 layer_contracts.md 注入。

模板文件格式（*.tmpl）：
  Part 1: YAML front-matter（元数据，含 name/label/layer/required_vars/description）
  分隔符: ---
  Part 2: 代码模板体（含 {{variable_name}} 占位符）

用法：
    mms template list
    mms template info service-method
    mms template use service-method --var entity=ObjectType --var method_name=create_object
    mms template use api-endpoint --var resource=object_type --output backend/app/api/v1/endpoints/object_type.py
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_TEMPLATE_DIR = _ROOT / "docs" / "memory" / "templates" / "code"
_CONTRACTS_FILE = _ROOT / "docs" / "context" / "layer_contracts.md"

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_G}✅{_X} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_Y}⚠️{_X}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_R}❌{_X} {msg}")


def _info(msg: str) -> None:
    print(f"  {_D}ℹ️  {msg}{_X}")


# ── 模板数据结构 ──────────────────────────────────────────────────────────────

class CodeTemplate:
    """单个代码模板（从 .tmpl 文件加载）"""

    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        self._meta: Dict = {}
        self._body: str = ""
        self._load()

    def _load(self) -> None:
        """解析模板文件：YAML front-matter + --- + 模板体"""
        raw = self.path.read_text(encoding="utf-8")

        # 检测 front-matter（以 --- 开头，找第二个 ---）
        if raw.startswith("---\n") or raw.startswith("---\r\n"):
            rest = raw[4:]
            end_markers = ["\n---\n", "\n---\r\n"]
            end_idx = -1
            for marker in end_markers:
                idx = rest.find(marker)
                if idx != -1:
                    end_idx = idx
                    marker_len = len(marker)
                    break

            if end_idx != -1:
                front_raw = rest[:end_idx]
                self._body = rest[end_idx + marker_len:].strip()
                self._meta = self._parse_yaml(front_raw)
                return

        # 无 front-matter
        self._meta = {"name": self.name, "label": self.name}
        self._body = raw

    def _parse_yaml(self, text: str) -> Dict:
        """解析 YAML front-matter（优先使用 yaml 库，降级为手动解析）"""
        try:
            import yaml  # type: ignore[import]
            return yaml.safe_load(text) or {}
        except ImportError:
            result: Dict = {}
            for line in text.splitlines():
                stripped = line.strip()
                if ":" in stripped and not stripped.startswith("-"):
                    k, _, v = stripped.partition(":")
                    result[k.strip()] = v.strip()
            return result

    @property
    def label(self) -> str:
        return self._meta.get("label", self.name)

    @property
    def layer(self) -> str:
        return self._meta.get("layer", "")

    @property
    def description(self) -> str:
        return self._meta.get("description", "")

    @property
    def user_vars(self) -> List[str]:
        """返回模板中需要用户提供的变量（排除 arch_constraints）"""
        placeholders = re.findall(r"\{\{(\w+)\}\}", self._body)
        seen = set()
        result = []
        for p in placeholders:
            if p != "arch_constraints" and p not in seen:
                seen.add(p)
                result.append(p)
        return result

    def get_arch_constraints(self) -> str:
        """从 layer_contracts.md 提取当前 layer 的架构约束摘要"""
        if not _CONTRACTS_FILE.exists() or not self.layer:
            return ""

        content = _CONTRACTS_FILE.read_text(encoding="utf-8")
        layer_short = self.layer.split("_")[0]  # "L4_application" → "L4"

        # 提取对应层的章节
        pattern = rf"##\s*{re.escape(layer_short)}[^\n]*\n(.*?)(?=\n##\s*[LCA]|\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if not match:
            return f"# （layer_contracts.md 中未找到 {layer_short} 的约束定义）"

        section = match.group(1)

        # 只提取「必须出现」和「禁止出现」部分
        must_m = re.search(r"\*\*必须出现\*\*.*?(?=\*\*禁止|\*\*说明|\Z)", section, re.DOTALL)
        must_not_m = re.search(r"\*\*禁止出现\*\*.*?(?=\*\*|\Z)", section, re.DOTALL)

        parts = []
        if must_m:
            parts.append("# 架构约束（必须）\n" + must_m.group(0)[:600].strip())
        if must_not_m:
            parts.append("# 架构约束（禁止）\n" + must_not_m.group(0)[:300].strip())

        return "\n\n".join(parts) if parts else section[:600]

    def render(self, variables: Dict[str, str]) -> Tuple[str, List[str]]:
        """
        渲染模板，替换所有变量占位符。

        Args:
            variables: 用户提供的变量字典

        Returns:
            (rendered_code, missing_vars)
            若 missing_vars 非空，表示有未提供的必填变量
        """
        if self._body is None:
            return "", ["模板内容为空"]

        # 自动注入架构约束
        all_vars = dict(variables)
        if "{{arch_constraints}}" in self._body:
            all_vars["arch_constraints"] = self.get_arch_constraints()

        # 检查缺失变量
        all_placeholders = re.findall(r"\{\{(\w+)\}\}", self._body)
        missing = [p for p in dict.fromkeys(all_placeholders) if p not in all_vars]
        if missing:
            return "", missing

        result = self._body
        for key, value in all_vars.items():
            result = result.replace(f"{{{{{key}}}}}", value)

        return result, []

    def show_info(self) -> None:
        """打印模板元数据和变量说明"""
        print(f"\n{_B}{'─' * 60}{_X}")
        print(f"{_B}  模板：{self.name}{_X}  （{self.label}）")
        if self.layer:
            print(f"  层级：{_C}{self.layer}{_X}")
        if self.description:
            print(f"  描述：{self.description}")
        print(f"\n  {_C}需提供的变量（--var KEY=VALUE）：{_X}")
        if self.user_vars:
            for v in self.user_vars:
                print(f"    --var {v}=<值>")
        else:
            print(f"    （无需用户变量）")
        if "{{arch_constraints}}" in self._body:
            print(f"\n  {_D}arch_constraints 从 layer_contracts.md 自动注入，无需手动提供{_X}")
        print(f"\n  用法示例：")
        var_example = " ".join(f"--var {v}=<值>" for v in self.user_vars[:3])
        print(f"    mms template use {self.name} {var_example}")
        print(f"{_B}{'─' * 60}{_X}")

    def show_preview(self) -> None:
        """打印模板前 40 行"""
        lines = self._body.splitlines()[:40]
        print(f"\n{_D}--- 模板预览（前 40 行）---{_X}")
        for i, line in enumerate(lines, 1):
            print(f"  {i:3d}  {line}")
        if len(self._body.splitlines()) > 40:
            total = len(self._body.splitlines())
            print(f"  {_D}... （共 {total} 行）{_X}")


# ── 模板注册表 ────────────────────────────────────────────────────────────────

def load_templates() -> Dict[str, CodeTemplate]:
    """从模板目录加载所有 *.tmpl 文件"""
    _TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        path.stem: CodeTemplate(path.stem, path)
        for path in sorted(_TEMPLATE_DIR.glob("*.tmpl"))
    }


def get_template(name: str) -> Optional[CodeTemplate]:
    """按名称获取模板"""
    return load_templates().get(name)


# ── CLI 命令处理 ──────────────────────────────────────────────────────────────

def cmd_template_list() -> int:
    """列出所有可用模板"""
    templates = load_templates()
    if not templates:
        try:
            path_display = _TEMPLATE_DIR.relative_to(_ROOT)
        except ValueError:
            path_display = _TEMPLATE_DIR
        _warn(f"暂无模板（{path_display}/*.tmpl）")
        print(f"  {_D}内置模板详见 docs/memory/templates/code/{_X}")
        return 0

    print(f"\n{_B}代码模板库（{len(templates)} 个模板）{_X}")
    print("─" * 60)
    for name, tmpl in templates.items():
        layer_tag = f"  [{tmpl.layer}]" if tmpl.layer else ""
        print(f"  {_C}{name:<28}{_X}{layer_tag}")
        if tmpl.description:
            print(f"    {_D}{tmpl.description[:65]}{_X}")
        if tmpl.user_vars:
            print(f"    {_D}变量：{', '.join(tmpl.user_vars[:5])}{_X}")
    print("─" * 60)
    print(f"  {_D}mms template info <名称>  查看变量说明{_X}")
    print(f"  {_D}mms template use <名称> --var KEY=VALUE  渲染模板{_X}\n")
    return 0


def cmd_template_info(name: str) -> int:
    """显示模板详情 + 预览"""
    tmpl = get_template(name)
    if tmpl is None:
        _err(f"模板不存在：{name}")
        print(f"  运行 {_C}mms template list{_X} 查看可用模板")
        return 1
    tmpl.show_info()
    tmpl.show_preview()
    return 0


def cmd_template_use(
    name: str,
    variables: Dict[str, str],
    output: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    """渲染模板并输出到 stdout 或文件"""
    tmpl = get_template(name)
    if tmpl is None:
        _err(f"模板不存在：{name}")
        print(f"  运行 {_C}mms template list{_X} 查看可用模板")
        return 1

    rendered, missing = tmpl.render(variables)
    if missing:
        _err(f"缺少必填变量：{', '.join(missing)}")
        print(f"\n  {_Y}请通过 --var KEY=VALUE 提供以下变量：{_X}")
        for v in missing:
            print(f"    --var {v}=<值>")
        print(f"\n  运行 {_C}mms template info {name}{_X} 查看完整变量说明")
        return 1

    if dry_run:
        print(f"\n{_Y}[dry-run] 渲染结果预览：{_X}")
        print("─" * 60)
        print(rendered[:1200] + ("..." if len(rendered) > 1200 else ""))
        print("─" * 60)
        return 0

    if output:
        out_path = _ROOT / output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        _ok(f"已写入：{output}")
        line_count = len(rendered.splitlines())
        print(f"  {_D}共 {line_count} 行，请检查 TODO 注释并补充业务逻辑{_X}")
    else:
        print(rendered)

    return 0
