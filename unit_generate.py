"""
unit_generate.py — mms unit generate 命令实现

将 EP 文件分解为 DAG（有向无环图），由 capable model（gemini-2.5-pro）作为"编排 Agent"
生成逻辑执行计划，small model 逐 Unit 原子执行。

流程：
  1. 解析 EP 文件（ep_parser）
  2. 若 EP 有 DAG Sketch 节 → 解析为 DagUnit 列表（优先，无需 LLM）
  3. 否则调用 LLM（gemini-2.5-pro via auto_detect("dag_orchestration")）生成 DAG JSON
  4. 原子性验证（atomicity_check）标注 model_hint + score
  5. 写入 docs/memory/_system/dag/EP-NNN.json
  6. 打印 DAG 概览

用法（通过 CLI）：
  mms unit generate --ep EP-117
  mms unit generate --ep EP-117 --force   # 强制重新生成（覆盖已有）
  mms unit generate --ep EP-117 --no-llm  # 仅解析 DAG Sketch，不调用 LLM
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from _paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent

# ANSI
_G = "\033[92m"
_Y = "\033[93m"
_R = "\033[91m"
_C = "\033[96m"
_B = "\033[1m"
_D = "\033[2m"
_X = "\033[0m"

# ── LLM Prompt ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """你是 MDP 的 DAG 编排 Agent。你的任务是将一个执行计划（EP）分解为原子 Unit。

**原子化 4 条硬性约束（必须严格遵守）：**
1. 每个 Unit 最多涉及 2 个文件（业务文件 + 对应测试文件）
2. 单个 Unit 上下文 ≤ 4000 tokens（适合 8B 模型）或 ≤ 8000 tokens（适合 16B 模型）
3. 不跨架构层（一个 Unit 只属于一个层）
4. 每个 Unit 必须可被 pytest 或 arch_check 自动验证

**层依赖顺序（影响 order 字段）：**
- order=1：L3_domain（数据模型）、L2_infrastructure（基础设施）可并行
- order=2：L4_application（服务层，依赖数据模型）
- order=3：L5_interface（API/前端，依赖服务层）
- order=4：testing（集成测试，依赖全部业务层）
- order=5：docs（文档同步，最后）

**model_hint 建议：**
- "8b"：单文件、纯机械操作（如：只修改一个函数签名）
- "16b"：1-2 文件、逻辑清晰（如：标准 CRUD Service 方法）
- "capable"：需要理解多层关系或复杂 prompt 工程

**输出格式（严格 JSON 数组，不含注释）：**
[
  {
    "id": "U1",
    "title": "一句话描述（≤ 30 字）",
    "layer": "L4_application",
    "files": ["scripts/mms/dag_model.py"],
    "test_files": ["scripts/mms/tests/test_dag_model.py"],
    "depends_on": [],
    "order": 2,
    "model_hint": "8b"
  }
]"""

_USER_PROMPT_TEMPLATE = """请将以下 EP 分解为原子 Unit。

**EP ID：** {ep_id}
**标题：** {title}
**目标：** {purpose}

**Scope（当前列出的 Unit）：**
{scope_text}

**架构层信息（来自 layer_contracts.md 摘要）：**
{layer_contracts_summary}

