#!/usr/bin/env python3
"""
unit_runner.py — Unit LLM 自动执行引擎

将 mms unit next（上下文生成）与 mms unit done（验证+提交）连接起来，
中间插入 LLM 代码生成 + 文件应用 + 沙箱回滚的自动化流程。

执行流程（3-Strike 重试循环）：
  1. 生成 unit_context（复用 unit_context.py）
  2. 调用 LLM 生成代码（structured ===BEGIN-CHANGES=== 协议）
  3. 解析 + Scope Guard + 语法预验证
  4. 应用文件变更（GitSandbox 保护）
  5. 运行 arch_check diff + pytest
  6. PASS → git commit + mark_done
     FAIL → rollback + 将错误注入上下文 → 重试（最多 3 次）
  7. 3 次全部失败 → 完全回滚 + 输出诊断报告

--save-output 模式（EP-120 双模型对比工作流）：
  启用后，LLM 原始输出保存到
    docs/memory/private/compare/<EP>/<Unit>/qwen.txt
    docs/memory/private/compare/<EP>/<Unit>/context.md
  不写入任何业务文件（等同于 dry-run + 存盘）。
  后续由 Cursor Sonnet 独立生成 sonnet.txt，再运行
    mms unit compare --ep EP-NNN --unit U1
  生成机械 diff 报告，由用户三选一后 apply。

用法：
    from unit_runner import UnitRunner, RunResult
    runner = UnitRunner()
    result = runner.run("EP-119", "U1", model="capable")
    if result.success:
        print(f"✅ 完成，commit: {result.commit_hash}")
    else:
        print(f"❌ 失败：{result.error}")
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent

_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

try:
    from mms_config import cfg as _cfg  # type: ignore[import]
except ImportError:
    try:
        from mms.mms_config import cfg as _cfg  # type: ignore[import]
    except ImportError:
        _cfg = None  # type: ignore[assignment]

def _icfg(attr: str, default: int) -> int:
    """从 _cfg 安全读取整数属性，不可用时返回 default。"""
    if _cfg is None:
        return default
    return int(getattr(_cfg, attr, default))

def _bcfg(attr: str, default: bool) -> bool:
    """从 _cfg 安全读取布尔属性，不可用时返回 default。"""
    if _cfg is None:
        return default
    return bool(getattr(_cfg, attr, default))

MAX_RETRIES = _icfg("runner_max_retries", 2)          # fallback: config.yaml → runner.retry.max_retries (default=2)
ARCH_CHECK_TIMEOUT = _icfg("runner_timeout_arch_check", 30)   # fallback: config.yaml → runner.timeout.arch_check_seconds (default=30)
TEST_TIMEOUT = _icfg("runner_timeout_test", 120)       # fallback: config.yaml → runner.timeout.test_seconds (default=120)
LLM_TIMEOUT = _icfg("runner_timeout_llm", 180)         # fallback: config.yaml → runner.timeout.llm_seconds (default=180)

# EP-129: AIU Feedback 配置
AIU_FEEDBACK_BUDGET_MULTIPLIER = 1.5   # Level 1: token budget 扩充倍数
AIU_MAX_FEEDBACK_LEVEL = 3             # 最大 Feedback 级别


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class AiuOutputCarry:
    """
    AIU 间输出传递的签名快照（EP-131）。

    在 Unit 内部的 AIU 循环中，将前置 AIU 生成的代码签名（仅 class/def 行）
    注入到下一个 AIU 的上下文，解决小模型长程连贯性问题。

    设计约束：
      - snippet 严格限制 ≤ 200 tokens（约 800 字符）
      - 只传递 class/def 签名行，不传递方法体
      - 通过 ast.parse() 从生成代码中提取，失败时 snippet 为空（graceful）
    """
    aiu_type: str       # 来源 AIU 类型（如 "CONTRACT_ADD_RESPONSE"）
    snippet: str        # 提取的签名片段（≤ 800 字符）
    file_path: str      # 来源文件路径
    extracted_at: str   # ISO 8601 时间戳

    @classmethod
    def from_generated_content(
        cls,
        aiu_type: str,
        file_path: str,
        content: str,
        max_chars: int = 800,
    ) -> "AiuOutputCarry":
        """
        从 LLM 生成的文件内容提取签名片段。
        使用 ast.parse() 提取 class/function 签名（仅适用于 .py 文件）。
        TypeScript 等文件使用正则表达式提取。
        """
        from datetime import datetime, timezone
        snippet = _extract_signature_snippet(content, file_path, max_chars=max_chars)
        return cls(
            aiu_type=aiu_type,
            snippet=snippet,
            file_path=file_path,
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_prompt_block(self) -> str:
        """生成注入到下一个 AIU prompt 的文本块"""
        if not self.snippet:
            return ""
        return (
            f"# 前置 AIU [{self.aiu_type}] 签名（来自 {self.file_path}）\n"
            f"# 你的代码必须与以下签名保持类型兼容：\n"
            f"{self.snippet}\n"
        )


def _extract_signature_snippet(
    content: str,
    file_path: str,
    max_chars: int = 800,
) -> str:
    """
    从代码内容中提取类/函数签名（不含方法体）。
    Python 文件：使用 ast.parse() 精确提取。
    其他文件：使用正则提取 class/function/interface/type 定义行。
    返回结果严格截断到 max_chars 字符。
    """
    if not content or not content.strip():
        return ""

    lines = content.splitlines()
    sig_lines: List[str] = []

    if file_path.endswith(".py"):
        # Python：提取 class/def 签名行（仅签名，不含方法体）
        import ast as _ast
        try:
            tree = _ast.parse(content)
        except SyntaxError:
            # 语法错误时降级为正则
            return _extract_signature_regex(content, max_chars)

        for node in _ast.walk(tree):
            if isinstance(node, (_ast.ClassDef, _ast.FunctionDef, _ast.AsyncFunctionDef)):
                # 取签名行（类/函数定义行，不含 body）
                node_lines = lines[node.lineno - 1: node.end_lineno]  # type: ignore[attr-defined]
                # 找到 ":" 结束的签名部分
                for i, line in enumerate(node_lines):
                    sig_lines.append(line)
                    if line.rstrip().endswith(":") and i > 0:
                        break
                    if i == 0 and line.rstrip().endswith(":"):
                        break
                    # 多行签名最多保留 5 行
                    if i >= 4:
                        sig_lines.append("    ...")
                        break
    else:
        sig_lines = _extract_signature_regex_lines(content)

    result = "\n".join(sig_lines)
    if len(result) > max_chars:
        suffix = "\n# ... (截断)"
        result = result[: max_chars - len(suffix)] + suffix
    return result


def _extract_signature_regex(content: str, max_chars: int) -> str:
    """使用正则提取签名（fallback）"""
    lines = _extract_signature_regex_lines(content)
    result = "\n".join(lines)
    return result[:max_chars] if len(result) > max_chars else result


def _extract_signature_regex_lines(content: str) -> List[str]:
    """提取 class/function/interface/type/export 定义行"""
    import re
    sig_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if re.match(
            r"^(class |def |async def |export (class |function |interface |type |const )|interface |type )",
            stripped,
        ):
            sig_lines.append(line)
    return sig_lines


@dataclass
class AttemptLog:
    """单次尝试的日志"""
    attempt: int
    llm_response_preview: str    # LLM 输出前 200 字符
    parse_ok: bool
    apply_ok: bool
    arch_ok: bool
    test_ok: bool
    error: Optional[str] = None


@dataclass
class RunResult:
    """Unit 执行结果"""
    ep_id: str
    unit_id: str
    success: bool
    commit_hash: Optional[str] = None
    attempts: int = 0
    attempt_logs: List[AttemptLog] = field(default_factory=list)
    error: Optional[str] = None
    dry_run: bool = False
    save_output: bool = False          # EP-120：--save-output 模式
    output_path: Optional[str] = None  # EP-120：qwen.txt 存盘路径
    changed_files: List[str] = field(default_factory=list)


# ── LLM Prompt ───────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是 MDP 平台的自动化代码生成引擎。你的任务是根据 Unit 上下文实现代码变更。

【输出格式要求（严格遵守）】
你必须且只能输出以下格式的代码变更块，不要输出任何其他内容：

===BEGIN-CHANGES===
FILE: <相对于项目根的文件路径>
ACTION: <create 或 replace>
CONTENT:
<完整的文件内容，不要截断，不要省略>
===END-FILE===
===END-CHANGES===

【重要约束】
- ACTION 只允许：create（新建文件）或 replace（完整替换已有文件）
- CONTENT 必须是完整的文件内容，不能使用 "..." 省略
- 不要在 CONTENT 外包裹 markdown 代码块（```python 等）
- 不要在 ===BEGIN-CHANGES=== 和 ===END-CHANGES=== 之外输出任何解释性文字
- 严格遵守 unit.files 中声明的文件路径，不要创建其他文件
"""

