"""
Layer 2 · D2 注入提升（Injection Lift）

评测"有记忆注入 vs 无记忆注入"对代码生成质量的提升。

核心指标：
  lift_pass_at_1   = Pass@1(with_injection) - Pass@1(without_injection)
  lift_token_roi   = lift_pass_at_1 / avg_injection_tokens * 1000
                     （每千个注入 token 带来的 Pass@1 提升）
  avg_injection_tokens — 平均注入的 token 数（越少越好）

运行前提：
  - 需要 LLM API（llm_available=True）
  - 仅在 RunLevel.FAST 或 FULL 时运行

扩展方式：
  - 新增任务：在 tasks/<domain>/*.yaml 中添加 code_gen_task 类型 case
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InjectionLiftCase:
    """单个注入提升测试任务"""
    case_id:          str
    description:      str
    domain:           str
    task_description: str              # 模拟用户输入的任务描述
    required_imports: List[str]        # 生成代码中必须包含的导入/签名（用于离线检查）
    forbidden_patterns: List[str] = field(default_factory=list)
    reference_test:   Optional[str] = None   # pytest 可运行的测试脚本（在线评测用）
    metadata:         Dict[str, Any]  = field(default_factory=dict)


@dataclass
class InjectionLiftResult:
    """注入提升评测结果"""
    case_id:           str
    pass_at_1_with:    Optional[float] = None   # 有注入时的 Pass@1
    pass_at_1_without: Optional[float] = None   # 无注入时的 Pass@1
    lift:              float = 0.0              # 差值
    avg_injection_tokens: float = 0.0
    token_roi:         float = 0.0              # lift / (avg_tokens/1000)
    skipped:           bool = False
    skip_reason:       str = ""
    error:             str = ""


def compute_lift(results: List[InjectionLiftResult]) -> Dict[str, float]:
    """汇总注入提升指标"""
    valid = [r for r in results if not r.skipped and not r.error]
    if not valid:
        return {
            "avg_lift_pass_at_1": 0.0,
            "avg_token_roi":      0.0,
            "avg_injection_tokens": 0.0,
            "cases_evaluated":    0.0,
        }
    return {
        "avg_lift_pass_at_1":   round(sum(r.lift for r in valid) / len(valid), 4),
        "avg_token_roi":        round(sum(r.token_roi for r in valid) / len(valid), 4),
        "avg_injection_tokens": round(
            sum(r.avg_injection_tokens for r in valid) / len(valid), 1
        ),
        "cases_evaluated":      float(len(valid)),
    }


def mock_injection_lift_result(case: InjectionLiftCase) -> InjectionLiftResult:
    """
    在 dry_run 或无 LLM 环境下，返回占位结果。
    真实实现需要调用 LLM API 并比较结果。
    """
    return InjectionLiftResult(
        case_id=case.case_id,
        skipped=True,
        skip_reason="LLM API 不可用（dry_run 或 llm_available=False）",
    )


def run_dual_rail(case: InjectionLiftCase, context: str = "") -> InjectionLiftResult:
    """
    真实双轨 LLM 对比（Phase 4 实现）。

    双轨设计：
      Track A（无注入）：直接将 task_description 发给 LLM
      Track B（有注入）：将 context（记忆图谱上下文）前置后发给 LLM

    评测标准：
      - 代码语法正确（syntax_pass）→ 得 0.5 分
      - pytest 通过（pytest_pass / Pass@1）→ 得 1.0 分

    LLM 不可用时自动降级为 mock_injection_lift_result。
    """
    try:
        from mms.llm.bailian_provider import BailianProvider
        from mms.execution.sandboxed_runner import SandboxedCodeRunner
    except ImportError:
        return mock_injection_lift_result(case)

    runner = SandboxedCodeRunner(timeout_seconds=60)

    def _call_llm(prompt: str) -> Optional[str]:
        try:
            provider = BailianProvider()
            return provider.chat(prompt, model="qwen3-coder-next", max_tokens=1024)
        except Exception:
            return None

    def _score(code: Optional[str]) -> tuple[float, Optional[bool], Optional[bool]]:
        """返回 (score, syntax_pass, pytest_pass)"""
        if not code:
            return 0.0, False, False
        result = runner.run(code=code, file_path="generated.py",
                            test_script=case.reference_test)
        if result.pytest_pass is True:
            return 1.0, True, True
        if result.syntax_pass:
            return 0.5, True, False
        return 0.0, False, False

    # Track A（无注入）
    prompt_a = f"请根据以下任务描述生成 Python 代码：\n\n{case.task_description}"
    code_a = _call_llm(prompt_a)
    score_a, _, _ = _score(code_a)

    # Track B（有注入）
    prompt_b = f"以下是相关背景知识：\n\n{context}\n\n请根据以下任务描述生成 Python 代码：\n\n{case.task_description}"
    code_b = _call_llm(prompt_b)
    score_b, syntax_b, pytest_b = _score(code_b)

    lift = score_b - score_a
    injection_tokens = len(context.split()) if context else 0
    token_roi = (lift / (injection_tokens / 1000)) if injection_tokens > 0 else 0.0

    return InjectionLiftResult(
        case_id=case.case_id,
        pass_at_1_with=score_b,
        pass_at_1_without=score_a,
        lift=lift,
        avg_injection_tokens=float(injection_tokens),
        token_roi=round(token_roi, 4),
    )
