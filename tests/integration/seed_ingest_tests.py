"""
tests/integration/seed_ingest_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan seed 命令组集成测试（真实 CLI 调用，无 mock）

特点：
  - 直接调用 mulan CLI，使用真实网络 / 真实文件系统
  - 写入测试产生的种子包使用 __ci_test__ 前缀，测试后自动清理
  - 结果写入 tests/integration/results/seed_ingest_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/seed_ingest_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/seed_ingest_tests.py -v -s

测试分组：
  A 组：seed list
  B 组：seed ingest 输入源验证
  C 组：seed ingest 选项行为
  D 组：内容质量
  E 组：seed ingest-batch
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent          # 项目根目录
_CLI = [sys.executable, str(_ROOT / "cli.py")]
_RESULTS_DIR = Path(__file__).resolve().parent / "results"

_PYTEST_RAW = (
    "https://raw.githubusercontent.com/sanjeed5/awesome-cursor-rules-mdc"
    "/main/rules-mdc/pytest.mdc"
)
_PYDANTIC_RAW = (
    "https://raw.githubusercontent.com/sanjeed5/awesome-cursor-rules-mdc"
    "/main/rules-mdc/pydantic.mdc"
)
_DIR_URL_REAL = (
    "https://github.com/sanjeed5/awesome-cursor-rules-mdc/tree/main/rules-mdc"
)
_DIR_URL_FAKE = "https://github.com/user/repo/tree/main/rules-mdc"
_LOCAL_MDC = _ROOT / "tests" / "integration" / "_fixture_test_rule.mdc"

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
    checks: List[tuple[str, bool, str]]   # (描述, passed, 期望值)
    passed: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        self.passed = (
            self.actual_exit == self.expected_exit
            and all(ok for _, ok, _ in self.checks)
            and self.error is None
        )


# ── 运行 CLI 的辅助函数 ───────────────────────────────────────────────────────

def run(*args: str, timeout: int = 30) -> tuple[int, str, str]:
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


def check_in(output: str, keyword: str) -> bool:
    return keyword in output

def check_not_in(output: str, keyword: str) -> bool:
    return keyword not in output

def check_exit(actual: int, expected: int) -> bool:
    return actual == expected


# ── 夹具：本地测试文件 ────────────────────────────────────────────────────────

def _setup_fixture():
    """创建本地测试 .mdc 文件（B-05 用）。"""
    _LOCAL_MDC.write_text(
        textwrap.dedent("""\
        # Test Rules for MMS Integration

        MUST use type annotations in all Python functions.
        NEVER use `eval()` or `exec()` in production code.
        ALWAYS handle exceptions explicitly, never use bare `except:`.

        ## Examples

        ```python
        # ✅ Good
        def add(a: int, b: int) -> int:
            return a + b

        # ❌ Bad
        def add(a, b):
            return a + b
        ```
        """),
        encoding="utf-8",
    )


def _cleanup_test_seeds():
    """删除 __ci_test__ 前缀的临时种子包。"""
    v31_root = _ROOT / "docs" / "memory" / "seed_packs"
    for pack in v31_root.glob("__ci_test__*"):
        shutil.rmtree(pack, ignore_errors=True)
    _LOCAL_MDC.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []

    # ── 组 A：seed list ───────────────────────────────────────────────────────

    # A-01：展示两个目录的种子包
    code, out, err = run("seed", "list")
    results.append(CaseResult(
        id="A-01", group="A", name="seed list 展示 v3.1 + v2 双目录",
        command="mulan seed list",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("输出含 v3.1 标签",      check_in(out, "v3.1"),           "v3.1"),
            ("输出含 v2 标签",         check_in(out, "v2"),             "v2"),
            ("含 memories: 统计",      check_in(out, "memories:"),      "memories:"),
            ("含 constraints: 指示符", check_in(out, "constraints:"),   "constraints:✓/✗"),
            ("含至少一个 v3.1 包名",   check_in(out, "python_sqlalchemy") or
                                        check_in(out, "infrastructure_redis"), "已知包名"),
        ],
    ))

    # A-02：无子命令等同 list
    code2, out2, _ = run("seed")
    results.append(CaseResult(
        id="A-02", group="A", name="mulan seed（无子命令）等同 seed list",
        command="mulan seed",
        expected_exit=0, actual_exit=code2, stdout=out2, stderr="",
        checks=[
            ("输出与 seed list 相同", out2.strip() == out.strip(), "与 A-01 输出一致"),
        ],
    ))

    # A-03：空目录提示
    # 用一个不存在的临时包名验证"无种子包"不会崩溃（通过观察 exit=0 即可）
    results.append(CaseResult(
        id="A-03", group="A", name="seed list exit=0 不崩溃",
        command="mulan seed list",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0", code == 0, "0"),
        ],
    ))

    # ── 组 B：seed ingest 输入源验证 ─────────────────────────────────────────

    # B-01：无参数
    code, out, err = run("seed", "ingest")
    results.append(CaseResult(
        id="B-01", group="B", name="不带参数报错（exit≠0）",
        command="mulan seed ingest",
        expected_exit=2, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 2",          code == 2,                      "2"),
            ("提示 URL_OR_PATH 必填",   check_in(err, "URL_OR_PATH")
                                         or check_in(err, "required"),  "URL_OR_PATH / required"),
        ],
    ))

    # B-02：目录 URL 被拒绝并引导
    code, out, err = run("seed", "ingest", _DIR_URL_REAL, "--dry-run")
    results.append(CaseResult(
        id="B-02", group="B", name="GitHub 目录 URL 被拒绝，给出 ingest-batch 引导",
        command=f"mulan seed ingest '{_DIR_URL_REAL}' --dry-run",
        expected_exit=1, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 1",          code == 1,                      "1"),
            ("提示使用 ingest-batch",   check_in(out, "ingest-batch"),   "ingest-batch"),
            ("不含 Traceback",          check_not_in(out + err, "Traceback"), "无崩溃"),
        ],
    ))

    # B-03：合法 raw URL + dry-run
    code, out, err = run("seed", "ingest", _PYTEST_RAW, "--dry-run", timeout=30)
    results.append(CaseResult(
        id="B-03", group="B", name="合法 raw URL + --dry-run 正常工作",
        command=f"mulan seed ingest '{_PYTEST_RAW}' --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",           code == 0,                     "0"),
            ("显示原始内容字符数",        check_in(out, "原始内容"),     "原始内容"),
            ("显示清洗后保留率",          check_in(out, "清洗后"),       "清洗后"),
            ("保留率 >50%（含数字）",     any(
                int(m.group(1)) >= 50
                for m in __import__("re").finditer(r'(\d+)%', out)
            ),                                                           "≥50%"),
            ("显示 dry-run 目标目录",     check_in(out, "dry-run"),     "dry-run"),
            ("不写入文件",                not (_ROOT / "docs/memory/seed_packs/pytest_dronly").exists(),
                                                                         "无文件写入"),
        ],
    ))

    # B-04：404 URL
    code, out, err = run(
        "seed", "ingest",
        "https://raw.githubusercontent.com/not-exist-xyz/not-exist-xyz/main/fake.mdc",
        "--dry-run", timeout=20,
    )
    results.append(CaseResult(
        id="B-04", group="B", name="不存在的 URL 返回 404 并 exit=1",
        command="mulan seed ingest 'https://.../not-exist/fake.mdc' --dry-run",
        expected_exit=1, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 1",   code == 1,              "1"),
            ("提示 404",         check_in(out, "404"),   "404"),
        ],
    ))

    # B-05：本地文件
    _setup_fixture()
    code, out, err = run("seed", "ingest", str(_LOCAL_MDC), "--dry-run")
    results.append(CaseResult(
        id="B-05", group="B", name="本地 .mdc 文件 dry-run 正常",
        command=f"mulan seed ingest '{_LOCAL_MDC}' --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",         code == 0,                    "0"),
            ("显示原始内容字符数",      check_in(out, "原始内容"),    "原始内容"),
            ("显示 dry-run 预览",       check_in(out, "dry-run"),     "dry-run"),
        ],
    ))

    # B-06：不存在的本地文件
    code, out, err = run("seed", "ingest", "/tmp/absolutely_not_exist_xyz.mdc", "--dry-run")
    results.append(CaseResult(
        id="B-06", group="B", name="不存在的本地文件报错 exit=1",
        command="mulan seed ingest '/tmp/absolutely_not_exist_xyz.mdc' --dry-run",
        expected_exit=1, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 1",   code == 1,                   "1"),
            ("提示文件不存在",    check_in(out, "不存在") or
                                  check_in(out, "not found"),  "不存在 / not found"),
        ],
    ))

    # ── 组 C：seed ingest 选项行为 ────────────────────────────────────────────

    CI_NAME = "__ci_test__pytest"
    CI_NAME_CUSTOM = "__ci_test__custom"

    # 先清理残留
    _cleanup_test_seeds()

    # C-01：dry-run 不创建文件
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, "--dry-run", timeout=30)
    target_path = _ROOT / "docs" / "memory" / "seed_packs" / CI_NAME
    results.append(CaseResult(
        id="C-01", group="C", name="--dry-run 不创建任何文件",
        command=f"mulan seed ingest ... --seed-name {CI_NAME} --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",           code == 0,                     "0"),
            ("显示 dry-run 目标目录",     check_in(out, "dry-run"),      "dry-run"),
            ("种子包目录未被创建",         not target_path.exists(),      f"不存在 {CI_NAME}/"),
        ],
    ))

    # C-02：--seed-name 自定义名称
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME_CUSTOM, "--dry-run", timeout=30)
    results.append(CaseResult(
        id="C-02", group="C", name="--seed-name 使用自定义包名",
        command=f"mulan seed ingest ... --seed-name {CI_NAME_CUSTOM} --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",            code == 0,                      "0"),
            ("输出中含自定义包名",          check_in(out, CI_NAME_CUSTOM),  CI_NAME_CUSTOM),
        ],
    ))

    # C-03：--format v31 路径
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, "--format", "v31", "--dry-run", timeout=30)
    results.append(CaseResult(
        id="C-03", group="C", name="--format v31 输出路径含 docs/memory/seed_packs/",
        command=f"mulan seed ingest ... --format v31 --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",                  code == 0,                          "0"),
            ("路径含 docs/memory/seed_packs",    check_in(out, "docs/memory/seed_packs"), "v3.1 路径"),
        ],
    ))

    # C-04：--format v2 路径
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, "--format", "v2", "--dry-run", timeout=30)
    results.append(CaseResult(
        id="C-04", group="C", name="--format v2 输出路径含 seed_packs/（不含 docs）",
        command=f"mulan seed ingest ... --format v2 --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",              code == 0,                  "0"),
            ("路径含 seed_packs/",           check_in(out, "seed_packs/"), "v2 路径"),
            ("路径不含 docs/memory",         check_not_in(out, "docs/memory/seed_packs"), "非 v3.1 路径"),
        ],
    ))

    # C-05：真实写入，验证 v3.1 目录结构
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, timeout=30)
    seed_dir = _ROOT / "docs" / "memory" / "seed_packs" / CI_NAME
    results.append(CaseResult(
        id="C-05", group="C", name="首次写入生成完整 v3.1 目录结构",
        command=f"mulan seed ingest ... --seed-name {CI_NAME}",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",             code == 0,                           "0"),
            ("meta.yaml 存在",             (seed_dir / "meta.yaml").exists(),   "meta.yaml"),
            ("constraints.yaml 存在",      (seed_dir / "constraints.yaml").exists(), "constraints.yaml"),
            ("memories/ 目录存在",         (seed_dir / "memories").is_dir(),    "memories/"),
            ("memories/ 含 AC-*.md 文件",  len(list((seed_dir / "memories").glob("*.md"))) >= 1
                                           if (seed_dir / "memories").is_dir() else False, "≥1 个 .md"),
            ("输出含 ✅ 种子包已写入",      check_in(out, "✅"),                 "✅"),
        ],
    ))

    # C-06：重复运行（无 --force）→ 跳过，不输出 ✅
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, timeout=30)
    results.append(CaseResult(
        id="C-06", group="C", name="已存在种子包无 --force 时跳过（不覆盖）",
        command=f"mulan seed ingest ... --seed-name {CI_NAME}（第二次）",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",          code == 0,                      "0"),
            ("输出含 ⏭️ 跳过标志",       check_in(out, "⏭️") or
                                         check_in(out, "跳过"),          "⏭️ / 跳过"),
            ("不含 ✅ 就绪标志",          check_not_in(out, "✅"),        "无 ✅"),
        ],
    ))

    # C-07：--force 覆盖写入
    code, out, err = run("seed", "ingest", _PYTEST_RAW,
                         "--seed-name", CI_NAME, "--force", timeout=30)
    results.append(CaseResult(
        id="C-07", group="C", name="--force 覆盖已有种子包",
        command=f"mulan seed ingest ... --seed-name {CI_NAME} --force",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",      code == 0,              "0"),
            ("输出含 ✅ 已写入",     check_in(out, "✅"),    "✅"),
        ],
    ))

    # ── 组 D：内容质量 ────────────────────────────────────────────────────────

    # D-01：保留率 >50%
    code, out, err = run("seed", "ingest", _PYTEST_RAW, "--dry-run",
                         "--seed-name", CI_NAME, timeout=30)
    import re as _re
    retention = 0
    m = _re.search(r'保留\s+(\d+)%', out)
    if not m:
        # 兼容 "保留 88%，" 格式
        m = _re.search(r'(\d+)%', out)
    if m:
        retention = int(m.group(1))
    results.append(CaseResult(
        id="D-01", group="D", name="噪声清洗保留率 >50%（pytest.mdc）",
        command=f"mulan seed ingest '{_PYTEST_RAW}' --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",      code == 0,         "0"),
            ("保留率 >50%",          retention >= 50,   f"实际 {retention}%"),
        ],
    ))

    # D-02：memories/ 含 AC-*.md 且有 frontmatter
    seed_dir = _ROOT / "docs" / "memory" / "seed_packs" / CI_NAME
    md_files = list((seed_dir / "memories").glob("*.md")) if (seed_dir / "memories").is_dir() else []
    first_md_content = md_files[0].read_text(encoding="utf-8") if md_files else ""
    results.append(CaseResult(
        id="D-02", group="D", name="memories/ 含 AC-*.md 且有 YAML frontmatter",
        command="（检查 C-05 写入的文件结构）",
        expected_exit=0, actual_exit=0, stdout=first_md_content[:500], stderr="",
        checks=[
            ("有 .md 文件",           len(md_files) >= 1,             f"{len(md_files)} 个"),
            ("含 frontmatter ---",    check_in(first_md_content, "---"), "---"),
            ("含 id: 字段",           check_in(first_md_content, "id:"), "id:"),
            ("含 tier: 字段",         check_in(first_md_content, "tier:"), "tier:"),
        ],
    ))

    # D-03：LLM pending 模式不崩溃，无错误选项名
    code, out, err = run("seed", "ingest", _PYTEST_RAW, "--dry-run",
                         "--seed-name", CI_NAME, timeout=30)
    results.append(CaseResult(
        id="D-03", group="D", name="LLM 降级不崩溃，输出 fallback/pending 友好提示",
        command=f"mulan seed ingest '{_PYTEST_RAW}' --dry-run（LLM pending 环境）",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",              code == 0,                      "0"),
            ("不含 Traceback",              check_not_in(out + err, "Traceback"), "无崩溃"),
            ("不含 v31-manual 错误选项名",  check_not_in(out, "v31-manual"), "无错误选项"),
            ("LLM 降级状态友好提示",         check_in(out, "Pending") or
                                            check_in(out, "pending") or
                                            check_in(out, "fallback") or
                                            check_in(out, "占位符"),         "pending/fallback 提示"),
        ],
    ))

    # ── 组 E：seed ingest-batch ───────────────────────────────────────────────

    # E-01：不存在仓库 → exit=1
    code, out, err = run("seed", "ingest-batch", _DIR_URL_FAKE, "--dry-run", timeout=20)
    results.append(CaseResult(
        id="E-01", group="E", name="不存在仓库的目录 URL → exit=1 + 友好错误",
        command=f"mulan seed ingest-batch '{_DIR_URL_FAKE}' --dry-run",
        expected_exit=1, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 1",          code == 1,                   "1"),
            ("提示 404",                 check_in(out, "404"),        "404"),
            ("提示 API 地址",            check_in(out, "api.github.com"), "api.github.com"),
            ("不含 Traceback",           check_not_in(out + err, "Traceback"), "无崩溃"),
        ],
    ))

    # E-02：--filter 关键词过滤（使用真实目录）
    code, out, err = run(
        "seed", "ingest-batch", _DIR_URL_REAL,
        "--filter", "pytest,pydantic", "--dry-run", timeout=40,
    )
    results.append(CaseResult(
        id="E-02", group="E", name="--filter 关键词过滤（pytest,pydantic）",
        command=f"mulan seed ingest-batch '{_DIR_URL_REAL}' --filter 'pytest,pydantic' --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",             code == 0,                   "0"),
            ("发现 >100 个规则文件",        check_in(out, "发现") and
                                            any(int(t) > 100 for t in out.split()
                                                if t.isdigit()),         ">100 个文件"),
            ("过滤后剩余 2 个",             check_in(out, "2/"),         "2/xxx"),
            ("处理了 pytest.mdc",           check_in(out, "pytest"),     "pytest"),
            ("处理了 pydantic.mdc",         check_in(out, "pydantic"),   "pydantic"),
        ],
    ))

    # E-03：--prefix 前缀
    code, out, err = run(
        "seed", "ingest-batch", _DIR_URL_REAL,
        "--filter", "fastapi", "--prefix", "ext_", "--dry-run", timeout=40,
    )
    results.append(CaseResult(
        id="E-03", group="E", name="--prefix 前缀拼接到种子包名称",
        command=f"mulan seed ingest-batch '{_DIR_URL_REAL}' --filter fastapi --prefix ext_ --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",          code == 0,              "0"),
            ("包名含 ext_ 前缀",         check_in(out, "ext_"),  "ext_"),
        ],
    ))

    # E-04：多个 raw URL
    code, out, err = run(
        "seed", "ingest-batch", _PYTEST_RAW, _PYDANTIC_RAW, "--dry-run", timeout=40,
    )
    results.append(CaseResult(
        id="E-04", group="E", name="多个 raw URL 逐一处理",
        command="mulan seed ingest-batch <pytest-url> <pydantic-url> --dry-run",
        expected_exit=0, actual_exit=code, stdout=out, stderr=err,
        checks=[
            ("exit code 为 0",            code == 0,                  "0"),
            ("处理 [1/2]",                check_in(out, "[1/2]"),     "[1/2]"),
            ("处理 [2/2]",                check_in(out, "[2/2]"),     "[2/2]"),
            ("批量完成显示 2/2",           check_in(out, "2/2"),       "2/2 成功"),
        ],
    ))

    # E-05：raw URL 不显示 GITHUB_TOKEN 提示；目录 URL 显示
    code_raw, out_raw, _ = run("seed", "ingest-batch", _PYTEST_RAW, "--dry-run", timeout=20)
    code_dir, out_dir, _ = run("seed", "ingest-batch", _DIR_URL_FAKE, "--dry-run", timeout=15)
    results.append(CaseResult(
        id="E-05a", group="E", name="纯 raw URL 时不显示 GITHUB_TOKEN 提示",
        command="mulan seed ingest-batch <raw-url> --dry-run",
        expected_exit=0, actual_exit=code_raw, stdout=out_raw, stderr="",
        checks=[
            ("exit code 为 0",          code_raw == 0,                    "0"),
            ("无 GITHUB_TOKEN 提示",    check_not_in(out_raw, "GITHUB_TOKEN"), "无 Token 提示"),
        ],
    ))
    results.append(CaseResult(
        id="E-05b", group="E", name="目录 URL 时显示 GITHUB_TOKEN 提示",
        command="mulan seed ingest-batch <dir-url> --dry-run",
        expected_exit=1, actual_exit=code_dir, stdout=out_dir, stderr="",
        checks=[
            ("exit code 为 1（404）",    code_dir == 1,                   "1"),
            ("有 GITHUB_TOKEN 提示",     check_in(out_dir, "GITHUB_TOKEN"), "Token 提示"),
        ],
    ))

    # 清理测试产物
    _cleanup_test_seeds()

    return results


# ══════════════════════════════════════════════════════════════════════════════
# 报告生成
# ══════════════════════════════════════════════════════════════════════════════

def _render_markdown(results: List[CaseResult], elapsed_s: float) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    passed = sum(1 for r in results if r.passed)
    total = len(results)

    lines = [
        f"# mulan seed ingest 集成测试报告",
        f"",
        f"> 生成时间：{now}  |  耗时：{elapsed_s:.1f}s  "
        f"|  结果：**{passed}/{total} 通过**",
        f"",
        f"## 汇总",
        f"",
        f"| ID | 组 | 测试名称 | 结果 |",
        f"|----|----|----------|------|",
    ]
    for r in results:
        icon = "✅ PASS" if r.passed else "❌ FAIL"
        lines.append(f"| {r.id} | {r.group} | {r.name} | {icon} |")

    lines += ["", "---", "", "## 详细结果", ""]

    for r in results:
        icon = "✅ PASS" if r.passed else "❌ FAIL"
        lines += [
            f"### {icon} {r.id}：{r.name}",
            f"",
            f"**命令**",
            f"```",
            r.command,
            f"```",
            f"",
            f"**期望 exit code**：`{r.expected_exit}`　**实际 exit code**：`{r.actual_exit}`",
            f"",
            f"**检查项**",
            f"",
            f"| 描述 | 结果 | 期望值 |",
            f"|------|------|--------|",
        ]
        for desc, ok, expected in r.checks:
            check_icon = "✅" if ok else "❌"
            lines.append(f"| {desc} | {check_icon} | `{expected}` |")

        if r.stdout.strip():
            preview = r.stdout.strip()[:800]
            if len(r.stdout.strip()) > 800:
                preview += "\n... (截断)"
            lines += [
                f"",
                f"**实际输出（前 800 字符）**",
                f"```",
                preview,
                f"```",
            ]
        if r.stderr.strip():
            lines += [
                f"",
                f"**stderr**",
                f"```",
                r.stderr.strip()[:300],
                f"```",
            ]
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import time
    print("=" * 60)
    print("  mulan seed ingest 集成测试（真实 CLI 调用）")
    print("=" * 60)

    t0 = time.perf_counter()
    results = run_all_cases()
    elapsed = time.perf_counter() - t0

    passed = sum(1 for r in results if r.passed)
    total = len(results)

    # 控制台汇总
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

    # 写入 Markdown 报告
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _RESULTS_DIR / f"seed_ingest_{ts}.md"
    report_path.write_text(_render_markdown(results, elapsed), encoding="utf-8")
    print(f"  报告：{report_path.relative_to(_ROOT)}")
    print()

    return 0 if passed == total else 1


# ── pytest 兼容入口 ───────────────────────────────────────────────────────────
# 当通过 pytest 调用时，将每个 CaseResult 转为独立的 pytest 测试函数

import pytest  # noqa: E402（在文件末尾 import 避免影响直接运行）

_cached_results: List[CaseResult] = []


@pytest.fixture(scope="module", autouse=True)
def _run_and_cache():
    """模块级 fixture：运行所有用例并缓存结果（避免重复 CLI 调用）。"""
    global _cached_results
    if not _cached_results:
        _cached_results = run_all_cases()


def _get_result(cid: str) -> CaseResult:
    for r in _cached_results:
        if r.id == cid:
            return r
    pytest.skip(f"未找到用例 {cid}，可能尚未运行")


# 自动为每个用例生成 pytest 测试函数
def _make_pytest_test(case_id: str):
    def _test(self):
        r = _get_result(case_id)
        failures = [f"{desc}（期望 {exp}）" for desc, ok, exp in r.checks if not ok]
        if r.actual_exit != r.expected_exit:
            failures.insert(0, f"exit code {r.actual_exit} ≠ {r.expected_exit}")
        assert not failures, "\n".join(failures)
    _test.__name__ = f"test_{case_id.lower().replace('-', '_')}"
    _test.__doc__ = ""
    return _test


class TestSeedIngestIntegration:
    """集成测试类：每个方法对应一个 CaseResult。"""


_ALL_IDS = [
    "A-01", "A-02", "A-03",
    "B-01", "B-02", "B-03", "B-04", "B-05", "B-06",
    "C-01", "C-02", "C-03", "C-04", "C-05", "C-06", "C-07",
    "D-01", "D-02", "D-03",
    "E-01", "E-02", "E-03", "E-04", "E-05a", "E-05b",
]

for _cid in _ALL_IDS:
    setattr(TestSeedIngestIntegration, f"test_{_cid.lower().replace('-', '_')}", _make_pytest_test(_cid))


if __name__ == "__main__":
    sys.exit(main())
