"""
unit_cmd.py — mms unit 状态管理命令实现

提供 DAG Unit 生命周期管理的所有子命令：

  mms unit generate --ep EP-NNN           # 生成 DAG
  mms unit status   --ep EP-NNN           # 查看 DAG 执行状态
  mms unit next     --ep EP-NNN [--model] # 获取下一个可执行 Unit + 压缩上下文
  mms unit done     --ep EP-NNN --unit U1 # 标记完成（验证 + git commit）
  mms unit context  --ep EP-NNN --unit U1 # 生成指定 Unit 的执行上下文
  mms unit reset    --ep EP-NNN --unit U1 # 回退 Unit 状态为 pending
  mms unit skip     --ep EP-NNN --unit U1 # 跳过（不验证，不 commit）
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).resolve().parents[2]

# ANSI
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

# 状态图标
STATUS_ICONS = {
    "pending":     f"{_D}⏳{_X}",
    "in_progress": f"{_C}🔄{_X}",
    "done":        f"{_G}✅{_X}",
    "skipped":     f"{_Y}⏭️ {_X}",
}


# ── 通用工具 ──────────────────────────────────────────────────────────────────

def _load_dag(ep_id: str):
    """加载 DAG 状态，失败时打印友好错误"""
    try:
        from dag_model import DagState  # type: ignore[import]
    except ImportError:
        from mms.dag_model import DagState  # type: ignore[import]
    return DagState.load(ep_id)


def _git_commit(ep_id: str, unit_id: str, title: str) -> Optional[str]:
    """
    执行 git add -A && git commit，返回 commit hash。
    失败时返回 None（不中断流程）。
    """
    commit_msg = f"{ep_id} {unit_id}: {title}"
    try:
        subprocess.run(["git", "add", "-A"], cwd=_ROOT, check=True, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=_ROOT, check=True, capture_output=True, text=True,
        )
        # 提取 commit hash
        hash_match = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_ROOT, capture_output=True, text=True,
        )
        return hash_match.stdout.strip() if hash_match.returncode == 0 else None
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
        if "nothing to commit" in stderr:
            print(f"  {_Y}⚠️  无新文件变更，跳过 git commit{_X}")
        else:
            print(f"  {_Y}⚠️  git commit 失败：{stderr[:100]}{_X}")
        return None


def _run_tests(test_files: List[str]) -> bool:
    """运行指定测试文件，返回是否通过"""
    existing = [f for f in test_files if (_ROOT / f).exists()]
    if not existing:
        return True

    print(f"  {_D}运行测试（{len(existing)} 个文件）...{_X}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *existing, "-v", "--tb=short", "-q"],
        cwd=_ROOT, capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + result.stderr
    # 打印摘要
    for line in output.splitlines():
        if any(kw in line for kw in ("passed", "failed", "error", "PASSED", "FAILED")):
            print(f"    {line}")
    return result.returncode == 0


# ── status ────────────────────────────────────────────────────────────────────

def cmd_unit_status(ep_id: str) -> int:
    """mms unit status --ep EP-NNN"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        dag = _load_dag(ep_norm)
    except FileNotFoundError as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1

    done, total = dag.progress()
    pct = int(done / total * 100) if total else 0
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)

    print(f"\n{_B}{ep_norm} DAG 执行状态{_X}（{total} 个 Unit）")
    print(f"  进度 [{bar}] {pct}%  {done}/{total}")
    print("─" * 62)

    batches = dag.get_batch_groups()
    for batch in batches:
        order = batch[0].order
        parallel_note = f"  {_D}（可并行）{_X}" if len(batch) > 1 else ""
        print(f"\n  {_C}Batch {order}{_X}{parallel_note}")
        for u in batch:
            icon = STATUS_ICONS.get(u.status, "❓")
            hint_color = _G if u.model_hint == "8b" else (_Y if u.model_hint == "16b" else _C)
            commit_str = f"{_D}git:{u.git_commit[:7]}{_X}" if u.git_commit else ""
            deps_str = f"{_D}← {', '.join(u.depends_on)}{_X}" if u.depends_on else ""
            files_str = f"{len(u.files)+len(u.test_files)} files"
            print(
                f"    {icon} {_B}{u.id}{_X} {u.title[:32]:<32} "
                f"{hint_color}[{u.model_hint}]{_X} "
                f"{_D}{files_str}{_X}  {commit_str} {deps_str}"
            )

    print(f"\n{'─' * 62}")
    next_unit = dag.next_executable()
    if next_unit:
        print(f"  下一步：{_C}mms unit next --ep {ep_norm} --model {next_unit.model_hint}{_X}")
    elif dag.overall_status == "done":
        print(f"  {_G}✅ 所有 Unit 已完成！{_X}")
        print(f"  {_D}建议：mms postcheck --ep {ep_norm}{_X}")
    print()
    return 0


