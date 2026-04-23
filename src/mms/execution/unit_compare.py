#!/usr/bin/env python3
"""
unit_compare.py — EP-120 双模型代码对比工具

功能：
  1. compare(ep_id, unit_id)
     读取 qwen.txt 和 sonnet.txt，生成机械 diff 报告 report.md，
     并运行 arch_check / pytest 摘要（不写业务文件）。
     完成后自动调用 qwen3-32b 进行语义评审，写入 report.md 末尾。

  2. apply(ep_id, unit_id, source)
     将 qwen 或 sonnet 的 ===BEGIN-CHANGES=== 格式输出应用到业务文件，
     提交 git commit，并标记 DAG Unit 为 done。

存储结构（对应 --save-output + sonnet-save）：
    docs/memory/private/compare/<EP-ID>/<UNIT-ID>/
        context.md   — 发送给双模型的上下文（由 mms unit run --save-output 生成）
        qwen.txt     — qwen 原始输出（===BEGIN-CHANGES=== 格式）
        sonnet.txt   — Cursor Sonnet 输出（同格式，由 mms unit sonnet-save 写入）
        report.md    — 机械 diff + qwen3-32b 语义评审报告（由 compare() 生成）

用法：
    from mms.execution.unit_compare import compare, apply, save_sonnet_output
    compare("EP-120", "U1")   # 生成 report.md（含 qwen3-32b 评审）
    apply("EP-120", "U1", source="qwen")   # 应用 qwen 版本
"""

from __future__ import annotations

import difflib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_COMPARE_ROOT = _ROOT / "docs" / "memory" / "private" / "compare"

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

try:
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except ImportError:
    try:
        from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
    except ImportError:
        _cfg = None  # type: ignore[assignment]

# fallback: config.yaml → runner.timeout.arch_check_seconds (default=30)
ARCH_CHECK_TIMEOUT = int(getattr(_cfg, "runner_timeout_arch_check", 30)) if _cfg else 30
# fallback: config.yaml → runner.timeout.test_seconds (default=120)
TEST_TIMEOUT = int(getattr(_cfg, "runner_timeout_test", 120)) if _cfg else 120


# ── 辅助：读取对比目录 ────────────────────────────────────────────────────────

def _compare_dir(ep_id: str, unit_id: str) -> Path:
    return _COMPARE_ROOT / ep_id.upper() / unit_id.upper()


def _read_file(path: Path) -> Optional[str]:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


# ── sonnet-save：保存 Cursor Sonnet 输出 ─────────────────────────────────────

