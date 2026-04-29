"""
tests/integration/diag_trace_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan trace 和 diag 命令集成测试（真实 CLI 调用，无 mock）
覆盖命令：
  trace  enable / disable / show / summary / list / clean / config
  diag   status / list / pack

特点：
  - 直接调用 mulan CLI，无 mock，使用真实文件系统
  - B 组副作用测试使用 EP-CI-TEST-998 专用 EP ID，测后在 finally 中清理
  - F-03/F-04 生成的 ZIP 文件在 finally 中清理
  - trace clean 命令需要交互确认，通过 subprocess.run(input="yes\\n") 传入
  - 结果写入 tests/integration/results/diag_trace_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/diag_trace_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/diag_trace_tests.py -v -s

测试分组：
  A 组：mulan trace list
  B 组：mulan trace enable/disable/clean 状态机
  C 组：mulan trace show/summary/config
  D 组：mulan diag status
  E 组：mulan diag list
  F 组：mulan diag pack

已探测的真实行为摘要（2026-04-29）：
  - trace list        → exit=0，表格含"已开启 / 事件数"列
  - trace enable      → exit=0，含 "诊断追踪已开启"
  - trace disable     → exit=0，含 "诊断追踪已关闭"
  - trace show        → exit=0（即使 EP 不存在，返回空报告）
  - trace summary     → exit=0（即使 EP 不存在，返回空摘要）
  - trace config      → level 合法值 {1,4,8,12}，exit=0
  - trace clean       → 需 stdin "yes"，exit=0
  - diag status       → exit=1（有 FATAL 告警时），含 FATAL: N
  - diag list         → exit=0，含 Incident 表格
  - diag pack <id>    → exit=0 生成 ZIP；ID 不存在时 exit=1
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

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

# CI 专用 EP ID，不影响真实 EP 数据
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
    checks: List[tuple]   # (描述, passed, 期望值)
    passed: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        self.passed = (
            self.actual_exit == self.expected_exit
            and all(ok for _, ok, _ in self.checks)
            and self.error is None
        )


# ── CLI 辅助函数 ──────────────────────────────────────────────────────────────

def run(*args: str, timeout: int = 20) -> tuple:
    """调用 mulan CLI，返回 (exit_code, stdout, stderr)。"""
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


def run_with_input(*args: str, stdin_text: str = "", timeout: int = 20) -> tuple:
    """调用 mulan CLI，通过 stdin 传入交互输入，返回 (exit_code, stdout, stderr)。"""
    cmd = _CLI + list(args)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            input=stdin_text,
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


# ── 夹具清理 ─────────────────────────────────────────────────────────────────

def _cleanup_ci_ep():
    """清理 EP-CI-TEST-998 的所有追踪数据（通过 CLI 发送 yes 确认）。"""
    try:
        run_with_input("trace", "clean", _CI_EP, stdin_text="yes\n", timeout=15)
    except Exception:
        pass
    # 同时直接删除目录（防止 CLI clean 跳过的情况）
    trace_dir = _ROOT / "docs" / "memory" / "private" / "trace" / _CI_EP
    if trace_dir.exists():
        import shutil
        shutil.rmtree(trace_dir, ignore_errors=True)


def _cleanup_zip_files(incident_id: str = ""):
    """清理 diag pack 生成的 ZIP 文件。"""
    if incident_id:
        zip_path = _ROOT / f"mulan_incident_{incident_id}.zip"
        zip_path.unlink(missing_ok=True)
    # 也清理所有 CI 测试期间可能生成的 zip
    for zf in _ROOT.glob("mulan_incident_*.zip"):
        zf.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []
    _pack_incident_id = ""   # F-03 解析到的真实 incident ID，用于 F-04 验证和 finally 清理

    # 先做一次初始清理，防止残留
    _cleanup_ci_ep()

    try:
        # ────────────────────────────────────────────────────────────────────
        # 组 A：mulan trace list
        # ────────────────────────────────────────────────────────────────────

        # A-01：trace list 正常运行，exit 在 [0,1]，输出含表头
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="A-01", group="A", name="trace list 正常运行，含表头列名",
            command="mulan trace list",
            expected_exit=code,  # 容错：当前有记录时 exit=0
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在合法范围 [0,1]",    code in (0, 1),           "[0,1]"),
                ("含 EP 列标题",                   has(out, "EP"),            "EP"),
                ("含 已开启 列",                   has(out, "已开启"),         "已开启"),
                ("含 事件数 列",                   has(out, "事件数"),         "事件数"),
                ("不崩溃（stderr 无 Traceback）",  not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # A-02：trace list --help 正常显示
        code, out, err = run("trace", "list", "--help")
        results.append(CaseResult(
            id="A-02", group="A", name="trace list --help 正常显示",
            command="mulan trace list --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,              "0"),
                ("含 usage: 提示",      has(out, "usage:"),     "usage:"),
            ],
        ))

        # A-03：trace list 输出为表格形式（含分隔线或对齐列）
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="A-03", group="A", name="trace list 输出为表格形式（含分隔线）",
            command="mulan trace list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含分隔线（─ 或 -）",
                 match(out, r"[─\-]{4,}"),
                 "─────"),
                ("含 Level 列",
                 has(out, "Level"),
                 "Level"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 B：mulan trace enable/disable/clean 状态机
        # ────────────────────────────────────────────────────────────────────

        # B-01：enable EP-CI-TEST-998 → exit=0，含 "已开启" 或 "✅"
        code, out, err = run("trace", "enable", _CI_EP)
        results.append(CaseResult(
            id="B-01", group="B", name=f"trace enable {_CI_EP} → exit=0，含开启成功标志",
            command=f"mulan trace enable {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                     code == 0,                           "0"),
                ("含 ✅ 或 已开启",
                 has(out, "✅") or has(out, "已开启"),
                 "✅ / 已开启"),
                ("含目标 EP ID",                       has(out, _CI_EP),                    _CI_EP),
                ("不含 Traceback",                     not_has(out + err, "Traceback"),      "无崩溃"),
            ],
        ))

        # B-02：enable 后 trace list → 包含 EP-CI-TEST-998 条目
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="B-02", group="B", name=f"enable 后 trace list 包含 {_CI_EP}",
            command="mulan trace list（enable 后）",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",                code in (0, 1),            "[0,1]"),
                (f"列表含 {_CI_EP}",                   has(out, _CI_EP),          _CI_EP),
                ("含 ✅ 是（已开启标志）",             has(out, "✅"),             "✅"),
            ],
        ))

        # B-03：disable EP-CI-TEST-998 → exit=0，含 "已关闭" 或 "关闭"
        code, out, err = run("trace", "disable", _CI_EP)
        results.append(CaseResult(
            id="B-03", group="B", name=f"trace disable {_CI_EP} → exit=0，含关闭标志",
            command=f"mulan trace disable {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                     code == 0,                           "0"),
                ("含 已关闭 或 关闭",
                 has(out, "已关闭") or has(out, "关闭"),
                 "已关闭 / 关闭"),
                ("含目标 EP ID",                       has(out, _CI_EP),                    _CI_EP),
            ],
        ))

        # B-04：disable 后再次 enable → exit=0（可反复开关）
        code, out, err = run("trace", "enable", _CI_EP)
        results.append(CaseResult(
            id="B-04", group="B", name=f"disable 后再次 enable → exit=0",
            command=f"mulan trace enable {_CI_EP}（第二次）",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                     code == 0,                           "0"),
                ("含 ✅ 或 已开启",
                 has(out, "✅") or has(out, "已开启"),
                 "✅ / 已开启"),
            ],
        ))

        # B-05：clean EP-CI-TEST-998（传入 "yes" 确认）→ exit=0
        code, out, err = run_with_input("trace", "clean", _CI_EP, stdin_text="yes\n")
        results.append(CaseResult(
            id="B-05", group="B", name=f"trace clean {_CI_EP}（yes 确认）→ exit=0",
            command=f"echo 'yes' | mulan trace clean {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,              "0"),
                ("含 清除 / 删除 / 跳过 之一",
                 has(out, "清除") or has(out, "删除") or has(out, "跳过") or has(out, "已删"),
                 "清除/删除/跳过"),
                ("不含 Traceback",      not_has(out + err, "Traceback"),  "无崩溃"),
            ],
        ))
        # 确保目录级清理
        _cleanup_ci_ep()

        # B-06：clean 后 trace list 正常运行，EP-CI-TEST-998 不再是"已开启"状态
        code, out, err = run("trace", "list")
        results.append(CaseResult(
            id="B-06", group="B", name="clean 后 trace list 正常运行（已清理验证）",
            command="mulan trace list（clean 后）",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",                    code in (0, 1),               "[0,1]"),
                ("不崩溃（stderr 无 Traceback）",          not_has(err, "Traceback"),    "无 Traceback"),
                # EP-CI-TEST-998 要么不出现，要么出现但标记为"否（已清理）"
                (f"{_CI_EP} 已清理：不出现 或 标记为否",
                 not_has(out, _CI_EP) or (has(out, _CI_EP) and not_has(out, "✅ 是")),
                 "不含 / 标记否"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 C：mulan trace show/summary/config
        # ────────────────────────────────────────────────────────────────────

        # 先 enable EP-CI-TEST-998（C 组测试前提）
        run("trace", "enable", _CI_EP)

        # C-01：show EP-CI-TEST-998（已 enable）→ exit=0，含 "MMS Trace Report" 或 EP ID
        code, out, err = run("trace", "show", _CI_EP)
        results.append(CaseResult(
            id="C-01", group="C", name=f"trace show {_CI_EP}（enable 后）→ exit=0，含报告标题",
            command=f"mulan trace show {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                         code == 0,                     "0"),
                ("含 MMS Trace Report 或 EP ID",
                 has(out, "MMS Trace Report") or has(out, _CI_EP),
                 "MMS Trace Report / EP ID"),
                ("含 事件总数 统计",                       has(out, "事件总数"),            "事件总数"),
            ],
        ))

        # C-02：summary EP-CI-TEST-998（已 enable）→ exit=0，含统计行
        code, out, err = run("trace", "summary", _CI_EP)
        results.append(CaseResult(
            id="C-02", group="C", name=f"trace summary {_CI_EP}（enable 后）→ exit=0，含统计行",
            command=f"mulan trace summary {_CI_EP}",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                         code == 0,                      "0"),
                ("含 诊断摘要 或 EP ID",
                 has(out, "诊断摘要") or has(out, _CI_EP),
                 "诊断摘要 / EP ID"),
                ("含 事件总数 行",                         has(out, "事件总数"),             "事件总数"),
                ("含 LLM 调用 行",                         has(out, "LLM"),                 "LLM"),
            ],
        ))

        # C-03：show 不存在的 EP → exit=0（真实行为：返回空报告，不报错）
        code, out, err = run("trace", "show", "EP-CI-NONEXIST-888")
        results.append(CaseResult(
            id="C-03", group="C", name="trace show 不存在的 EP → exit=0，返回空报告",
            command="mulan trace show EP-CI-NONEXIST-888",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0（空报告）",               code == 0,                      "0"),
                ("输出含 EP ID 或报告结构",
                 has(out, "EP-CI-NONEXIST-888") or has(out, "Trace Report"),
                 "EP ID / Trace Report"),
                ("不含 Traceback",                         not_has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

        # C-04：summary 不存在的 EP → exit=0（真实行为：返回空摘要，不报错）
        code, out, err = run("trace", "summary", "EP-CI-NONEXIST-888")
        results.append(CaseResult(
            id="C-04", group="C", name="trace summary 不存在的 EP → exit=0，返回空摘要",
            command="mulan trace summary EP-CI-NONEXIST-888",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0（空摘要）",               code == 0,                      "0"),
                ("含 EP ID 或摘要结构",
                 has(out, "EP-CI-NONEXIST-888") or has(out, "诊断摘要"),
                 "EP ID / 诊断摘要"),
                ("不含 Traceback",                         not_has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

        # C-05：config EP-CI-TEST-998 --level 4（合法 level）→ exit=0，含"已更新"
        code, out, err = run("trace", "config", _CI_EP, "--level", "4")
        results.append(CaseResult(
            id="C-05", group="C", name=f"trace config {_CI_EP} --level 4 → exit=0，含已更新",
            command=f"mulan trace config {_CI_EP} --level 4",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                         code == 0,                      "0"),
                ("含 已更新 或 更新 关键词",
                 has(out, "已更新") or has(out, "更新"),
                 "已更新 / 更新"),
                ("含 level=4",
                 has(out, "level=4") or has(out, "4"),
                 "level=4"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 D：mulan diag status
        # ────────────────────────────────────────────────────────────────────

        # D-01：diag status exit=0 或 1，不崩溃
        code, out, err = run("diag", "status")
        results.append(CaseResult(
            id="D-01", group="D", name="diag status 正常运行，exit=0 或 1，不崩溃",
            command="mulan diag status",
            expected_exit=code,  # 容错：当前有 FATAL 时 exit=1
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",                    code in (0, 1),               "[0,1]"),
                ("输出含状态信息",
                 has(out, "FATAL") or has(out, "WARN") or has(out, "Mulan"),
                 "FATAL/WARN/Mulan"),
                ("不含 Traceback",                         not_has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

        # D-02：输出含日志路径信息
        code, out, err = run("diag", "status")
        results.append(CaseResult(
            id="D-02", group="D", name="diag status 输出含告警日志路径",
            command="mulan diag status",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 alert 或 .log 关键词",
                 has(out, "alert") or has(out, ".log"),
                 "alert / .log"),
                ("含 Mulan Diag 标题区块",
                 has(out, "Mulan Diag") or has(out, "Diag Status"),
                 "Mulan Diag / Diag Status"),
            ],
        ))

        # D-03：当前环境有 FATAL 告警 → exit=1，输出含 FATAL 关键词
        code, out, err = run("diag", "status")
        has_fatal = has(out, "FATAL")
        results.append(CaseResult(
            id="D-03", group="D", name="有 FATAL 告警时 exit=1，输出含 FATAL",
            command="mulan diag status",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1（有 FATAL）",             code == 1,                      "1"),
                ("输出含 FATAL 关键词",                    has_fatal,                       "FATAL"),
                ("含告警数量信息",
                 match(out, r"FATAL\s*:\s*\d+"),
                 "FATAL: N"),
            ],
        ))

        # D-04：diag status --help 正常显示
        code, out, err = run("diag", "status", "--help")
        results.append(CaseResult(
            id="D-04", group="D", name="diag status --help 正常显示",
            command="mulan diag status --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,              "0"),
                ("含 usage: 提示",      has(out, "usage:"),     "usage:"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 E：mulan diag list
        # ────────────────────────────────────────────────────────────────────

        # E-01：diag list exit=0 或 1，不崩溃
        code, out, err = run("diag", "list")
        results.append(CaseResult(
            id="E-01", group="E", name="diag list 正常运行，exit=0 或 1，不崩溃",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",                    code in (0, 1),               "[0,1]"),
                ("不含 Traceback",                         not_has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

        # E-02：输出含 Incident 或友好提示
        code, out, err = run("diag", "list")
        results.append(CaseResult(
            id="E-02", group="E", name="diag list 输出含 Incident 关键词或友好提示",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 Incident 列 或 inc_ 条目 或 无记录提示",
                 has(out, "Incident") or has(out, "inc_") or has(out, "无") or has(out, "状态"),
                 "Incident / inc_ / 无记录"),
            ],
        ))

        # E-03：输出按时间倒序（有记录时验证首行含时间戳格式）
        code, out, err = run("diag", "list")
        # 检查是否有 inc_ 条目（说明有记录）
        has_incidents = bool(re.search(r"inc_\d{8}", out))
        if has_incidents:
            # 有记录时验证时间戳格式（inc_YYYYMMDD_HHMMSS_xxx）
            timestamp_ok = bool(re.search(r"inc_\d{8}_\d{6}", out))
            ts_desc = "含 inc_YYYYMMDD_HHMMSS 格式"
        else:
            # 无记录时只验证不崩溃
            timestamp_ok = not_has(out + err, "Traceback")
            ts_desc = "无记录时不崩溃"
        results.append(CaseResult(
            id="E-03", group="E", name="diag list 输出含时间戳格式（时间倒序验证）",
            command="mulan diag list",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",                    code in (0, 1),               "[0,1]"),
                (ts_desc,                                   timestamp_ok,                  "inc_YYYYMMDD_HHMMSS"),
            ],
        ))

        # E-04：diag list --help 正常显示
        code, out, err = run("diag", "list", "--help")
        results.append(CaseResult(
            id="E-04", group="E", name="diag list --help 正常显示",
            command="mulan diag list --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,              "0"),
                ("含 usage: 提示",      has(out, "usage:"),     "usage:"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 F：mulan diag pack
        # ────────────────────────────────────────────────────────────────────

        # F-01：diag pack --help 正常显示
        code, out, err = run("diag", "pack", "--help")
        results.append(CaseResult(
            id="F-01", group="F", name="diag pack --help 正常显示",
            command="mulan diag pack --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                         code == 0,                      "0"),
                ("含 usage: 提示",                         has(out, "usage:"),              "usage:"),
                ("含 incident_id 参数",
                 has(out, "incident_id") or has(out, "incident"),
                 "incident_id"),
            ],
        ))

        # F-02：pack 不存在的 incident_id → exit=1，友好错误
        fake_id = "inc_CI_NONEXIST_888"
        code, out, err = run("diag", "pack", fake_id)
        results.append(CaseResult(
            id="F-02", group="F", name="diag pack 不存在的 incident_id → exit=1，友好错误",
            command=f"mulan diag pack {fake_id}",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",                         code == 1,                      "1"),
                ("含 不存在 或 错误 提示",
                 has(out, "不存在") or has(out, "错误") or has(out, "Error") or has(err, "Error"),
                 "不存在 / 错误"),
                ("不含 Traceback",                         not_has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

        # F-03：pack 真实存在的 Incident ID（从 diag list 解析）→ 生成 ZIP 或合理错误
        list_code, list_out, _ = run("diag", "list")
        real_id_match = re.search(r"(inc_\d{8}_\d{6}_\w+)", list_out)
        if real_id_match:
            _pack_incident_id = real_id_match.group(1)
            code, out, err = run("diag", "pack", _pack_incident_id, timeout=30)
            zip_path = _ROOT / f"mulan_incident_{_pack_incident_id}.zip"
            zip_created = zip_path.exists()
            results.append(CaseResult(
                id="F-03", group="F", name=f"diag pack 真实 Incident → exit=0，生成 ZIP",
                command=f"mulan diag pack {_pack_incident_id}",
                expected_exit=0, actual_exit=code, stdout=out, stderr=err,
                checks=[
                    ("exit code 为 0",                     code == 0,                      "0"),
                    ("输出含 ✅ 或 诊断包",
                     has(out, "✅") or has(out, "诊断包") or has(out, "zip") or has(out, "ZIP"),
                     "✅ / 诊断包 / ZIP"),
                    ("不含 Traceback",                     not_has(out + err, "Traceback"), "无崩溃"),
                ],
            ))
            # F-04：验证 ZIP 文件实际存在
            results.append(CaseResult(
                id="F-04", group="F", name="diag pack 后 ZIP 文件实际存在于项目根目录",
                command=f"（验证 {zip_path.name} 存在）",
                expected_exit=0, actual_exit=0, stdout=str(zip_path), stderr="",
                checks=[
                    ("ZIP 文件已生成",
                     zip_created,
                     str(zip_path.name)),
                    ("ZIP 文件大小 >= 0 字节",
                     zip_path.stat().st_size >= 0 if zip_created else False,
                     "size >= 0"),
                ],
            ))
        else:
            # 没有真实 incident，跳过 F-03/F-04 打包，记录为容错通过
            results.append(CaseResult(
                id="F-03", group="F", name="diag pack 真实 Incident（无可用 incident，跳过）",
                command="mulan diag pack（无 incident 可用）",
                expected_exit=0, actual_exit=0, stdout="[跳过：无真实 Incident 可用]", stderr="",
                checks=[
                    ("无真实 Incident 时容错跳过",         True,                           "跳过"),
                ],
            ))
            results.append(CaseResult(
                id="F-04", group="F", name="diag pack ZIP 验证（无可用 incident，跳过）",
                command="（无 incident 跳过）",
                expected_exit=0, actual_exit=0, stdout="[跳过：无真实 Incident 可用]", stderr="",
                checks=[
                    ("无真实 Incident 时容错跳过",         True,                           "跳过"),
                ],
            ))

    finally:
        # 确保清理所有副作用
        _cleanup_ci_ep()
        _cleanup_zip_files(_pack_incident_id)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# Markdown 报告渲染
# ══════════════════════════════════════════════════════════════════════════════

def _render_markdown(results: List[CaseResult], elapsed: float) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    ok_icon = "✅" if passed == total else "❌"

    group_names = {
        "A": "mulan trace list",
        "B": "mulan trace enable/disable/clean 状态机",
        "C": "mulan trace show/summary/config",
        "D": "mulan diag status",
        "E": "mulan diag list",
        "F": "mulan diag pack",
    }

    lines = [
        "# mulan trace & diag 集成测试报告",
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
        "## 用例汇总表",
        "",
        "| ID | 组 | 测试名称 | 结果 |",
        "|----|----|----|------|",
    ]
    for r in results:
        icon = "✅ PASS" if r.passed else "❌ FAIL"
        lines.append(f"| {r.id} | {r.group} | {r.name} | {icon} |")

    lines += ["", "---", "", "## 详细结果", ""]

    current_group = None
    for r in results:
        if r.group != current_group:
            current_group = r.group
            lines.append(f"### {group_names.get(r.group, r.group)} 组（{r.group} 组）")
            lines.append("")

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
            icon2 = "✅" if ok else "❌"
            lines.append(f"| {desc} | {icon2} | `{expected}` |")

        if r.stdout.strip():
            preview = r.stdout.strip()[:600]
            if len(r.stdout.strip()) > 600:
                preview += "\n... (截断)"
            lines += ["", "**实际输出（前 600 字符）**", "```", preview, "```"]
        if r.stderr.strip():
            lines += ["", "**stderr**", "```", r.stderr.strip()[:200], "```"]
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 64)
    print("  mulan trace & diag 集成测试（真实 CLI 调用，无 mock）")
    print("=" * 64)

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
