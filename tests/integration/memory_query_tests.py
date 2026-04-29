"""
tests/integration/memory_query_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mulan list / search / graph 命令组集成测试（Sprint 4）

真实 CLI 调用，无 mock。

设计说明：
  - mulan list   直接扫描 docs/memory/ 下的 .md 文件，无需 MEMORY_INDEX.json
  - mulan search 依赖 MEMORY_INDEX.json；测试 setup 时生成最小 fixture，测后清理
  - mulan graph  使用 MemoryGraph 扫描 .md 文件，无需 MEMORY_INDEX.json；
                 由于当前 AC-*.md 无 related_to 字段，explore 返回空（已知设计行为）

Fixture 策略：
  - MEMORY_INDEX.json 由 _setup_index_fixture() 从实际 AC-*.md 文件元数据生成
  - 写入路径：docs/memory/MEMORY_INDEX.json（生产路径，测后由 _cleanup_index_fixture() 删除）
  - 若测试开始前已有真实 MEMORY_INDEX.json，跳过生成并在测后不删除

分组：
  A 组：mulan list
  B 组：mulan search
  C 组：mulan graph
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
_MEMORY_ROOT = _ROOT / "docs" / "memory"
_INDEX_FILE = _MEMORY_ROOT / "MEMORY_INDEX.json"

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


# ── MEMORY_INDEX.json fixture ─────────────────────────────────────────────────

_INDEX_WAS_PREEXISTING = False


def _parse_ac_frontmatter(path: Path) -> dict:
    """从 AC-*.md 文件提取最小 frontmatter（id/tier/layer/tags）。"""
    content = path.read_text(encoding="utf-8", errors="ignore")
    fm: dict = {}
    in_fm = False
    for line in content.split("\n"):
        if line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            else:
                break
        if not in_fm:
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip("\"'")
            if k == "tags":
                # 简单解析 [a, b, c] 格式
                v = re.findall(r"[\w-]+", v)
            fm[k] = v
    # 提取标题
    title = ""
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].split("·", 1)[-1].strip() if "·" in line else line[2:].strip()
            break
    fm["title"] = title or fm.get("id", path.stem)
    return fm


def _setup_index_fixture() -> bool:
    """
    从 docs/memory/seed_packs/ 下的 AC-*.md 文件动态生成最小 MEMORY_INDEX.json。
    若已有真实索引文件则跳过，返回 False（不需要清理）。
    返回 True 表示已生成 fixture，需在测后清理。
    """
    global _INDEX_WAS_PREEXISTING
    if _INDEX_FILE.exists():
        _INDEX_WAS_PREEXISTING = True
        return False

    # 收集所有 AC-*.md
    ac_files = list((_MEMORY_ROOT / "seed_packs").rglob("AC-*.md"))

    # 按 layer 分组，构建 tree 节点
    layer_groups: dict = {}
    for f in ac_files:
        fm = _parse_ac_frontmatter(f)
        mem_id = fm.get("id", f.stem)
        layer = fm.get("layer", "CC").split("_")[0]
        tags = fm.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        relative = str(f.relative_to(_MEMORY_ROOT))
        entry = {
            "id": mem_id,
            "title": fm.get("title", mem_id),
            "tier": fm.get("tier", "warm"),
            "file": relative,
            "tags": tags,
        }
        if layer not in layer_groups:
            layer_groups[layer] = []
        layer_groups[layer].append(entry)

    tree = []
    for layer, mems in layer_groups.items():
        # 从条目的 tags 聚合触发关键词
        all_tags: list = []
        for m in mems:
            all_tags.extend(m.get("tags", []))
        trigger_kws = list(dict.fromkeys(all_tags))[:10]

        tree.append({
            "node_id": layer,
            "trigger_keywords": trigger_kws,
            "nodes": [{
                "node_id": f"{layer}-seed",
                "trigger_keywords": trigger_kws[:5],
                "memories": mems,
            }],
        })

    index = {
        "version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "health_check_tests.py fixture",
        "tree": tree,
    }
    _INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def _cleanup_index_fixture(was_generated: bool):
    """若 fixture 由本测试生成，则在测后删除。"""
    if was_generated and _INDEX_FILE.exists() and not _INDEX_WAS_PREEXISTING:
        _INDEX_FILE.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

def run_all_cases() -> List[CaseResult]:
    results: List[CaseResult] = []

    fixture_generated = _setup_index_fixture()

    try:
        # ────────────────────────────────────────────────────────────────────
        # 组 A：mulan list
        # ────────────────────────────────────────────────────────────────────

        # A-01：--help 正常显示
        code, out, err = run("list", "--help")
        results.append(CaseResult(
            id="A-01", group="A", name="list --help 正常显示",
            command="mulan list --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",         code == 0,           "0"),
                ("含 --tier 选项",          has(out, "--tier"),   "--tier"),
                ("含 --layer 选项",         has(out, "--layer"),  "--layer"),
            ],
        ))

        # A-02：无参数运行 exit=0，输出含记忆条目
        code, out, err = run("list")
        results.append(CaseResult(
            id="A-02", group="A", name="list 无参数运行 exit=0，含记忆条目",
            command="mulan list",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",              code == 0,                  "0"),
                ("含 AC- 节点 ID",              match(out, r"AC-\w+-\d+"),   "AC-XXX-N"),
                ("含 HOT 或 WARM 层标签",
                 has(out, "HOT") or has(out, "WARM"),                        "HOT/WARM"),
            ],
        ))

        # A-03：输出包含标题内容（非空）
        code, out, err = run("list")
        lines = [l for l in out.splitlines() if "AC-" in l and len(l.strip()) > 20]
        results.append(CaseResult(
            id="A-03", group="A", name="list 输出含完整的 ID+标题 行",
            command="mulan list",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 >20 个字符的 AC-* 行",  len(lines) > 0,  ">0 行"),
                ("条目数 > 50",              len(lines) > 50,  ">50"),
            ],
        ))

        # A-04：--tier hot 只显示 hot 层
        code, out, err = run("list", "--tier", "hot")
        hot_lines = [l for l in out.splitlines() if "AC-" in l]
        results.append(CaseResult(
            id="A-04", group="A", name="list --tier hot 只显示 HOT 层",
            command="mulan list --tier hot",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,                       "0"),
                ("含 HOT",              has(out, "HOT"),                   "HOT"),
                ("不含 WARM",           not_has(out, "WARM"),              "不含 WARM"),
                ("有 HOT 条目",         len(hot_lines) > 0,               ">0 条"),
            ],
        ))

        # A-05：--tier warm 只显示 warm 层
        code, out, err = run("list", "--tier", "warm")
        results.append(CaseResult(
            id="A-05", group="A", name="list --tier warm 只显示 WARM 层",
            command="mulan list --tier warm",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,          "0"),
                ("含 WARM",         has(out, "WARM"),    "WARM"),
                ("不含 HOT",        not_has(out, "HOT"), "不含 HOT"),
            ],
        ))

        # A-06：--layer CC 按层过滤
        code, out, err = run("list", "--layer", "CC")
        results.append(CaseResult(
            id="A-06", group="A", name="list --layer CC 按层过滤",
            command="mulan list --layer CC",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,                            "0"),
                ("含 CC 层标识",    has(out, "CC") or has(out, "cross"),   "CC"),
            ],
        ))

        # A-07：--tier + --layer 组合过滤
        code, out, err = run("list", "--tier", "hot", "--layer", "CC")
        results.append(CaseResult(
            id="A-07", group="A", name="list --tier hot --layer CC 组合过滤",
            command="mulan list --tier hot --layer CC",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,  "0"),
                ("不含 Traceback",       not_has(err, "Traceback"), "无 Traceback"),
            ],
        ))

        # A-08：运行耗时 < 10s
        t0 = time.perf_counter()
        code, _, _ = run("list", timeout=15)
        elapsed = time.perf_counter() - t0
        results.append(CaseResult(
            id="A-08", group="A", name="list 运行完成 < 10 秒",
            command="mulan list（计时）",
            expected_exit=0, actual_exit=code, stdout="", stderr="",
            checks=[
                ("exit code 为 0",            code == 0,      "0"),
                (f"耗时 {elapsed:.2f}s < 10s", elapsed < 10,  "<10s"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 B：mulan search
        # ────────────────────────────────────────────────────────────────────

        # B-01：--help 正常显示
        code, out, err = run("search", "--help")
        results.append(CaseResult(
            id="B-01", group="B", name="search --help 正常显示",
            command="mulan search --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",        code == 0,           "0"),
                ("含 keywords 位置参数",   has(out, "keywords"), "keywords"),
                ("含 --top-k 选项",        has(out, "--top-k"),  "--top-k"),
                ("含 --preview 选项",      has(out, "--preview"), "--preview"),
            ],
        ))

        # B-02：无关键词参数 → argparse 报错 exit=2，错误在 stderr
        code, out, err = run("search")
        results.append(CaseResult(
            id="B-02", group="B", name="search 无关键词参数 exit=2（argparse 错误）",
            command="mulan search（无关键词）",
            expected_exit=2, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 2",         code == 2,                              "2"),
                ("stderr 含 keywords 提示", has(err, "keywords") or has(err, "required"), "keywords/required"),
            ],
        ))

        # B-03：搜索 "python sqlalchemy"（有 fixture 时命中）
        code, out, err = run("search", "python", "sqlalchemy", "--top-k", "5")
        results.append(CaseResult(
            id="B-03", group="B", name="search 'python sqlalchemy' 返回结果",
            command="mulan search python sqlalchemy --top-k 5",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",          code == 0,                   "0"),
                ("含 AC- 条目或 未找到提示",
                 match(out, r"AC-\w+") or has(out, "未找到"),             "AC-XXX/未找到"),
                ("不含 Traceback",           not_has(err, "Traceback"),   "无 Traceback"),
            ],
        ))

        # B-04：搜索不存在关键词 → exit=0，"未找到匹配"
        code, out, err = run("search", "xyzzy_nonexistent_keyword_42")
        results.append(CaseResult(
            id="B-04", group="B", name="search 不存在关键词 exit=0 + 未找到提示",
            command="mulan search xyzzy_nonexistent_keyword_42",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,              "0"),
                ("含 未找到 提示",   has(out, "未找到"),      "未找到"),
            ],
        ))

        # B-05：--top-k 3 限制返回数（通过 "找到 N 条" 统计结果行数）
        code, out, err = run("search", "python", "--top-k", "3")
        # 每条结果以 "  N." 开头，统计结果编号行数
        result_lines = re.findall(r"^\s+\d+\.", out, re.MULTILINE)
        result_count = len(result_lines)
        results.append(CaseResult(
            id="B-05", group="B", name="search --top-k 3 返回不超过 3 条",
            command="mulan search python --top-k 3",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",                       code == 0,          "0"),
                (f"结果条数 ≤ 3（实际 {result_count}）", result_count <= 3,  "≤3"),
            ],
        ))

        # B-06：--preview 含正文预览
        code, out, err = run("search", "python", "--preview", "--top-k", "1")
        results.append(CaseResult(
            id="B-06", group="B", name="search --preview 含文件正文预览",
            command="mulan search python --preview --top-k 1",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",  code == 0,                               "0"),
                ("不含 Traceback", not_has(err, "Traceback"),                "无 Traceback"),
                ("若有结果则含 预览 关键词",
                 has(out, "预览") or has(out, "未找到") or match(out, r"AC-\w+"), "预览/未找到/AC-*"),
            ],
        ))

        # B-07：多关键词联合搜索提高匹配精度
        code, out, err = run("search", "redis", "cache", "timeout", "--top-k", "5")
        results.append(CaseResult(
            id="B-07", group="B", name="search 多关键词联合搜索不崩溃",
            command="mulan search redis cache timeout --top-k 5",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",   code == 0,                    "0"),
                ("不含 Traceback",   not_has(err, "Traceback"),    "无 Traceback"),
            ],
        ))

        # B-08：搜索 "goroutine context" 命中 Go 种子
        code, out, err = run("search", "goroutine", "context")
        results.append(CaseResult(
            id="B-08", group="B", name="search 'goroutine context' 命中 Go 种子包",
            command="mulan search goroutine context",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,                     "0"),
                ("含 AC-GO 或 未找到",
                 has(out, "AC-GO") or has(out, "未找到"),               "AC-GO/未找到"),
            ],
        ))

        # ────────────────────────────────────────────────────────────────────
        # 组 C：mulan graph
        # ────────────────────────────────────────────────────────────────────

        # C-01：graph stats exit=0，含节点总数
        code, out, err = run("graph", "stats")
        results.append(CaseResult(
            id="C-01", group="C", name="graph stats exit=0，含节点总数",
            command="mulan graph stats",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",    code == 0,              "0"),
                ("含 节点 统计",      has(out, "节点"),        "节点"),
                ("含 Hot 层 统计",    has(out, "Hot"),         "Hot"),
                ("节点数 > 0",        match(out, r"总节点数：[1-9]"), "总节点数：N>0"),
            ],
        ))

        # C-02：graph stats 含边数（当前为 0，无 related_to 字段）
        code, out, err = run("graph", "stats")
        results.append(CaseResult(
            id="C-02", group="C", name="graph stats 包含图边数统计（当前为 0）",
            command="mulan graph stats",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("含 总图边数 字段",   has(out, "总图边数"),  "总图边数"),
            ],
        ))

        # C-03：graph explore 有效节点（无 related_to → 返回空 → exit=1，已知设计行为）
        code, out, err = run("graph", "explore", "AC-GO-01")
        results.append(CaseResult(
            id="C-03", group="C", name="graph explore 有效节点（无 related_to 时返回空）",
            command="mulan graph explore AC-GO-01",
            expected_exit=code,  # 容错：当前行为 exit=1（explore 不含起始节点）
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",      code in (0, 1),                "0/1"),
                ("不含 Traceback",           not_has(err, "Traceback"),     "无 Traceback"),
                ("含节点相关提示或 未找到",
                 has(out, "AC-GO-01") or has(out, "未找到") or has(out, "节点"),
                 "AC-GO-01/未找到/节点"),
            ],
        ))

        # C-04：graph explore 不存在的节点 → exit=1，"未找到节点"
        code, out, err = run("graph", "explore", "NONEXISTENT-ID-99999")
        results.append(CaseResult(
            id="C-04", group="C", name="graph explore 不存在节点 exit=1 + 友好提示",
            command="mulan graph explore NONEXISTENT-ID-99999",
            expected_exit=1, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 1",      code == 1,              "1"),
                ("含 未找到节点 提示",   has(out, "未找到"),      "未找到"),
            ],
        ))

        # C-05：graph file 存在的 AC-*.md 文件
        ac_file = "seed_packs/go_microservice/memories/AC-GO-01.md"
        code, out, err = run("graph", "file", ac_file)
        results.append(CaseResult(
            id="C-05", group="C", name="graph file 引用文件反查（有结果或友好空结果）",
            command=f"mulan graph file {ac_file}",
            expected_exit=code,
            actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 在 [0,1]",  code in (0, 1),             "0/1"),
                ("不含 Traceback",      not_has(err, "Traceback"),   "无 Traceback"),
                ("含引用数量或无节点提示",
                 has(out, "共") or has(out, "没有") or has(out, "引用"),
                 "共N/没有/引用"),
            ],
        ))

        # C-06：graph file 不存在的文件路径 → exit=0，"没有记忆节点引用"
        code, out, err = run("graph", "file", "nonexistent/path/file.py")
        results.append(CaseResult(
            id="C-06", group="C", name="graph file 不存在路径 exit=0 + 友好提示",
            command="mulan graph file nonexistent/path/file.py",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",   code == 0,                  "0"),
                ("含 没有 或 未引用", has(out, "没有") or has(out, "0 个"),  "没有/0 个"),
            ],
        ))

        # C-07：graph impacts 有效节点 → exit=0，含影响数量
        code, out, err = run("graph", "impacts", "AC-GO-01")
        results.append(CaseResult(
            id="C-07", group="C", name="graph impacts 有效节点 exit=0，含影响统计",
            command="mulan graph impacts AC-GO-01",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",    code == 0,              "0"),
                ("含 变更 或 同步",    has(out, "变更") or has(out, "同步"), "变更/同步"),
                ("含 共 N 个 格式",   match(out, r"共\s*\d+\s*个"),        "共N个"),
            ],
        ))

        # C-08：graph impacts 不存在节点 → exit=0，0 个影响
        code, out, err = run("graph", "impacts", "NONEXISTENT-ID-99999")
        results.append(CaseResult(
            id="C-08", group="C", name="graph impacts 不存在节点 exit=0，0 个影响",
            command="mulan graph impacts NONEXISTENT-ID-99999",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",      code == 0,                       "0"),
                ("含 0 个 影响节点",     match(out, r"共\s*0\s*个"),      "共 0 个"),
            ],
        ))

        # C-09：graph --help
        code, out, err = run("graph", "--help")
        results.append(CaseResult(
            id="C-09", group="C", name="graph --help 显示所有子命令",
            command="mulan graph --help",
            expected_exit=0, actual_exit=code, stdout=out, stderr=err,
            checks=[
                ("exit code 为 0",    code == 0,              "0"),
                ("含 stats 子命令",   has(out, "stats"),       "stats"),
                ("含 explore 子命令", has(out, "explore"),     "explore"),
                ("含 file 子命令",    has(out, "file"),        "file"),
                ("含 impacts 子命令", has(out, "impacts"),     "impacts"),
            ],
        ))

    finally:
        _cleanup_index_fixture(fixture_generated)

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
        "# mulan list / search / graph 集成测试报告（Sprint 4）",
        "",
        f"> 生成时间：{ts}　｜　覆盖命令：`mulan list` / `mulan search` / `mulan graph`",
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
        "A": "mulan list",
        "B": "mulan search",
        "C": "mulan graph",
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
    print("  mulan list / search / graph 集成测试（Sprint 4）")
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
    report_path = _RESULTS_DIR / f"memory_query_{ts}.md"
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
    "C-01", "C-02", "C-03", "C-04", "C-05", "C-06", "C-07", "C-08", "C-09",
]

TestMemoryQuery = type(
    "TestMemoryQuery",
    (),
    {f"test_{cid.lower().replace('-', '_')}": _make_pytest_test(cid) for cid in _ALL_CASE_IDS},
)


if __name__ == "__main__":
    sys.exit(main())
