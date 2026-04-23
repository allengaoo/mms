"""
fix_gen.py — LLM 辅助架构违反修复补丁生成器

使用 deepseek-coder-v2:16b 生成最小代码补丁，修复 arch_check 发现的架构违反。

工作流：
1. 读取目标源文件（+ 关键上下文行）
2. 注入 MMS 记忆规则（AC-2 / AC-3 记忆片段）
3. 调用 qwen3-coder-next 生成修复建议
4. 输出到 stdout 供审查；通过 --apply 直接写入文件

用法：
  python3 scripts/mms/fix_gen.py --file backend/app/services/control/scenario_service.py \\
      --violation AC-2 --method get_scenario
  python3 scripts/mms/fix_gen.py --file backend/app/services/control/scenario_service.py \\
      --violation AC-3 --method create_scenario
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE  # fix_gen.py is at mms root level

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]
_OLLAMA_CODER_MODEL = os.environ.get("OLLAMA_CODER_MODEL", "deepseek-coder-v2:16b")

# ── 规则记忆片段（从 MMS 注入） ────────────────────────────────────────────────

_RULE_AC2 = """
[记忆规则 AC-2] Service 公开方法首参必须包含 SecurityContext：
- 方法签名应包含 `ctx: SecurityContext` 或 `ctx: Optional[SecurityContext] = None` 作为首个非 self 参数
- 若方法内部已通过 contextvar 获取（`get_context()`），修复策略：在签名末尾增加可选参数
  `ctx: Optional[SecurityContext] = None`，方法体开头加 `ctx = ctx or get_context()`
- 不要改变方法的内部逻辑，只增加参数声明即可通过检查
- 示例修复：
  # Before:
  async def get_scenario(self, scenario_id: str) -> Scenario:
      ctx = get_context()
      ...

  # After:
  async def get_scenario(
      self, scenario_id: str, ctx: Optional[SecurityContext] = None
  ) -> Scenario:
      ctx = ctx or get_context()
      ...
"""

_RULE_AC3 = """
[记忆规则 AC-3] 所有 WRITE 操作必须调用 AuditService.log()：
- AuditService 路径：`from app.services.control.audit_service import audit_service`
- 调用签名（所有参数均为 keyword-only）：
  await audit_service.log(
      action="<动词_名词>",     # 如 "create_scenario", "delete_file"
      target_type="<资源类型>", # 如 "scenario", "file", "connector"
      target_id=<str>,         # 资源 ID
      changes=None,            # 可选：变更前后值 dict
  )
- 注意：若 ctx 参数可用，传入 `ctx=ctx`；否则 AuditService 会自动从 contextvar 取
- 位置：在 DB commit 成功之后、方法 return 之前调用
- 注意：audit_service.log 是 async 方法，必须用 await
"""

_RULE_AUDIT_IMPORT = """
导入方式：
  from app.services.control.audit_service import audit_service