_USER_PROMPT_TEMPLATE = """\
# Unit 执行上下文

{unit_context}

# 执行指令

请根据上述上下文，生成完整的代码实现。
严格遵守架构约束和层边界契约。
"""

# EP-131：携带前置 AIU 输出快照的 prompt（仅在 aiu_carry_section 非空时使用）
_USER_PROMPT_WITH_CARRY_TEMPLATE = """\
# Unit 执行上下文

{unit_context}

{aiu_carry_section}

# 执行指令

请根据上述上下文，生成完整的代码实现。
严格遵守架构约束和层边界契约。
前置步骤输出快照中的签名必须保持类型兼容。
"""

_RETRY_PROMPT_TEMPLATE = """\
# Unit 执行上下文

{unit_context}

# 上次尝试的代码未通过验证

上次生成的代码存在以下问题，请修复后重新生成：

## 错误信息
{error_msg}

## 修复要求
1. 仔细阅读错误信息，找到根本原因
2. 完整重新生成所有涉及文件（不要只生成修改部分）
3. 确保代码符合架构约束

请重新生成完整的代码实现：
"""


# ── 辅助函数 ─────────────────────────────────────────────────────────────────

def _quick_syntax_check(files_and_content: dict) -> Optional[str]:
    """
    EP-131：对 LLM 生成的 Python 文件内容做快速 AST 语法检查（< 1ms）。

    在调用 arch_check 和 pytest 之前执行，用于快速淘汰语法错误，
    避免等待 arch_check 超时（30s）才能发现简单语法问题。

    Args:
        files_and_content: {文件相对路径: 文件内容} 字典（从 parse_llm_output 解析）

    Returns:
        None    → 所有 Python 文件语法检查通过
        str     → 第一个语法错误的描述（含文件名和行号）

    注意：
      - 只检查 .py 文件，TypeScript/YAML 等跳过
      - 仅检测语法错误（SyntaxError），不做类型检查
      - 不需要写入磁盘，直接在内存中 parse
    """
    import ast as _ast
    for path, content in files_and_content.items():
        if not isinstance(path, str) or not path.endswith(".py"):
            continue
        if not content or not isinstance(content, str):
            continue
        try:
            _ast.parse(content)
        except SyntaxError as e:
            lineno = e.lineno or 0
            return f"{path} 第 {lineno} 行语法错误：{e.msg}"
    return None


def _build_aiu_carry_section(carries: List["AiuOutputCarry"]) -> str:
    """
    EP-131：将前置 AIU 的输出快照拼装为 prompt 中的"前置快照"节。

    Args:
        carries: 前置 AIU 的 AiuOutputCarry 列表

    Returns:
        str：注入 prompt 的文本块（空列表时返回空字符串）
    """
    if not carries:
        return ""

    blocks = []
    for carry in carries:
        block = carry.to_prompt_block()
        if block:
            blocks.append(block)

    if not blocks:
        return ""

    return (
        "# 前置 AIU 输出快照（必须与以下签名保持类型兼容）\n"
        "# ─────────────────────────────────────────────\n"
        + "\n".join(blocks)
        + "# ─────────────────────────────────────────────\n"
    )


