#!/usr/bin/env python3
"""
ep_wizard.py — mms ep 交互式工作流向导

将完整 EP 生命周期串为一个引导式 CLI，每步有清晰说明与确认提示。

完整工作流（7 步）：
  Step 1  意图合成        mms synthesize "任务" --template <类型>
  Step 2  EP 文件确认     [用户在 Cursor 中生成 EP 文件后按 Enter 继续]
  Step 3  建立基线        mms precheck --ep EP-NNN
  Step 4  生成 DAG        mms unit generate --ep EP-NNN  (Gemini 2.5 Pro)
  Step 5  Unit 循环       每个 Unit：qwen run + sonnet-save + compare + apply
  Step 6  后校验          mms postcheck --ep EP-NNN
  Step 7  知识沉淀        mms distill --ep EP-NNN / mms dream --ep EP-NNN

用法：
  mms ep start EP-122
  mms ep start EP-122 --from-step 5    # 从指定步骤继续
  mms ep status EP-122                 # 查看向导进度

内部状态存储：
  docs/memory/private/wizard/<EP-NNN>/wizard_state.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_WIZARD_STATE_DIR = _ROOT / "docs" / "memory" / "private" / "wizard"


def _get_tracer(ep_id: str) -> Optional[object]:
    """安全获取当前 EP 的 Tracer（若未开启返回 None，零开销）。"""
    try:
        sys.path.insert(0, str(_HERE))
        from trace.collector import get_tracer  # type: ignore[import]
        return get_tracer(ep_id)
    except Exception:
        return None

# ANSI
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


def _hr(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _header(title: str) -> None:
    print(f"\n{_c('=' * 60, _B)}")
    print(f"  {_c(title, _B)}")
    print(_c('=' * 60, _B))


def _step_header(step: int, total: int, title: str) -> None:
    print(f"\n{_c(f'[Step {step}/{total}]', _C)} {_c(title, _B)}")
    _hr()


def _ask(prompt: str, default: str = "Y") -> bool:
    """交互确认，返回 True=继续 / False=跳过"""
    hint = f"[{'Y/n' if default == 'Y' else 'y/N'}]"
    try:
        ans = input(f"  → {prompt} {hint} ").strip().upper()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return default == "Y"
    return ans in ("Y", "YES")


def _ask_text(prompt: str, default: str = "") -> str:
    """交互输入文本（单行）"""
    try:
        ans = input(f"  → {prompt}{f' [{default}]' if default else ''}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return ans or default


def _ask_multiline(prompt: str, default: str = "") -> str:
    """
    交互输入多行文本。
    用法：输入内容后，在**空行按 Enter** 结束输入。
    支持粘贴多行内容（如从文档复制的任务描述）。
    """
    if default:
        print(f"  已记录内容（直接按 Enter 保留）：")
        for line in default.splitlines():
            print(f"    {_c(line, _D)}")

    print(f"  → {prompt}")
    print(f"  {_c('（支持多行粘贴；输入完成后按一次 Enter 结束，空行确认）', _D)}")
    lines = []
    try:
        while True:
            try:
                line = input()
            except EOFError:
                # Ctrl+D — 直接结束
                break
            lines.append(line)
            # 遇到空行时结束（允许内容段之间有空行，但连续两个空行退出）
            if line == "" and lines and lines[-2] == "" if len(lines) >= 2 else line == "":
                # 移除末尾的空行
                while lines and lines[-1] == "":
                    lines.pop()
                break
    except KeyboardInterrupt:
        print()

    result = "\n".join(lines).strip()
    return result or default


def _run_cmd(
    cmd: List[str],
    description: str,
    ep_id: Optional[str] = None,
    step: Optional[str] = None,
    unit_id: Optional[str] = None,
) -> int:
    """运行子命令，打印结果，返回 returncode。
    如果传入 ep_id，自动记录 Level 1 步骤耗时到 Tracer。
    """
    print(f"  {_c('$', _D)} {' '.join(cmd)}")
    t0 = time.monotonic()
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
    rc = result.returncode
    if rc == 0:
        print(f"  {_c('✅', _G)} {description} 完成")
    else:
        print(f"  {_c('❌', _R)} {description} 失败（exit {rc}）")

    # Level 1 诊断记录
    if ep_id and step:
        tracer = _get_tracer(ep_id)
        if tracer:
            tracer.record_step(  # type: ignore[union-attr]
                step=step,
                result="ok" if rc == 0 else "error",
                elapsed_ms=elapsed_ms,
                unit_id=unit_id,
                description=description,
            )
    return rc


# ── 向导状态持久化 ─────────────────────────────────────────────────────────────

class WizardState:
    def __init__(self, ep_id: str) -> None:
        self.ep_id = ep_id.upper()
        self._path = _WIZARD_STATE_DIR / self.ep_id / "wizard_state.json"
        self.current_step: int = 1
        self.completed_steps: List[int] = []
        self.task_desc: str = ""
        self.template: str = ""
        self.ep_file: str = ""
        self.total_units: int = 0
        self.completed_units: List[str] = []
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.updated_at: str = self.started_at

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        data = {
            "ep_id": self.ep_id,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "task_desc": self.task_desc,
            "template": self.template,
            "ep_file": self.ep_file,
            "total_units": self.total_units,
            "completed_units": self.completed_units,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, ep_id: str) -> "WizardState":
        ep_id = ep_id.upper()
        state = cls(ep_id)
        path = _WIZARD_STATE_DIR / ep_id / "wizard_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                state.current_step = data.get("current_step", 1)
                state.completed_steps = data.get("completed_steps", [])
                state.task_desc = data.get("task_desc", "")
                state.template = data.get("template", "")
                state.ep_file = data.get("ep_file", "")
                state.total_units = data.get("total_units", 0)
                state.completed_units = data.get("completed_units", [])
                state.started_at = data.get("started_at", state.started_at)
                state.updated_at = data.get("updated_at", state.started_at)
            except Exception:
                pass
        return state

    def mark_step_done(self, step: int) -> None:
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        self.current_step = step + 1
        self.save()


# ── 各步骤实现 ─────────────────────────────────────────────────────────────────

def _step1_synthesize(state: WizardState) -> bool:
    """Step 1: 意图合成"""
    _step_header(1, 7, "意图合成（mms synthesize）")
    print(f"  模型：{_c('qwen3-32b（百炼）', _C)}\n")

    if state.task_desc:
        if not _ask("重新输入任务描述？", default="N"):
            task_desc = state.task_desc
        else:
            task_desc = _ask_multiline("请输入任务描述（支持多行）", default="")
    else:
        task_desc = _ask_multiline("请输入任务描述（支持多行）")

    if not task_desc:
        print(f"  {_c('❌', _R)} 任务描述不能为空")
        return False

    templates = [
        "ep-backend-api", "ep-frontend", "ep-ontology",
        "ep-data-pipeline", "ep-debug", "ep-devops", "ep-others",
    ]
    print(f"\n  可用模板：{', '.join(templates)}")
    template = _ask_text("EP 类型模板", default=state.template or "ep-backend-api")

    state.task_desc = task_desc
    state.template = template
    state.save()

    if not _ask("立即执行 mms synthesize？"):
        print(f"  {_c('⏭️  已跳过', _Y)}")
        return True

    cmd = [sys.executable, str(_HERE / "cli.py"), "synthesize",
           task_desc, "--template", template]
    rc = _run_cmd(cmd, "意图合成", ep_id=state.ep_id, step="synthesize")
    return rc == 0


def _step2_ep_confirm(state: WizardState) -> bool:
    """Step 2: 确认 EP 文件已在 Cursor 中生成"""
    _step_header(2, 7, "确认 EP 文件")
    print(f"  请在 Cursor 对话中根据上一步的提示词生成 EP 文件。")
    print(f"  EP 文件应保存到：{_c('docs/execution_plans/', _C)}{state.ep_id}_*.md\n")

    # 尝试自动查找
    ep_dir = _ROOT / "docs" / "execution_plans"
    if ep_dir.exists():
        candidates = sorted(ep_dir.glob(f"{state.ep_id}_*.md"))
        if candidates:
            ep_file = str(candidates[-1].relative_to(_ROOT))
            print(f"  {_c('✅', _G)} 已自动找到 EP 文件：{ep_file}")
            state.ep_file = ep_file
            state.save()
            return True

    print(f"  {_c('⚠️ ', _Y)} 未自动找到 EP 文件，请确认文件已创建后按 Enter 继续")
    input("  → 按 Enter 继续...")

    # 再次查找
    if ep_dir.exists():
        candidates = sorted(ep_dir.glob(f"{state.ep_id}_*.md"))
        if candidates:
            ep_file = str(candidates[-1].relative_to(_ROOT))
            print(f"  {_c('✅', _G)} 找到 EP 文件：{ep_file}")
            state.ep_file = ep_file
            state.save()

    return True


def _step3_precheck(state: WizardState) -> bool:
    """Step 3: 建立基线（EP-131 改造：自动执行，去掉强制确认）"""
    _step_header(3, 7, "建立基线（mms precheck）")
    print(f"  运行 arch_check 基线检查，记录当前代码状态。\n")

    cmd = [sys.executable, str(_HERE / "cli.py"), "precheck", "--ep", state.ep_id]
    rc = _run_cmd(cmd, "precheck 基线建立", ep_id=state.ep_id, step="precheck")
    # precheck 失败时仅警告，不阻塞（存在预存警告的项目正常情况下也能继续）
    if rc != 0:
        print(f"  {_c('⚠️  precheck 存在警告，继续执行', _Y)}")
    return True


def _step4_dag_generate(state: WizardState) -> bool:
    """Step 4: 生成 DAG（EP-131 改造：自动执行，去掉强制确认）"""
    _step_header(4, 7, "生成 DAG 执行计划（mms unit generate）")
    print(f"  模型：{_c('gemini-2.5-pro（Google）', _C)}")
    print(f"  将 EP 分解为原子 Unit，生成有向无环图执行计划。\n")

    cmd = [sys.executable, str(_HERE / "cli.py"), "unit", "generate", "--ep", state.ep_id]
    rc = _run_cmd(cmd, "DAG 生成", ep_id=state.ep_id, step="dag_generate")

    if rc == 0:
        # 读取生成的 DAG 统计 Unit 数
        dag_file = _ROOT / "docs" / "memory" / "_system" / "dag" / f"{state.ep_id}.json"
        if dag_file.exists():
            try:
                dag_data = json.loads(dag_file.read_text(encoding="utf-8"))
                units = dag_data.get("units", [])
                state.total_units = len(units)
                state.save()
                print(f"  {_c('·', _D)} DAG 共 {state.total_units} 个 Unit")
            except Exception:
                pass

    return rc == 0


def _step5_unit_loop(state: WizardState) -> bool:
    """Step 5: Unit 执行循环（双模型对比）

    流程：
      A→B→C→D（qwen生成 + Sonnet生成 + sonnet-save + compare）逐 Unit 执行
      所有 Unit 的 compare 完成后，统一一次性选择每个 Unit 使用哪个版本并 apply
    """
    _step_header(5, 7, "Unit 执行循环（双模型对比）")

    # 读取 DAG 获取 Unit 列表
    dag_file = _ROOT / "docs" / "memory" / "_system" / "dag" / f"{state.ep_id}.json"
    units: List[dict] = []
    if dag_file.exists():
        try:
            dag_data = json.loads(dag_file.read_text(encoding="utf-8"))
            units = dag_data.get("units", [])
        except Exception:
            pass

    if not units:
        print(f"  {_c('⚠️ ', _Y)} 未找到 DAG 文件或 Unit 列表为空")
        print(f"  请先执行 Step 4 或手动运行：mms unit generate --ep {state.ep_id}")
        if not _ask("手动指定 Unit 数量继续？", default="N"):
            return False
        try:
            n = int(_ask_text("Unit 数量", default="1"))
            units = [{"id": f"U{i+1}", "title": f"Unit {i+1}"} for i in range(n)]
        except ValueError:
            return False

    total = len(units)
    pending = [u for u in units if u["id"] not in state.completed_units]

    print(f"  共 {total} 个 Unit，已完成 {len(state.completed_units)} 个，待执行 {len(pending)} 个\n")
    print(f"  {_c('流程说明：', _D)} 先对所有 Unit 完成 A→D（生成+对比），最后统一选择版本并 apply\n")

    # ── Phase 1：逐 Unit 完成 A→D（生成+对比），不 apply ────────────────────────
    compare_results: List[dict] = []  # 记录每个 Unit 的对比状态

    for unit in pending:
        unit_id = unit["id"]
        unit_title = unit.get("title", unit_id)
        compare_dir = _ROOT / "docs" / "memory" / "private" / "compare" / state.ep_id / unit_id.upper()

        print(f"\n  {_c(f'── {unit_id}: {unit_title}', _B)}")
        _hr("  ·")

        # A 路径：qwen 代码生成
        print(f"\n  {_c('A. qwen 代码生成', _C)}  [{_c('qwen3-coder-next', _D)}]")
        if _ask(f"执行 mms unit run --save-output ({unit_id})？"):
            cmd = [sys.executable, str(_HERE / "cli.py"), "unit", "run",
                   "--ep", state.ep_id, "--unit", unit_id, "--save-output"]
            _run_cmd(cmd, f"qwen 代码生成 {unit_id}")
        else:
            print(f"    {_c('⏭️  已跳过', _Y)}")

        # B 路径：在终端直接打印 context.md 内容，供用户发送给 Cursor Sonnet
        context_file = compare_dir / "context.md"
        print(f"\n  {_c('B. Cursor Sonnet 代码生成', _C)}  [{_c('手动', _D)}]")
        if context_file.exists():
            print(f"    · context.md 路径：{context_file}")
            print(f"\n{'─' * 60}")
            print(_c("  ▼ 请将以下内容全部发送给 Cursor Sonnet", _Y))
            print("─" * 60)
            try:
                ctx_content = context_file.read_text(encoding="utf-8")
                print(ctx_content)
            except Exception as e:
                print(f"    {_c(f'⚠️  读取 context.md 失败：{e}', _Y)}")
            print("─" * 60)
            print(_c("  ▲ 内容结束（Sonnet 输出完成后继续）", _Y))
            print("─" * 60)
        else:
            print(f"    {_c('⚠️  context.md 尚未生成，请先执行步骤 A', _Y)}")
        print(f"\n    · Sonnet 输出后，将 ===BEGIN-CHANGES=== 格式块粘贴到终端：")
        print(f"      {_c(f'mms unit sonnet-save --ep {state.ep_id} --unit {unit_id}', _D)}")
        input("    → Sonnet 输出完成后按 Enter 继续...")

        # C：存盘 Sonnet 输出
        print(f"\n  {_c('C. 存盘 Sonnet 输出', _C)}")
        sonnet_file = compare_dir / "sonnet.txt"
        if not sonnet_file.exists():
            if _ask("现在运行 mms unit sonnet-save（从 stdin 读取）？"):
                cmd = [sys.executable, str(_HERE / "cli.py"), "unit", "sonnet-save",
                       "--ep", state.ep_id, "--unit", unit_id]
                subprocess.run(cmd, cwd=str(_ROOT))
        else:
            print(f"    {_c('✅', _G)} sonnet.txt 已存在：{sonnet_file}")

        # D：Diff + Gemini 评审
        compare_ok = False
        report_file = compare_dir / "report.md"
        print(f"\n  {_c('D. Diff 对比 + Gemini 语义评审', _C)}  [{_c('gemini-2.5-pro', _D)}]")
        if _ask(f"执行 mms unit compare ({unit_id})？"):
            cmd = [sys.executable, str(_HERE / "cli.py"), "unit", "compare",
                   "--ep", state.ep_id, "--unit", unit_id]
            rc = _run_cmd(cmd, f"对比报告 + Gemini 评审 {unit_id}",
                          ep_id=state.ep_id, step="compare", unit_id=unit_id)
            compare_ok = rc == 0
            if report_file.exists():
                print(f"    · 报告路径：{report_file}")

        compare_results.append({
            "unit_id": unit_id,
            "unit_title": unit_title,
            "compare_ok": compare_ok,
            "report_file": str(report_file),
        })

    # ── Phase 2：所有 Unit compare 完成，统一选择版本并批量 apply ─────────────────
    if not compare_results:
        return True

    print(f"\n\n{'═' * 60}")
    print(_c("  ✅ 所有 Unit 的对比评审已完成，现在统一选择版本", _B))
    print(f"{'═' * 60}")
    print(f"  {_c('请阅读各 Unit 的 report.md 后做出选择（qwen / sonnet / skip）', _D)}\n")

    # 展示所有 report.md 路径供快速查阅
    for cr in compare_results:
        icon = _c("✅", _G) if cr["compare_ok"] else _c("⚠️ ", _Y)
        print(f"  {icon} {cr['unit_id']}: {cr['unit_title']}")
        print(f"       报告：{cr['report_file']}")
    print()

    # 批量收集选择
    apply_choices: List[Tuple[str, str]] = []  # [(unit_id, choice)]
    for cr in compare_results:
        unit_id = cr["unit_id"]
        unit_title = cr["unit_title"]
        default_choice = "qwen"
        print(f"  {_c(unit_id, _B)} — {unit_title}")
        choice = _ask_text(
            f"    应用哪个版本？(qwen/sonnet/skip)",
            default=default_choice,
        ).lower().strip()
        apply_choices.append((unit_id, choice))

    # 执行批量 apply
    print(f"\n  {_c('── 开始批量应用 ──', _B)}")
    for unit_id, choice in apply_choices:
        if choice not in ("qwen", "sonnet"):
            print(f"  {_c('⏭️ ', _Y)} {unit_id}：已跳过（{choice}）")
            continue
        cmd = [sys.executable, str(_HERE / "cli.py"), "unit", "compare",
               "--apply", choice, "--ep", state.ep_id, "--unit", unit_id]
        rc = _run_cmd(cmd, f"应用 {choice} 版本 {unit_id}",
                      ep_id=state.ep_id, step="apply", unit_id=unit_id)
        if rc == 0:
            state.completed_units.append(unit_id)
            state.save()
            print(f"    {_c('✅', _G)} {unit_id} 已完成")
        else:
            print(f"    {_c('❌', _R)} {unit_id} 应用失败，请手动检查后运行：")
            print(f"       mms unit compare --apply {choice} --ep {state.ep_id} --unit {unit_id}")

    done_count = len(state.completed_units)
    print(f"\n  {_c(f'Unit 完成进度：{done_count}/{total}', _G if done_count == total else _Y)}")
    return True


def _step6_postcheck(state: WizardState) -> bool:
    """Step 6: 后校验（EP-131 改造：自动执行，去掉强制确认）"""
    _step_header(6, 7, "后校验（mms postcheck）")
    print(f"  运行 pytest + arch_check diff，验证所有变更符合架构规范。\n")

    cmd = [sys.executable, str(_HERE / "cli.py"), "postcheck", "--ep", state.ep_id]
    rc = _run_cmd(cmd, "后校验", ep_id=state.ep_id, step="postcheck")
    if rc != 0:
        print(f"  {_c('⚠️  postcheck 存在问题，请查看报告后手动修复', _Y)}")
    return True


def _step7_distill(state: WizardState) -> bool:
    """Step 7: 知识沉淀"""
    _step_header(7, 7, "知识沉淀")
    print(f"  模型：{_c('qwen3-32b（百炼）', _C)}\n")

    # autoDream
    if _ask("运行 mms dream（自动萃取 EP 知识草稿）？"):
        cmd = [sys.executable, str(_HERE / "cli.py"), "dream", "--ep", state.ep_id]
        _run_cmd(cmd, "autoDream 知识萃取", ep_id=state.ep_id, step="dream")

    # 手动蒸馏
    if _ask("运行 mms distill（深度蒸馏 EP → 记忆条目）？"):
        cmd = [sys.executable, str(_HERE / "cli.py"), "distill", "--ep", state.ep_id]
        _run_cmd(cmd, "知识蒸馏", ep_id=state.ep_id, step="distill")

    return True


# ── 主入口 ────────────────────────────────────────────────────────────────────

_STEPS = [
    (1, "意图合成",      _step1_synthesize),
    (2, "确认 EP 文件",  _step2_ep_confirm),
    (3, "建立基线",      _step3_precheck),
    (4, "生成 DAG",      _step4_dag_generate),
    (5, "Unit 执行循环", _step5_unit_loop),
    (6, "后校验",        _step6_postcheck),
    (7, "知识沉淀",      _step7_distill),
]


def run_ep_wizard(ep_id: str, from_step: int = 1) -> int:
    """
    执行 EP 交互式工作流向导。

    Args:
        ep_id:     EP 编号（如 "EP-122"）
        from_step: 从第几步开始（默认 1，支持断点续跑）

    Returns:
        0 = 完成所有步骤，1 = 中途退出
    """
    ep_id = ep_id.upper()
    state = WizardState.load(ep_id)

    _header(f"MMS EP 工作流向导 — {ep_id}")
    print(f"\n  模型分工：")
    print(f"    意图识别  →  {_c('qwen3-32b', _C)}（百炼）")
    print(f"    DAG 生成  →  {_c('gemini-2.5-pro', _C)}（Google）")
    print(f"    代码生成  →  {_c('qwen3-coder-next', _C)}（百炼 A 路径）")
    print(f"               {_c('Cursor Sonnet', _C)}（B 路径，手动）")
    print(f"    语义评审  →  {_c('gemini-2.5-pro', _C)}（Google，自动）")
    print(f"    知识蒸馏  →  {_c('qwen3-32b', _C)}（百炼）")
    print(f"\n  共 7 步。按 Ctrl+C 可随时中断，下次从当前步骤续跑。\n")

    if from_step > 1:
        print(f"  {_c(f'▶ 从 Step {from_step} 继续', _Y)}\n")

    completed_all = True
    for step_num, step_title, step_fn in _STEPS:
        if step_num < from_step:
            continue

        try:
            ok = step_fn(state)
        except KeyboardInterrupt:
            print(f"\n\n  {_c('⏸️  用户中断', _Y)} — 进度已保存，下次运行：")
            print(f"    mms ep start {ep_id} --from-step {step_num}\n")
            return 1

        if ok:
            state.mark_step_done(step_num)
        else:
            print(f"\n  {_c(f'❌ Step {step_num} 未通过，建议修复后重新运行此步骤', _R)}")
            print(f"    mms ep start {ep_id} --from-step {step_num}\n")
            completed_all = False
            if not _ask("忽略此步骤错误，继续下一步？", default="N"):
                return 1

    if completed_all:
        _header(f"🎉  {ep_id} 工作流完成！")
        print(f"\n  所有 7 个步骤已完成。建议后续：")
        print(f"    · 查看记忆草稿：mms dream --list")
        print(f"    · 审核并提升：  mms dream --promote")
        print(f"    · 运行 GC：     mms gc\n")
    return 0


def show_ep_status(ep_id: str) -> int:
    """显示 EP 向导进度状态"""
    ep_id = ep_id.upper()
    state = WizardState.load(ep_id)

    _header(f"EP 工作流进度 — {ep_id}")
    print()

    step_names = {
        1: "意图合成",
        2: "确认 EP 文件",
        3: "建立基线",
        4: "生成 DAG",
        5: "Unit 执行循环",
        6: "后校验",
        7: "知识沉淀",
    }

    for step_num, name in step_names.items():
        if step_num in state.completed_steps:
            icon = _c("✅", _G)
        elif step_num == state.current_step:
            icon = _c("▶", _C)
        else:
            icon = _c("○", _D)
        print(f"  {icon} Step {step_num}: {name}")

    if state.task_desc:
        print(f"\n  任务：{state.task_desc[:60]}")
    if state.total_units:
        done = len(state.completed_units)
        print(f"  Unit 进度：{done}/{state.total_units}（{state.completed_units}）")

    print(f"\n  续跑命令：mms ep start {ep_id} --from-step {state.current_step}\n")
    return 0
