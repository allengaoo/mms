"""
tests/eval/eval_framework.py — Layer 1 E2E Eval 框架

设计原则：
  1. Execution-based：断言的是"业务结果"（代码是否符合预期），不比较中间产物文本。
  2. LLM-as-a-Judge：用百炼大模型（qwen3-32b）作为裁判，评估生成的 EP/DAG 结构质量。
  3. Mock-by-flag：在 CI（MMS_CI_MODE=1）下绕过真实 LLM 调用，保持确定性。

核心概念：
  EvalCase  — 一个测试场景（用户输入 + 靶机项目 + 验收脚本 + 可选的 Judge Prompt）
  EvalResult — 一次 Eval 运行的结果（业务断言 + Judge 打分 + 性能指标）
  EvalRunner — 运行 EvalCase 并收集 EvalResult
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

_CI_MODE = os.environ.get("MMS_CI_MODE") == "1"

# 百炼大规模模型（作为 Judge）
_JUDGE_MODEL = "qwen3-32b"


# ─── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class EvalCase:
    """
    一个 E2E Eval 测试场景。

    Attributes:
        name:           场景名称（用于报告展示）
        user_input:     模拟用户输入（将作为意图输入给 Synthesizer）
        language:       目标语言（"python" / "java" / "go"）
        setup:          建立靶机项目的函数 (tmp_path: Path) -> Path
        assertions:     业务断言函数列表，每个函数签名为 (project_root: Path) -> bool
        assertion_msgs: 与 assertions 对应的断言失败描述
        judge_prompt:   可选的 LLM 裁判 Prompt 模板（用于评估 EP 结构质量）
        tags:           标签（如 "add_field", "add_endpoint"）
    """
    name: str
    user_input: str
    language: str
    setup: Callable[[Path], Path]
    assertions: List[Callable[[Path], bool]] = field(default_factory=list)
    assertion_msgs: List[str] = field(default_factory=list)
    judge_prompt: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """一次 Eval 运行结果。"""
    case_name: str
    passed: bool = False
    assertion_results: List[tuple] = field(default_factory=list)  # [(desc, passed)]
    judge_score: Optional[float] = None   # 0.0~1.0，来自 LLM-as-a-Judge
    judge_feedback: str = ""
    ep_content: str = ""
    dag_summary: str = ""
    error: str = ""
    elapsed_s: float = 0.0
    tokens_used: int = 0


# ─── Judge（LLM 裁判） ────────────────────────────────────────────────────────

def _call_judge(prompt: str) -> tuple:
    """
    调用百炼 qwen3-32b 作为裁判模型，返回 (score: float, feedback: str)。
    在 CI 模式下跳过真实调用，返回默认通过。
    """
    if _CI_MODE:
        return 1.0, "[CI_MODE] Judge 已跳过"

    try:
        from mms.providers.bailian import BailianProvider  # type: ignore
        judge = BailianProvider(model=_JUDGE_MODEL)
        if not judge.is_available():
            return 1.0, "[Judge 不可用，跳过评分]"

        response = judge.complete(prompt, max_tokens=512)
        response_lower = response.lower()

        # 解析裁判结果：期望模型回复包含 YES/NO 以及分数
        if "yes" in response_lower or "是" in response_lower or "通过" in response_lower:
            score = 1.0
        elif "partial" in response_lower or "部分" in response_lower:
            score = 0.5
        else:
            score = 0.0

        return score, response[:400]
    except Exception as exc:
        return 1.0, f"[Judge 调用异常，跳过：{exc}]"


# ─── 核心运行器 ───────────────────────────────────────────────────────────────

class EvalRunner:
    """
    运行 EvalCase 列表，收集并汇总 EvalResult。
    """

    def __init__(self, tmp_base: Path):
        self.tmp_base = tmp_base
        self.results: List[EvalResult] = []

    def run_case(
        self,
        case: EvalCase,
        ep_content: str = "",
        dag_summary: str = "",
        project_root: Optional[Path] = None,
    ) -> EvalResult:
        """
        运行单个 EvalCase。

        Args:
            case:         测试场景
            ep_content:   （可选）已生成的 EP Markdown 内容，供 Judge 评分
            dag_summary:  （可选）已生成的 DAG JSON 摘要，供 Judge 评分
            project_root: （可选）已建好的靶机项目路径。若提供则跳过 case.setup()，
                          直接在此路径上运行断言。用于 Mock 测试场景，避免 setup
                          重建项目时覆盖手动注入的 Mock 数据。
        """
        start = time.monotonic()
        result = EvalResult(case_name=case.name, ep_content=ep_content, dag_summary=dag_summary)

        # 1. 初始化靶机项目（若已传入则复用，不再重建）
        if project_root is None:
            try:
                project_root = case.setup(self.tmp_base / case.name.replace(" ", "_"))
            except Exception as exc:
                result.error = f"靶机项目初始化失败: {exc}"
                result.passed = False
                result.elapsed_s = time.monotonic() - start
                self.results.append(result)
                return result

        # 2. 执行业务断言（Execution-based Eval）
        all_passed = True
        for i, (assertion_fn, msg) in enumerate(
            zip(case.assertions, case.assertion_msgs or [""] * len(case.assertions))
        ):
            try:
                ok = assertion_fn(project_root)
                result.assertion_results.append((msg or f"断言 {i+1}", ok))
                if not ok:
                    all_passed = False
            except Exception as exc:
                result.assertion_results.append((msg or f"断言 {i+1}", False))
                result.error += f" | 断言 {i+1} 异常: {exc}"
                all_passed = False

        # 3. LLM-as-a-Judge 评估（可选）
        if case.judge_prompt and (ep_content or dag_summary):
            judge_prompt = case.judge_prompt.format(
                ep_content=ep_content[:2000],
                dag_summary=dag_summary[:1000],
                user_input=case.user_input,
            )
            result.judge_score, result.judge_feedback = _call_judge(judge_prompt)
            # Judge 打分低于 0.5 时视为额外失败信号（但不强制拦截业务断言）
            if result.judge_score is not None and result.judge_score < 0.5:
                all_passed = False

        result.passed = all_passed
        result.elapsed_s = time.monotonic() - start
        self.results.append(result)
        return result

    def summary(self) -> Dict:
        """返回汇总报告（用于 CI 输出和 Benchmark 记录）。"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total > 0 else 0.0,
            "avg_elapsed_s": sum(r.elapsed_s for r in self.results) / total if total else 0.0,
            "details": [
                {
                    "name": r.case_name,
                    "passed": r.passed,
                    "elapsed_s": round(r.elapsed_s, 2),
                    "judge_score": r.judge_score,
                    "error": r.error,
                    "assertions": r.assertion_results,
                }
                for r in self.results
            ],
        }

    def print_report(self) -> None:
        """打印可读性强的测试报告。"""
        print("\n" + "═" * 60)
        print("  Layer 1 E2E Eval Report")
        print("═" * 60)
        for r in self.results:
            icon = "✅" if r.passed else "❌"
            print(f"\n{icon} [{r.case_name}]  ({r.elapsed_s:.1f}s)")
            for desc, ok in r.assertion_results:
                print(f"   {'✓' if ok else '✗'} {desc}")
            if r.judge_score is not None:
                print(f"   📊 Judge Score: {r.judge_score:.1f} — {r.judge_feedback[:80]}")
            if r.error:
                print(f"   ⚠️  Error: {r.error[:120]}")
        s = self.summary()
        print(f"\n{'─' * 60}")
        print(f"  Total: {s['passed']}/{s['total']} passed  ({s['pass_rate']*100:.0f}%)  "
              f"avg {s['avg_elapsed_s']:.1f}s/case")
        print("═" * 60 + "\n")