def _call_llm(prompt: str, model_hint: str = "capable") -> tuple:
    """
    调用 LLM，根据 model_hint 选择合适的 provider。
    返回 (response_text, actual_model_name)。

    model_hint 路由规则：
      "fast" / "8b" / "16b" → code_generation_simple → bailian_coder (qwen3-coder-next)
      "capable" 及其他      → code_generation        → bailian_coder (qwen3-coder-next)
    """
    sys.path.insert(0, str(_HERE))
    try:
        from providers.factory import get_provider_for_task  # type: ignore[import]
    except ImportError:
        try:
            from mms.providers.factory import get_provider_for_task  # type: ignore[import]
        except ImportError:
            return "", "unknown"

    if model_hint in ("8b", "16b", "fast"):
        task = "code_generation_simple"
    else:
        task = "code_generation"

    try:
        provider = get_provider_for_task(task)
        if provider is None:
            return "", "unknown"
        actual_model = getattr(provider, "model_name", task)
        # fallback: config.yaml → runner.max_tokens.code_generation (default=4096)
        max_tok = _icfg("runner_max_tokens_code_generation", 4096)
        return provider.complete(prompt, max_tokens=max_tok), actual_model
    except Exception as exc:
        print(f"  {_Y}⚠️  LLM 调用异常：{exc}{_X}")
        return "", "error"


def _run_arch_check(files: List[str]) -> tuple:
    """
    运行 arch_check，返回 (passed: bool, output: str)。
    仅检查本次涉及的文件（精准模式）。
    """
    arch_check = _HERE / "arch_check.py"
    if not arch_check.exists():
        return True, "（arch_check.py 不存在，跳过）"

    try:
        result = subprocess.run(
            [sys.executable, str(arch_check)],
            cwd=str(_ROOT), capture_output=True, text=True,
            timeout=ARCH_CHECK_TIMEOUT,
        )
        output = (result.stdout + result.stderr).strip()
        passed = result.returncode == 0
        return passed, output
    except subprocess.TimeoutExpired:
        return False, f"arch_check 超时（{ARCH_CHECK_TIMEOUT}s）"
    except Exception as e:
        return False, f"arch_check 执行异常（请检查 arch_check.py 是否可用）：{e}"


def _run_tests(test_files: List[str]) -> tuple:
    """
    运行指定测试文件，返回 (passed: bool, summary: str)。
    """
    existing = [f for f in test_files if (_ROOT / f).exists()]
    if not existing:
        return True, "（无测试文件声明或文件不存在，跳过）"

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *existing, "-v", "--tb=short", "-q", "--no-header"],
            cwd=str(_ROOT), capture_output=True, text=True,
            timeout=TEST_TIMEOUT,
        )
        output = result.stdout + result.stderr
        # 提取摘要行
        summary = ""
        for line in output.splitlines():
            if "passed" in line or "failed" in line or "error" in line:
                summary = line.strip()
                break
        return result.returncode == 0, summary or f"exit {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"pytest 超时（{TEST_TIMEOUT}s）"
    except Exception as e:
        return False, f"pytest 执行异常：{e}"


def _load_unit(ep_id: str, unit_id: str):
    """加载 DagUnit，失败时抛出 ValueError"""
    try:
        from dag_model import DagState  # type: ignore[import]
    except ImportError:
        from mms.dag_model import DagState  # type: ignore[import]

    state = DagState.load(ep_id.upper())
    if state is None:
        raise ValueError(f"未找到 EP {ep_id} 的 DAG 状态文件，请先运行 mms unit generate --ep {ep_id}")

    unit = next((u for u in state.units if u.id.upper() == unit_id.upper()), None)
    if unit is None:
        raise ValueError(f"未找到 Unit {unit_id}（EP：{ep_id}）")

    return state, unit


def _generate_unit_context(unit, model: str = "capable") -> str:
    """调用 unit_context.py 生成压缩上下文"""
    try:
        from unit_context import generate_unit_context  # type: ignore[import]
    except ImportError:
        try:
            from mms.unit_context import generate_unit_context  # type: ignore[import]
        except ImportError:
            return f"# Unit: {unit.id}\n# {unit.title}\n# 文件：{', '.join(unit.files)}"

    model_map = {"8b": "8b", "16b": "16b", "capable": "capable", "fast": "8b"}
    return generate_unit_context(
        unit_id=unit.id,
        title=unit.title,
        layer=unit.layer,
        files=unit.files,
        test_files=unit.test_files,
        model=model_map.get(model, "capable"),
    )


def _generate_unit_context_with_budget(unit, model: str, token_budget: int) -> str:
    """
    EP-129 Level 1 Feedback：以扩充的 token budget 重新生成上下文。
    """
    try:
        from unit_context import generate_unit_context  # type: ignore[import]
    except ImportError:
        try:
            from mms.unit_context import generate_unit_context  # type: ignore[import]
        except ImportError:
            return ""

    model_override = "capable"  # 扩充预算时始终用 capable 级别的上下文窗口
    return generate_unit_context(
        unit_id=unit.id,
        title=unit.title,
        layer=unit.layer,
        files=unit.files,
        test_files=unit.test_files,
        model=model_override,
        token_budget_override=token_budget,
    )


