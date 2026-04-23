#!/usr/bin/env python3
"""
ep_runner.py — EP 自动执行 Pipeline（EP-131）

将 precheck → unit 循环 → postcheck → 知识沉淀建议 串联为单条命令：
    mms ep run EP-131

设计原则：
  - ep_runner 只做"调度"，不重复实现 UnitRunner / precheck / postcheck 的逻辑
  - 断点续跑：基于 DagState.status 实现幂等（已 done 的 Unit 自动跳过）
  - 计划摘要：置信度灰区（0.6-0.85）时输出可读摘要等待确认（零 LLM 消耗）
  - graceful degradation：DAG 文件不存在时提示生成，AST 失败时继续执行

执行流程（4 Phase）：
  Phase 0  环境准备（EP 文件存在检查、AST 索引新鲜度检查）
  Phase 1  precheck（可跳过）
  Phase 2  Unit 循环（调用 UnitRunner，按 order 分批，失败时保存断点）
  Phase 3  postcheck（可跳过）
  Phase 4  知识沉淀建议（打印提示，不自动执行）

状态持久化：
  docs/memory/_system/ep_run/{EP-NNN}.json

用法：
    from ep_runner import EpRunPipeline
    pipeline = EpRunPipeline()
    result = pipeline.run("EP-131")
    if result.success:
        print(f"✅ EP-131 完成，共 {result.units_done} 个 Unit")

EP-131 | 2026-04-18
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_DAG_DIR = _ROOT / "docs" / "memory" / "_system" / "dag"
_EP_RUN_DIR = _ROOT / "docs" / "memory" / "_system" / "ep_run"
_EP_DIR = _ROOT / "docs" / "execution_plans"

# ANSI 颜色
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_X}" if _USE_COLOR else text


def _ok(msg: str) -> None:
    print(f"  {_c('✅', _G)} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_c('⚠️ ', _Y)} {msg}")


def _err(msg: str) -> None:
    print(f"  {_c('❌', _R)} {msg}")


def _info(msg: str) -> None:
    print(f"  {_c('ℹ️  ' + msg, _D)}")


def _hr(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _phase_header(phase: int, title: str) -> None:
    print(f"\n{_c(f'[Phase {phase}]', _C)} {_c(title, _B)}")
    _hr()


# ── 置信度灰区常量（从 mms_config 读取，硬编码为 fallback）─────────────────────

try:
    sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]


def _fcfg(attr: str, default: float) -> float:
    if _cfg is None:
        return default
    return float(getattr(_cfg, attr, default))


def _icfg(attr: str, default: int) -> int:
    if _cfg is None:
        return default
    return int(getattr(_cfg, attr, default))


def _bcfg(attr: str, default: bool) -> bool:
    if _cfg is None:
        return default
    return bool(getattr(_cfg, attr, default))


# 置信度灰区阈值（低于此值视为"灰区"，触发计划摘要确认）
GREY_CONFIDENCE_LOW: float = _fcfg("runner_grey_confidence_low", 0.60)
GREY_CONFIDENCE_HIGH: float = _fcfg("runner_grey_confidence_high", 0.85)

# precheck / postcheck 超时（秒）
PRECHECK_TIMEOUT: int = _icfg("runner_timeout_precheck", 60)
POSTCHECK_TIMEOUT: int = _icfg("runner_timeout_postcheck", 120)

# Unit 执行超时（秒，单个 Unit 的总时间上限，含 LLM 调用）
UNIT_EXEC_TIMEOUT: int = _icfg("runner_timeout_unit_exec", 600)

# 计划摘要中是否显示 token 预算估算
SHOW_TOKEN_BUDGET: bool = _bcfg("runner_show_token_budget", True)


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class EpRunState:
    """
    EP Pipeline 执行状态，持久化到 docs/memory/_system/ep_run/{EP-NNN}.json

    设计说明：
      - 不重复存储 Unit 级别状态（那是 DagState 的职责）
      - 只记录 Pipeline 的阶段进度和断点信息
      - started_at / updated_at 使用 ISO 8601 UTC 时间戳
    """
    ep_id: str
    phase: str = "pending"          # pending|env_check|precheck|unit_loop|postcheck|done|failed
    resume_unit: Optional[str] = None        # 失败/中断时的续跑起点
    failure_unit: Optional[str] = None       # 失败的 Unit ID
    failure_error: Optional[str] = None      # 失败错误摘要（前 500 字符）
    started_at: str = ""
    updated_at: str = ""
    completed_units: List[str] = field(default_factory=list)
    total_units: int = 0
    precheck_done: bool = False
    postcheck_done: bool = False
    dry_run: bool = False

    def save(self) -> None:
        _EP_RUN_DIR.mkdir(parents=True, exist_ok=True)
        path = _EP_RUN_DIR / f"{self.ep_id.upper()}.json"
        self.updated_at = datetime.now(timezone.utc).isoformat()
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, ep_id: str) -> Optional["EpRunState"]:
        path = _EP_RUN_DIR / f"{ep_id.upper()}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]
            return cls(**{k: v for k, v in data.items() if k in known})
        except Exception:
            return None

    @classmethod
    def new(cls, ep_id: str, dry_run: bool = False) -> "EpRunState":
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            ep_id=ep_id.upper(),
            phase="pending",
            started_at=now,
            updated_at=now,
            dry_run=dry_run,
        )


@dataclass
class UnitRunSummary:
    """单个 Unit 的执行摘要（用于最终报告）"""
    unit_id: str
    title: str
    status: str          # done|failed|skipped
    attempts: int = 0
    commit_hash: Optional[str] = None
    error: Optional[str] = None
    elapsed_s: float = 0.0


@dataclass
class EpRunResult:
    """EP Pipeline 执行结果"""
    ep_id: str
    success: bool
    units_done: int = 0
    units_failed: int = 0
    units_skipped: int = 0
    total_units: int = 0
    unit_summaries: List[UnitRunSummary] = field(default_factory=list)
    failure_unit: Optional[str] = None
    failure_error: Optional[str] = None
    dry_run: bool = False
    elapsed_s: float = 0.0


# ── IntentPlanSummary（零 LLM 计划摘要生成器）────────────────────────────────

@dataclass
class BatchGroup:
    """一个执行批次（同 order 的 Unit）"""
    order: int
    units: List[dict]    # {id, title, model_hint, token_budget, confidence, is_grey}


@dataclass
class IntentPlanSummary:
    """
    EP 执行前的人类可读计划摘要。
    由确定性规则生成（零 LLM 消耗）。

    is_grey: 是否有置信度处于灰区的 Unit（触发"建议确认"提示）
    """
    ep_id: str
    batches: List[BatchGroup]
    grey_unit_ids: List[str]
    total_token_estimate: int
    llm_call_estimate: int
    is_grey: bool

    @classmethod
    def from_dag_state(cls, ep_id: str, dag_state) -> "IntentPlanSummary":
        """从 DagState 构建摘要（不调用 LLM，不读 intent_classifier）"""
        batches: List[BatchGroup] = []
        grey_ids: List[str] = []
        total_tokens = 0
        llm_calls = 0

        # 按 order 分批
        groups: Dict[int, List] = {}
        for unit in dag_state.units:
            groups.setdefault(unit.order, []).append(unit)

        for order in sorted(groups.keys()):
            batch_units = []
            for unit in groups[order]:
                # 从 aiu_steps 估算 token 预算
                token_budget = 0
                _budget_fast = _cfg.runner_token_budget_fast if _cfg else 2000
                _budget_capable = _cfg.runner_token_budget_capable if _cfg else 4000
                for step in getattr(unit, "aiu_steps", []):
                    token_budget += step.get("token_budget", _budget_fast) if isinstance(step, dict) else _budget_fast
                if token_budget == 0:
                    # 无 AIU 分解时，按模型 hint 估算
                    model_hint = getattr(unit, "model_hint", "capable")
                    token_budget = _budget_capable if model_hint == "capable" else _budget_fast

                # 置信度：尝试从 unit 属性读取（EP-129 新增字段），默认 1.0
                confidence = float(getattr(unit, "intent_confidence", 1.0))
                is_grey = GREY_CONFIDENCE_LOW <= confidence < GREY_CONFIDENCE_HIGH
                if is_grey:
                    grey_ids.append(unit.id)

                total_tokens += token_budget
                if unit.status not in ("done", "skipped"):
                    llm_calls += 1

                batch_units.append({
                    "id": unit.id,
                    "title": unit.title,
                    "model_hint": getattr(unit, "model_hint", "capable"),
                    "token_budget": token_budget,
                    "confidence": confidence,
                    "is_grey": is_grey,
                    "status": unit.status,
                })
            batches.append(BatchGroup(order=order, units=batch_units))

        return cls(
            ep_id=ep_id.upper(),
            batches=batches,
            grey_unit_ids=grey_ids,
            total_token_estimate=total_tokens,
            llm_call_estimate=llm_calls,
            is_grey=bool(grey_ids),
        )

    def print(self) -> None:
        """打印可读的计划摘要"""
        print(f"\n{_c('─' * 60, _D)}")
        print(f"{_c('[计划摘要]', _B)} {_c(self.ep_id, _C)} — 执行顺序预览")
        print(_c("─" * 60, _D))

        for batch in self.batches:
            done_count = sum(1 for u in batch.units if u["status"] in ("done", "skipped"))
            print(f"\n  {_c(f'Batch {batch.order}', _B)} ({len(batch.units)} 个 Unit，{done_count} 已完成)：")
            for u in batch.units:
                status_icon = (
                    _c("✅", _G) if u["status"] in ("done", "skipped")
                    else _c("⚠️ ", _Y) if u["is_grey"]
                    else _c("○", _D)
                )
                token_str = f"~{u['token_budget']} tokens" if SHOW_TOKEN_BUDGET else ""
                grey_tag = _c(" [灰区]", _Y) if u["is_grey"] else ""
                print(
                    f"    {status_icon} {_c(u['id'], _B)} [{u['model_hint']}]"
                    f"{grey_tag}  {u['title']}"
                )
                if token_str:
                    print(f"         {_c(token_str, _D)}")

        print(f"\n  {_c('总预算', _D)}：~{self.total_token_estimate:,} tokens"
              f"（约 {self.llm_call_estimate} 次 LLM 调用）")

        if self.grey_unit_ids:
            print(
                f"\n  {_c('⚠️  注意', _Y)}：Unit {', '.join(self.grey_unit_ids)} "
                f"的意图置信度处于灰区，建议确认 AIU 分解计划是否符合预期。"
            )
        print(_c("─" * 60, _D))


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _normalize_ep_id(ep_id: str) -> str:
    """统一 EP ID 格式，如 '131' → 'EP-131'，'ep-131' → 'EP-131'"""
    ep_id = ep_id.strip().upper()
    if not ep_id.startswith("EP-"):
        ep_id = f"EP-{ep_id}"
    return ep_id


def _find_ep_file(ep_id: str) -> Optional[Path]:
    """在 docs/execution_plans/ 中查找 EP 文件（前缀匹配）"""
    for path in _EP_DIR.glob(f"{ep_id}_*.md"):
        return path
    # 也支持不带尾缀的精确文件名
    exact = _EP_DIR / f"{ep_id}.md"
    if exact.exists():
        return exact
    return None


def _run_subprocess(
    cmd: List[str],
    description: str,
    timeout: int = 60,
    cwd: Optional[Path] = None,
) -> tuple:
    """
    运行子进程，返回 (success: bool, output: str)。
    timeout 超时时返回 (False, "超时信息")。
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd or _ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        return success, output
    except subprocess.TimeoutExpired:
        return False, f"{description} 超时（{timeout}s）"
    except Exception as e:
        return False, f"{description} 执行异常：{e}"


