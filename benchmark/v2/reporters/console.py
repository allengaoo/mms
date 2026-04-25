"""
Console Reporter — 彩色终端输出

扩展方式：无需修改，通过 LayerResult.metrics 自动展示新指标。
"""
from __future__ import annotations

from benchmark.v2.schema import BenchmarkResult, LayerResult, TaskStatus


_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"
_DIM    = "\033[2m"


def _bar(value: float, width: int = 20) -> str:
    filled = int(value * width)
    empty  = width - filled
    color  = _GREEN if value >= 0.8 else (_YELLOW if value >= 0.5 else _RED)
    return f"{color}{'█' * filled}{'░' * empty}{_RESET} {value:.1%}"


def _status_icon(layer_result: LayerResult) -> str:
    if layer_result.score >= 0.8:
        return f"{_GREEN}✓{_RESET}"
    if layer_result.score >= 0.5:
        return f"{_YELLOW}⚠{_RESET}"
    return f"{_RED}✗{_RESET}"


def print_result(result: BenchmarkResult, verbose: bool = False) -> None:
    """向 stdout 打印完整 Benchmark 报告"""
    print()
    print(f"{_BOLD}{'═' * 60}{_RESET}")
    print(f"{_BOLD}  木兰（Mulan）Benchmark v{result.version}  {_DIM}@{result.timestamp}{_RESET}")
    print(f"{_BOLD}{'═' * 60}{_RESET}")
    print()

    for layer_num in sorted(result.layer_results.keys()):
        lr = result.layer_results[layer_num]
        icon = _status_icon(lr)
        print(f"  {icon} {_BOLD}Layer {layer_num}: {lr.name}{_RESET}")
        print(f"     得分:    {_bar(lr.score)}")
        print(f"     任务:    总 {lr.tasks_total}  通过 {_GREEN}{lr.tasks_passed}{_RESET}"
              f"  跳过 {_YELLOW}{lr.tasks_skipped}{_RESET}  失败 {_RED}{lr.tasks_failed}{_RESET}"
              f"  耗时 {lr.duration_seconds:.1f}s")

        # 展示关键指标
        if lr.metrics:
            print(f"     {_DIM}── 指标 ──────────────────────────────────────{_RESET}")
            for key, val in lr.metrics.items():
                if key.endswith("_total") or key == "mode":
                    continue
                formatted = f"{val:.4f}" if isinstance(val, float) else str(val)
                print(f"     {_DIM}{key:<38}{_RESET} {formatted}")

        if verbose and lr.task_results:
            print(f"     {_DIM}── 任务详情 ──────────────────────────────────{_RESET}")
            for tr in lr.task_results:
                if tr.status == TaskStatus.PASSED:
                    sym = f"{_GREEN}✓{_RESET}"
                elif tr.status == TaskStatus.SKIPPED:
                    sym = f"{_YELLOW}↷{_RESET}"
                elif tr.status == TaskStatus.ERROR:
                    sym = f"{_RED}!{_RESET}"
                else:
                    sym = f"{_RED}✗{_RESET}"
                score_str = f"({tr.score:.2f})" if tr.status != TaskStatus.SKIPPED else "(skip)"
                print(f"     {sym} {tr.task_id:<40} {score_str}")
                if tr.error_message and verbose:
                    print(f"       {_RED}{tr.error_message}{_RESET}")
        print()

    # 综合得分
    print(f"{'─' * 60}")
    overall = result.overall_score
    print(f"  {_BOLD}综合得分: {_bar(overall, width=30)}{_RESET}")
    print(f"{'═' * 60}")
    print()