def _aiu_feedback_analysis(
    unit,
    ep_id: str,
    unit_id: str,
    error_msg: str,
) -> dict:
    """
    EP-129 AIU Feedback Analysis。
    分析失败错误，决定三级回退策略。

    返回：
      {
        "action": "retry_with_expanded_budget" | "insert_prerequisite_aiu" | "split_aiu" | "give_up",
        "level": 1 | 2 | 3,
        "new_budget": int,           # Level 1 使用
        "suggested_aiu_type": str,   # Level 2 使用
        "split_suggestion": str,     # Level 3 使用
      }
    """
    try:
        sys.path.insert(0, str(_HERE))
        from aiu_types import classify_error, AIUErrorPattern, ERROR_TO_FEEDBACK_LEVEL  # type: ignore[import]
    except ImportError:
        return {"action": "give_up", "level": 0}

    error_pattern = classify_error(error_msg)
    suggested_level = ERROR_TO_FEEDBACK_LEVEL.get(error_pattern, 1)

    # 查询历史 feedback 记录，避免在同级别反复循环
    history_level = _get_aiu_feedback_history_level(ep_id, unit_id)
    if history_level >= AIU_MAX_FEEDBACK_LEVEL:
        return {"action": "give_up", "level": history_level, "reason": "已达最大 Feedback 级别"}

    # 实际使用级别：历史最高级别 +1（确保每次回退更深一级）
    actual_level = max(suggested_level, history_level + 1)
    actual_level = min(actual_level, AIU_MAX_FEEDBACK_LEVEL)

    print(f"  {_D}错误模式：{error_pattern} → Feedback Level {actual_level}{_X}")

    if actual_level == 1:
        # Level 1: 扩充 token budget
        current_tokens = len(unit.files) * 1500  # 粗略估算
        new_budget = int(current_tokens * AIU_FEEDBACK_BUDGET_MULTIPLIER)
        new_budget = min(new_budget, 16000)  # 上限 16K
        return {
            "action": "retry_with_expanded_budget",
            "level": 1,
            "new_budget": new_budget,
            "error_pattern": error_pattern.value,
        }

    elif actual_level == 2:
        # Level 2: 建议插入前置 AIU
        suggested_aiu = _suggest_prerequisite_aiu(error_pattern, error_msg)
        return {
            "action": "insert_prerequisite_aiu",
            "level": 2,
            "suggested_aiu_type": suggested_aiu,
            "error_pattern": error_pattern.value,
        }

    else:
        # Level 3: 建议分裂 AIU
        split_suggestion = _generate_split_suggestion(unit, error_msg)
        return {
            "action": "split_aiu",
            "level": 3,
            "split_suggestion": split_suggestion,
            "error_pattern": error_pattern.value,
        }


def _suggest_prerequisite_aiu(error_pattern, error_msg: str) -> str:
    """根据错误模式推断需要的前置 AIU 类型。"""
    try:
        from aiu_types import AIUErrorPattern, AIUType  # type: ignore[import]
    except ImportError:
        return "SCHEMA_ADD_FIELD"

    if error_pattern == AIUErrorPattern.MISSING_FIELD:
        return AIUType.SCHEMA_ADD_FIELD.value
    if error_pattern == AIUErrorPattern.MISSING_SCHEMA:
        if "request" in error_msg.lower():
            return AIUType.CONTRACT_ADD_REQUEST.value
        return AIUType.CONTRACT_ADD_RESPONSE.value
    return AIUType.SCHEMA_ADD_FIELD.value


def _generate_split_suggestion(unit, error_msg: str) -> str:
    """生成 Level 3 分裂建议文本。"""
    files_str = ", ".join(unit.files[:3]) if unit.files else "未知文件"
    return (
        f"建议将 Unit [{unit.id}] 分裂为：\n"
        f"  子任务 A：仅处理数据结构定义（涉及 {files_str} 中的 Model/Schema 部分）\n"
        f"  子任务 B：在子任务 A 完成后，处理业务逻辑和 API 路由部分\n"
        f"参考错误：{error_msg[:200]}"
    )


def _get_aiu_feedback_history_level(ep_id: str, unit_id: str) -> int:
    """
    从 feedback_stats.jsonl 读取当前 unit 已经历的最高 Feedback 级别。
    用于防止在同一级别反复循环。
    """
    feedback_path = _ROOT / "docs" / "memory" / "_system" / "feedback_stats.jsonl"
    if not feedback_path.exists():
        return 0

    max_level = 0
    try:
        import json as _json
        for line in feedback_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = _json.loads(line)
            if record.get("ep_id") == ep_id and record.get("unit_id") == unit_id:
                max_level = max(max_level, int(record.get("level", 0)))
    except Exception:
        pass
    return max_level


def _record_aiu_feedback(
    ep_id: str,
    unit_id: str,
    level: int,
    success: bool,
    error: str,
) -> None:
    """
    将 AIU Feedback 执行记录写入 feedback_stats.jsonl。
    类比数据库的 Cardinality Feedback 持久化到 Statistics 字典。
    """
    feedback_path = _ROOT / "docs" / "memory" / "_system" / "feedback_stats.jsonl"
    feedback_path.parent.mkdir(parents=True, exist_ok=True)

    import json as _json
    from datetime import datetime, timezone

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ep_id": ep_id,
        "unit_id": unit_id,
        "level": level,
        "success": success,
        "error_preview": error[:200] if error else "",
        "type": "aiu_feedback",
    }
    with feedback_path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(record, ensure_ascii=False) + "\n")


# ── 核心执行引擎 ─────────────────────────────────────────────────────────────