# ── next ──────────────────────────────────────────────────────────────────────

def cmd_unit_next(ep_id: str, model: str = "capable") -> int:
    """mms unit next --ep EP-NNN [--model 8b|16b|capable]"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        dag = _load_dag(ep_norm)
    except FileNotFoundError as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1

    unit = dag.next_executable(model=model)
    if unit is None:
        done, total = dag.progress()
        if done == total:
            print(f"\n{_G}✅ {ep_norm} 所有 Unit 已完成！{_X}")
            print(f"  运行：{_C}mms postcheck --ep {ep_norm}{_X}")
        else:
            print(f"\n{_Y}⚠️  当前无可执行 Unit（等待依赖完成）{_X}")
            print(f"  运行：{_C}mms unit status --ep {ep_norm}{_X} 查看详情")
        return 0

    print(f"\n{_B}下一个 Unit：{ep_norm} {unit.id}{_X}")
    print(f"  标题：{unit.title}")
    print(f"  层级：{unit.layer}")
    print(f"  模型建议：{unit.model_hint}（原子化得分：{unit.atomicity_score:.2f}）")
    print(f"  涉及文件：")
    for f in unit.files:
        exists = "✅" if (_ROOT / f).exists() else "📝(新建)"
        print(f"    {exists} {f}")
    for f in unit.test_files:
        exists = "✅" if (_ROOT / f).exists() else "📝(新建)"
        print(f"    {exists} {f} [test]")

    # 标记为 in_progress
    dag.mark_in_progress(unit.id)
    dag.save()

    print(f"\n{_D}─ 执行上下文 ──────────────────────────────────{_X}")

    # 生成压缩上下文
    try:
        from unit_context import generate_unit_context  # type: ignore[import]
    except ImportError:
        from mms.unit_context import generate_unit_context  # type: ignore[import]

    try:
        from ep_parser import parse_ep_by_id  # type: ignore[import]
    except ImportError:
        from mms.ep_parser import parse_ep_by_id  # type: ignore[import]

    description = ""
    try:
        parsed = parse_ep_by_id(ep_norm)
        for su in parsed.scope_units:
            if su.unit_id == unit.id:
                description = su.description
                break
    except Exception:
        pass

    context = generate_unit_context(
        unit_id=unit.id,
        title=unit.title,
        layer=unit.layer,
        files=unit.files,
        test_files=unit.test_files,
        model=model,
        ep_id=ep_norm,
        description=description,
    )
    print(context)

    print(f"\n{_D}完成后运行：{_C}mms unit done --ep {ep_norm} --unit {unit.id}{_X}\n")
    return 0


# ── done ──────────────────────────────────────────────────────────────────────

def cmd_unit_done(
    ep_id: str,
    unit_id: str,
    skip_tests: bool = False,
    skip_commit: bool = False,
) -> int:
    """mms unit done --ep EP-NNN --unit U1"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        dag = _load_dag(ep_norm)
    except FileNotFoundError as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1

    try:
        unit = dag._get_unit(unit_id)
    except ValueError as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1

    print(f"\n{_B}mms unit done · {ep_norm} {unit_id}{_X}")
    print(f"  {unit.title}")
    print("─" * 55)

    # ── A1: 原子性验证 ───────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 1 · 原子性验证{_X}")
    try:
        from atomicity_check import validate_unit  # type: ignore[import]
    except ImportError:
        from mms.atomicity_check import validate_unit  # type: ignore[import]

    all_files = unit.files + unit.test_files
    _, score, _ = validate_unit(files=all_files, model=unit.model_hint, verbose=True)

    # ── A2: 运行测试 ─────────────────────────────────────────────────────────
    if not skip_tests and unit.test_files:
        print(f"\n{_C}▶ Step 2 · 运行测试（pytest）{_X}")
        tests_passed = _run_tests(unit.test_files)
        if not tests_passed:
            print(f"\n{_R}❌ 测试失败，Unit 未标记为完成{_X}")
            print(f"  修复测试后重新运行：{_C}mms unit done --ep {ep_norm} --unit {unit_id}{_X}")
            return 1
        print(f"  {_G}✅ 测试通过{_X}")
    else:
        print(f"\n{_C}▶ Step 2 · 跳过测试{_X}（{'--skip-tests' if skip_tests else '无测试文件'}）")

    # ── A3: git commit ───────────────────────────────────────────────────────
    commit_hash = None
    if not skip_commit:
        print(f"\n{_C}▶ Step 3 · git commit{_X}")
        commit_hash = _git_commit(ep_norm, unit_id, unit.title)
        if commit_hash:
            print(f"  {_G}✅ git commit：{commit_hash}{_X}")

    # ── 更新 DAG 状态 ────────────────────────────────────────────────────────
    dag.mark_done(unit_id, commit_hash)
    dag.save()
    done, total = dag.progress()

    print(f"\n{'─' * 55}")
    print(f"  {_G}{_B}✅ {ep_norm} {unit_id} 已完成！{_X}")
    print(f"  进度：{done}/{total} Units")

    # 提示下一步
    next_unit = dag.next_executable()
    if next_unit:
        print(f"\n  下一个 Unit：{_C}mms unit next --ep {ep_norm} --model {next_unit.model_hint}{_X}")
    elif done == total:
        print(f"\n  {_G}所有 Unit 完成！{_X}")
        print(f"  运行后校验：{_C}mms postcheck --ep {ep_norm}{_X}")
    print()
    return 0