def _load_dag_state(ep_id: str):
    """安全加载 DagState，失败时返回 None"""
    try:
        sys.path.insert(0, str(_HERE))
        from dag_model import DagState  # type: ignore[import]
        return DagState.load(ep_id)
    except FileNotFoundError:
        return None
    except Exception as e:
        _warn(f"加载 DAG 状态失败：{e}")
        return None


def _run_unit(
    ep_id: str,
    unit_id: str,
    model: str = "capable",
    dry_run: bool = False,
) -> "UnitRunSummary":
    """
    调用 UnitRunner 执行单个 Unit，返回 UnitRunSummary。
    """
    try:
        from unit_runner import UnitRunner  # type: ignore[import]
    except ImportError:
        try:
            from mms.unit_runner import UnitRunner  # type: ignore[import]
        except ImportError:
            return UnitRunSummary(
                unit_id=unit_id, title="", status="failed",
                error="unit_runner 模块无法导入",
            )

    t0 = time.monotonic()
    runner = UnitRunner()
    run_result = runner.run(ep_id=ep_id, unit_id=unit_id, model=model, dry_run=dry_run)
    elapsed = round(time.monotonic() - t0, 1)

    # 获取 Unit title（从 DagState 读取）
    title = unit_id
    dag_state = _load_dag_state(ep_id)
    if dag_state is not None:
        for u in dag_state.units:
            if u.id.upper() == unit_id.upper():
                title = u.title
                break

    return UnitRunSummary(
        unit_id=unit_id,
        title=title,
        status="done" if run_result.success else "failed",
        attempts=run_result.attempts,
        commit_hash=run_result.commit_hash,
        error=run_result.error,
        elapsed_s=elapsed,
    )