def _sanitize_unicode(text: str) -> str:
    """过滤 UTF-16 代理字符（surrogates），防止 UnicodeEncodeError。"""
    return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def save_sonnet_output(ep_id: str, unit_id: str, content: str) -> str:
    """
    将 Cursor Sonnet 生成的 ===BEGIN-CHANGES=== 格式内容写入 sonnet.txt。

    Args:
        ep_id:    EP 编号（如 "EP-120"）
        unit_id:  Unit ID（如 "U1"）
        content:  Sonnet 输出的原始文本（应包含 ===BEGIN-CHANGES=== 块）

    Returns:
        sonnet.txt 的绝对路径字符串

    Raises:
        SystemExit: 如果内容不含 ===BEGIN-CHANGES=== 且用户拒绝强制保存
    """
    # 过滤代理字符，防止 UnicodeEncodeError（emoji 等特殊字符的非法编码）
    content = _sanitize_unicode(content)

    d = _compare_dir(ep_id, unit_id)
    d.mkdir(parents=True, exist_ok=True)

    # 格式预检：内容必须包含 ===BEGIN-CHANGES=== 块
    if "===BEGIN-CHANGES===" not in content:
        print(f"\n  {_Y}⚠️  输入内容中未检测到 ===BEGIN-CHANGES=== 格式块{_X}")
        print(f"  {_D}  这通常意味着 Sonnet 输出的是解释性文字而非代码变更块。{_X}")
        print(f"  {_D}  请确认 context.md 末尾的「输出格式要求」已发送给 Sonnet。{_X}")
        try:
            ans = input(f"\n  → 仍然强制保存（无格式的内容将导致 compare 失败）？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            print(f"  {_R}❌{_X} 已取消保存，请重新从 Sonnet 获取正确格式的输出")
            raise SystemExit(1)
        print(f"  {_Y}⚠️  强制保存（无有效格式块），compare 阶段将报 ⚠️ 警告{_X}")

    header = (
        f"# sonnet 输出 — {ep_id.upper()} {unit_id.upper()}\n"
        f"# 生成时间：{datetime.now(timezone.utc).isoformat()}\n\n"
    )
    sonnet_path = d / "sonnet.txt"
    sonnet_path.write_text(header + content, encoding="utf-8")
    return str(sonnet_path)


# ── 解析 ===BEGIN-CHANGES=== 块 ──────────────────────────────────────────────

def _parse_changes_from_text(text: str) -> List[Tuple[str, str, str]]:
    """
    从文本中解析所有文件变更块。
    返回 [(path, action, content), ...]
    """
    results: List[Tuple[str, str, str]] = []
    if "===BEGIN-CHANGES===" not in text:
        return results

    start = text.find("===BEGIN-CHANGES===")
    end = text.find("===END-CHANGES===", start)
    if end == -1:
        block = text[start + len("===BEGIN-CHANGES==="):]
    else:
        block = text[start + len("===BEGIN-CHANGES==="):end]

    parts = block.split("===END-FILE===")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        file_path = ""
        action = "replace"
        content_lines: List[str] = []
        in_content = False

        for line in lines:
            if line.startswith("FILE:"):
                file_path = line[5:].strip()
            elif line.startswith("ACTION:"):
                action = line[7:].strip().lower()
            elif line.startswith("CONTENT:"):
                in_content = True
            elif in_content:
                content_lines.append(line)

        if file_path:
            results.append((file_path, action, "\n".join(content_lines)))

    return results


# ── 机械 diff 生成 ────────────────────────────────────────────────────────────

def _file_diff(qwen_content: str, sonnet_content: str, file_path: str) -> str:
    """生成单文件 unified diff（最多 80 行）"""
    qwen_lines = qwen_content.splitlines(keepends=True)
    sonnet_lines = sonnet_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        qwen_lines, sonnet_lines,
        fromfile=f"qwen/{file_path}",
        tofile=f"sonnet/{file_path}",
        lineterm="",
    ))
    if not diff:
        return "（两版本内容相同，无 diff）"

    MAX_LINES = 80
    if len(diff) > MAX_LINES:
        shown = diff[:MAX_LINES]
        shown.append(f"\n... 省略 {len(diff) - MAX_LINES} 行（共 {len(diff)} 行 diff）...\n")
        return "".join(shown)
    return "".join(diff)


def _count_changes(content: str) -> Tuple[int, int]:
    """统计 diff 中的增减行数"""
    added = sum(1 for l in content.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in content.splitlines() if l.startswith("-") and not l.startswith("---"))
    return added, removed


# ── arch_check / pytest 摘要（只读，不写文件）────────────────────────────────

def _run_arch_check_summary() -> Tuple[bool, str]:
    arch_check = _HERE / "mms.analysis.arch_check.py"
    if not arch_check.exists():
        return True, "mms.analysis.arch_check.py 不存在，跳过"
    try:
        r = subprocess.run(
            [sys.executable, str(arch_check)],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=ARCH_CHECK_TIMEOUT,
        )
        passed = r.returncode == 0
        lines = (r.stdout + r.stderr).strip().splitlines()
        summary = lines[-1] if lines else f"exit {r.returncode}"
        return passed, summary
    except subprocess.TimeoutExpired:
        return False, f"arch_check 超时（{ARCH_CHECK_TIMEOUT}s）"
    except Exception as e:
        return True, f"arch_check 异常（已跳过）：{e}"