class UnitRunner:
    """
    单个 Unit 的 LLM 驱动执行引擎。

    外部接口：
        runner = UnitRunner()
        result = runner.run(ep_id, unit_id, model, dry_run, confirm)
    """

    def __init__(self, max_retries: int = MAX_RETRIES):
        self.max_retries = max_retries

    def run(
        self,
        ep_id: str,
        unit_id: str,
        model: str = "capable",
        dry_run: bool = False,
        confirm: bool = False,
        save_output: bool = False,
    ) -> RunResult:
        """
        执行单个 Unit（3-Strike 重试循环）。

        Args:
            ep_id:        EP 编号（如 "EP-119"）
            unit_id:      Unit ID（如 "U1"）
            model:        执行模型（"8b" | "16b" | "capable"）
            dry_run:      True=只生成代码打印预览，不写文件
            confirm:      True=写入前打印摘要等待用户确认
            save_output:  True=EP-120 双模型对比模式：LLM 输出存盘
                          docs/memory/private/compare/<EP>/<Unit>/qwen.txt
                          不写入任何业务文件

        Returns:
            RunResult
        """
        ep_id = ep_id.upper()
        unit_id = unit_id.upper()
        result = RunResult(
            ep_id=ep_id, unit_id=unit_id, success=False,
            dry_run=dry_run, save_output=save_output,
        )

        print(f"\n{_B}MMS Unit Runner · {ep_id} {unit_id}{_X}")
        print("─" * 60)

        # ── 加载 Unit 信息 ────────────────────────────────────────────────────
        try:
            state, unit = _load_unit(ep_id, unit_id)
        except (ValueError, FileNotFoundError) as e:
            result.error = str(e)
            print(f"  {_R}❌{_X} {e}")
            return result

        print(f"  {_D}标题：{unit.title}{_X}")
        print(f"  {_D}文件：{', '.join(unit.files)}{_X}")
        print(f"  {_D}模型：{model} | 原子化分：{unit.atomicity_score:.2f}{_X}")

        # 检查 Unit 是否已完成
        if unit.status == "done":
            print(f"  {_Y}⚠️  Unit 已标记完成（commit: {unit.git_commit}），跳过{_X}")
            result.success = True
            result.commit_hash = unit.git_commit
            return result

        # ── 生成上下文 ────────────────────────────────────────────────────────
        print(f"\n{_C}▶ Step 1 · 生成执行上下文{_X}")
        unit_context = _generate_unit_context(unit, model)
        print(f"  {_D}上下文约 {len(unit_context) // 4} tokens{_X}")

        # ── 3-Strike 重试循环 ─────────────────────────────────────────────────
        error_context = ""

        for attempt in range(1, self.max_retries + 2):  # 1, 2, 3
            result.attempts = attempt
            print(f"\n{_C}▶ 尝试 {attempt}/{self.max_retries + 1}{_X}")

            attempt_log = AttemptLog(
                attempt=attempt,
                llm_response_preview="",
                parse_ok=False,
                apply_ok=False,
                arch_ok=False,
                test_ok=False,
            )

            # Step 2: 调用 LLM
            print(f"  {_D}调用 LLM 生成代码...{_X}")
            if error_context:
                prompt = _RETRY_PROMPT_TEMPLATE.format(
                    unit_context=unit_context,
                    error_msg=error_context,
                )
            else:
                prompt = _USER_PROMPT_TEMPLATE.format(unit_context=unit_context)

            full_prompt = _SYSTEM_PROMPT + "\n\n" + prompt
            _llm_t0 = time.monotonic()
            raw_response, actual_model_name = _call_llm(full_prompt, model_hint=model)
            _llm_elapsed = round((time.monotonic() - _llm_t0) * 1000, 1)

            # Level 4 诊断：记录 LLM 调用（model 记录实际模型名，而非 hint）
            try:
                sys.path.insert(0, str(_HERE))
                from trace.collector import get_tracer, estimate_tokens  # type: ignore[import]
                _tracer = get_tracer(ep_id)
                if _tracer:
                    _tracer.record_llm(  # type: ignore[union-attr]
                        step="unit_run",
                        unit_id=unit_id,
                        model=actual_model_name,
                        tokens_in=estimate_tokens(full_prompt),
                        tokens_out=estimate_tokens(raw_response),
                        elapsed_ms=_llm_elapsed,
                        attempt=attempt,
                        max_attempts=MAX_RETRIES + 1,
                        result="ok" if raw_response else "error",
                        llm_result="success" if raw_response else "empty_response",
                        prompt=full_prompt if raw_response else None,
                        response=raw_response if raw_response else None,
                    )
            except Exception:
                pass

            if not raw_response:
                attempt_log.error = "LLM 调用失败（返回为空）"
                result.attempt_logs.append(attempt_log)
                error_context = "LLM 未返回任何内容，请重试。"
                print(f"  {_R}❌{_X} LLM 调用失败")
                continue

            attempt_log.llm_response_preview = raw_response[:200]

            # Step 3: 解析 + Scope Guard + 预验证
            try:
                from file_applier import parse_and_validate  # type: ignore[import]
            except ImportError:
                from mms.file_applier import parse_and_validate  # type: ignore[import]

            changes, parse_errors = parse_and_validate(
                raw_response,
                allowed_files=unit.files,
                strict_scope=False,  # 警告模式（过滤超出 scope 的文件，不阻断整次尝试）
            )

            if parse_errors:
                for err in parse_errors:
                    print(f"  {_Y}⚠️  {err}{_X}")

            if not changes:
                err_msg = "LLM 未输出有效的文件变更块"
                attempt_log.error = err_msg
                result.attempt_logs.append(attempt_log)
                error_context = f"{err_msg}\n期望格式：\n{BEGIN_HINT}"
                print(f"  {_R}❌{_X} {err_msg}")
                continue

            attempt_log.parse_ok = True

            # EP-131：快速语法预验证（< 1ms，在 arch_check 前检出明显语法错误）
            files_and_content = {c.path: c.content for c in changes if hasattr(c, "content")}
            if files_and_content:
                syntax_err = _quick_syntax_check(files_and_content)
                if syntax_err:
                    attempt_log.error = f"语法预验证失败：{syntax_err}"
                    result.attempt_logs.append(attempt_log)
                    error_context = f"生成的代码存在语法错误，请修复：\n{syntax_err}"
                    print(f"  {_R}❌{_X} 语法预验证失败：{syntax_err}")
                    continue
                print(f"  {_G}✅{_X} 语法预验证通过")

            # save-output 路径合法性校验：确保所有文件路径不含空格（防止 shell 命令混入）
            invalid_paths = [c.path for c in changes if " " in c.path or not c.path.strip()]
            if invalid_paths:
                err_msg = f"LLM 输出包含非法文件路径（含空格或空串）：{invalid_paths}"
                attempt_log.error = err_msg
                result.attempt_logs.append(attempt_log)
                error_context = f"{err_msg}\n请确保 unit.files 中只填写文件路径，不要填写 shell 命令。"
                print(f"  {_R}❌{_X} {err_msg}")
                continue

            print(f"  {_G}✅{_X} 解析到 {len(changes)} 个文件变更")

            # save-output 模式（EP-120）：存盘 qwen.txt + context.md，不写业务文件
            if save_output:
                out_path = self._save_qwen_output(
                    ep_id, unit_id, raw_response, unit_context, changes
                )
                result.success = True
                result.output_path = out_path
                result.changed_files = [c.path for c in changes]
                print(f"  {_G}✅{_X} qwen 输出已存盘：{out_path}")
                return result

            # dry-run 模式：打印预览，不写文件
            if dry_run:
                self._print_dry_run_preview(changes)
                result.success = True
                result.changed_files = [c.path for c in changes]
                return result

            # Step 4: 建立沙箱 + 应用文件
            try:
                from sandbox import GitSandbox  # type: ignore[import]
                from file_applier import FileApplier  # type: ignore[import]
            except ImportError:
                from mms.sandbox import GitSandbox  # type: ignore[import]
                from mms.file_applier import FileApplier  # type: ignore[import]

            sandbox = GitSandbox(unit.files, root=_ROOT)
            sandbox.snapshot()
            applier = FileApplier(root=_ROOT)

            # 可选：--confirm 模式等待用户确认
            if confirm:
                if not self._ask_confirm(changes):
                    sandbox.rollback()
                    result.error = "用户取消执行"
                    return result

            print(f"\n  {_D}应用文件变更...{_X}")
            apply_results = applier.apply(changes, allowed_files=unit.files, sandbox=sandbox)
            apply_ok = all(r.success for r in apply_results)

            if not apply_ok:
                failed = [r for r in apply_results if not r.success]
                err_msg = "\n".join(f"  - {r.path}: {r.error}" for r in failed)
                attempt_log.error = f"文件应用失败：\n{err_msg}"
                result.attempt_logs.append(attempt_log)
                sandbox.rollback()
                error_context = f"文件写入失败：\n{err_msg}"
                print(f"  {_R}❌{_X} 文件应用失败，已回滚")
                continue

            attempt_log.apply_ok = True

            # Step 5: 验证（arch_check + pytest）
            print(f"\n{_C}▶ 验证（arch_check + pytest）{_X}")
            arch_ok, arch_output = _run_arch_check(unit.files)
            test_ok, test_summary = _run_tests(unit.test_files or unit.files)

            attempt_log.arch_ok = arch_ok
            attempt_log.test_ok = test_ok

            if arch_ok and test_ok:
                print(f"  {_G}✅{_X} arch_check：通过")
                print(f"  {_G}✅{_X} pytest：{test_summary}")

                # Step 6: commit + mark_done
                commit_msg = f"{ep_id} {unit_id}: {unit.title}"
                commit_hash = sandbox.commit(commit_msg)
                print(f"  {_G}✅{_X} git commit：{commit_hash or '（无变更）'}")

                # Level 1 诊断：记录 git commit
                try:
                    from trace.collector import get_tracer  # type: ignore[import]
                    _tracer = get_tracer(ep_id)
                    if _tracer:
                        _tracer.record_git(  # type: ignore[union-attr]
                            commit_hash=commit_hash,
                            unit_id=unit_id,
                            step="unit_run",
                        )
                except Exception:
                    pass

                # 更新 DAG 状态
                unit.status = "done"
                unit.git_commit = commit_hash
                unit.completed_at = datetime.now(timezone.utc).isoformat()
                state.save()

                result.success = True
                result.commit_hash = commit_hash
                result.changed_files = sandbox.changed_files
                result.attempt_logs.append(attempt_log)

                print(f"\n{'─' * 60}")
                print(f"  {_G}{_B}✅  PASS — Unit {unit_id} 完成！{_X}")
                print(f"  {_D}commit: {commit_hash} | 尝试次数: {attempt}{_X}\n")
                return result

            else:
                # 验证失败 → 回滚 → 构建错误上下文 → 重试
                sandbox.rollback()

                error_parts = []
                if not arch_ok:
                    print(f"  {_R}❌{_X} arch_check 失败")
                    error_parts.append(f"## arch_check 违反\n{arch_output[:800]}")
                if not test_ok:
                    print(f"  {_R}❌{_X} pytest 失败：{test_summary}")
                    error_parts.append(f"## 测试失败\n{test_summary}")

                error_context = "\n\n".join(error_parts)
                attempt_log.error = error_context[:200]
                result.attempt_logs.append(attempt_log)
                print(f"  {_D}已回滚，准备第 {attempt + 1} 次尝试...{_X}")

        # ── 3 次全部失败 → AIU Feedback Analysis ────────────────────────────
        last_error = error_context or "未知错误"
        print(f"\n{'─' * 60}")
        print(f"  {_R}{_B}❌  FAIL — {self.max_retries + 1} 次 prompt 重试后仍未通过{_X}")
        print(f"  {_Y}▶ 触发 AIU Feedback Analysis...{_X}")

        feedback_result = _aiu_feedback_analysis(
            unit=unit,
            ep_id=ep_id,
            unit_id=unit_id,
            error_msg=last_error,
        )

        if feedback_result.get("action") == "retry_with_expanded_budget":
            # Level 1: 扩充上下文预算后重试
            new_budget = feedback_result.get("new_budget", 4000)
            print(f"  {_C}Level 1 回退：扩充 token budget 至 {new_budget}，重新生成上下文{_X}")
            expanded_context = _generate_unit_context_with_budget(unit, model, new_budget)
            if expanded_context and expanded_context != unit_context:
                error_context = f"[Level 1 Feedback] 上下文已扩充（budget={new_budget}）。\n之前的错误：{last_error[:400]}"
                unit_context = expanded_context
                # 重新进入单次重试（不再循环，最多 1 次 Level 1 重试）
                attempt_log_l1 = AttemptLog(
                    attempt=self.max_retries + 2,
                    llm_response_preview="", parse_ok=False,
                    apply_ok=False, arch_ok=False, test_ok=False,
                )
                prompt_l1 = _RETRY_PROMPT_TEMPLATE.format(
                    unit_context=unit_context, error_msg=error_context
                )
                raw_l1, model_l1 = _call_llm(_SYSTEM_PROMPT + "\n\n" + prompt_l1, model_hint=model)
                if raw_l1:
                    try:
                        from file_applier import parse_and_validate, FileApplier  # type: ignore[import]
                        from sandbox import GitSandbox  # type: ignore[import]
                    except ImportError:
                        from mms.file_applier import parse_and_validate, FileApplier  # type: ignore[import]
                        from mms.sandbox import GitSandbox  # type: ignore[import]
                    changes_l1, _ = parse_and_validate(raw_l1, allowed_files=unit.files, strict_scope=False)
                    if changes_l1:
                        sandbox_l1 = GitSandbox(unit.files, root=_ROOT)
                        sandbox_l1.snapshot()
                        applier_l1 = FileApplier(root=_ROOT)
                        apply_results_l1 = applier_l1.apply(changes_l1, allowed_files=unit.files, sandbox=sandbox_l1)
                        if all(r.success for r in apply_results_l1):
                            arch_ok_l1, arch_out_l1 = _run_arch_check(unit.files)
                            test_ok_l1, test_sum_l1 = _run_tests(unit.test_files or unit.files)
                            if arch_ok_l1 and test_ok_l1:
                                commit_msg_l1 = f"{ep_id} {unit_id} [L1-Feedback]: {unit.title}"
                                commit_hash_l1 = sandbox_l1.commit(commit_msg_l1)
                                _record_aiu_feedback(ep_id, unit_id, level=1, success=True, error=last_error)
                                result.success = True
                                result.commit_hash = commit_hash_l1
                                result.changed_files = sandbox_l1.changed_files
                                result.attempt_logs.append(attempt_log_l1)
                                print(f"  {_G}✅ Level 1 Feedback 成功！commit: {commit_hash_l1}{_X}")
                                return result
                            sandbox_l1.rollback()
                        else:
                            sandbox_l1.rollback()

        elif feedback_result.get("action") == "insert_prerequisite_aiu":
            # Level 2: 建议插入前置 AIU
            suggested_aiu = feedback_result.get("suggested_aiu_type", "SCHEMA_ADD_FIELD")
            print(f"  {_Y}Level 2 回退建议：在本 Unit 前插入前置步骤 [{suggested_aiu}]{_X}")
            print(f"  {_D}提示：请手动执行前置步骤后再重试本 Unit{_X}")
            _record_aiu_feedback(ep_id, unit_id, level=2, success=False, error=last_error)

        elif feedback_result.get("action") == "split_aiu":
            # Level 3: 建议分裂当前 AIU
            split_suggestion = feedback_result.get("split_suggestion", "")
            print(f"  {_R}Level 3 回退建议：当前任务过于复杂，建议分裂为多个子任务{_X}")
            if split_suggestion:
                print(f"  {_D}分裂建议：{split_suggestion}{_X}")
            _record_aiu_feedback(ep_id, unit_id, level=3, success=False, error=last_error)

        result.error = f"{self.max_retries + 1} 次尝试全部失败，AIU Feedback 级别: {feedback_result.get('level', 0)}（已回滚）"
        print(f"\n  {_D}诊断建议：{_X}")
        print(f"    1. 运行 {_C}mms unit context --ep {ep_id} --unit {unit_id}{_X} 查看完整上下文")
        print(f"    2. 检查 unit.files 声明是否完整（当前：{unit.files}）")
        print(f"    3. 手动编写代码后运行 {_C}mms unit done --ep {ep_id} --unit {unit_id}{_X}")
        return result

    @staticmethod
    def _save_qwen_output(
        ep_id: str,
        unit_id: str,
        raw_response: str,
        unit_context: str,
        changes,
    ) -> str:
        """
        EP-120 双模型对比：将 qwen 输出存盘，返回 qwen.txt 路径字符串。

        目录结构：
            docs/memory/private/compare/<EP-ID>/<UNIT-ID>/
                context.md   — 发送给 qwen 的上下文（供 Sonnet 生成时对齐）
                qwen.txt     — qwen 原始 ===BEGIN-CHANGES=== 格式输出
        """
        compare_dir = (
            _ROOT / "docs" / "memory" / "private" / "compare"
            / ep_id / unit_id
        )
        compare_dir.mkdir(parents=True, exist_ok=True)

        # 存 context.md（末尾追加 Sonnet 输出格式要求，引导 LLM 输出标准块）
        _SONNET_FORMAT_HINT = (
            "\n\n---\n"
            "## ⚠️ 输出格式要求（Cursor Sonnet 必须严格遵守）\n\n"
            "请按以下格式输出代码变更，**不要输出任何解释性文字**，\n"
            "不要使用 markdown 代码块（```python 等），直接输出格式块：\n\n"
            "===BEGIN-CHANGES===\n"
            "FILE: <相对于项目根的文件路径（如 scripts/mms/foo.py）>\n"
            "ACTION: replace\n"
            "CONTENT:\n"
            "<完整的文件内容，不能省略，不能截断>\n"
            "===END-FILE===\n"
            "===END-CHANGES===\n\n"
            "> 说明：\n"
            "> - ACTION 只允许 `create`（新建）或 `replace`（完整替换）\n"
            "> - 多个文件变更时，在 `===BEGIN-CHANGES===` 和 `===END-CHANGES===` 之间\n"
            ">   依次列多个 FILE...CONTENT...===END-FILE=== 块\n"
            "> - **格式错误将导致 mms unit compare 无法解析你的输出**\n"
        )
        ctx_path = compare_dir / "context.md"
        ctx_path.write_text(unit_context + _SONNET_FORMAT_HINT, encoding="utf-8")

        # 存 qwen.txt（原始 LLM 输出）
        qwen_path = compare_dir / "qwen.txt"
        header = (
            f"# qwen 输出 — {ep_id} {unit_id}\n"
            f"# 生成时间：{datetime.now(timezone.utc).isoformat()}\n"
            f"# 涉及文件：{', '.join(c.path for c in changes)}\n\n"
        )
        qwen_path.write_text(header + raw_response, encoding="utf-8")

        return str(qwen_path)

    @staticmethod
    def _print_dry_run_preview(changes) -> None:
        """打印 dry-run 模式的变更预览"""
        print(f"\n{_Y}[dry-run] 变更预览（不写入文件）：{_X}")
        print("─" * 60)
        for change in changes:
            lines = change.content.splitlines()
            print(f"\n{_B}FILE: {change.path}  ACTION: {change.action}{_X}")
            for line in lines[:20]:
                print(f"  {line}")
            if len(lines) > 20:
                print(f"  {_D}... 共 {len(lines)} 行 ...{_X}")
        print("─" * 60)

    @staticmethod
    def _ask_confirm(changes) -> bool:
        """--confirm 模式：显示变更摘要，等待用户确认"""
        print(f"\n{_Y}[confirm] 即将写入以下文件：{_X}")
        for c in changes:
            lines = len(c.content.splitlines())
            print(f"  {c.action.upper()}: {c.path} ({lines} 行)")
        try:
            user = input("\n  确认执行？[Y/n]: ").strip().lower()
            return user in ("", "y", "yes")
        except (KeyboardInterrupt, EOFError):
            return False