# ── 核心 Pipeline ─────────────────────────────────────────────────────────────

class EpRunPipeline:
    """
    EP 级别的完整自动化执行引擎。

    外部接口：
        pipeline = EpRunPipeline()
        result = pipeline.run("EP-131")

    断点续跑：
        result = pipeline.run("EP-131", from_unit="U3")
        # U1/U2 如果 DagState 已标记 done，自动跳过
        # 若 from_unit 指定，则从该 Unit 开始（即使之前 Unit 不是 done 也跳过）
    """

    def run(
        self,
        ep_id: str,
        from_unit: Optional[str] = None,
        only_units: Optional[List[str]] = None,
        dry_run: bool = False,
        skip_precheck: bool = False,
        skip_postcheck: bool = False,
        auto_confirm: bool = False,
        model: str = "capable",
    ) -> EpRunResult:
        """
        执行完整 EP Pipeline。

        Args:
            ep_id:           EP 编号（如 "EP-131" 或 "131"）
            from_unit:       断点续跑起点（如 "U3"，之前的 Unit 强制跳过）
            only_units:      只执行指定的 Unit（如 ["U1", "U2"]）
            dry_run:         模拟执行，不写文件不提交 git
            skip_precheck:   跳过 Phase 1 precheck
            skip_postcheck:  跳过 Phase 3 postcheck
            auto_confirm:    跳过计划摘要确认（CI 模式）
            model:           默认执行模型（Unit 自身 model_hint 优先）
        """
        ep_id = _normalize_ep_id(ep_id)
        t_start = time.monotonic()
        result = EpRunResult(ep_id=ep_id, success=False, dry_run=dry_run)

        # 加载或新建执行状态
        state = EpRunState.load(ep_id)
        if state is None or state.phase in ("done", "failed"):
            state = EpRunState.new(ep_id, dry_run=dry_run)
        state.save()

        print(f"\n{_c('═' * 60, _B)}")
        print(f"  {_c('MMS EP Runner', _B)}  ·  {_c(ep_id, _C)}")
        if dry_run:
            print(f"  {_c('[DRY-RUN 模式：不写文件，不提交 git]', _Y)}")
        print(_c("═" * 60, _B))

        # ── Phase 0：环境准备 ─────────────────────────────────────────────────
        _phase_header(0, "环境准备")
        state.phase = "env_check"
        state.save()

        ep_file = _find_ep_file(ep_id)
        if ep_file is None:
            _err(f"未找到 EP 文件：{ep_id}（在 {_EP_DIR} 中查找 {ep_id}_*.md）")
            state.phase = "failed"
            state.failure_error = f"EP 文件不存在：{ep_id}"
            state.save()
            result.failure_error = state.failure_error
            return result
        _ok(f"EP 文件：{ep_file.name}")

        # 检查 DAG 状态
        dag_state = _load_dag_state(ep_id)
        if dag_state is None:
            _warn(f"未找到 DAG 状态文件，请先运行：mms unit generate --ep {ep_id}")
            # 尝试从 EP 文件解析 Scope 作为临时 Unit 列表
            dag_state = self._try_bootstrap_dag(ep_id, ep_file)
            if dag_state is None:
                _err("无法确定执行计划，终止")
                state.phase = "failed"
                state.failure_error = "DAG 状态不存在且无法自动生成"
                state.save()
                result.failure_error = state.failure_error
                return result

        all_units = dag_state.units
        state.total_units = len(all_units)
        result.total_units = len(all_units)
        _ok(f"DAG 加载完成：共 {len(all_units)} 个 Unit")

        # 确定执行范围
        exec_units = self._resolve_exec_units(
            all_units,
            from_unit=from_unit,
            only_units=only_units,
        )
        _info(f"执行范围：{len(exec_units)} 个 Unit（跳过已完成或范围外的）")

        # ── 计划摘要（置信度灰区时输出，等待确认）────────────────────────────
        summary = IntentPlanSummary.from_dag_state(ep_id, dag_state)
        summary.print()

        if summary.is_grey and not auto_confirm:
            try:
                ans = input(f"\n{_c('继续执行？', _B)} [Y/n]: ").strip().upper()
                if ans and ans not in ("Y", "YES"):
                    print(f"  {_c('已取消执行', _Y)}")
                    state.phase = "failed"
                    state.failure_error = "用户取消（计划摘要确认阶段）"
                    state.save()
                    result.failure_error = state.failure_error
                    return result
            except (EOFError, KeyboardInterrupt):
                print()
                # EOF 场景（CI 环境）默认继续
                _info("（EOF/CI 模式，自动确认继续）")
        elif auto_confirm:
            _info("--auto-confirm 已设置，跳过计划摘要确认")

        # ── Phase 1：precheck ─────────────────────────────────────────────────
        if not skip_precheck and not state.precheck_done:
            _phase_header(1, "前置检查（precheck）")
            state.phase = "precheck"
            state.save()

            ok, output = _run_subprocess(
                [sys.executable, str(_HERE / "cli.py"), "precheck", "--ep", ep_id],
                description="precheck",
                timeout=PRECHECK_TIMEOUT,
            )
            if ok:
                _ok("precheck 完成")
                state.precheck_done = True
                state.save()
            else:
                _warn(f"precheck 存在警告（继续执行）：{output[:200]}")
                state.precheck_done = True
                state.save()
        else:
            _info("跳过 precheck（--skip-precheck 或已执行）")

        # ── Phase 2：Unit 循环 ────────────────────────────────────────────────
        _phase_header(2, f"Unit 执行（{len(exec_units)} 个）")
        state.phase = "unit_loop"
        state.save()

        # 按 order 分批执行（V1：顺序执行，不并行）
        order_groups: Dict[int, List] = {}
        for unit in exec_units:
            order_groups.setdefault(unit.order, []).append(unit)

        for batch_order in sorted(order_groups.keys()):
            batch = order_groups[batch_order]
            print(f"\n  {_c(f'── Batch {batch_order} ──', _B)}")

            for unit in batch:
                unit_id = unit.id.upper()
                unit_model = getattr(unit, "model_hint", model) or model

                # 幂等检查（DagState 中已 done）
                if unit.status == "done":
                    _ok(f"{unit_id} 已完成，跳过")
                    result.units_skipped += 1
                    result.unit_summaries.append(UnitRunSummary(
                        unit_id=unit_id, title=unit.title,
                        status="skipped", commit_hash=unit.git_commit,
                    ))
                    continue

                print(f"\n  {_c(f'▶ {unit_id}', _C)}  {unit.title}")
                print(f"    {_c(f'模型：{unit_model}', _D)}")

                # 检查依赖是否满足
                done_ids = _load_dag_state(ep_id).done_ids() if not dry_run else []
                if not unit.is_executable(done_ids) and not dry_run:
                    _warn(f"{unit_id} 的依赖未满足（{unit.depends_on}），跳过")
                    summary_item = UnitRunSummary(
                        unit_id=unit_id, title=unit.title,
                        status="failed",
                        error=f"依赖未满足：{unit.depends_on}",
                    )
                    result.unit_summaries.append(summary_item)
                    result.units_failed += 1
                    state.failure_unit = unit_id
                    state.failure_error = f"依赖未满足：{unit.depends_on}"
                    state.resume_unit = unit_id
                    state.save()
                    self._print_failure_report(ep_id, unit_id, state.failure_error)
                    result.failure_unit = unit_id
                    result.failure_error = state.failure_error
                    return result

                # 执行 Unit
                summary_item = _run_unit(ep_id, unit_id, model=unit_model, dry_run=dry_run)
                result.unit_summaries.append(summary_item)

                if summary_item.status == "done":
                    _ok(f"{unit_id} 完成（{summary_item.elapsed_s}s，{summary_item.attempts} 次尝试）")
                    if summary_item.commit_hash:
                        _info(f"commit: {summary_item.commit_hash}")
                    result.units_done += 1
                    state.completed_units.append(unit_id)
                    state.save()
                else:
                    # Unit 失败：保存断点，终止 Pipeline
                    _err(f"{unit_id} 执行失败（3-Strike 耗尽）")
                    state.phase = "failed"
                    state.failure_unit = unit_id
                    state.failure_error = (summary_item.error or "")[:500]
                    state.resume_unit = unit_id
                    state.save()
                    result.units_failed += 1
                    result.failure_unit = unit_id
                    result.failure_error = state.failure_error
                    self._print_failure_report(ep_id, unit_id, state.failure_error)
                    return result

        # ── Phase 3：postcheck ────────────────────────────────────────────────
        if not skip_postcheck and not state.postcheck_done:
            _phase_header(3, "后置检查（postcheck）")
            state.phase = "postcheck"
            state.save()

            ok, output = _run_subprocess(
                [sys.executable, str(_HERE / "cli.py"), "postcheck", "--ep", ep_id],
                description="postcheck",
                timeout=POSTCHECK_TIMEOUT,
            )
            if ok:
                _ok("postcheck 完成")
            else:
                _warn(f"postcheck 存在问题（已记录，继续）：{output[:200]}")
            state.postcheck_done = True
            state.save()
        else:
            _info("跳过 postcheck（--skip-postcheck 或已执行）")

        # ── Phase 4：知识沉淀建议 ─────────────────────────────────────────────
        _phase_header(4, "知识沉淀建议")
        done_count, total_count = (
            (sum(1 for u in dag_state.units if u.status == "done"), len(dag_state.units))
            if dag_state else (result.units_done, result.total_units)
        )
        print(f"\n  {_c('EP 执行完成！', _G)}"
              f"  {done_count}/{total_count} 个 Unit 完成")
        print(f"\n  {_c('建议执行以下命令进行知识沉淀：', _D)}")
        print(f"    {_c(f'mms distill --ep {ep_id}', _B)}   # 手动知识蒸馏")
        print(f"    {_c(f'mms dream --ep {ep_id}', _B)}     # 自动萃取知识草稿")
        print()

        # 更新最终状态
        state.phase = "done"
        state.save()
        result.success = True
        result.elapsed_s = round(time.monotonic() - t_start, 1)

        # 打印最终报告
        self._print_final_report(result)
        return result

    # ── 私有辅助方法 ─────────────────────────────────────────────────────────

    def _resolve_exec_units(
        self,
        all_units: list,
        from_unit: Optional[str] = None,
        only_units: Optional[List[str]] = None,
    ) -> list:
        """
        根据 from_unit 和 only_units 参数过滤执行范围。

        优先级：
          1. only_units 指定时，只执行列表中的 Unit
          2. from_unit 指定时，跳过该 Unit 之前的所有 Unit
          3. 两者都未指定，返回全部非 done 的 Unit（包含 pending 和 failed）
        """
        if only_units:
            upper_only = {u.upper() for u in only_units}
            return [u for u in all_units if u.id.upper() in upper_only]

        if from_unit:
            from_upper = from_unit.upper()
            found = False
            result = []
            for unit in all_units:
                if unit.id.upper() == from_upper:
                    found = True
                if found:
                    result.append(unit)
            if not result:
                _warn(f"--from-unit {from_unit} 未找到，将执行所有 Unit")
                return all_units
            return result

        # 默认：只跳过已明确 done 的 Unit（skipped 也要重试）
        return [u for u in all_units if u.status != "done"]

    def _try_bootstrap_dag(self, ep_id: str, ep_file: Path):
        """
        尝试从 EP 文件的 Scope 表格解析 Unit 列表，临时构建 DagState。
        这是 DAG 文件不存在时的降级路径。
        返回 DagState 或 None。
        """
        try:
            from dag_model import DagState, DagUnit  # type: ignore[import]
        except ImportError:
            return None

        try:
            content = ep_file.read_text(encoding="utf-8")
        except Exception:
            return None

        import re
        # 匹配 Scope 表格行：| U1 | 描述 | 文件 |... （逐行扫描）
        rows = []
        for line in content.splitlines():
            m = re.match(
                r"\|\s*(U\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
                line,
            )
            if m:
                rows.append((m.group(1), m.group(2), m.group(3)))

        if not rows:
            return None

        units = []
        for i, (uid, title, files_raw) in enumerate(rows[:20]):  # 最多解析 20 个
            files = [f.strip().strip("`") for f in files_raw.split(",") if f.strip()]
            units.append(DagUnit(
                id=uid.strip(),
                title=title.strip(),
                layer="unknown",
                files=files,
                depends_on=[],
                order=i + 1,
                model_hint="capable",
            ))

        if not units:
            return None

        from datetime import datetime, timezone
        dag = DagState(
            ep_id=ep_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            orchestrator_model="ep_runner_bootstrap",
            units=units,
        )
        _info(f"从 EP 文件 Scope 表格临时解析了 {len(units)} 个 Unit（建议运行 mms unit generate 生成完整 DAG）")
        return dag

    def _print_failure_report(self, ep_id: str, unit_id: str, error: str) -> None:
        """打印失败诊断报告和续跑建议"""
        print(f"\n{_c('─' * 60, _R)}")
        print(f"  {_c('❌ Unit 执行失败', _R)}  ·  {ep_id} / {unit_id}")
        print(_c("─" * 60, _R))
        if error:
            print(f"\n  {_c('错误摘要：', _B)}")
            for line in error.splitlines()[:10]:
                print(f"    {line}")
        print(f"\n  {_c('续跑建议：', _B)}")
        print(f"    {_c(f'mms ep run {ep_id} --from-unit {unit_id}', _C)}"
              f"  # 修复后从此 Unit 续跑")
        print(f"    {_c(f'mms unit run --ep {ep_id} --unit {unit_id}', _C)}"
              f"  # 单独调试此 Unit")
        print(_c("─" * 60, _R))

    def _print_final_report(self, result: EpRunResult) -> None:
        """打印最终执行报告"""
        print(f"\n{_c('═' * 60, _G)}")
        print(f"  {_c('EP Run 完成', _G)}  ·  {_c(result.ep_id, _C)}")
        print(_c("═" * 60, _G))
        print(f"  总耗时：{result.elapsed_s}s")
        print(f"  完成：{_c(str(result.units_done), _G)}"
              f"  跳过：{_c(str(result.units_skipped), _Y)}"
              f"  失败：{_c(str(result.units_failed), _R)}"
              f"  / 共 {result.total_units}")

        if result.dry_run:
            print(f"  {_c('[DRY-RUN 模式，未修改任何文件]', _Y)}")

        if result.unit_summaries:
            print(f"\n  {'Unit':<6} {'状态':<8} {'耗时':>6}  标题")
            _hr("  -")
            for s in result.unit_summaries:
                icon = (
                    _c("✅", _G) if s.status in ("done",)
                    else _c("⏭️ ", _Y) if s.status == "skipped"
                    else _c("❌", _R)
                )
                elapsed = f"{s.elapsed_s:.1f}s" if s.elapsed_s > 0 else "—"
                print(f"  {s.unit_id:<6} {icon} {elapsed:>6}  {s.title[:40]}")

        print(_c("═" * 60, _G))