def _run_test_summary(test_files: List[str]) -> Tuple[bool, str]:
    existing = [f for f in test_files if (_ROOT / f).exists()]
    if not existing:
        return True, "无测试文件，跳过"
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", *existing, "-q", "--tb=no", "--no-header"],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=TEST_TIMEOUT,
        )
        output = r.stdout + r.stderr
        summary = ""
        for line in output.splitlines():
            if "passed" in line or "failed" in line or "error" in line:
                summary = line.strip()
                break
        return r.returncode == 0, summary or f"exit {r.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（{TEST_TIMEOUT}s）"
    except Exception as e:
        return False, f"pytest 异常：{e}"


# ── 核心：compare() — 生成 report.md ─────────────────────────────────────────

def compare(ep_id: str, unit_id: str) -> int:
    """
    读取 qwen.txt 和 sonnet.txt，生成机械 diff 报告 report.md。

    Returns:
        0 = 成功生成报告，1 = 失败（缺少文件等）
    """
    ep_id = ep_id.upper()
    unit_id = unit_id.upper()
    d = _compare_dir(ep_id, unit_id)

    print(f"\n{_B}MMS Unit Compare · {ep_id} {unit_id}{_X}")
    print("─" * 60)

    qwen_raw = _read_file(d / "qwen.txt")
    sonnet_raw = _read_file(d / "sonnet.txt")

    if qwen_raw is None:
        print(f"  {_R}❌{_X} 未找到 qwen.txt，请先运行：mms unit run --ep {ep_id} --unit {unit_id} --save-output")
        return 1
    if sonnet_raw is None:
        print(f"  {_R}❌{_X} 未找到 sonnet.txt，请先让 Cursor Sonnet 生成代码并运行：mms unit sonnet-save --ep {ep_id} --unit {unit_id}")
        return 1

    qwen_changes = _parse_changes_from_text(qwen_raw)
    sonnet_changes = _parse_changes_from_text(sonnet_raw)

    if not qwen_changes:
        print(f"  {_Y}⚠️  qwen.txt 中未解析到有效的 ===BEGIN-CHANGES=== 块{_X}")
    if not sonnet_changes:
        print(f"  {_Y}⚠️  sonnet.txt 中未解析到有效的 ===BEGIN-CHANGES=== 块{_X}")

    # 汇总所有涉及文件
    qwen_file_map = {path: (action, content) for path, action, content in qwen_changes}
    sonnet_file_map = {path: (action, content) for path, action, content in sonnet_changes}
    all_files = sorted(set(list(qwen_file_map.keys()) + list(sonnet_file_map.keys())))

    # ── 运行验证 ──────────────────────────────────────────────────────────────
    print(f"\n{_C}▶ 运行 arch_check（基线）{_X}")
    arch_ok, arch_summary = _run_arch_check_summary()
    arch_icon = _G + "✅" + _X if arch_ok else _R + "❌" + _X
    print(f"  {arch_icon} {arch_summary}")

    test_files = [p for p in all_files if "test" in p]
    test_ok, test_summary = _run_test_summary(test_files)
    test_icon = _G + "✅" + _X if test_ok else _Y + "⚠️ " + _X
    print(f"  {test_icon} pytest（仅测试文件）：{test_summary}")

    # ── 生成 report.md ────────────────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    report_lines = [
        f"# 双模型对比报告 — {ep_id} {unit_id}",
        f"\n生成时间：{now}",
        f"\n---\n",
        "## 自动化检查摘要",
        f"\n| 检查项 | 状态 | 说明 |",
        "| ------ | ---- | ---- |",
        f"| arch_check | {'✅ 通过' if arch_ok else '❌ 失败'} | {arch_summary} |",
        f"| pytest     | {'✅ 通过' if test_ok else '⚠️ 警告'} | {test_summary} |",
        "\n---\n",
        "## 文件变更对比",
    ]

    total_added = 0
    total_removed = 0

    for fpath in all_files:
        qwen_action, qwen_content = qwen_file_map.get(fpath, ("—", ""))
        sonnet_action, sonnet_content = sonnet_file_map.get(fpath, ("—", ""))

        diff_text = _file_diff(qwen_content, sonnet_content, fpath)
        added, removed = _count_changes(diff_text)
        total_added += added
        total_removed += removed

        report_lines += [
            f"\n### `{fpath}`",
            f"\n| 版本   | action  | 行数 |",
            "| ------ | ------- | ---- |",
            f"| qwen   | {qwen_action}  | {len(qwen_content.splitlines())} |",
            f"| sonnet | {sonnet_action} | {len(sonnet_content.splitlines())} |",
            f"\n**diff（+{added} / -{removed}）：**",
            "\n```diff",
            diff_text,
            "```",
        ]

    report_lines += [
        "\n---\n",
        f"## 总计差异：+{total_added} / -{total_removed}",
        "\n---\n",
        "## 语义评审（LLM 自动生成）",
        "\n> 由 code_review 模型自动生成（当前路由：bailian_plus/qwen3-32b，可通过 MMS_TASK_MODEL_OVERRIDE 切换）。如需人工复核，可在 Cursor 对话中读取此报告。",
        "\n_（评审中...）_",
    ]

    report_path = d / "report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    # ── LLM 语义评审（EP-132：自动路由，默认 qwen3-32b）─────────────────────────
    print(f"\n{_C}▶ 调用 LLM 进行语义评审（code_review → bailian_plus）…{_X}")
    review_result = _run_qwen_review(
        ep_id=ep_id,
        unit_id=unit_id,
        report_so_far="\n".join(report_lines),
        qwen_raw=qwen_raw,
        sonnet_raw=sonnet_raw,
    )

    # 将评审结果追加到 report.md
    apply_section = [
        "\n---\n",
        "## 应用版本",
        "\n执行以下命令应用选定版本：",
        "\n```bash",
        f"# 应用 qwen 版本",
        f"mms unit compare --apply qwen --ep {ep_id} --unit {unit_id}",
        f"# 应用 sonnet 版本",
        f"mms unit compare --apply sonnet --ep {ep_id} --unit {unit_id}",
        "```",
    ]

    # 替换占位符，写入最终报告
    final_lines = [
        l for l in report_lines if l != "\n_（评审中...）_"
    ] + [f"\n{review_result}"] + apply_section
    report_path.write_text("\n".join(final_lines), encoding="utf-8")

    print(f"\n  {_G}✅{_X} 报告已生成：{report_path}")
    print(f"  {_D}总计差异：+{total_added} / -{total_removed} 行，涉及 {len(all_files)} 个文件{_X}")
    if "评审失败" in review_result or "不可用" in review_result:
        print(f"  {_Y}⚠️  qwen3-32b 评审未完成，请在 Cursor 对话中手动读取 report.md{_X}")
    else:
        print(f"  {_G}✅{_X} qwen3-32b 语义评审已完成，建议已写入 report.md")
    return 0