# ── context ───────────────────────────────────────────────────────────────────

def cmd_unit_context(ep_id: str, unit_id: str, model: str = "capable") -> int:
    """mms unit context --ep EP-NNN --unit U1"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        from unit_context import generate_from_dag  # type: ignore[import]
    except ImportError:
        from mms.unit_context import generate_from_dag  # type: ignore[import]

    try:
        context = generate_from_dag(ep_norm, unit_id, model)
        print(context)
        return 0
    except Exception as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1


# ── reset ─────────────────────────────────────────────────────────────────────

def cmd_unit_reset(ep_id: str, unit_id: str) -> int:
    """mms unit reset --ep EP-NNN --unit U1"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        dag = _load_dag(ep_norm)
        unit = dag._get_unit(unit_id)
        old_status = unit.status
        dag.reset_unit(unit_id)
        dag.save()
        print(f"\n{_Y}⚠️  {ep_norm} {unit_id} 已重置：{old_status} → pending{_X}")
        print(f"  {_D}注意：git commit 未回退，如需回退请手动 git revert{_X}\n")
        return 0
    except Exception as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1


# ── skip ──────────────────────────────────────────────────────────────────────

def cmd_unit_skip(ep_id: str, unit_id: str) -> int:
    """mms unit skip --ep EP-NNN --unit U1（跳过，不验证不 commit）"""
    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    try:
        dag = _load_dag(ep_norm)
        dag.mark_skipped(unit_id)
        dag.save()
        done, total = dag.progress()
        print(f"\n{_Y}⏭️  {ep_norm} {unit_id} 已跳过（{done}/{total}）{_X}\n")
        return 0
    except Exception as e:
        print(f"\n{_R}❌ {e}{_X}")
        return 1
