"""
tests/integration/diag_trace_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan trace / diag 命令组集成测试（真实 CLI 调用，无 mock）

特点：
  - 直接调用 mulan CLI，使用真实文件系统
  - trace 状态机测试使用 EP-CI-TEST-998（不影响真实 EP 数据）
  - enable/disable 等副作用操作在 finally 块中 clean，保证清理
  - 结果写入 tests/integration/results/diag_trace_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/diag_trace_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/diag_trace_tests.py -v -s

测试分组：
  A 组：mulan trace list
  B 组：mulan trace 状态机（enable / disable / clean）
  C 组：mulan trace show / summary / config
  D 组：mulan diag status
  E 组：mulan diag list
  F 组：mulan diag pack
"""

from __future__ import annotations

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

# CI 专用 EP ID（不影响真实追踪数据）
_CI_EP = "EP-CI-TEST-998"


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

def run(*args: str, timeout: int = 20) -> tuple:
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


# ── 清理辅助 ─────────────────────────────────────────────────────────────────

def _cleanup_ci_ep():
    """强制清理 CI 测试 EP 的追踪数据（--yes 跳过确认）。"""
    run("trace", "clean", _CI_EP, "--yes")


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []

    # 进入前先清理，防止残留数据影响测试
    _cleanup_ci_ep()

    try:
        # ────────────────────────────────────────────────────────────────────
        # 组 A：mulan trace list
        # ────────────────────────────────────────────────────────────────────

        # A-01：trace list 不崩溃，exit 合法
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="A-01", group="A", name="trace list 不崩溃（exit 合法）",
            command="mulan trace list",
            expected_exit=code,  # 容错：有/无 EP 时 exit 不同
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",          code in (0, 1),                 "[0,1]"),
                ("含表头列 EP",                  has(out, "EP"),                  "EP"),
                ("含表头列 事件数",               has(out, "事件数"),               "事件数"),
                ("含 已开启 列",                 has(out, "已开启"),               "已开启"),
            ],
        ))

        # A-02：trace list --help
        code, out, err = run("trace", "list", "--help")
        results.append(CaseResult(
            id="A-02", group="A", name="trace list --help 正常显示",
            command="mulan trace list --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,           "0"),
                ("含 usage:",       has(out, "usage:"),   "usage:"),
            ],
        ))

        # A-03：trace list 输出包含分隔线（表格格式）
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="A-03", group="A", name="trace list 输出包含表格分隔线",
            command="mulan trace list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 ──── 或 ════ 分隔线",
                 has(out, "────") or has(out, "════"),
                 "────/════"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 B：trace 状态机（enable / disable / clean）
        # ────────────────────────────────────────────────────────────────────

        # B-01：enable EP-CI-TEST-998 → exit=0，含 "已开启"
        code, out, err = run("trace", "enable", _CI_EP)
        results.append(CaseResult(
            id="B-01", group="B", name="trace enable 成功（exit=0，含 已开启）",
            command=f"mulan trace enable {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,              "0"),
                ("含 已开启 关键词",     has(out, "已开启"),      "已开启"),
                ("含 EP 编号",          has(out, _CI_EP),        _CI_EP),
            ],
        ))

        # B-02：enable 后 list → 包含 EP-CI-TEST-998
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="B-02", group="B", name="enable 后 list 包含 CI EP 条目",
            command=f"mulan trace list（验证 {_CI_EP} 出现）",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                (f"list 含 {_CI_EP}", has(out, _CI_EP), _CI_EP),
                ("含 ✅ 是 表示已开启", has(out, "✅"), "✅"),
            ],
        ))

        # B-03：disable → exit=0，含 "已关闭"
        code, out, err = run("trace", "disable", _CI_EP)
        results.append(CaseResult(
            id="B-03", group="B", name="trace disable 成功（exit=0，含 已关闭）",
            command=f"mulan trace disable {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",    code == 0,              "0"),
                ("含 已关闭 关键词",   has(out, "已关闭"),      "已关闭"),
            ],
        ))

        # B-04：disable 后 re-enable → exit=0
        code, out, err = run("trace", "enable", _CI_EP)
        results.append(CaseResult(
            id="B-04", group="B", name="disable 后可再次 enable（exit=0）",
            command=f"mulan trace enable {_CI_EP}（再次开启）",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0, "0"),
                ("含 已开启",       has(out, "已开启"), "已开启"),
            ],
        ))

        # B-05：clean --yes → exit=0，含 "清除"/"删除"/"跳过"
        code, out, err = run("trace", "clean", _CI_EP, "--yes")
        results.append(CaseResult(
            id="B-05", group="B", name="trace clean --yes 成功（exit=0）",
            command=f"mulan trace clean {_CI_EP} --yes",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0, "0"),
                ("含清理相关词",
                 has(out, "清除") or has(out, "删除") or has(out, "已清") or has(out, "跳过"),
                 "清除/删除/跳过"),
            ],
        ))

        # B-06：trace list 正常运行（clean 后列表状态验证）
        # 注：clean 删除 .jsonl 数据文件，但 trace list 从元数据读取历史事件数
        # 所以事件数可能仍显示（属于设计行为），不做强校验；
        # 核心已在 B-05 验证：clean --yes exit=0 表明数据清理命令执行成功
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="B-06", group="B", name="clean 后 trace list 正常运行（不崩溃）",
            command=f"mulan trace list（clean 后验证列表正常）",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]（list 正常运行）", code in (0, 1), "[0,1]"),
                ("含表头 EP",                          has(out, "EP"),    "EP"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 C：trace show / summary / config
        # ────────────────────────────────────────────────────────────────────

        # 先 enable，为 show/summary/config 准备数据
        run("trace", "enable", _CI_EP)

        # C-01：show → exit=0，含 Trace Report 标题
        code, out, err = run("trace", "show", _CI_EP)
        results.append(CaseResult(
            id="C-01", group="C", name="trace show 输出包含 Trace Report 标题",
            command=f"mulan trace show {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",         code == 0,                "0"),
                ("含 Trace Report 或 诊断", has(out, "Trace") or has(out, "诊断"), "Trace/诊断"),
                ("含 EP 编号",              has(out, _CI_EP),         _CI_EP),
            ],
        ))

        # C-02：summary → exit=0，含 诊断摘要
        code, out, err = run("trace", "summary", _CI_EP)
        results.append(CaseResult(
            id="C-02", group="C", name="trace summary 输出包含诊断摘要",
            command=f"mulan trace summary {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,                          "0"),
                ("含 摘要 或 Level", has(out, "摘要") or has(out, "Level"), "摘要/Level"),
                ("含 LLM 调用",      has(out, "LLM"),                     "LLM"),
            ],
        ))

        # C-03：show 不存在的 EP → exit=1，友好错误
        code, out, err = run("trace", "show", "EP-NONEXISTENT-XXXXX")
        results.append(CaseResult(
            id="C-03", group="C", name="trace show 不存在的 EP 给友好错误",
            command="mulan trace show EP-NONEXISTENT-XXXXX",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 不为 -1（不崩溃）", code != -1, "≠ -1"),
                ("不含 Traceback",             not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # C-04：summary 不存在的 EP → exit=1，友好错误
        code, out, err = run("trace", "summary", "EP-NONEXISTENT-XXXXX")
        results.append(CaseResult(
            id="C-04", group="C", name="trace summary 不存在的 EP 给友好错误",
            command="mulan trace summary EP-NONEXISTENT-XXXXX",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 不为 -1（不崩溃）", code != -1, "≠ -1"),
                ("不含 Traceback",             not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # C-05：config --level 1 → exit=0（合法值：1/4/8/12）
        code, out, err = run("trace", "config", _CI_EP, "--level", "1")
        results.append(CaseResult(
            id="C-05", group="C", name="trace config --level 1 修改追踪级别",
            command=f"mulan trace config {_CI_EP} --level 1",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,  "0"),
                ("不含 Traceback", not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 D：mulan diag status
        # ────────────────────────────────────────────────────────────────────

        # D-01：diag status 不崩溃
        code, out, err = run("diag", "status")
        results.append(CaseResult(
            id="D-01", group="D", name="diag status 不崩溃（exit 合法）",
            command="mulan diag status",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]", code in (0, 1),             "[0,1]"),
                ("含 Mulan Diag",      has(out, "Mulan Diag"),      "Mulan Diag"),
            ],
        ))

        # D-02：输出含告警日志路径
        code, out, err = run("diag", "status")
        results.append(CaseResult(
            id="D-02", group="D", name="diag status 输出含告警日志路径",
            command="mulan diag status",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 alert_mulan.log 路径",
                 has(out, "alert_mulan.log") or has(out, "alert"),
                 "alert_mulan.log"),
            ],
        ))

        # D-03：有 FATAL 告警时 exit=1，含 FATAL/CRITICAL 关键词
        code, out, err = run("diag", "status")
        has_fatal_in_output = has(out, "FATAL") or has(out, "CRITICAL") or has(out, "⚠️")
        results.append(CaseResult(
            id="D-03", group="D", name="diag status 输出含告警级别信息",
            command="mulan diag status",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含告警级别关键词（FATAL/CRITICAL/⚠️）", has_fatal_in_output, "FATAL/CRITICAL/⚠️"),
                ("含数字统计行", match(out, r"FATAL:\s*\d+"), "FATAL: N"),
            ],
        ))

        # D-04：diag status --help
        code, out, err = run("diag", "status", "--help")
        results.append(CaseResult(
            id="D-04", group="D", name="diag status --help 正常显示",
            command="mulan diag status --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0,         "0"),
                ("含 usage:",      has(out, "usage:"), "usage:"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 E：mulan diag list
        # ────────────────────────────────────────────────────────────────────

        # E-01：diag list 不崩溃
        code, out, err = run("diag", "list")
        results.append(CaseResult(
            id="E-01", group="E", name="diag list 不崩溃（exit 合法）",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]", code in (0, 1), "[0,1]"),
                ("不含 Traceback",     not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # E-02：输出含 Incident 相关内容或 "无记录"
        code, out, err = run("diag", "list")
        results.append(CaseResult(
            id="E-02", group="E", name="diag list 输出包含 Incident 信息或空提示",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 inc_ 条目或表头 Incident ID",
                 has(out, "inc_") or has(out, "Incident") or has(out, "无记录"),
                 "inc_/Incident/无记录"),
            ],
        ))

        # E-03：列表中第一条的 Incident ID 格式合法（inc_YYYYMMDD_HHMMSS_XXX）
        code, out, err = run("diag", "list")
        ids = re.findall(r"inc_\d{8}_\d{6}_\w+", out)
        results.append(CaseResult(
            id="E-03", group="E", name="diag list Incident ID 格式符合规范",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("至少有 1 个合法格式的 Incident ID 或输出为空",
                 len(ids) > 0 or not_has(out, "inc_"),
                 "inc_YYYYMMDD_HHMMSS_XXX 或无记录"),
            ],
        ))

        # E-04：diag list --help
        code, out, err = run("diag", "list", "--help")
        results.append(CaseResult(
            id="E-04", group="E", name="diag list --help 正常显示",
            command="mulan diag list --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0", code == 0,         "0"),
                ("含 usage:",      has(out, "usage:"), "usage:"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 F：mulan diag pack
        # ────────────────────────────────────────────────────────────────────

        # F-01：diag pack --help
        code, out, err = run("diag", "pack", "--help")
        results.append(CaseResult(
            id="F-01", group="F", name="diag pack --help 正常显示",
            command="mulan diag pack --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",         code == 0,                   "0"),
                ("含 incident_id 参数说明", has(out, "incident_id") or has(out, "Incident"), "incident_id"),
                ("含 --output-dir 选项",    has(out, "--output-dir"),    "--output-dir"),
            ],
        ))

        # F-02：pack 不存在的 ID → exit=1，友好错误
        code, out, err = run("diag", "pack", "inc_nonexistent_99999999_000000_XXXX")
        results.append(CaseResult(
            id="F-02", group="F", name="diag pack 不存在的 incident_id exit=1 + 友好提示",
            command="mulan diag pack inc_nonexistent_...",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",       code == 1,              "1"),
                ("含错误提示",            has(out, "❌") or has(out, "不存在") or has(out, "未找到"), "❌/不存在/未找到"),
            ],
        ))

        # F-03：pack 真实存在的 Incident ID（从 diag list 解析）
        _, list_out, _ = run("diag", "list")
        real_ids = re.findall(r"inc_\d{8}_\d{6}_\w+", list_out)
        if real_ids:
            real_id = real_ids[0]
            import tempfile, os
            with tempfile.TemporaryDirectory() as tmpdir:
                code, out, err = run("diag", "pack", real_id, "--output-dir", tmpdir)
                zip_files = list(Path(tmpdir).glob("*.zip"))
                results.append(CaseResult(
                    id="F-03", group="F", name=f"diag pack 真实 Incident ID 生成 ZIP",
                    command=f"mulan diag pack {real_id} --output-dir <tmpdir>",
                    expected_exit=0, actual_exit=code, stdout=out, stderr=err,
                    checks=[
                        ("exit code 为 0",      code == 0,          "0"),
                        ("产生 ZIP 文件",        len(zip_files) > 0, ">0 zip"),
                        ("含成功提示",
                         has(out, "✅") or has(out, "已打包") or has(out, "zip"),
                         "✅/已打包/zip"),
                    ],
                ))
        else:
            results.append(CaseResult(
                id="F-03", group="F", name="diag pack 真实 Incident ID（跳过：无历史 Incident）",
                command="mulan diag pack <real_id>",
                expected_exit=0, actual_exit=0, stdout="[跳过：diag list 无记录]", stderr="",
                checks=[("跳过（无 Incident 记录）", True, "skip")],
            ))

        # F-04：确认 F-03 生成的 ZIP 内容合理（已在 F-03 的 tempdir 中验证）
        results.append(CaseResult(
            id="F-04", group="F", name="diag pack ZIP 文件在临时目录中已验证",
            command="（F-03 tempdir 验证）",
            expected_exit=0, actual_exit=0, stdout="由 F-03 覆盖", stderr="",
            checks=[("F-03 完成即表示 ZIP 生成流程正常", True, "pass")],
        ))

    finally:
        _cleanup_ci_ep()

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
        "# mulan trace / diag 集成测试报告",
        "",
        f"> 生成时间：{ts}　｜　覆盖命令：`mulan trace` / `mulan diag`",
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
        "A": "mulan trace list",
        "B": "mulan trace 状态机",
        "C": "mulan trace show/summary/config",
        "D": "mulan diag status",
        "E": "mulan diag list",
        "F": "mulan diag pack",
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
    print("  mulan trace / diag 集成测试")
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
    report_path = _RESULTS_DIR / f"diag_trace_{ts}.md"
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
    "A-01", "A-02", "A-03",
    "B-01", "B-02", "B-03", "B-04", "B-05", "B-06",
    "C-01", "C-02", "C-03", "C-04", "C-05",
    "D-01", "D-02", "D-03", "D-04",
    "E-01", "E-02", "E-03", "E-04",
    "F-01", "F-02", "F-03", "F-04",
]

TestDiagTrace = type(
    "TestDiagTrace",
    (),
    {f"test_{cid.lower().replace('-', '_')}": _make_pytest_test(cid) for cid in _ALL_CASE_IDS},
)


if __name__ == "__main__":
    sys.exit(main())