注意：audit_service 是模块级单例实例，不是类本身。
"""


def _read_file_window(path: Path, center_line: int = 0, window: int = 60) -> str:
    """读取文件的关键窗口（含行号），center_line=0 表示读全文"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if center_line == 0 or len(lines) <= window:
        numbered = [f"{i+1:4d}| {ln}" for i, ln in enumerate(lines)]
    else:
        start = max(0, center_line - window // 2)
        end = min(len(lines), center_line + window // 2)
        numbered = [f"{i+1+start:4d}| {ln}" for i, ln in enumerate(lines[start:end])]
    return "\n".join(numbered)


def _build_prompt(
    file_path: Path,
    violation: str,
    method_name: str,
    center_line: int = 0,
) -> str:
    """构造给 deepseek-coder 的 Prompt"""
    rule = _RULE_AC2 if violation == "AC-2" else _RULE_AC3
    code_window = _read_file_window(file_path, center_line, window=80)
    rel_path = str(file_path.relative_to(_ROOT))

    return f"""你是一个 Python 架构修复专家。我需要你对以下文件的 `{method_name}` 方法做最小改动，
使其满足企业架构约束 {violation}。

---

## 架构约束规则

{rule}
{_RULE_AUDIT_IMPORT if violation == "AC-3" else ""}

---

## 当前代码（文件：{rel_path}）

```python
{code_window}
```

---

## 任务

请针对 `{method_name}` 方法，输出**最小的、仅针对该方法的修复代码片段**（unified diff 格式或直接给出修复后的方法完整代码）。

要求：
1. 只修改 `{method_name}` 方法（及顶部 import 区域如有需要）
2. 不要改变方法的业务逻辑
3. 输出格式：先给出修复后的完整方法代码，再简述你改了什么（1-2句）
4. Python 版本兼容 3.9，不使用 `match` 语句，`Optional` 使用 `typing.Optional`
"""


def run_llm(prompt: str, model: str = _CODER_MODEL) -> str:
    """
    调用 LLM 生成修复补丁。
    调用 qwen3-coder-next 生成修复建议。
    """
    sys.path.insert(0, str(_ROOT / "scripts"))
    sys.path.insert(0, str(_ROOT / "scripts" / "mms"))

    try:
        from mms.providers.factory import auto_detect
    except ImportError:
        from mms.providers.factory import auto_detect  # type: ignore[no-redef]

    provider = auto_detect("code_generation_simple")

    if not provider.is_available():
        print("[fix_gen] 百炼 Provider 不可用，请检查 DASHSCOPE_API_KEY 配置", file=sys.stderr)
        sys.exit(1)

    print(f"[fix_gen] 正在调用 {provider.model_name}，请稍候...", file=sys.stderr)
    # fallback: config.yaml → runner.max_tokens.fix_gen (default=2048)
    max_tok = int(getattr(_cfg, "runner_max_tokens_fix_gen", 2048)) if _cfg else 2048
    return provider.complete(prompt, max_tokens=max_tok)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="mms.execution.fix_gen.py — LLM 辅助架构违反补丁生成器（百炼）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 生成 AC-2 修复建议（get_scenario 首参缺失）
  python3 scripts/mms/fix_gen.py \\
    --file backend/app/services/control/scenario_service.py \\
    --violation AC-2 --method get_scenario --line 178

  # 生成 AC-3 修复建议（create_scenario 缺 audit log）
  python3 scripts/mms/fix_gen.py \\
    --file backend/app/services/control/scenario_service.py \\
    --violation AC-3 --method create_scenario --line 87
""",
    )
    parser.add_argument("--file",      required=True, help="目标源文件相对路径")
    parser.add_argument("--violation", required=True, choices=["AC-2", "AC-3"], help="违反类型")
    parser.add_argument("--method",    required=True, help="目标方法名")
    parser.add_argument("--line",      type=int, default=0, help="方法起始行号（用于定位窗口）")
    parser.add_argument("--model",     default=_CODER_MODEL, help=f"LLM 模型（默认 {_CODER_MODEL}，百炼优先）")
    parser.add_argument("--dry-run",   action="store_true", help="只打印 Prompt，不调用 LLM")
    args = parser.parse_args()

    file_path = _ROOT / args.file
    if not file_path.exists():
        print(f"[fix_gen] 文件不存在: {file_path}", file=sys.stderr)
        return 1

    prompt = _build_prompt(
        file_path=file_path,
        violation=args.violation,
        method_name=args.method,
        center_line=args.line,
    )

    if args.dry_run:
        print("=== PROMPT (dry-run) ===")
        print(prompt[:2000])
        print("... (truncated)")
        return 0

    result = run_llm(prompt, model=args.model)

    print("\n" + "=" * 60)
    print(f"[fix_gen] {args.violation} 修复建议 — {args.method}()")
    print("=" * 60)
    print(result)
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