# ── qwen3-32b 语义评审实现 ──────────────────────────────────────────────────────

_REVIEW_PROMPT_TEMPLATE = """你是 MDP 平台的高级代码审查员。请对以下两个模型生成的代码版本进行语义评审。

## 任务背景
EP: {ep_id}  Unit: {unit_id}

## 机械 Diff 报告摘要
{diff_summary}

## qwen 完整输出
{qwen_raw}

## sonnet 完整输出
{sonnet_raw}

## 评审要求（请逐条回答）

1. **代码质量**：哪个版本的代码质量更高？从以下维度分析：
   - 架构合规性（SecurityContext/RLS/AuditService/API 信封格式）
   - 可读性与命名规范
   - 错误处理完整性

2. **逻辑差异**：两版本是否存在逻辑差异（而非仅风格差异）？如有，描述差异及其影响。

3. **架构违规**：是否发现以下任一违规？
   - Service 方法首参非 SecurityContext/RequestContext
   - DB 查询缺少 tenant_id 过滤（RLS 缺失）
   - WRITE 操作未调用 AuditService.log()
   - API 返回裸列表（非信封格式）
   - session.begin() 在 execute() 后调用（事务策略违规）

4. **最终建议**：
   - [ ] 选 A（qwen）
   - [ ] 选 B（sonnet）
   - [ ] 手动合并（说明需要合并哪些部分）

请用简洁的中文回答，重点突出差异和违规，不需要逐行复述代码。"""


