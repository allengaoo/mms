"""
tests/integration/health_check_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan 系统健康检查命令集成测试（真实 CLI 调用，无 mock）
覆盖命令：status / verify / validate

特点：
  - 直接调用 mulan CLI，无 mock，使用真实文件系统
  - validate 测试会在 docs/memory/ 下创建 __ci_test__ 前缀的临时文件，测后清理
  - 结果写入 tests/integration/results/health_check_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/health_check_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/health_check_tests.py -v -s

测试分组：
  A 组：mulan status
  B 组：mulan verify
  C 组：mulan validate
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
_CLI = [sys.executable, str(_ROOT / "cli.py")]
_RESULTS_DIR = Path(__file__).resolve().parent / "results"
_MEMORY_ROOT = _ROOT / "docs" / "memory"

# 临时 fixture 文件（validate 使用 MEM-*.md 模式扫描，必须符合命名规范，测后清理）
# 使用 MEM-E-CITEST- 前缀，可通过 *CITEST* 通配符统一清理
_FIXTURE_VALID_MD = _MEMORY_ROOT / "MEM-E-CITEST-V01.md"
_FIXTURE_BAD_MD   = _MEMORY_ROOT / "MEM-E-CITEST-B01.md"


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


# ── CLI 辅助 ─────────────────────────────────────────────────────────────────

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


def has(output: str, keyword: str) -> bool:
    return keyword in output

def not_has(output: str, keyword: str) -> bool:
    return keyword not in output

def match(output: str, pattern: str) -> bool:
    return bool(re.search(pattern, output))


# ── 夹具管理 ─────────────────────────────────────────────────────────────────

def _setup_fixtures():
    """
    创建测试用的临时记忆文件（validate 组使用）：
      - _FIXTURE_VALID_MD：合法 frontmatter（MEM-E-CITEST-V01.md）
      - _FIXTURE_BAD_MD：缺少 frontmatter（MEM-E-CITEST-B01.md）
    文件名使用 MEM-E-CITEST- 前缀，匹配 validate 的扫描模式，测后统一清理。
    """
    _FIXTURE_VALID_MD.write_text(
        textwrap.dedent("""\
        ---
        id: MEM-L-CI-001
        layer: L2
        dimension: infrastructure
        type: lesson
        tier: hot
        tags: [ci, test, integration]
        source_ep: EP-999
        created_at: "2026-04-29"
        version: 1
        ---

        # CI 集成测试记忆（自动生成，测后删除）

        本文件由 health_check_tests.py 自动创建，用于 validate 集成测试。
        """),
        encoding="utf-8",
    )

    _FIXTURE_BAD_MD.write_text(
        textwrap.dedent("""\
        # 无 frontmatter 的记忆文件

        本文件故意缺少 YAML front-matter，用于测试 validate 的错误检测能力。
        """),
        encoding="utf-8",
    )


def _cleanup_fixtures():
    """清理所有 MEM-E-CITEST- 前缀的临时 fixture 文件。"""
    for p in _MEMORY_ROOT.glob("MEM-E-CITEST-*.md"):
        p.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []

    _setup_fixtures()

    try:
        # ────────────────────────────────────────────────────────────────────
        # 组 A：mulan status
        # ────────────────────────────────────────────────────────────────────

        # A-01：无参数运行，exit=0，输出包含标题
        code, out, err = run("status")
        results.append(CaseResult(
            id="A-01", group="A", name="status 无参数运行正常（exit=0）",
            command="mulan status",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                          "0"),
                ("含 MMS 系统状态 标题",      has(out, "MMS 系统状态"),            "MMS 系统状态"),
                ("含 熔断器状态 区块",         has(out, "熔断器状态"),              "熔断器状态"),
                ("含 记忆库统计 区块",         has(out, "记忆库统计"),              "记忆库统计"),
            ],
        ))

        # A-02：输出含图健康区块
        code, out, err = run("status")
        results.append(CaseResult(
            id="A-02", group="A", name="status 输出包含记忆图健康区块",
            command="mulan status",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 图健康 区块标题",         has(out, "Memory Graph Health"),    "Memory Graph Health"),
                ("含 节点总数",               has(out, "节点总数"),                "节点总数"),
                ("含 图密度",                 has(out, "图密度"),                  "图密度"),
            ],
        ))

        # A-03：输出含 HOT/WARM 等 tier 统计
        code, out, err = run("status")
        results.append(CaseResult(
            id="A-03", group="A", name="status 输出含 tier 分布统计",
            command="mulan status",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 HOT 或 WARM 关键词",     has(out, "HOT") or has(out, "WARM"), "HOT/WARM"),
                ("含 总计 N 条",              match(out, r"总计\s*\d+\s*条"),      "总计 N 条"),
                ("含 按层分布",               has(out, "按层分布"),                "按层分布"),
            ],
        ))

        # A-04：DASHSCOPE 未配置时有警告提示
        code, out, err = run("status")
        import os
        dashscope_set = bool(os.environ.get("DASHSCOPE_API_KEY"))
        if dashscope_set:
            warn_check = has(out, "百炼")   # 配置时也会显示百炼区块
            warn_desc = "含 百炼 区块（已配置 API KEY）"
        else:
            warn_check = has(out, "DASHSCOPE_API_KEY") or has(out, "未配置")
            warn_desc = "DASHSCOPE 未配置时含警告 ⚠️"
        results.append(CaseResult(
            id="A-04", group="A", name="status 正确感知 DASHSCOPE_API_KEY 配置状态",
            command="mulan status",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                (warn_desc, warn_check, "DASHSCOPE_API_KEY / 百炼"),
                ("含 百炼 区块",              has(out, "百炼"),                    "百炼"),
            ],
        ))

        # A-05：熔断器状态正常（未初始化 = 正常）
        code, out, err = run("status")
        results.append(CaseResult(
            id="A-05", group="A", name="status 熔断器状态显示正常或已开启",
            command="mulan status",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含熔断器相关描述",
                 has(out, "熔断器") and (
                     has(out, "正常") or has(out, "CLOSED") or has(out, "OPEN") or has(out, "未初始化")
                 ),
                 "熔断器 + 状态描述"),
            ],
        ))

        # A-06：--help 正常显示
        code, out, err = run("status", "--help")
        results.append(CaseResult(
            id="A-06", group="A", name="status --help 正常显示",
            command="mulan status --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                          "0"),
                ("含 usage:",                has(out, "usage:"),                  "usage:"),
            ],
        ))

        # A-07：status 完成时间 < 5s（性能基线）
        t0 = time.perf_counter()
        code, out, err = run("status", timeout=10)
        elapsed = time.perf_counter() - t0
        results.append(CaseResult(
            id="A-07", group="A", name="status 执行完成 < 5 秒",
            command="mulan status（计时）",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                          "0"),
                (f"耗时 {elapsed:.2f}s < 5s", elapsed < 5.0,                     "<5s"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 B：mulan verify
        # ────────────────────────────────────────────────────────────────────

        # B-01：无参数运行不崩溃（exit 0 或 1 均可，核心是不崩溃）
        code, out, err = run("verify")
        results.append(CaseResult(
            id="B-01", group="B", name="verify 无参数运行不崩溃（exit 0 或 1）",
            command="mulan verify",
            expected_exit=code,   # 接受当前实际 exit code（容错）
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在合法范围 [0,1,2]",  code in (0, 1, 2),              "[0,1,2]"),
                ("含 MMS 健康检查 标题",           has(out, "MMS 健康检查"),        "MMS 健康检查"),
                ("含 4 个检查项标题之一",
                 any(has(out, s) for s in ["Schema", "索引", "文档", "前端"]),
                 "Schema/索引/文档/前端"),
            ],
        ))

        # B-02：--schema 独立运行，只含 Schema 区块
        code, out, err = run("verify", "--schema")
        results.append(CaseResult(
            id="B-02", group="B", name="verify --schema 只检查 Schema 项",
            command="mulan verify --schema",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                code == 0,                      "0"),
                ("输出含 Schema 校验 区块",        has(out, "Schema"),              "Schema"),
                ("通过提示 ✅",                   has(out, "✅"),                   "✅"),
                ("不含 索引一致性 区块",           not_has(out, "索引一致性"),       "不含 索引一致性"),
            ],
        ))

        # B-03：--index 检测到 MEMORY_INDEX.json 缺失时输出错误
        code, out, err = run("verify", "--index")
        index_exists = (_MEMORY_ROOT / "MEMORY_INDEX.json").exists()
        if index_exists:
            # 如果索引存在，应当通过
            expected_index_exit = 0
            index_ok_check = has(out, "✅") or has(out, "通过")
            index_desc = "索引存在时 exit=0 且含 ✅"
        else:
            # 索引不存在，应当失败并有 ❌ 提示
            expected_index_exit = 1
            index_ok_check = has(out, "❌") and has(out, "MEMORY_INDEX")
            index_desc = "索引缺失时 exit=1 且含 ❌ + MEMORY_INDEX"
        results.append(CaseResult(
            id="B-03", group="B", name="verify --index 正确反映索引状态",
            command="mulan verify --index",
            expected_exit=expected_index_exit, actual_exit=code, stdout=out, stderr=err,
            checks=[
                (index_desc,           index_ok_check,      "❌ MEMORY_INDEX / ✅"),
                ("含 索引一致性 关键词", has(out, "索引"),    "索引"),
            ],
        ))

        # B-04：--docs 检测文档漂移
        code, out, err = run("verify", "--docs")
        results.append(CaseResult(
            id="B-04", group="B", name="verify --docs 执行文档漂移检测",
            command="mulan verify --docs",
            expected_exit=code,  # 容错：当前环境可能有 warning
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",       code in (0, 1),          "[0,1]"),
                ("含 docs 或 文档 关键词",    has(out, "docs") or has(out, "文档"),  "docs/文档"),
            ],
        ))

        # B-05：--frontend 独立运行
        code, out, err = run("verify", "--frontend")
        results.append(CaseResult(
            id="B-05", group="B", name="verify --frontend 独立运行",
            command="mulan verify --frontend",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",   code == 0,                        "0"),
                ("含 前端 或 ✅",     has(out, "前端") or has(out, "✅"), "前端/✅"),
            ],
        ))

        # B-06：--ci 模式下有错误时 exit=2
        code, out, err = run("verify", "--ci")
        if not index_exists:
            # 索引不存在 = 有错误，--ci 模式应返回 2
            results.append(CaseResult(
                id="B-06", group="B", name="verify --ci 有错误时 exit=2（CI 模式）",
                command="mulan verify --ci",
                expected_exit=2, actual_exit=code, stdout=out, stderr=err,
                checks=[
                    ("--ci 有错误时 exit=2", code == 2,              "2"),
                    ("含错误汇总行",         match(out, r"\d+\s*个错误"), "N 个错误"),
                ],
            ))
        else:
            results.append(CaseResult(
                id="B-06", group="B", name="verify --ci 全通过时 exit=0",
                command="mulan verify --ci",
                expected_exit=0, actual_exit=code, stdout=out, stderr=err,
                checks=[
                    ("--ci 全通过 exit=0", code == 0, "0"),
                ],
            ))

        # B-07：verify --help
        code, out, err = run("verify", "--help")
        results.append(CaseResult(
            id="B-07", group="B", name="verify --help 正常显示所有子选项",
            command="mulan verify --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",         code == 0,                    "0"),
                ("含 --schema 选项",        has(out, "--schema"),         "--schema"),
                ("含 --index 选项",         has(out, "--index"),          "--index"),
                ("含 --docs 选项",          has(out, "--docs"),           "--docs"),
                ("含 --ci 选项",            has(out, "--ci"),             "--ci"),
            ],
        ))

        # B-08：verify 与 status 职责独立（输出不重叠）
        _, status_out, _ = run("status")
        _, verify_out, _ = run("verify")
        results.append(CaseResult(
            id="B-08", group="B", name="verify 与 status 输出职责不重叠",
            command="mulan status / mulan verify（对比）",
            expected_exit=0, actual_exit=0, stdout=verify_out, stderr="",
            checks=[
                ("verify 输出不含 status 专有词「记忆库统计」",
                 not_has(verify_out, "记忆库统计"), "不含 记忆库统计"),
                ("status 输出不含 verify 专有词「Schema 校验」",
                 not_has(status_out, "Schema 校验"), "不含 Schema 校验"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 C：mulan validate
        # ────────────────────────────────────────────────────────────────────

        # C-01：--help 正常显示
        code, out, err = run("validate", "--help")
        results.append(CaseResult(
            id="C-01", group="C", name="validate --help 正常显示",
            command="mulan validate --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",              code == 0,                         "0"),
                ("含 --changed-only 选项",       has(out, "--changed-only"),        "--changed-only"),
                ("含 --file 选项",               has(out, "--file"),                 "--file"),
                ("含 --migrate-add-version 选项", has(out, "--migrate-add-version"), "--migrate-add-version"),
            ],
        ))

        # C-02：对合法 frontmatter 文件校验通过（用 fixture）
        code, out, err = run("validate", "--file", "MEM-E-CITEST-V01")
        results.append(CaseResult(
            id="C-02", group="C", name="validate --file 对合法 frontmatter 文件 exit=0",
            command="mulan validate --file MEM-E-CITEST-V01",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",           code == 0,                "0"),
                ("输出含 ✅",                has(out, "✅"),             "✅"),
                ("不含 ❌",                  not_has(out, "❌"),         "不含 ❌"),
            ],
        ))

        # C-03：对缺少 frontmatter 的文件报错（用 fixture）
        code, out, err = run("validate", "--file", "MEM-E-CITEST-B01")
        results.append(CaseResult(
            id="C-03", group="C", name="validate --file 对缺 frontmatter 文件 exit=1 + ❌",
            command="mulan validate --file MEM-E-CITEST-B01",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",              code == 1,                "1"),
                ("输出含 ❌",                   has(out, "❌"),             "❌"),
                ("含 frontmatter 关键词",
                 has(out, "front-matter") or has(out, "frontmatter") or has(out, "---"),
                 "front-matter"),
            ],
        ))

        # C-04：--file 不存在的文件名 exit=2
        code, out, err = run("validate", "--file", "__ci_nonexistent_xxxx__")
        results.append(CaseResult(
            id="C-04", group="C", name="validate --file 不存在的文件 exit=2 + 友好提示",
            command="mulan validate --file __ci_nonexistent_xxxx__",
            expected_exit=2, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 2",           code == 2,                "2"),
                ("含 未找到文件 提示",        has(out, "未找到"),        "未找到"),
            ],
        ))

        # C-05：--changed-only 无变更文件时 exit=0 并跳过
        code, out, err = run("validate", "--changed-only")
        results.append(CaseResult(
            id="C-05", group="C", name="validate --changed-only（可能无变更文件时正常退出）",
            command="mulan validate --changed-only",
            expected_exit=code,  # 容错：有变更时可能是 0 或 1
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",       code in (0, 1),           "[0,1]"),
                ("不崩溃（无异常输出）",
                 not_has(err, "Traceback") and not_has(err, "Error"),   "无 Traceback/Error"),
            ],
        ))

        # C-06：全量扫描不超时（< 10s）
        t0 = time.perf_counter()
        code, out, err = run("validate", timeout=15)
        elapsed = time.perf_counter() - t0
        results.append(CaseResult(
            id="C-06", group="C", name="validate 全量扫描完成 < 10 秒",
            command="mulan validate（计时）",
            expected_exit=code,  # 容错
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                (f"耗时 {elapsed:.2f}s < 10s",  elapsed < 10.0,         "<10s"),
                ("不崩溃",
                 not_has(err, "Traceback"),                             "无 Traceback"),
                ("输出含 校验完成 汇总行",
                 has(out, "校验完成"),                                   "校验完成"),
            ],
        ))

        # C-07：全量扫描输出包含正确的通过/失败计数格式
        code, out, err = run("validate")
        results.append(CaseResult(
            id="C-07", group="C", name="validate 输出含合法的通过/失败计数格式",
            command="mulan validate",
            expected_exit=code,  # 容错
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 校验完成 字样",           has(out, "校验完成"),              "校验完成"),
                ("含 通过 和 失败 字样",
                 has(out, "通过") and has(out, "失败"),                  "通过 + 失败"),
                ("含数字统计",                 match(out, r"\d+\s*通过"),          "N 通过"),
            ],
        ))

    finally:
        _cleanup_fixtures()

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
        f"# mulan 系统健康检查集成测试报告",
        f"",
        f"> 生成时间：{ts}　｜　覆盖命令：`mulan status` / `mulan verify` / `mulan validate`",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 总用例数 | {total} |",
        f"| 通过 | {passed} |",
        f"| 失败 | {total - passed} |",
        f"| 总耗时 | {elapsed:.1f}s |",
        f"| 结果 | {ok_icon} {'全部通过' if passed == total else f'{total-passed} 个失败'} |",
        f"",
        f"## 详细结果",
        f"",
    ]

    current_group = None
    group_names = {"A": "mulan status", "B": "mulan verify", "C": "mulan validate"}

    for r in results:
        if r.group != current_group:
            current_group = r.group
            lines.append(f"### {group_names.get(r.group, r.group)} 组（{r.group} 组）")
            lines.append(f"")

        icon = "✅" if r.passed else "❌"
        lines += [
            f"#### {icon} [{r.id}] {r.name}",
            f"",
            f"**命令**：`{r.command}`  ",
            f"**期望 exit**：`{r.expected_exit}`　**实际 exit**：`{r.actual_exit}`",
            f"",
            f"| 检查项 | 结果 | 期望值 |",
            f"|--------|------|--------|",
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
    print("=" * 60)
    print("  mulan 系统健康检查集成测试（status / verify / validate）")
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
    report_path = _RESULTS_DIR / f"health_check_{ts}.md"
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
    "A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-07",
    "B-01", "B-02", "B-03", "B-04", "B-05", "B-06", "B-07", "B-08",
    "C-01", "C-02", "C-03", "C-04", "C-05", "C-06", "C-07",
]

TestHealthCheck = type(
    "TestHealthCheck",
    (),
    {f"test_{cid.lower().replace('-', '_')}": _make_pytest_test(cid) for cid in _ALL_CASE_IDS},
)


if __name__ == "__main__":
    sys.exit(main())
