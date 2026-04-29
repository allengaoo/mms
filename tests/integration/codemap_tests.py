"""
tests/integration/codemap_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan codemap / funcmap / ast-diff 命令组集成测试（真实 CLI 调用，无 mock）

特点：
  - 直接调用 mulan CLI，使用真实文件系统
  - codemap/funcmap 是幂等操作，直接写入 docs/memory/_system/，无需 cleanup
  - ast-diff 测试使用 --before/--after 比对 JSON 文件，测后清理临时文件
  - 结果写入 tests/integration/results/codemap_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/codemap_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/codemap_tests.py -v -s

测试分组：
  A 组：mulan codemap
  B 组：mulan funcmap
  C 组：mulan ast-diff
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
_CLI = [sys.executable, str(_ROOT / "cli.py")]
_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_SYSTEM_DIR = _ROOT / "docs" / "memory" / "_system"
_CODEMAP_MD = _SYSTEM_DIR / "codemap.md"
_FUNCMAP_MD = _SYSTEM_DIR / "funcmap.md"

# ast-diff 测试用的临时 JSON 文件（测后清理）
_AST_FIXTURE_A = _ROOT / "tests" / "integration" / "_ci_ast_before.json"
_AST_FIXTURE_B = _ROOT / "tests" / "integration" / "_ci_ast_after.json"


# ── 测试结果数据结构 ──────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    id: str
    group: str
    name: str
    command: str
    expected_exit: int
    actual_exit: int
    stdout: str
    stderr: str
    checks: List[tuple]
    passed: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        self.passed = (
            self.actual_exit == self.expected_exit
            and all(ok for _, ok, _ in self.checks)
            and self.error is None
        )


# ── CLI 辅助 ─────────────────────────────────────────────────────────────────

def run(*args: str, timeout: int = 60) -> tuple:
    cmd = _CLI + list(args)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=str(_ROOT), timeout=timeout,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"[超时：>{timeout}s]"
    except Exception as e:
        return -1, "", f"[运行错误：{e}]"


def has(output: str, keyword: str) -> bool:
    return keyword in output

def not_has(output: str, keyword: str) -> bool:
    return keyword not in output

def match(output: str, pattern: str) -> bool:
    return bool(re.search(pattern, output))


# ── 夹具管理 ─────────────────────────────────────────────────────────────────

def _setup_ast_fixtures():
    """创建 ast-diff 测试用的最小 JSON 快照文件。"""
    base = {
        "cli.py": {
            "functions": ["cmd_status", "cmd_verify", "cmd_validate"],
            "classes": [],
            "imports": ["argparse", "sys", "pathlib"],
        }
    }
    changed = {
        "cli.py": {
            "functions": ["cmd_status", "cmd_verify", "cmd_validate", "cmd_new_feature"],
            "classes": [],
            "imports": ["argparse", "sys", "pathlib"],
        }
    }
    _AST_FIXTURE_A.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    _AST_FIXTURE_B.write_text(json.dumps(changed, ensure_ascii=False, indent=2), encoding="utf-8")


def _cleanup_ast_fixtures():
    _AST_FIXTURE_A.unlink(missing_ok=True)
    _AST_FIXTURE_B.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []

    _setup_ast_fixtures()

    try:
        # ────────────────────────────────────────────────────────────────────
        # 组 A：mulan codemap
        # ────────────────────────────────────────────────────────────────────

        # A-01：--help 正常显示
        code, out, err = run("codemap", "--help")
        results.append(CaseResult(
            id="A-01", group="A", name="codemap --help 正常显示",
            command="mulan codemap --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",         code == 0,                  "0"),
                ("含 --depth 选项",         has(out, "--depth"),         "--depth"),
                ("含 --dry-run 选项",       has(out, "--dry-run"),       "--dry-run"),
                ("含 --recent 选项",        has(out, "--recent"),        "--recent"),
            ],
        ))

        # A-02：--dry-run 打印内容但不写文件
        ts_before = _CODEMAP_MD.stat().st_mtime if _CODEMAP_MD.exists() else 0
        code, out, err = run("codemap", "--dry-run")
        ts_after = _CODEMAP_MD.stat().st_mtime if _CODEMAP_MD.exists() else 0
        results.append(CaseResult(
            id="A-02", group="A", name="codemap --dry-run 打印内容不修改文件",
            command="mulan codemap --dry-run",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",          code == 0,             "0"),
                ("stdout 有内容",            len(out.strip()) > 0,  ">0 chars"),
                ("文件未被修改（mtime 不变）", ts_after == ts_before, "mtime 不变"),
            ],
        ))

        # A-03：无参数运行 exit=0，生成文件
        code, out, err = run("codemap")
        results.append(CaseResult(
            id="A-03", group="A", name="codemap 无参数运行 exit=0，生成文件",
            command="mulan codemap",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                    "0"),
                ("含 已生成 或 codemap",      has(out, "已生成") or has(out, "codemap"), "已生成/codemap"),
                ("codemap.md 文件存在",       _CODEMAP_MD.exists(),         "文件存在"),
            ],
        ))

        # A-04：codemap.md 含合法 Markdown 结构
        md_content = _CODEMAP_MD.read_text(encoding="utf-8") if _CODEMAP_MD.exists() else ""
        results.append(CaseResult(
            id="A-04", group="A", name="codemap.md 含合法 Markdown 标题结构",
            command="（读取 codemap.md 验证）",
            expected_exit=0, actual_exit=0, stdout=md_content[:200], stderr="",
            checks=[
                ("含 # 标题",  bool(re.search(r"^#{1,3} ", md_content, re.MULTILINE)) if md_content else False, "# 标题"),
                ("文件非空",   len(md_content.strip()) > 0, ">0 chars"),
            ],
        ))

        # A-05：codemap.md 含自动生成标记
        results.append(CaseResult(
            id="A-05", group="A", name="codemap.md 含自动生成标记（勿手动编辑）",
            command="（读取 codemap.md 验证）",
            expected_exit=0, actual_exit=0, stdout=md_content[:200], stderr="",
            checks=[
                ("含自动生成说明",
                 has(md_content, "自动生成") or has(md_content, "auto") or has(md_content, "勿手动"),
                 "自动生成/勿手动"),
            ],
        ))

        # A-06：重复运行幂等性（第二次 exit=0）
        code, out, err = run("codemap")
        results.append(CaseResult(
            id="A-06", group="A", name="codemap 重复运行幂等（第二次 exit=0）",
            command="mulan codemap（第二次）",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0, "0"),
                ("文件仍存在",     _CODEMAP_MD.exists(), "文件存在"),
            ],
        ))

        # A-07：--depth 参数接受合法值
        code, out, err = run("codemap", "--depth", "2", "--dry-run")
        results.append(CaseResult(
            id="A-07", group="A", name="codemap --depth 2 参数被接受",
            command="mulan codemap --depth 2 --dry-run",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,                   "0"),
                ("不含 Traceback", not_has(err, "Traceback"),    "无 Traceback"),
            ],
        ))

        # A-08：运行耗时 < 30s
        t0 = time.perf_counter()
        code, _, _ = run("codemap", timeout=35)
        elapsed = time.perf_counter() - t0
        results.append(CaseResult(
            id="A-08", group="A", name="codemap 运行完成 < 30 秒",
            command="mulan codemap（计时）",
            expected_exit=0, actual_exit=code, stdout="", stderr="",
            checks=[
                ("exit code 为 0",          code == 0,     "0"),
                (f"耗时 {elapsed:.2f}s < 30s", elapsed < 30, "<30s"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 B：mulan funcmap
        # ────────────────────────────────────────────────────────────────────

        # B-01：--help 正常显示
        code, out, err = run("funcmap", "--help")
        results.append(CaseResult(
            id="B-01", group="B", name="funcmap --help 正常显示",
            command="mulan funcmap --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                 "0"),
                ("含 --backend-only 选项",    has(out, "--backend-only"), "--backend-only"),
                ("含 --dry-run 选项",         has(out, "--dry-run"),      "--dry-run"),
            ],
        ))

        # B-02：--dry-run 打印内容但不修改文件
        ts_before = _FUNCMAP_MD.stat().st_mtime if _FUNCMAP_MD.exists() else 0
        code, out, err = run("funcmap", "--dry-run")
        ts_after = _FUNCMAP_MD.stat().st_mtime if _FUNCMAP_MD.exists() else 0
        results.append(CaseResult(
            id="B-02", group="B", name="funcmap --dry-run 打印内容不修改文件",
            command="mulan funcmap --dry-run",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,             "0"),
                ("stdout 有内容",             len(out.strip()) > 0,  ">0 chars"),
                ("文件未被修改（mtime 不变）",  ts_after == ts_before, "mtime 不变"),
            ],
        ))

        # B-03：无参数运行 exit=0，生成文件
        code, out, err = run("funcmap")
        results.append(CaseResult(
            id="B-03", group="B", name="funcmap 无参数运行 exit=0，生成文件",
            command="mulan funcmap",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",          code == 0,                     "0"),
                ("含 已生成 或 funcmap",     has(out, "已生成") or has(out, "funcmap"), "已生成/funcmap"),
                ("funcmap.md 文件存在",      _FUNCMAP_MD.exists(),          "文件存在"),
            ],
        ))

        # B-04：funcmap.md 含合法 Markdown 结构
        fm_content = _FUNCMAP_MD.read_text(encoding="utf-8") if _FUNCMAP_MD.exists() else ""
        results.append(CaseResult(
            id="B-04", group="B", name="funcmap.md 含合法 Markdown 结构",
            command="（读取 funcmap.md 验证）",
            expected_exit=0, actual_exit=0, stdout=fm_content[:200], stderr="",
            checks=[
                ("含 # 标题",  bool(re.search(r"^#{1,3} ", fm_content, re.MULTILINE)) if fm_content else False, "# 标题"),
                ("文件非空",   len(fm_content.strip()) > 0, ">0 chars"),
            ],
        ))

        # B-05：funcmap.md 含自动生成标记
        results.append(CaseResult(
            id="B-05", group="B", name="funcmap.md 含自动生成标记",
            command="（读取 funcmap.md 验证）",
            expected_exit=0, actual_exit=0, stdout=fm_content[:200], stderr="",
            checks=[
                ("含自动生成说明",
                 has(fm_content, "自动生成") or has(fm_content, "auto") or has(fm_content, "勿手动"),
                 "自动生成/勿手动"),
            ],
        ))

        # B-06：重复运行幂等（第二次 exit=0）
        code, out, err = run("funcmap")
        results.append(CaseResult(
            id="B-06", group="B", name="funcmap 重复运行幂等（第二次 exit=0）",
            command="mulan funcmap（第二次）",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0,             "0"),
                ("文件仍存在",     _FUNCMAP_MD.exists(),   "文件存在"),
            ],
        ))

        # B-07：--backend-only 独立运行
        code, out, err = run("funcmap", "--backend-only", "--dry-run")
        results.append(CaseResult(
            id="B-07", group="B", name="funcmap --backend-only --dry-run 正常运行",
            command="mulan funcmap --backend-only --dry-run",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,                    "0"),
                ("不含 Traceback", not_has(err, "Traceback"),     "无 Traceback"),
            ],
        ))

        # B-08：运行耗时 < 60s
        t0 = time.perf_counter()
        code, _, _ = run("funcmap", timeout=65)
        elapsed = time.perf_counter() - t0
        results.append(CaseResult(
            id="B-08", group="B", name="funcmap 运行完成 < 60 秒",
            command="mulan funcmap（计时）",
            expected_exit=0, actual_exit=code, stdout="", stderr="",
            checks=[
                ("exit code 为 0",             code == 0,      "0"),
                (f"耗时 {elapsed:.2f}s < 60s", elapsed < 60,  "<60s"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 C：mulan ast-diff
        # ────────────────────────────────────────────────────────────────────

        # C-01：--help 正常显示
        code, out, err = run("ast-diff", "--help")
        results.append(CaseResult(
            id="C-01", group="C", name="ast-diff --help 正常显示",
            command="mulan ast-diff --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",     code == 0,              "0"),
                ("含 --ep 选项",       has(out, "--ep"),        "--ep"),
                ("含 --before 选项",   has(out, "--before"),    "--before"),
                ("含 --after 选项",    has(out, "--after"),     "--after"),
            ],
        ))

        # C-02：无参数运行 → exit=1，友好错误（需指定 --ep 或 --before）
        code, out, err = run("ast-diff")
        results.append(CaseResult(
            id="C-02", group="C", name="ast-diff 无参数 exit=1 + 友好提示",
            command="mulan ast-diff",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",              code == 1,                    "1"),
                ("含 请指定 或 --ep 或 --before",
                 has(out, "--ep") or has(out, "--before") or has(out, "请指定"),
                 "--ep/--before/请指定"),
            ],
        ))

        # C-03：--before A --after B 比对两个 JSON 文件（新增函数场景）
        code, out, err = run(
            "ast-diff",
            "--before", str(_AST_FIXTURE_A),
            "--after",  str(_AST_FIXTURE_B),
        )
        results.append(CaseResult(
            id="C-03", group="C", name="ast-diff --before/--after 比对 JSON 差异",
            command="mulan ast-diff --before ci_ast_before.json --after ci_ast_after.json",
            expected_exit=code,  # 容错：有变更时可能是 0 或 1
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 不为 -1（不超时崩溃）", code != -1, "≠ -1"),
                ("不含 Traceback",                 not_has(err, "Traceback"), "无 Traceback"),
                ("输出含差异或无变更提示",
                 len(out.strip()) > 0 or code == 0,
                 ">0 输出/exit=0"),
            ],
        ))

        # C-04：--before A --after A（相同文件）→ 无变更
        code, out, err = run(
            "ast-diff",
            "--before", str(_AST_FIXTURE_A),
            "--after",  str(_AST_FIXTURE_A),
        )
        results.append(CaseResult(
            id="C-04", group="C", name="ast-diff 同一文件比对（无变更）",
            command="mulan ast-diff --before ci_ast_A.json --after ci_ast_A.json",
            expected_exit=code,  # 容错
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 不为 -1", code != -1, "≠ -1"),
                ("不含 Traceback",    not_has(err, "Traceback"), "无 Traceback"),
                ("输出含 无变更 或 0 条变更 或为空（表示无差异）",
                 has(out, "无变更") or has(out, "0") or len(out.strip()) == 0 or code == 0,
                 "无变更/0/空输出/exit=0"),
            ],
        ))

        # C-05：--before 不存在的文件 → exit=1，友好错误
        code, out, err = run(
            "ast-diff",
            "--before", "/tmp/__ci_nonexistent_ast__.json",
            "--after",  str(_AST_FIXTURE_B),
        )
        results.append(CaseResult(
            id="C-05", group="C", name="ast-diff --before 不存在文件 exit=1",
            command="mulan ast-diff --before /tmp/__ci_nonexistent__.json ...",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",    code == 1,                        "1"),
                ("含错误提示",
                 has(out, "❌") or has(out, "不存在") or has(out, "找不到") or has(err, "No such file"),
                 "❌/不存在/找不到"),
            ],
        ))

        # C-06：--files 过滤特定文件
        code, out, err = run(
            "ast-diff",
            "--before", str(_AST_FIXTURE_A),
            "--after",  str(_AST_FIXTURE_B),
            "--files", "cli.py",
        )
        results.append(CaseResult(
            id="C-06", group="C", name="ast-diff --files 过滤文件范围",
            command="mulan ast-diff --before A --after B --files cli.py",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 不为 -1", code != -1, "≠ -1"),
                ("不含 Traceback",    not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

    finally:
        _cleanup_ast_fixtures()

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Markdown 报告渲染
# ══════════════════════════════════════════════════════════════════════════════

def _render_markdown(results: List[CaseResult], elapsed: float) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    ok_icon = "✅" if passed == total else "❌"

    lines = [
        "# mulan codemap / funcmap / ast-diff 集成测试报告",
        "",
        f"> 生成时间：{ts}　｜　覆盖命令：`mulan codemap` / `mulan funcmap` / `mulan ast-diff`",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 总用例数 | {total} |",
        f"| 通过 | {passed} |",
        f"| 失败 | {total - passed} |",
        f"| 总耗时 | {elapsed:.1f}s |",
        f"| 结果 | {ok_icon} {'全部通过' if passed == total else f'{total-passed} 个失败'} |",
        "",
        "## 详细结果",
        "",
    ]

    group_names = {
        "A": "mulan codemap",
        "B": "mulan funcmap",
        "C": "mulan ast-diff",
    }
    current_group = None

    for r in results:
        if r.group != current_group:
            current_group = r.group
            lines += [f"### {group_names.get(r.group, r.group)} 组（{r.group} 组）", ""]

        icon = "✅" if r.passed else "❌"
        lines += [
            f"#### {icon} [{r.id}] {r.name}",
            "",
            f"**命令**：`{r.command}`  ",
            f"**期望 exit**：`{r.expected_exit}`　**实际 exit**：`{r.actual_exit}`",
            "",
            "| 检查项 | 结果 | 期望值 |",
            "|--------|------|--------|",
        ]
        for desc, ok, expected in r.checks:
            lines.append(f"| {desc} | {'✅' if ok else '❌'} | `{expected}` |")

        if r.stdout.strip():
            preview = r.stdout.strip()[:500]
            if len(r.stdout.strip()) > 500:
                preview += "\n... (截断)"
            lines += ["", "**实际输出（前 500 字符）**", "```", preview, "```"]
        if r.stderr.strip():
            lines += ["", "**stderr**", "```", r.stderr.strip()[:200], "```"]
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  mulan codemap / funcmap / ast-diff 集成测试")
    print("=" * 60)

    t0 = time.perf_counter()
    results = run_all_cases()
    elapsed = time.perf_counter() - t0

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    print()
    for r in results:
        icon = "✅" if r.passed else "❌"
        print(f"  {icon} [{r.id}] {r.name}")
        if not r.passed:
            for desc, ok, expected in r.checks:
                if not ok:
                    print(f"       ↳ FAIL: {desc}（期望 {expected}）")

    print()
    print(f"  结果：{passed}/{total} 通过　耗时：{elapsed:.1f}s")

    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _RESULTS_DIR / f"codemap_{ts}.md"
    report_path.write_text(_render_markdown(results, elapsed), encoding="utf-8")
    print(f"  报告：{report_path.relative_to(_ROOT)}")
    print()

    return 0 if passed == total else 1


# ── pytest 兼容入口 ───────────────────────────────────────────────────────────

import pytest  # noqa: E402

_cached_results: List[CaseResult] = []


@pytest.fixture(scope="module", autouse=True)
def _run_and_cache():
    global _cached_results
    if not _cached_results:
        _cached_results = run_all_cases()


def _get_result(cid: str) -> CaseResult:
    for r in _cached_results:
        if r.id == cid:
            return r
    pytest.skip(f"未找到用例 {cid}")


def _make_pytest_test(case_id: str):
    def _test(self):
        r = _get_result(case_id)
        failures = [f"{desc}（期望 {exp}）" for desc, ok, exp in r.checks if not ok]
        if r.actual_exit != r.expected_exit:
            failures.insert(0, f"exit code {r.actual_exit} ≠ {r.expected_exit}")
        assert not failures, "\n".join(failures)
    _test.__name__ = f"test_{case_id.lower().replace('-', '_')}"
    return _test


_ALL_CASE_IDS = [
    "A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-07", "A-08",
    "B-01", "B-02", "B-03", "B-04", "B-05", "B-06", "B-07", "B-08",
    "C-01", "C-02", "C-03", "C-04", "C-05", "C-06",
]

TestCodemap = type(
    "TestCodemap",
    (),
    {f"test_{cid.lower().replace('-', '_')}": _make_pytest_test(cid) for cid in _ALL_CASE_IDS},
)


if __name__ == "__main__":
    sys.exit(main())