def _run_qwen_review(
    ep_id: str,
    unit_id: str,
    report_so_far: str,
    qwen_raw: str,
    sonnet_raw: str,
) -> str:
    """调用 qwen3-32b 进行语义评审，返回评审文本。"""
    try:
        try:
            from mms.providers.factory import auto_detect  # type: ignore[import]
        except ImportError:
            from mms.providers.factory import auto_detect  # type: ignore[import]

        provider = auto_detect("code_review")
        print(f"  · 语义评审使用 Provider：{provider.model_name}")

        # 截断过长内容，避免超出 token 限制（从 cfg 读取，默认 3000/4000 字符）
        _diff_limit = int(getattr(_cfg, "compare_diff_truncate_chars", 3000)) if _cfg else 3000
        _code_limit = int(getattr(_cfg, "compare_code_truncate_chars", 4000)) if _cfg else 4000
        diff_summary = report_so_far[:_diff_limit]
        qwen_truncated = qwen_raw[:_code_limit] + ("\n...(截断)" if len(qwen_raw) > _code_limit else "")
        sonnet_truncated = sonnet_raw[:_code_limit] + ("\n...(截断)" if len(sonnet_raw) > _code_limit else "")

        prompt = _REVIEW_PROMPT_TEMPLATE.format(
            ep_id=ep_id,
            unit_id=unit_id,
            diff_summary=diff_summary,
            qwen_raw=qwen_truncated,
            sonnet_raw=sonnet_truncated,
        )

        # fallback: config.yaml → runner.max_tokens.code_review (default=4096)
        review_max_tok = int(getattr(_cfg, "runner_max_tokens_code_review", 4096)) if _cfg else 4096
        import time as _time
        _t0 = _time.monotonic()
        review_text = provider.complete(prompt, max_tokens=review_max_tok)
        _elapsed = round((_time.monotonic() - _t0) * 1000, 1)

        # Level 4 诊断：记录 qwen3-32b 评审调用
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            from mms.trace.collector import get_tracer, estimate_tokens  # type: ignore[import]
            _tracer = get_tracer(ep_id)
            if _tracer:
                _tracer.record_llm(  # type: ignore[union-attr]
                    step="compare",
                    unit_id=unit_id,
                    model=getattr(provider, "model_name", "code_review_model"),
                    tokens_in=estimate_tokens(prompt),
                    tokens_out=estimate_tokens(review_text),
                    elapsed_ms=_elapsed,
                    result="ok",
                    llm_result="success",
                )
        except Exception:
            pass

        return review_text.strip()

    except Exception as e:
        return (
            f"⚠️  qwen3-32b 评审失败（{type(e).__name__}）：{e}\n\n"
            "请在 Cursor 对话中手动读取此报告并进行语义评审。"
        )


# ── 核心：apply() — 应用选定版本到业务文件 ───────────────────────────────────

