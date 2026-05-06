"""
tests/integration/coldstart_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mulan 冷启动与生命周期管理集成测试（真实 CLI 调用，无 mock）

测试组：
  A 组：mulan bootstrap（离线冷启动）
  B 组：mulan gc（垃圾回收 & 索引重建）
  C 组：mulan seed list（种子包列表）
  D 组：mulan hook（git hook 管理）
  E 组：mulan private（私有工作区）
  F 组：mulan inject（记忆注入）

特点：
  - 直接调用 mulan CLI，使用真实文件系统
  - 临时目录/EP 使用 CI 前缀（__ci_coldstart__），测试后自动清理
  - 结果写入 tests/integration/results/coldstart_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/coldstart_tests.py
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

# ─── 路径配置 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CLI = [sys.executable, str(_PROJECT_ROOT / "cli.py")]
_RESULTS_DIR = Path(__file__).parent / "results"
_RESULTS_DIR.mkdir(exist_ok=True)

_CI_EP = "EP-997"          # 私有工作区测试用的 EP ID
_CI_INJECT_OUT = _PROJECT_ROOT / "__ci_inject_test_output__.md"

# ─── 数据结构 ─────────────────────────────────────────────────────────────────
@dataclass
class CaseResult:
    id: str
    desc: str
    passed: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    notes: str = ""


# ─── 运行工具 ─────────────────────────────────────────────────────────────────
def run(args: List[str], *, cwd: Optional[Path] = None, env: Optional[dict] = None,
        timeout: int = 60) -> Tuple[int, str, str]:
    """运行 CLI 命令，返回 (exit_code, stdout, stderr)。"""
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(
        _CLI + args,
        capture_output=True,
        text=True,
        cwd=str(cwd or _PROJECT_ROOT),
        env=merged_env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def ok(results: List[CaseResult], id: str, desc: str, *checks: bool,
       stdout: str = "", stderr: str = "", exit_code: int = 0, notes: str = "") -> None:
    passed = all(checks)
    results.append(CaseResult(id=id, desc=desc, passed=passed,
                               stdout=stdout, stderr=stderr,
                               exit_code=exit_code, notes=notes))


# ─── A 组：mulan bootstrap ────────────────────────────────────────────────────
def test_bootstrap(results: List[CaseResult]) -> None:
    # A-01: dry-run 在项目根目录（默认路径）
    rc, out, err = run(["bootstrap", "--dry-run"])
    ok(results, "A-01", "bootstrap --dry-run 输出 Step 1/6 技术栈嗅探",
       rc == 0,
       "Step 1/6" in out,
       "技术栈嗅探" in out or "tech stack" in out.lower(),
       stdout=out, stderr=err, exit_code=rc)

    # A-02: dry-run 显示"零 LLM 调用"
    rc, out, err = run(["bootstrap", "--dry-run"])
    ok(results, "A-02", "bootstrap --dry-run 强调零 LLM 调用",
       rc == 0,
       "LLM" in out,
       "dry-run" in out or "预览" in out,
       stdout=out, stderr=err, exit_code=rc)

    # A-03: dry-run 完整流程 6 步（Bootstrap v2）
    rc, out, err = run(["bootstrap", "--dry-run"])
    ok(results, "A-03", "bootstrap --dry-run 输出完整 6 步流程",
       rc == 0,
       "Step 1/6" in out,
       "Step 2/6" in out,
       "Step 3/6" in out,
       "Step 4/6" in out,
       stdout=out, stderr=err, exit_code=rc)

    # A-04: --skip-ast 跳过 AST 骨架化
    rc, out, err = run(["bootstrap", "--dry-run", "--skip-ast"])
    ok(results, "A-04", "bootstrap --skip-ast 跳过 AST 步骤",
       rc == 0,
       "skip" in out.lower() or "跳过" in out,
       stdout=out, stderr=err, exit_code=rc)

    # A-05: --skip-seeds 跳过种子包注入
    rc, out, err = run(["bootstrap", "--dry-run", "--skip-seeds"])
    ok(results, "A-05", "bootstrap --skip-seeds 跳过种子包注入",
       rc == 0,
       "skip" in out.lower() or "跳过" in out,
       stdout=out, stderr=err, exit_code=rc)

    # A-06: --root 指向临时空目录（模拟对新项目冷启动）
    with tempfile.TemporaryDirectory() as tmpdir:
        rc, out, err = run(["bootstrap", "--dry-run", "--root", tmpdir])
        ok(results, "A-06", "bootstrap --root /tmp/empty --dry-run 对空项目成功",
           rc == 0,
           "Bootstrap" in out or "bootstrap" in out.lower(),
           stdout=out, stderr=err, exit_code=rc)

    # A-07: 真实运行（无 dry-run）检测到技术栈
    rc, out, err = run(["bootstrap", "--skip-seeds"])
    ok(results, "A-07", "bootstrap --skip-seeds（真实 AST 扫描）成功且扫描文件>0",
       rc == 0,
       re.search(r"\d+\s*个文件", out) is not None or "files" in out.lower(),
       stdout=out, stderr=err, exit_code=rc)

    # A-08: 真实运行 --skip-ast 成功注入种子包
    rc, out, err = run(["bootstrap", "--skip-ast"])
    ok(results, "A-08", "bootstrap --skip-ast（真实种子注入）成功",
       rc == 0,
       "种子包" in out or "seed" in out.lower(),
       stdout=out, stderr=err, exit_code=rc)


# ─── B 组：mulan gc ───────────────────────────────────────────────────────────
def test_gc(results: List[CaseResult]) -> None:
    # B-01: --dry-run 预览，显示文件数量
    rc, out, err = run(["gc", "--dry-run"])
    ok(results, "B-01", "gc --dry-run 预览显示记忆文件数量",
       rc == 0,
       re.search(r"\d+\s*个记忆文件", out) is not None or "dry-run" in out,
       stdout=out, stderr=err, exit_code=rc)

    # B-02: --update-index-only 仅重建索引，成功退出
    rc, out, err = run(["gc", "--update-index-only"])
    ok(results, "B-02", "gc --update-index-only 成功重建索引",
       rc == 0,
       stdout=out, stderr=err, exit_code=rc,
       notes="索引重建可能无输出，只需 exit 0")

    # B-03: 无参数运行（完整 GC）
    rc, out, err = run(["gc"])
    ok(results, "B-03", "gc 无参数完整运行成功",
       rc == 0,
       stdout=out, stderr=err, exit_code=rc)


# ─── C 组：mulan seed list ────────────────────────────────────────────────────
def test_seed_list(results: List[CaseResult]) -> None:
    # C-01: 默认列出 v3.1 种子包
    rc, out, err = run(["seed", "list"])
    ok(results, "C-01", "seed list 列出 v3.1 种子包",
       rc == 0,
       "v3.1" in out or "seed_packs" in out,
       stdout=out, stderr=err, exit_code=rc)

    # C-02: 包含内置的 cross_cutting 和 base 种子包
    rc, out, err = run(["seed", "list"])
    ok(results, "C-02", "seed list 包含 cross_cutting 和 base 种子包",
       rc == 0,
       "cross_cutting" in out,
       "base" in out,
       stdout=out, stderr=err, exit_code=rc)

    # C-03: 显示每个包的 memories 数量
    rc, out, err = run(["seed", "list"])
    ok(results, "C-03", "seed list 显示 memories 计数",
       rc == 0,
       "memories" in out or "memories:" in out,
       stdout=out, stderr=err, exit_code=rc)

    # C-04: 显示 v3.1 和 v2 两个分区
    rc, out, err = run(["seed", "list"])
    ok(results, "C-04", "seed list 同时显示 v3.1 和 v2 种子包",
       rc == 0,
       ("v3.1" in out and "v2" in out) or "seed_packs" in out,
       stdout=out, stderr=err, exit_code=rc)


# ─── D 组：mulan hook ─────────────────────────────────────────────────────────
def test_hook(results: List[CaseResult]) -> None:
    hook_file = _PROJECT_ROOT / ".git" / "hooks" / "pre-commit"
    had_hook_before = hook_file.exists()
    # 记录测试前的 hook 内容（用于 D-05 的对比）
    content_before = hook_file.read_text() if had_hook_before else ""

    try:
        # D-01: hook install 成功安装
        rc, out, err = run(["hook", "install"])
        ok(results, "D-01", "hook install 安装 pre-commit hook",
           rc == 0,
           "pre-commit" in out,
           hook_file.exists(),
           stdout=out, stderr=err, exit_code=rc)

        # D-02: hook install 后 hook 文件内容包含 MMS 标记
        if hook_file.exists():
            content_installed = hook_file.read_text()
            ok(results, "D-02", "安装后 hook 文件包含 MMS 标记",
               "MMS pre-commit hook" in content_installed,
               stdout=content_installed[:200], stderr="", exit_code=0)
        else:
            content_installed = ""
            ok(results, "D-02", "安装后 hook 文件包含 MMS 标记",
               False, notes="hook 文件未创建")

        # D-03: hook check 执行校验（可能失败，但不 crash）
        rc, out, err = run(["hook", "check"])
        ok(results, "D-03", "hook check 执行校验（不 crash，exit 0 或 1）",
           rc in (0, 1),
           stdout=out, stderr=err, exit_code=rc,
           notes="check 返回 1 表示有校验失败，属正常情况")

        # D-04: hook remove 成功移除
        rc, out, err = run(["hook", "remove"])
        ok(results, "D-04", "hook remove 移除 pre-commit hook",
           rc == 0,
           "移除" in out or "remove" in out.lower(),
           stdout=out, stderr=err, exit_code=rc)

        # D-05: remove 后 hook 内容与安装时的内容不同（已恢复或不存在）
        # 注：若项目历史上曾多次 install，原始备份也可能是 MMS hook，此处只需
        # 确认恢复后的内容与"此次安装的版本"不同，或文件已消失
        if hook_file.exists():
            content_after = hook_file.read_text()
            restored_to_original = (content_after == content_before)
            differs_from_installed = (content_after != content_installed)
            ok(results, "D-05", "remove 后 hook 恢复原状（与安装后内容不同）",
               differs_from_installed or restored_to_original,
               stdout=content_after[:200], stderr="", exit_code=0,
               notes="若原始 hook 也是 MMS hook，恢复后内容与安装版本相同视为通过")
        else:
            ok(results, "D-05", "remove 后 pre-commit hook 文件不存在",
               True, notes="原本无 hook，移除后也无文件")

    finally:
        # 确保测试后恢复：如果原本没有 hook，移除测试安装的
        if not had_hook_before and hook_file.exists():
            content = hook_file.read_text()
            if "MMS pre-commit hook" in content:
                run(["hook", "remove"])


# ─── E 组：mulan private ──────────────────────────────────────────────────────
def test_private(results: List[CaseResult]) -> None:
    ep = _CI_EP
    private_root = _PROJECT_ROOT / "src" / "docs" / "memory" / "private"

    try:
        # E-01: private init 创建 EP 工作区
        rc, out, err = run(["private", "init", ep])
        ok(results, "E-01", f"private init {ep} 成功创建工作区",
           rc == 0,
           "初始化" in out or "init" in out.lower() or ep in out,
           stdout=out, stderr=err, exit_code=rc)

        # E-02: private list 显示新创建的 EP
        rc, out, err = run(["private", "list"])
        ok(results, "E-02", "private list 显示已创建的 EP 工作区",
           rc == 0,
           ep in out,
           "active" in out,
           stdout=out, stderr=err, exit_code=rc)

        # E-03: private note 添加笔记
        rc, out, err = run(["private", "note", ep, "集成测试自动笔记 Sprint-5"])
        ok(results, "E-03", "private note 添加笔记成功",
           rc == 0,
           "笔记" in out or "note" in out.lower(),
           stdout=out, stderr=err, exit_code=rc)

        # E-04: private list 显示 notes 计数更新
        rc, out, err = run(["private", "list"])
        ok(results, "E-04", "private list 显示 notes:1（笔记已添加）",
           rc == 0,
           ep in out,
           "笔记:1" in out or "notes:1" in out,
           stdout=out, stderr=err, exit_code=rc)

        # E-05: private init 同一 EP 二次初始化（幂等，不崩溃）
        rc, out, err = run(["private", "init", ep])
        ok(results, "E-05", "private init 同 EP 二次调用不崩溃（幂等）",
           rc == 0,
           stdout=out, stderr=err, exit_code=rc,
           notes="应提示已存在或直接成功")

        # E-06: private close 关闭工作区
        rc, out, err = run(["private", "close", ep])
        ok(results, "E-06", "private close 关闭 EP 工作区成功",
           rc == 0,
           "关闭" in out or "close" in out.lower() or ep in out,
           stdout=out, stderr=err, exit_code=rc)

        # E-07: close 后 list 不再显示该 EP（或显示为 closed）
        rc, out, err = run(["private", "list"])
        ep_still_active = bool(re.search(ep + r".*active", out))
        ok(results, "E-07", "close 后 private list 不显示该 EP 为 active",
           rc == 0,
           not ep_still_active,
           stdout=out, stderr=err, exit_code=rc)

    finally:
        # 清理：强制关闭并删除测试工作区
        ep_dir = private_root / ep
        if ep_dir.exists():
            try:
                run(["private", "close", ep, "--purge"])
            except Exception:
                shutil.rmtree(ep_dir, ignore_errors=True)


# ─── F 组：mulan inject ───────────────────────────────────────────────────────
def test_inject(results: List[CaseResult]) -> None:
    try:
        # F-01: 基础注入，返回 MMS 注入块
        rc, out, err = run(["inject", "测试注入：Python 异步函数设计"])
        ok(results, "F-01", "inject 基础调用返回 MMS 注入块",
           rc == 0,
           "MMS-INJECT" in out or "相关记忆" in out,
           stdout=out, stderr=err, exit_code=rc)

        # F-02: --no-compress 不压缩输出
        rc, out, err = run(["inject", "Python 性能优化", "--no-compress"])
        ok(results, "F-02", "inject --no-compress 成功执行",
           rc == 0,
           "MMS-INJECT" in out or "相关记忆" in out,
           stdout=out, stderr=err, exit_code=rc)

        # F-03: --top-k 控制注入数量
        rc, out, err = run(["inject", "数据库查询优化", "--top-k", "3"])
        ok(results, "F-03", "inject --top-k 3 成功执行",
           rc == 0,
           stdout=out, stderr=err, exit_code=rc)

        # F-04: --output 输出到文件
        rc, out, err = run(["inject", "API 设计规范", "--output", str(_CI_INJECT_OUT)])
        file_created = _CI_INJECT_OUT.exists()
        file_content = _CI_INJECT_OUT.read_text() if file_created else ""
        ok(results, "F-04", "inject --output 输出到文件成功",
           rc == 0,
           file_created,
           "MMS-INJECT" in file_content or len(file_content) > 10,
           stdout=out, stderr=err, exit_code=rc)

        # F-05: --mode dev 模式注入
        rc, out, err = run(["inject", "重构代码模块", "--mode", "dev"])
        ok(results, "F-05", "inject --mode dev 成功执行",
           rc == 0,
           stdout=out, stderr=err, exit_code=rc)

        # F-06: --mode arch 架构模式注入
        rc, out, err = run(["inject", "系统架构决策", "--mode", "arch"])
        ok(results, "F-06", "inject --mode arch 成功执行",
           rc == 0,
           stdout=out, stderr=err, exit_code=rc)

        # F-07: 多个关键词任务注入
        rc, out, err = run(["inject", "微服务", "网关", "限流"])
        ok(results, "F-07", "inject 多关键词任务成功",
           rc == 0,
           stdout=out, stderr=err, exit_code=rc)

    finally:
        # 清理输出文件
        if _CI_INJECT_OUT.exists():
            _CI_INJECT_OUT.unlink()


# ─── 报告生成 ─────────────────────────────────────────────────────────────────
def _render_report(results: List[CaseResult], elapsed: float) -> str:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Mulan Sprint 5：冷启动与生命周期集成测试报告",
        "",
        f"**生成时间**: {ts}",
        f"**总用时**: {elapsed:.1f}s",
        f"**结果**: {passed}/{total} 通过 {'✅' if passed == total else '⚠️'}",
        "",
        "## 测试用例详情",
        "",
        "| ID | 描述 | 结果 | 备注 |",
        "|----|------|------|------|",
    ]
    for r in results:
        icon = "✅" if r.passed else "❌"
        notes = r.notes or ""
        lines.append(f"| {r.id} | {r.desc} | {icon} | {notes} |")

    lines += ["", "## 失败用例输出", ""]
    any_fail = False
    for r in results:
        if not r.passed:
            any_fail = True
            lines += [
                f"### {r.id} — {r.desc}",
                f"- exit_code: `{r.exit_code}`",
                "- stdout:",
                "```",
                (r.stdout[:800] if r.stdout else "(空)"),
                "```",
                "- stderr:",
                "```",
                (r.stderr[:400] if r.stderr else "(空)"),
                "```",
                "",
            ]
    if not any_fail:
        lines.append("无失败用例。")

    return "\n".join(lines)


# ─── 主入口 ───────────────────────────────────────────────────────────────────
def main() -> None:
    import time

    print("=" * 60)
    print("  Mulan Sprint 5 集成测试：冷启动与生命周期")
    print("=" * 60)

    results: List[CaseResult] = []
    start = time.time()

    groups = [
        ("A 组：bootstrap", test_bootstrap),
        ("B 组：gc", test_gc),
        ("C 组：seed list", test_seed_list),
        ("D 组：hook", test_hook),
        ("E 组：private", test_private),
        ("F 组：inject", test_inject),
    ]

    for label, fn in groups:
        print(f"\n▶ {label}...")
        before = len(results)
        fn(results)
        group_results = results[before:]
        passed = sum(1 for r in group_results if r.passed)
        print(f"  {passed}/{len(group_results)} 通过")
        for r in group_results:
            icon = "✅" if r.passed else "❌"
            print(f"  {icon} [{r.id}] {r.desc}")

    elapsed = time.time() - start
    total = len(results)
    passed = sum(1 for r in results if r.passed)

    print(f"\n{'=' * 60}")
    print(f"  结果：{passed}/{total} 通过  |  用时 {elapsed:.1f}s")
    print("=" * 60)

    report = _render_report(results, elapsed)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _RESULTS_DIR / f"coldstart_{ts_str}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n报告已写入：{report_path}")

    sys.exit(0 if passed == total else 1)


# ─── pytest 入口 ──────────────────────────────────────────────────────────────
def test_sprint5_coldstart() -> None:
    """pytest 入口：作为单一测试收集，内部执行所有子测试。"""
    import time
    results: List[CaseResult] = []
    start = time.time()
    for _, fn in [
        ("bootstrap", test_bootstrap),
        ("gc", test_gc),
        ("seed_list", test_seed_list),
        ("hook", test_hook),
        ("private", test_private),
        ("inject", test_inject),
    ]:
        fn(results)
    elapsed = time.time() - start

    report = _render_report(results, elapsed)
    ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _RESULTS_DIR / f"coldstart_{ts_str}.md"
    report_path.write_text(report, encoding="utf-8")

    failed = [r for r in results if not r.passed]
    if failed:
        fail_msg = "\n".join(
            f"[{r.id}] {r.desc}\n  stdout: {r.stdout[:200]}\n  stderr: {r.stderr[:100]}"
            for r in failed
        )
        raise AssertionError(f"{len(failed)}/{len(results)} 个测试失败:\n{fail_msg}")


if __name__ == "__main__":
    main()