# ── 批次执行 ─────────────────────────────────────────────────────────────────

class BatchRunner:
    """
    顺序执行当前批次（或全部）待执行 Unit。

    注意：顺序执行（非并行），每个 Unit 完成后才执行下一个。
    并行执行留给第五阶段。
    """

    def __init__(self, max_retries: int = MAX_RETRIES, max_failures: int = 1):
        self.runner = UnitRunner(max_retries=max_retries)
        self.max_failures = max_failures

    def run_next(
        self,
        ep_id: str,
        model: str = "capable",
        dry_run: bool = False,
        confirm: bool = False,
    ) -> List[RunResult]:
        """执行当前批次中所有 pending Unit（按 order 顺序）"""
        try:
            from dag_model import DagState  # type: ignore[import]
        except ImportError:
            from mms.dag_model import DagState  # type: ignore[import]

        try:
            state = DagState.load(ep_id.upper())
        except (FileNotFoundError, ValueError):
            state = None
        if state is None:
            print(f"  {_R}❌{_X} 未找到 EP {ep_id} 的 DAG 状态，请先运行 mms unit generate")
            return []

        done_ids = [u.id for u in state.units if u.status in ("done", "skipped")]
        executable = [u for u in state.units if u.status == "pending" and u.is_executable(done_ids)]

        if not executable:
            print(f"  {_Y}⚠️  当前无可执行 Unit（所有 pending Unit 的依赖未完成）{_X}")
            return []

        # 按 order 分组，只执行最小 order 批次
        min_order = min(u.order for u in executable)
        batch = [u for u in executable if u.order == min_order]

        print(f"\n{_B}MMS Batch Runner · {ep_id.upper()} · Batch {min_order}（{len(batch)} 个 Unit）{_X}")

        results = []
        failures = 0

        for unit in batch:
            result = self.runner.run(ep_id, unit.id, model=model, dry_run=dry_run, confirm=confirm)
            results.append(result)

            if not result.success:
                failures += 1
                if failures >= self.max_failures:
                    print(f"\n  {_R}已达到最大失败数（{self.max_failures}），停止批次执行{_X}")
                    break

        return results

    def run_all(
        self,
        ep_id: str,
        model: str = "capable",
        dry_run: bool = False,
        confirm: bool = False,
        max_failures: int = 1,
    ) -> List[RunResult]:
        """顺序执行 EP 全部 pending Unit"""
        try:
            from dag_model import DagState  # type: ignore[import]
        except ImportError:
            from mms.dag_model import DagState  # type: ignore[import]

        all_results = []
        failures = 0

        while True:
            try:
                state = DagState.load(ep_id.upper())
            except (FileNotFoundError, ValueError):
                state = None
            if state is None:
                break

            done_ids = [u.id for u in state.units if u.status in ("done", "skipped")]
            pending = [u for u in state.units if u.status == "pending"]

            if not pending:
                print(f"\n  {_G}✅ 所有 Unit 已完成！{_X}")
                break

            executable = [u for u in pending if u.is_executable(done_ids)]
            if not executable:
                remaining = [u.id for u in pending]
                print(f"\n  {_Y}⚠️  剩余 Unit {remaining} 依赖未满足，停止执行{_X}")
                break

            # 执行最小批次
            min_order = min(u.order for u in executable)
            batch = [u for u in executable if u.order == min_order]

            for unit in batch:
                result = self.runner.run(ep_id, unit.id, model=model, dry_run=dry_run, confirm=confirm)
                all_results.append(result)

                if not result.success:
                    failures += 1
                    if failures >= max_failures:
                        print(f"\n  {_R}已达到最大失败数（{max_failures}），停止执行{_X}")
                        return all_results

        return all_results


# 用于 retry prompt 提示格式
BEGIN_HINT = """\
===BEGIN-CHANGES===
FILE: path/to/file.py
ACTION: create
CONTENT:
... 完整文件内容 ...
===END-FILE===
===END-CHANGES==="""