def apply(ep_id: str, unit_id: str, source: str) -> int:
    """
    应用 qwen 或 sonnet 版本到业务文件，提交 git commit，标记 DAG Unit done。

    Args:
        ep_id:   EP 编号
        unit_id: Unit ID
        source:  "qwen" 或 "sonnet"

    Returns:
        0 = 成功，1 = 失败
    """
    ep_id = ep_id.upper()
    unit_id = unit_id.upper()
    source = source.lower()

    if source not in ("qwen", "sonnet"):
        print(f"  {_R}❌{_X} source 必须是 qwen 或 sonnet，实际：{source}")
        return 1

    d = _compare_dir(ep_id, unit_id)
    src_file = d / f"{source}.txt"

    if not src_file.exists():
        print(f"  {_R}❌{_X} 未找到 {src_file}")
        return 1

    raw = src_file.read_text(encoding="utf-8")
    raw_changes = _parse_changes_from_text(raw)

    if not raw_changes:
        print(f"  {_R}❌{_X} {source}.txt 中未解析到有效的 ===BEGIN-CHANGES=== 块")
        return 1

    # 将 tuple 列表转换为 FileChange dataclass（避免 'tuple has no attribute path' 错误）
    try:
        try:
            from mms.execution.file_applier import FileChange  # type: ignore[import]
        except ImportError:
            from mms.execution.file_applier import FileChange  # type: ignore[import]
        changes = [FileChange(path=p, action=a, content=c) for p, a, c in raw_changes]
    except Exception as e:
        print(f"  {_R}❌{_X} FileChange 构建失败：{e}")
        return 1

    print(f"\n{_B}MMS Unit Compare Apply · {ep_id} {unit_id} · {source.upper()}{_X}")
    print("─" * 60)

    # 加载 DAG 获取 unit.files（Scope Guard）
    allowed_files: List[str] = []
    try:
        try:
            from mms.dag.dag_model import DagState  # type: ignore[import]
        except ImportError:
            from mms.dag.dag_model import DagState  # type: ignore[import]
        state = DagState.load(ep_id)
        if state:
            unit = next((u for u in state.units if u.id.upper() == unit_id), None)
            if unit:
                allowed_files = unit.files
    except Exception:
        pass

    # Scope Guard 检查（安全边界：严格限定为 unit.files，拒绝 LLM 任意声明的路径）
    all_paths = [c.path for c in changes]
    if allowed_files:
        out_of_scope = [path for path in all_paths if path not in allowed_files]
        if out_of_scope:
            print(f"  {_R}❌{_X} Scope Guard 拒绝：以下文件超出 unit.files 允许范围：")
            for p in out_of_scope:
                print(f"       {_Y}{p}{_X}")
            print(f"  {_D}  allowed: {allowed_files}{_X}")
            print(f"  提示：如需扩展范围，请先修改 DAG 中的 unit.files 并重新生成 DAG。")
            return 1
    else:
        # DAG 未加载（降级模式）：打印警告但允许继续
        print(f"  {_Y}⚠️  未能加载 DAG unit.files，Scope Guard 以降级模式运行（仅打印 diff）{_X}")

    # 应用文件变更
    try:
        try:
            from mms.execution.sandbox import GitSandbox  # type: ignore[import]
            from mms.execution.file_applier import FileApplier  # type: ignore[import]
        except ImportError:
            from mms.execution.sandbox import GitSandbox  # type: ignore[import]
            from mms.execution.file_applier import FileApplier  # type: ignore[import]

        sandbox = GitSandbox(all_paths, root=_ROOT)
        sandbox.snapshot()
        applier = FileApplier(root=_ROOT)

        # allowed_files 传入 unit.files（有效 Scope Guard）；降级时传全部路径
        effective_allowed = allowed_files if allowed_files else all_paths
        apply_results = applier.apply(changes, allowed_files=effective_allowed, sandbox=sandbox)
        apply_ok = all(r.success for r in apply_results)

        if not apply_ok:
            failed = [r for r in apply_results if not r.success]
            for r in failed:
                print(f"  {_R}❌{_X} {r.path}: {r.error}")
            sandbox.rollback()
            print(f"  {_R}❌{_X} 文件应用失败，已回滚")
            return 1

        for c in changes:
            print(f"  {_G}✅{_X} {c.action.upper()}: {c.path}")

    except Exception as e:
        print(f"  {_R}❌{_X} 应用失败：{e}")
        return 1

    # git commit
    commit_msg = f"{ep_id} {unit_id}: apply {source} version"
    commit_hash = sandbox.commit(commit_msg)
    print(f"  {_G}✅{_X} git commit：{commit_hash or '（无变更）'}")

    # 标记 DAG Unit done
    try:
        state = DagState.load(ep_id)
        if state:
            unit = next((u for u in state.units if u.id.upper() == unit_id), None)
            if unit:
                from datetime import datetime, timezone
                unit.status = "done"
                unit.git_commit = commit_hash
                unit.completed_at = datetime.now(timezone.utc).isoformat()
                state.save()
                print(f"  {_G}✅{_X} DAG Unit 已标记 done")
    except Exception as e:
        print(f"  {_Y}⚠️  DAG 状态更新失败（可手动运行 mms unit done）：{e}{_X}")

    print(f"\n{'─' * 60}")
    print(f"  {_G}{_B}✅  DONE — {source.upper()} 版本已应用{_X}\n")
    return 0
