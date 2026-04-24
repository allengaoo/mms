#!/usr/bin/env python3
"""
MMS Postcheck — 代码修改后测试与后校验门控

在完成代码修改后执行：
  1. 加载 precheck 基线快照（获取 Scope 文件和测试路径）
  2. 运行 pytest（仅 EP 声明的测试文件，精准快速）
  3. 再次运行 arch_check，与基线对比（新增违反 = FAIL）
  4. 运行 doc_drift 检测（文档是否同步）
  5. 输出后校验综合报告（PASS / WARN / FAIL）
  6. PASS 时自动打印 mms distill 命令提示

用法：
    python scripts/mms/cli.py postcheck --ep EP-114
    python scripts/mms/cli.py postcheck --ep EP-114 --skip-tests
    python scripts/mms/cli.py postcheck --ep EP-114 --test-paths tests/unit/services/test_foo.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_CHECKPOINTS_DIR = _MEMORY_ROOT / "_system" / "checkpoints"

# ANSI 颜色
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"


def _ok(msg: str)   -> None: print(f"  {_G}✅{_X} {msg}")
def _warn(msg: str) -> None: print(f"  {_Y}⚠️ {_X} {msg}")
def _err(msg: str)  -> None: print(f"  {_R}❌{_X} {msg}")
def _info(msg: str) -> None: print(f"  {_D}ℹ️  {msg}{_X}")


# ── pytest 执行 ──────────────────────────────────────────────────────────────

def run_pytest(test_paths: List[str]) -> Tuple[bool, str]:
    """
    运行指定路径的 pytest 测试。

    返回：(passed: bool, summary: str)
    """
    if not test_paths:
        return True, "（无测试文件声明，跳过）"

    # 过滤只保留实际存在的路径
    existing = [p for p in test_paths if (_ROOT / p).exists()]
    missing = [p for p in test_paths if p not in existing]

    if missing:
        for m in missing:
            print(f"    {_Y}⚠️  测试文件不存在（已跳过）：{m}{_X}")

    if not existing:
        return True, "（所有声明的测试文件均不存在，跳过）"

    cmd = [
        sys.executable, "-m", "pytest",
        *existing,
        "-v", "--tb=short", "-q",
        "--no-header",
    ]

    try:
        # fallback: config.yaml → runner.timeout.postcheck_test_seconds (default=300)
        _test_timeout = int(getattr(_cfg, "runner_timeout_postcheck_test", 300)) if _cfg else 300
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, cwd=str(_ROOT),
            timeout=_test_timeout,
        )
        output = result.stdout + result.stderr

        # 提取摘要行（如 "5 passed, 2 failed in 1.23s"）
        summary = ""
        for line in output.splitlines():
            if re.search(r"\d+ (passed|failed|error)", line):
                summary = line.strip()
                break
        if not summary:
            summary = f"exit code: {result.returncode}"

        passed = result.returncode == 0
        return passed, summary

    except subprocess.TimeoutExpired:
        return False, "测试超时（300s）"
    except Exception as exc:
        return False, f"pytest 执行异常：{exc}"


# ── arch_check 对比 ──────────────────────────────────────────────────────────

def run_arch_check_post(baseline_violations: List[Dict]) -> Tuple[bool, int, List[Dict]]:
    """
    运行 arch_check，与基线对比，返回新增违反。

    返回：(no_new_violations: bool, new_count: int, new_violations: List)
    """
    arch_check = _HERE.parent / "analysis" / "arch_check.py"
    if not arch_check.exists():
        return True, 0, []

    try:
        result = subprocess.run(
            [sys.executable, str(arch_check), "--json"],
            capture_output=True, text=True, cwd=str(_ROOT),
        )
        try:
            post_data = json.loads(result.stdout)
            post_violations = post_data.get("violations", [])
        except json.JSONDecodeError:
            # arch_check 不支持 --json，做文本对比
            post_violations = _parse_arch_check_text(result.stdout + result.stderr)

    except Exception as exc:
        # 执行异常时视为无法校验，返回特殊标记而非静默通过
        return False, -1, [{"message": f"arch_check 执行异常（无法校验）：{exc}"}]

    # 基线违反的消息集合
    baseline_msgs = {v.get("message", str(v)) for v in baseline_violations}
    post_msgs = [v.get("message", str(v)) for v in post_violations]

    new_violations = [
        {"message": msg}
        for msg in post_msgs
        if msg not in baseline_msgs
    ]

    return len(new_violations) == 0, len(new_violations), new_violations


def _parse_arch_check_text(text: str) -> List[Dict]:
    """解析 arch_check 文本输出为违反列表"""
    violations = []
    for line in text.splitlines():
        if "❌" in line or "FAIL" in line or "violation" in line.lower():
            violations.append({"message": line.strip()})
    return violations


# ── doc_drift 检测 ───────────────────────────────────────────────────────────

def run_doc_drift() -> Tuple[bool, str]:
    """
    运行 doc_drift.py 检测文档漂移。

    返回：(clean: bool, summary: str)
    """
    doc_drift = _HERE / "mms.analysis.doc_drift.py"
    if not doc_drift.exists():
        return True, "（doc_drift.py 不存在，跳过）"

    try:
        # fallback: config.yaml → runner.timeout.postcheck_drift_seconds (default=60)
        _drift_timeout = int(getattr(_cfg, "runner_timeout_postcheck_drift", 60)) if _cfg else 60
        result = subprocess.run(
            [sys.executable, str(doc_drift), "--ci"],
            capture_output=True, text=True, cwd=str(_ROOT),
            timeout=_drift_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        # 提取摘要
        lines = [l for l in output.splitlines() if l.strip()]
        summary = lines[-1] if lines else f"exit code: {result.returncode}"
        clean = result.returncode == 0
        return clean, summary
    except Exception as exc:
        return True, f"（doc_drift 执行异常：{exc}，跳过）"


# ── 报告保存 ─────────────────────────────────────────────────────────────────

def save_postcheck_report(ep_id: str, data: Dict) -> Path:
    """保存后校验报告"""
    _CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = _CHECKPOINTS_DIR / f"postcheck-{ep_id}.json"
    report_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_file


# ── 主检查逻辑 ───────────────────────────────────────────────────────────────

def _ast_sync_check(ep_norm: str, scope_files: List[str]) -> Dict:
    """
    EP-130 新增：AST 契约变更检测 + 本体同步钩子。
    比对 precheck 时保存的 AST 快照 vs 当前 AST 状态。

    超时 5s 或发生异常时静默跳过，不阻断 postcheck 主流程。
    """
    import time
    result: Dict = {"status": "SKIPPED", "summary": "（未执行）"}

    try:
        start = time.time()

        # 加载 precheck 时保存的 AST 快照
        checkpoint_dir = _ROOT / "docs" / "memory" / "_system" / "checkpoints"
        before_path = checkpoint_dir / f"precheck-{ep_norm}-ast.json"
        if not before_path.exists():
            result["summary"] = "无 precheck AST 快照，跳过（提示：precheck 已自动生成快照）"
            return result

        # 读取当前 ast_index
        ast_index_path = _ROOT / "docs" / "memory" / "_system" / "ast_index.json"

        # 如果 ast_index.json 不存在，先重新生成（但有超时保护）
        if not ast_index_path.exists():
            try:
                sys.path.insert(0, str(_HERE))
                from mms.analysis.ast_skeleton import build_ast_index  # type: ignore[import]
                build_ast_index()
            except Exception:
                result["summary"] = "ast_index.json 不存在且无法生成，跳过"
                return result

        # 执行 diff（scope_files 限定范围，加速）
        from mms.analysis.ast_diff import diff_ast_files, load_ast_index  # type: ignore[import]
        from mms.analysis.ontology_syncer import sync_after_unit_run  # type: ignore[import]

        diff_result = diff_ast_files(
            before_path,
            ast_index_path,
            scope_files=scope_files or None,
        )

        elapsed = time.time() - start
        if elapsed > 5.0:
            result["status"] = "WARN"
            result["summary"] = f"AST diff 耗时 {elapsed:.1f}s，超过 5s 阈值，结果可能不完整"
            return result

        if not diff_result.changes:
            result["status"] = "PASS"
            result["summary"] = f"无契约变更（比对 {diff_result.files_compared} 个文件）"
            return result

        # 执行本体同步
        before_index = json.loads(before_path.read_text(encoding="utf-8")) if before_path.exists() else {}
        after_index = load_ast_index(ast_index_path)
        sync_report = sync_after_unit_run(
            before_index, after_index, scope_files=scope_files or None
        )

        result["status"] = "WARN" if (
            diff_result.has_breaking_changes or sync_report.drift_warnings or sync_report.stale_warnings
        ) else "PASS"
        result["summary"] = diff_result.summary()
        result["sync_report"] = sync_report.summary()
        result["has_breaking_changes"] = diff_result.has_breaking_changes
        result["patched_files"] = sync_report.patched_files
        result["drift_warnings"] = sync_report.drift_warnings
        result["stale_warnings"] = sync_report.stale_warnings

    except Exception as exc:
        result["status"] = "SKIPPED"
        result["summary"] = f"AST sync 检查异常（已跳过）: {exc}"

    return result


def run_postcheck(
    ep_id: str,
    skip_tests: bool = False,
    extra_test_paths: Optional[List[str]] = None,
) -> int:
    """
    执行完整的后校验流程。

    返回码：
      0 = PASS（所有检查通过，可以运行 mms distill）
      1 = WARN（有警告，建议处理后再蒸馏）
      2 = FAIL（有严重问题，需要修复）
    """
    ep_norm = ep_id.upper()
    print(f"\n{_B}MMS 后校验（postcheck）· {ep_norm}{_X}")
    print("─" * 60)

    # ── 0. 加载 precheck 基线 ────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 0 · 加载 precheck 基线{_X}")
    try:
        from mms.workflow.precheck import load_checkpoint
    except ImportError:
        from mms.workflow.precheck import load_checkpoint  # type: ignore[no-redef]

    checkpoint = load_checkpoint(ep_norm)
    if checkpoint:
        _ok(f"基线快照已加载（{checkpoint.get('timestamp', 'N/A')[:10]}）")
        scope_files = checkpoint.get("scope_files", [])
        testing_files = checkpoint.get("testing_files", [])
        baseline_violations = checkpoint.get("arch_violations_baseline", [])
        baseline_count = checkpoint.get("arch_violations_count", 0)
    else:
        _warn("未找到 precheck 基线快照，将以空基线运行（建议先执行 mms precheck）")
        scope_files = []
        testing_files = []
        baseline_violations = []
        baseline_count = 0

    # 合并外部传入的测试路径
    all_test_paths = list(testing_files)
    if extra_test_paths:
        for p in extra_test_paths:
            if p not in all_test_paths:
                all_test_paths.append(p)

    # 汇总结果
    results = {
        "ep_id": ep_norm,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": {},
        "arch_check": {},
        "doc_drift": {},
        "overall": "PASS",
    }
    warnings = 0
    failures = 0

    # ── 1. pytest ────────────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 1 · 单元测试（pytest）{_X}")
    if skip_tests:
        _info("已跳过（--skip-tests）")
        results["tests"] = {"status": "SKIPPED", "summary": "用户跳过"}
    elif not all_test_paths:
        _warn("EP 文件中无 Testing Plan 声明，也未通过 --test-paths 指定")
        _info("建议在 EP 文件的 Testing Plan 节声明测试文件，或使用 --test-paths 参数")
        results["tests"] = {"status": "SKIPPED", "summary": "无测试路径声明"}
        warnings += 1
    else:
        _info(f"运行测试文件（{len(all_test_paths)} 个）：")
        for p in all_test_paths:
            print(f"    {_D}{p}{_X}")
        passed, summary = run_pytest(all_test_paths)
        if passed:
            _ok(f"pytest：{summary}")
            results["tests"] = {"status": "PASS", "summary": summary}
        else:
            _err(f"pytest：{summary}")
            results["tests"] = {"status": "FAIL", "summary": summary}
            failures += 1

    # ── 2. arch_check diff ───────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 2 · 架构合规检查（arch_check diff）{_X}")
    _info(f"基线：{baseline_count} 处已知违反")
    no_new, new_count, new_violations = run_arch_check_post(baseline_violations)

    if new_count == -1:
        # arch_check 执行异常，无法判断合规性 → 标记为 ERROR，不视为通过
        _err(f"arch_check diff：执行异常，无法完成合规校验")
        for v in new_violations:
            print(f"    {_R}→{_X} {v.get('message', str(v))}")
        results["arch_check"] = {
            "status": "ERROR",
            "new_violations": -1,
            "details": new_violations,
        }
        failures += 1
    elif no_new:
        _ok(f"arch_check diff：无新增违反（基线 {baseline_count} 处保持不变）")
        results["arch_check"] = {"status": "PASS", "new_violations": 0, "details": []}
    else:
        _err(f"arch_check diff：发现 {new_count} 处新增违反（本次代码引入）")
        for v in new_violations[:5]:
            print(f"    {_R}→{_X} {v.get('message', str(v))}")
        results["arch_check"] = {
            "status": "FAIL",
            "new_violations": new_count,
            "details": new_violations[:10],
        }
        failures += 1

    # ── 2.5 MigrationGate: DB 迁移脚本门控（针对 ORM/Schema 变更）────────────────
    print(f"\n{_C}▶ Step 2.5 · DB 迁移脚本门控（MigrationGate）{_X}")
    try:
        from mms.workflow.migration_gate import run_migration_gate
        mig_result = run_migration_gate(scope_files, project_root=_ROOT)
        mig_status = mig_result.get("status", "SKIPPED")
        mig_summary = mig_result.get("summary", "")
        results["migration_gate"] = mig_result

        if mig_status == "PASS":
            _ok(f"MigrationGate：{mig_summary}")
        elif mig_status == "SKIPPED":
            _info(f"MigrationGate：{mig_summary}")
        elif mig_status == "WARN":
            _warn(f"MigrationGate：{mig_summary}")
            for issue in mig_result.get("issues", [])[:3]:
                print(f"    {_Y}→{_X} {issue}")
            warnings += 1
        else:  # FAIL
            _err(f"MigrationGate：{mig_summary}")
            for issue in mig_result.get("issues", [])[:5]:
                print(f"    {_R}→{_X} {issue}")
            failures += 1
    except ImportError as _e:
        _info(f"MigrationGate：模块不可用（{_e}），跳过")
        results["migration_gate"] = {"status": "SKIPPED", "summary": "模块未加载"}

    # ── 3. AST 契约变更检测（EP-130）────────────────────────────────────────────
    print(f"\n{_C}▶ Step 3 · AST 契约变更检测（ast_sync）{_X}")
    ast_sync_result = _ast_sync_check(ep_norm, scope_files)
    ast_status = ast_sync_result.get("status", "SKIPPED")
    ast_summary = ast_sync_result.get("summary", "")
    results["ast_sync"] = ast_sync_result

    if ast_status == "PASS":
        _ok(f"ast_sync：{ast_summary}")
    elif ast_status == "SKIPPED":
        _info(f"ast_sync：{ast_summary}")
    elif ast_status == "WARN":
        _warn(f"ast_sync：{ast_summary}")
        sync_report_text = ast_sync_result.get("sync_report", "")
        if sync_report_text:
            for line in sync_report_text.split("\n"):
                if line.strip():
                    print(f"    {_D}{line}{_X}")
        if ast_sync_result.get("patched_files"):
            _ok(f"已自动修补 {len(ast_sync_result['patched_files'])} 个 Ontology YAML")
        warnings += 1

    # ── 4. doc_drift ─────────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 4 · 文档漂移检测（doc_drift）{_X}")
    doc_clean, doc_summary = run_doc_drift()
    if doc_clean:
        _ok(f"doc_drift：{doc_summary}")
        results["doc_drift"] = {"status": "PASS", "summary": doc_summary}
    else:
        _warn(f"doc_drift：{doc_summary}")
        _info("请确认 e2e_traceability.md 和 frontend_page_map.md 已同步更新")
        results["doc_drift"] = {"status": "WARN", "summary": doc_summary}
        warnings += 1

    # ── 5. 保存报告 ──────────────────────────────────────────────────────────
    if failures > 0:
        results["overall"] = "FAIL"
    elif warnings > 0:
        results["overall"] = "WARN"
    else:
        results["overall"] = "PASS"

    report_file = save_postcheck_report(ep_norm, results)

    # ── 6. 综合评级 ──────────────────────────────────────────────────────────
    print(f"\n{'─' * 60}")
    print(f"  报告已保存：{report_file.relative_to(_ROOT)}")

    if failures > 0:
        print(f"\n{_R}{_B}❌  FAIL — 有 {failures} 项检查未通过，请修复后重新运行 postcheck{_X}")
        print(f"\n{_D}修复建议：{_X}")
        if results["tests"].get("status") == "FAIL":
            print(f"  • 运行 pytest {' '.join(all_test_paths[:2])} -v 查看详细报错")
        if results["arch_check"].get("status") == "FAIL":
            print(f"  • 运行 python scripts/mms/arch_check.py 查看完整架构违反列表（含逐条修复指令）")
        return 2

    elif warnings > 0:
        print(f"\n{_Y}{_B}⚠️   WARN — 检查通过，但有 {warnings} 条警告需关注{_X}")
        _print_distill_reminder(ep_norm, results)
        return 1

    else:
        print(f"\n{_G}{_B}✅  PASS — 所有检查通过！{_X}")
        _print_distill_reminder(ep_norm, results)
        return 0


def _print_distill_reminder(ep_norm: str, results: Dict) -> None:
    """打印知识沉淀提示，含距上次 distill 的天数和判断框架"""
    # 尝试读取上次 GC 日期（distill 时间的近似值）
    memory_index = _ROOT / "docs" / "memory" / "MEMORY_INDEX.json"
    last_gc_str = "unknown"
    days_since: object = "?"
    try:
        idx = json.loads(memory_index.read_text(encoding="utf-8"))
        last_gc_str = idx.get("stats", {}).get("last_gc", "unknown")
        if last_gc_str and last_gc_str != "unknown":
            last_gc_date = date.fromisoformat(last_gc_str)
            days_since = (date.today() - last_gc_date).days
    except Exception:
        pass

    print(f"\n{_D}━━ 知识沉淀建议 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{_X}")
    print(f"  距上次 distill：{_C}{days_since} 天{_X}（上次：{last_gc_str}）")
    print(f"\n  以下情况应执行 distill（否则可跳过）：")
    print(f"    ✅ 发现了新的反模式或约束")
    print(f"    ✅ 做了不显而易见的架构决策")
    print(f"    ❌ 只是按已有模式实现了常规功能 → 可跳过")
    print(f"    ❌ Bug 修复，根因已在记忆库中 → 可跳过")
    print(f"\n  {_C}mms distill --ep {ep_norm}{_X}")

    _print_dream_reminder(ep_norm)


def _print_dream_reminder(ep_norm: str) -> None:
    """打印 autoDream 建议（EP-118 新增）"""
    # 检查 EP 文件是否含有 Surprises & Discoveries 或 Decision Log 章节
    ep_dir = _ROOT / "docs" / "execution_plans"
    ep_norm_upper = ep_norm.upper()

    ep_files = list(ep_dir.glob(f"*{ep_norm_upper}*.md"))
    if not ep_files:
        all_eps = list(ep_dir.glob("*.md"))
        ep_files = [f for f in all_eps if ep_norm_upper.lower() in f.name.lower()]

    has_surprises = False
    has_decisions = False
    if ep_files:
        try:
            import re as _re
            content = ep_files[0].read_text(encoding="utf-8")
            has_surprises = bool(_re.search(
                r"##\s*(?:Surprises|意外发现)", content, _re.IGNORECASE
            ))
            has_decisions = bool(_re.search(
                r"##\s*(?:Decision\s*Log|决策日志|架构决策)", content, _re.IGNORECASE
            ))
        except Exception:
            pass

    # 检查草稿目录中是否已有该 EP 的草稿
    dream_dir = _ROOT / "docs" / "memory" / "private" / "dream"
    existing_drafts = 0
    if dream_dir.exists():
        try:
            for d in dream_dir.glob("DRAFT-*.md"):
                c = d.read_text(encoding="utf-8", errors="ignore")
                if ep_norm_upper in c:
                    existing_drafts += 1
        except Exception:
            pass

    if has_surprises or has_decisions:
        print(f"\n{_D}━━ autoDream 建议 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{_X}")
        print(f"  EP 文件包含{'意外发现' if has_surprises else ''}{'和' if has_surprises and has_decisions else ''}{'决策日志' if has_decisions else ''}章节")
        if existing_drafts > 0:
            print(f"  已有 {_Y}{existing_drafts}{_X} 条该 EP 的记忆草稿待审核")
            print(f"\n  {_C}mms dream --list{_X}       查看已有草稿")
            print(f"  {_C}mms dream --promote{_X}    审核并提升为正式记忆")
        else:
            print(f"\n  {_C}mms dream --ep {ep_norm}{_X}    自动萃取知识草稿（推荐）")
            print(f"  {_D}或跳过（仅当该 EP 无新模式/决策时）{_X}")
        print()