请严格按 JSON 数组格式输出，不要有任何其他文字。"""


# ── 动态模型名查询（EP-132）──────────────────────────────────────────────────

def _get_dag_orchestration_model_name() -> str:
    """
    获取 dag_orchestration 任务当前实际使用的模型名（EP-132）。
    不硬编码 "gemini-2.5-pro"，动态读取 factory 中的实际路由结果。
    失败时返回 "dag_orchestration_model"（中性占位符）。
    """
    try:
        try:
            from mms.providers.factory import auto_detect  # type: ignore[import]
        except ImportError:
            from providers.factory import auto_detect  # type: ignore[import]
        provider = auto_detect("dag_orchestration")
        return getattr(provider, "model_name", "dag_orchestration_model")
    except Exception:
        return "dag_orchestration_model"


# ── JSON 修复解析（EP-132：兼容小模型输出）────────────────────────────────────

def _repair_and_parse_json(raw: str, ep_id: str = "") -> Optional[List[Dict]]:
    """
    增强版 JSON 解析器，兼容小模型常见输出格式问题（EP-132）。

    修复策略（按优先级顺序）：
      1. 标准解析：直接 json.loads()
      2. 去除 markdown 代码块（```json ... ```）
      3. 提取第一个完整 JSON 数组（[ ... ]）
      4. 去除尾部多余内容（小模型常在 JSON 后加解释文字）
      5. 修复常见 JSON 格式错误（尾部逗号、单引号、注释）
      6. 如果是对象而非数组，尝试提取 units / data / result 键
      7. 返回 None（所有策略失败，上层触发重试）

    Args:
        raw:    LLM 原始输出字符串
        ep_id:  EP 编号（用于日志）

    Returns:
        解析成功的列表，或 None
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # 策略 1：标准解析
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # 策略 6：从对象中提取列表字段
            for key in ("units", "data", "result", "dag", "items"):
                if isinstance(result.get(key), list):
                    return result[key]
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 2：去除 markdown 代码块
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?\s*```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("units", "data", "result", "dag", "items"):
                if isinstance(result.get(key), list):
                    return result[key]
    except (json.JSONDecodeError, ValueError):
        pass

    # 策略 3：提取第一个完整 JSON 数组 [ ... ]
    bracket_match = re.search(r"(\[.*?\])", text, re.DOTALL)
    if bracket_match:
        try:
            result = json.loads(bracket_match.group(1))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 策略 4：贪婪提取（从第一个 [ 到最后一个 ]）
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        # 策略 5：修复常见格式错误再试
        fixed = _fix_json_format(candidate)
        try:
            result = json.loads(fixed)
            if isinstance(result, list):
                ep_tag = f"[{ep_id}] " if ep_id else ""
                print(f"  ⚠️  {ep_tag}JSON 已修复（小模型格式问题）", flush=True)
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def _fix_json_format(text: str) -> str:
    """
    修复小模型常见 JSON 格式错误。

    修复项：
      - 尾部逗号：[1, 2, 3,] → [1, 2, 3]（JSON 不允许）
      - Python 单引号：{'key': 'val'} → {"key": "val"}
      - Python 注释：// comment 或 # comment（不标准）
      - Python True/False/None → true/false/null
      - 无引号键：{key: "val"} → {"key": "val"}
    """
    # 去除单行注释（// 和 #）
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"#[^\n]*", "", text)

    # Python True/False/None → JSON true/false/null
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # 单引号替换为双引号（简单场景，复杂场景可能误替换）
    # 只替换作为键或字符串值出现的单引号
    text = re.sub(r"'([^'\\]*)'", r'"\1"', text)

    # 尾部逗号：,} 或 ,]
    text = re.sub(r",\s*}", "}", text)
    text = re.sub(r",\s*\]", "]", text)

    # 无引号 JSON 键：{key: → {"key":
    text = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*:)', r'\1"\2"\3', text)

    return text


# ── DAG Sketch 解析 ───────────────────────────────────────────────────────────

def _parse_dag_sketch(dag_sketch: str, scope_units: List[Any]) -> Optional[List[Dict]]:
    """
    从 EP 的 DAG Sketch 节解析 Unit 依赖关系。

    支持格式：
      U1(dag_model) → U3(atomicity) → U5(generate) → U7(cli)
      U2(ep_parser) → U4(context)  → U6(unit_cmd) ↗

    返回：[{"id": "U1", "depends_on": [], "order": 1}, ...]
    或 None（无法解析）
    """
    if not dag_sketch or dag_sketch.strip().startswith("<!--"):
        return None

    # 提取所有 Unit ID 和依赖关系
    # 格式：U1 → U2 → U3 或 U1(title) → U2(title)
    dep_map: Dict[str, List[str]] = {}
    order_map: Dict[str, int] = {}

    lines = [l.strip() for l in dag_sketch.strip().splitlines() if l.strip()]
    current_order = 1

    for line in lines:
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        # 提取 Unit ID 序列
        unit_ids = re.findall(r"(U\d+)", line)
        if not unit_ids:
            continue
        # 判断是否是新批次（以 U 开头且前一个 Unit 没有箭头连接）
        if "→" in line or "->" in line or "↗" in line:
            # 链式依赖：U1 → U2 → U3
            for i, uid in enumerate(unit_ids):
                if uid not in dep_map:
                    dep_map[uid] = []
                if i > 0:
                    dep_map[uid].append(unit_ids[i - 1])
                if uid not in order_map:
                    order_map[uid] = current_order + i
        else:
            # 独立批次
            for uid in unit_ids:
                if uid not in dep_map:
                    dep_map[uid] = []
                if uid not in order_map:
                    order_map[uid] = current_order

    if not dep_map:
        return None

    # 与 scope_units 合并，补充 title 和 files
    scope_map = {su.unit_id: su for su in scope_units}
    result = []
    for uid, deps in dep_map.items():
        su = scope_map.get(uid)
        result.append({
            "id": uid,
            "title": su.description[:50] if su else uid,
            "layer": "unknown",
            "files": su.files if su else [],
            "test_files": [],
            "depends_on": deps,
            "order": order_map.get(uid, 1),
            "model_hint": "capable",
        })

    return result if result else None


# ── LLM 调用 ──────────────────────────────────────────────────────────────────

def _call_llm_generate_dag(
    ep_id: str,
    title: str,
    purpose: str,
    scope_units: List[Any],
    layer_contracts_summary: str,
) -> Optional[List[Dict]]:
    """调用 LLM（Gemini 2.5 Pro）生成 DAG JSON"""
    try:
        from mms.providers.factory import auto_detect  # type: ignore[import]
    except ImportError:
        try:
            from providers.factory import auto_detect  # type: ignore[import]
        except ImportError:
            print(f"  {_Y}⚠️  无法导入 LLM provider，跳过 LLM 生成{_X}", file=sys.stderr)
            return None

    scope_text = "\n".join(
        f"- {su.unit_id}: {su.description} | 文件：{', '.join(su.files) or '（待定）'}"
        for su in scope_units
    ) or "（EP Scope 为空，请根据 EP 标题和目标推断）"

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        ep_id=ep_id,
        title=title,
        purpose=purpose[:500],
        scope_text=scope_text,
        layer_contracts_summary=layer_contracts_summary[:800],
    )

    # 将 system + user 合并为单一 prompt（适配 Gemini 和 bailian 的 complete() 接口）
    full_prompt = f"{_SYSTEM_PROMPT}\n\n---\n\n{user_prompt}"

    try:
        try:
            from mms_config import cfg as _cfg  # type: ignore[import]
        except ImportError:
            from mms.mms_config import cfg as _cfg  # type: ignore[import]

        provider = auto_detect("dag_orchestration")
        print(f"  · DAG 生成使用 Provider：{provider.model_name}")

        # max_tokens 从 config 读取，避免 gemini thinking 模式 token 不足
        # fallback: config.yaml → dag.generation.max_tokens (default=8192)
        max_tokens = _cfg.dag_generation_max_tokens
        retry_multiplier = _cfg.dag_generation_retry_multiplier

        import time as _time
        _t0 = _time.monotonic()
        response = provider.complete(full_prompt, max_tokens=max_tokens)

        # MAX_TOKENS 自动重试：翻倍后再试一次
        if not response or response.strip() == "":
            doubled = max_tokens * retry_multiplier
            print(f"  {_Y}⚠️  首次调用输出为空，自动翻倍 max_tokens={doubled} 重试{_X}")
            response = provider.complete(full_prompt, max_tokens=doubled)

        _elapsed = round((_time.monotonic() - _t0) * 1000, 1)

        # Level 4 诊断：记录 DAG 生成 LLM 调用
        try:
            import sys as _sys
            from pathlib import Path as _Path
            _sys.path.insert(0, str(_Path(__file__).resolve().parent))
            from trace.collector import get_tracer, estimate_tokens  # type: ignore[import]
            _tracer = get_tracer(ep_id)
            if _tracer:
                _tracer.record_llm(  # type: ignore[union-attr]
                    step="dag_generate",
                    model=getattr(provider, "model_name", "dag_orchestration"),
                    tokens_in=estimate_tokens(full_prompt),
                    tokens_out=estimate_tokens(response),
                    elapsed_ms=_elapsed,
                    result="ok" if response else "error",
                    llm_result="success" if response else "empty_response",
                )
        except Exception:
            pass

        # 提取 JSON（EP-132：增强 JSON 修复逻辑，兼容小模型输出格式）
        raw = response.strip()
        parsed = _repair_and_parse_json(raw, ep_id=ep_id)
        if parsed is None:
            print(f"  {_R}JSON 解析失败（原始输出前 200 字符）：{raw[:200]}{_X}", file=sys.stderr)
        return parsed

    except Exception as e:
        print(f"  {_R}LLM 调用失败：{e}{_X}", file=sys.stderr)
        return None


# ── 层边界契约摘要 ────────────────────────────────────────────────────────────

def _load_layer_contracts_summary() -> str:
    """加载 layer_contracts.md 的精简摘要（用于 LLM prompt）"""
    contracts_path = _ROOT / "docs" / "context" / "layer_contracts.md"
    if not contracts_path.exists():
        return "（layer_contracts.md 不存在）"
    content = contracts_path.read_text(encoding="utf-8")
    # 只取 DAG 层依赖规则节
    dag_section = re.search(r"## DAG 层依赖规则.*?(?=\n---|\Z)", content, re.DOTALL)
    if dag_section:
        return dag_section.group(0)[:600]
    return content[:600]


# ── 原子性标注 ────────────────────────────────────────────────────────────────

def _annotate_atomicity(units_data: List[Dict]) -> List[Dict]:
    """对每个 Unit 运行原子性验证，标注 atomicity_score 和 model_hint"""
    try:
        from atomicity_check import validate_unit  # type: ignore[import]
    except ImportError:
        from mms.atomicity_check import validate_unit  # type: ignore[import]

    try:
        from mms_config import cfg as _cfg  # type: ignore[import]
    except ImportError:
        from mms.mms_config import cfg as _cfg  # type: ignore[import]

    # 阈值从 config 读取
    # fallback: config.yaml → dag.atomicity_thresholds.annotate_threshold_high (default=0.85)
    threshold_high = _cfg.dag_annotate_threshold_high
    # fallback: config.yaml → dag.atomicity_thresholds.annotate_threshold_mid (default=0.60)
    threshold_mid = _cfg.dag_annotate_threshold_mid

    annotated = []
    for u in units_data:
        files = u.get("files", [])
        test_files = u.get("test_files", [])
        all_files = files + test_files

        # 先用 capable 验证（不限 token）
        _, score, _ = validate_unit(
            files=all_files, model="capable", verbose=False
        )

        # 确定 model_hint
        if u.get("model_hint") and u["model_hint"] != "capable":
            # 保留 LLM 给出的 hint（如果更小）
            pass
        elif score >= threshold_high:
            _, is_8b, _ = validate_unit(files=all_files, model="8b", verbose=False)
            u["model_hint"] = "8b" if is_8b else "16b"
        elif score >= threshold_mid:
            _, is_16b, _ = validate_unit(files=all_files, model="16b", verbose=False)
            u["model_hint"] = "16b" if is_16b else "capable"
        else:
            u["model_hint"] = "capable"

        u["atomicity_score"] = score
        annotated.append(u)

    return annotated


# ── 打印 DAG 概览 ─────────────────────────────────────────────────────────────

def _print_dag_overview(dag_state: Any) -> None:
    """打印 DAG 执行批次概览"""
    from dag_model import DagState  # type: ignore[import]

    done, total = dag_state.progress()
    print(f"\n{_B}DAG 生成完成：{dag_state.ep_id}（{total} 个 Unit）{_X}")
    print("─" * 60)

    batches = dag_state.get_batch_groups()
    for batch in batches:
        order = batch[0].order
        parallel_note = f"（{len(batch)} 个可并行）" if len(batch) > 1 else ""
        print(f"\n  {_C}Batch {order}{_X} {_D}{parallel_note}{_X}")
        for u in batch:
            hint_color = _G if u.model_hint == "8b" else (_Y if u.model_hint == "16b" else _C)
            deps_str = f"← {', '.join(u.depends_on)}" if u.depends_on else ""
            files_str = f"{len(u.files)} 文件" if u.files else "文件待定"
            print(
                f"    {_B}{u.id}{_X} {u.title[:35]:<35} "
                f"{hint_color}[{u.model_hint}]{_X} "
                f"{_D}{files_str} {deps_str}{_X}"
            )

    print(f"\n{'─' * 60}")
    print(f"  模型分布：", end="")
    for hint in ("8b", "16b", "capable"):
        count = sum(1 for u in dag_state.units if u.model_hint == hint)
        if count:
            print(f"{hint}×{count}  ", end="")
    print()


# ── 主函数 ────────────────────────────────────────────────────────────────────

def run_unit_generate(
    ep_id: str,
    force: bool = False,
    no_llm: bool = False,
) -> int:
    """
    生成 EP 的 DAG 状态文件。

    Returns:
        0 成功，1 失败
    """
    try:
        from dag_model import DagState, make_dag_state  # type: ignore[import]
        from ep_parser import parse_ep_by_id  # type: ignore[import]
    except ImportError:
        from mms.dag_model import DagState, make_dag_state  # type: ignore[import]
        from mms.ep_parser import parse_ep_by_id  # type: ignore[import]

    ep_norm = ep_id.upper()
    if not ep_norm.startswith("EP-"):
        ep_norm = f"EP-{ep_norm}"

    print(f"\n{_B}mms unit generate · {ep_norm}{_X}")
    print("─" * 55)

    # ── 检查已有 DAG 状态 ────────────────────────────────────────────────────
    if DagState.exists(ep_norm) and not force:
        existing = DagState.load(ep_norm)
        done, total = existing.progress()
        print(f"  {_Y}⚠️  已存在 DAG 状态（{done}/{total} 完成），使用 --force 覆盖{_X}")
        _print_dag_overview(existing)
        return 0

    # ── 解析 EP 文件 ─────────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 1 · 解析 EP 文件{_X}")
    try:
        parsed = parse_ep_by_id(ep_norm)
        print(f"  {_G}✅{_X} {parsed.ep_id}：{parsed.title[:50]}")
        print(f"  {_D}Scope Units：{len(parsed.scope_units)} 个{_X}")
    except FileNotFoundError as e:
        print(f"  {_R}❌ {e}{_X}")
        return 1

    # ── DAG Sketch 优先 ──────────────────────────────────────────────────────
    units_data: Optional[List[Dict]] = None
    source = ""

    print(f"\n{_C}▶ Step 2 · 生成 DAG{_X}")
    if parsed.dag_sketch and not no_llm:
        print(f"  {_D}检测到 DAG Sketch 节，优先使用（跳过 LLM 调用）{_X}")
        units_data = _parse_dag_sketch(parsed.dag_sketch, parsed.scope_units)
        if units_data:
            source = "DAG Sketch（手工定义）"
            print(f"  {_G}✅{_X} DAG Sketch 解析成功（{len(units_data)} 个 Unit）")
        else:
            print(f"  {_Y}⚠️  DAG Sketch 内容无法解析，回退到 LLM 生成{_X}")

    if units_data is None and not no_llm:
        # EP-132：动态获取实际使用的模型名（不硬编码）
        _dag_model_name = _get_dag_orchestration_model_name()
        print(f"  {_D}调用 LLM（{_dag_model_name}）生成 DAG...{_X}")
        layer_summary = _load_layer_contracts_summary()
        units_data = _call_llm_generate_dag(
            ep_id=parsed.ep_id,
            title=parsed.title,
            purpose=parsed.purpose,
            scope_units=parsed.scope_units,
            layer_contracts_summary=layer_summary,
        )
        if units_data:
            source = f"LLM 生成（{_dag_model_name}）"
            print(f"  {_G}✅{_X} LLM 生成成功（{len(units_data)} 个 Unit）")
        else:
            print(f"  {_Y}⚠️  LLM 生成失败，从 EP Scope 构建最简 DAG{_X}")

    # ── 回退：从 EP Scope 构建最简 DAG ──────────────────────────────────────
    if units_data is None:
        units_data = [
            {
                "id": su.unit_id,
                "title": su.description[:50],
                "layer": "unknown",
                "files": su.files,
                "test_files": [],
                "depends_on": [],
                "order": i + 1,  # 串行执行
                "model_hint": "capable",
            }
            for i, su in enumerate(parsed.scope_units)
        ]
        source = "EP Scope（最简串行 DAG）"
        print(f"  {_Y}⚠️  使用最简串行 DAG（{len(units_data)} 个 Unit）{_X}")

    # ── 原子性标注 ───────────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 3 · 原子性验证与 model_hint 标注{_X}")
    units_data = _annotate_atomicity(units_data)
    try:
        from mms_config import cfg as _cfg  # type: ignore[import]
    except ImportError:
        from mms.mms_config import cfg as _cfg  # type: ignore[import]
    # fallback: config.yaml → dag.atomicity_thresholds.report_threshold (default=0.75)
    report_threshold = _cfg.dag_report_threshold
    atomic_count = sum(1 for u in units_data if u.get("atomicity_score", 0) >= report_threshold)
    print(f"  {_G}✅{_X} {atomic_count}/{len(units_data)} 个 Unit 满足 8B 原子化标准")

    # ── 写入 DAG 状态文件 ────────────────────────────────────────────────────
    print(f"\n{_C}▶ Step 4 · 写入 DAG 状态文件{_X}")
    dag = make_dag_state(
        ep_id=ep_norm,
        units_data=units_data,
        orchestrator_model=_get_dag_orchestration_model_name(),
    )
    saved_path = dag.save()
    print(f"  {_G}✅{_X} 已写入：{saved_path.relative_to(_ROOT)}")
    print(f"  {_D}生成方式：{source}{_X}")

    # ── 打印概览 ─────────────────────────────────────────────────────────────
    _print_dag_overview(dag)

    print(f"\n{_D}下一步：{_X}")
    print(f"  {_C}mms unit status --ep {ep_norm}{_X}   # 查看执行状态")
    print(f"  {_C}mms unit next --ep {ep_norm}{_X}      # 获取下一个 Unit\n")

    return 0
