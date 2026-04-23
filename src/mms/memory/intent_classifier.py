#!/usr/bin/env python3
"""
intent_classifier.py — MMS-OG v3.0 意图分类器

将用户的自然语言任务描述映射到 {layer, operation, entry_files} 三元组。

两阶段分类：
  阶段 0（本地，无 LLM）：
    从 docs/memory/ontology/arch_schema/intent_map.yaml 加载规则，
    按 priority 顺序匹配关键词，计算置信度。
    置信度 ≥ 0.80 时直接返回结果，跳过 LLM 调用。

  阶段 1（小 prompt LLM，约 300-500 tokens）：
    仅在本地置信度 < 0.80 时触发。
    LLM 输入：layers.yaml 的层定义摘要 + 用户描述。
    LLM 输出：JSON {layer, operation, confidence, candidate_keywords}。
    LLM 禁止输出文件路径（路径由 arch_resolver.py 确定性生成）。

用法：
  from mms.memory.intent_classifier import IntentClassifier
  classifier = IntentClassifier()
  result = classifier.classify("把导航栏精简为只保留本体管理平台")
  # result.layer == "L5_frontend"
  # result.operation == "modify_config"
  # result.confidence == 0.92 (本地命中，跳过 LLM)
  # result.entry_files_hint == ["frontend/src/config/navigation.ts", ...]
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent
_SCHEMA_DIR = _ROOT / "docs" / "memory" / "ontology" / "arch_schema"
_INTENT_MAP_PATH = _SCHEMA_DIR / "intent_map.yaml"
_LAYERS_PATH = _SCHEMA_DIR / "layers.yaml"

try:
    sys.path.insert(0, str(_HERE))
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    """意图分类结果。"""

    layer: str                              # 主影响层，如 "L5_frontend"
    operation: str                          # 操作类型，如 "modify_config"
    confidence: float                       # 置信度 [0.0, 1.0]
    entry_files_hint: List[str]             # 该层的入口文件（非验证过的完整路径）
    matched_rule_id: str = ""               # 命中的规则 ID（调试用）
    matched_keywords: List[str] = field(default_factory=list)  # 匹配到的关键词
    from_llm: bool = False                  # 是否来自 LLM 分类

    @property
    def skip_llm_round1(self) -> bool:
        """置信度足够高时跳过第1轮 LLM 调用。"""
        return self.confidence >= 0.80 and not self.from_llm


# ── YAML 简单加载 ────────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    """加载 YAML 文件，优先用 PyYAML，降级为空 dict。"""
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore[import]
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


# ── 核心分类器 ───────────────────────────────────────────────────────────────

class IntentClassifier:
    """
    意图分类器。

    本地优先：先用 intent_map.yaml 关键词规则匹配，
    置信度不足时才调用 LLM（小 prompt，约 400 tokens）。
    """

    def __init__(self) -> None:
        self._intent_map: Optional[dict] = None
        self._layers_data: Optional[dict] = None

    def _ensure_loaded(self) -> None:
        if self._intent_map is None:
            self._intent_map = _load_yaml(_INTENT_MAP_PATH)
        if self._layers_data is None:
            self._layers_data = _load_yaml(_LAYERS_PATH)

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def classify(self, task: str, use_llm_fallback: bool = True) -> IntentResult:
        """
        对任务描述进行意图分类。

        参数：
            task:             用户任务描述（自然语言）
            use_llm_fallback: 本地置信度不足时是否调用 LLM（默认 True）

        返回：
            IntentResult（含 layer、operation、confidence、entry_files_hint）
        """
        self._ensure_loaded()

        # 阶段 0：本地规则匹配
        local_result = self._local_match(task)

        # 置信度足够，直接返回
        if local_result.skip_llm_round1:
            return local_result

        # 阶段 1：LLM 小 prompt 分类（仅在置信度不足时触发）
        if use_llm_fallback:
            llm_result = self._llm_classify(task, local_result)
            if llm_result:
                return llm_result

        # 回退：返回本地最佳结果（即使置信度低）
        return local_result

    def local_match_only(self, task: str) -> IntentResult:
        """纯本地匹配（不调用 LLM），用于测试或快速预览。"""
        self._ensure_loaded()
        return self._local_match(task)

    # ── 本地规则匹配 ─────────────────────────────────────────────────────────

    def _local_match(self, task: str) -> IntentResult:
        """
        按 intent_map.yaml 规则做本地关键词匹配。

        算法：
          1. 将任务描述转小写，进行关键词匹配
          2. 按 priority 从高到低遍历规则
          3. 计算每条规则的命中比例 = 命中关键词数 / 规则总关键词数
          4. 命中比例 ≥ min_hit_ratio 的规则参与得分计算
          5. 得分 = min(命中比例 × 2, 1.0) + confidence_boost（若配置）
          6. 选出得分最高的规则
        """
        task_lower = task.lower()
        # 中文字符拆分（按字粒度）+ 英文词拆分
        task_tokens = set(re.findall(r"[\u4e00-\u9fff]{1,}", task))
        task_tokens.update(
            w.lower() for w in re.split(r"[^\w]+", task) if len(w) >= 2
        )

        rules = self._intent_map.get("rules", [])
        global_min_ratio = self._intent_map.get("defaults", {}).get("min_hit_ratio", 0.12)
        global_threshold = self._intent_map.get("defaults", {}).get("confidence_threshold", 0.80)

        best_score = -1.0
        best_rule: Optional[dict] = None
        best_hits: List[str] = []

        for rule in sorted(rules, key=lambda r: r.get("priority", 0), reverse=True):
            keywords: List[str] = rule.get("keywords", [])
            if not keywords:
                continue

            min_ratio = rule.get("min_hit_ratio", global_min_ratio)

            # 计算命中的关键词
            hits = []
            for kw in keywords:
                kw_lower = kw.lower()
                # 关键词可能是中文词组或英文词
                if kw_lower in task_lower or any(
                    kw_lower in token for token in task_tokens
                ):
                    hits.append(kw)

            if not hits:
                continue

            hit_ratio = len(hits) / max(len(keywords), 1)
            if hit_ratio < min_ratio:
                continue

            # 置信度：命中比例×2（上限1.0）+ boost
            score = min(hit_ratio * 2.0, 1.0) + float(rule.get("confidence_boost", 0.0))
            score = min(score, 1.0)

            if score > best_score:
                best_score = score
                best_rule = rule
                best_hits = hits

        if best_rule is None:
            # 无任何匹配，返回通用低置信度兜底
            return self._fallback_result(task)

        return IntentResult(
            layer=best_rule.get("layer", "L4_service"),
            operation=best_rule.get("operation", "modify_logic"),
            confidence=round(best_score, 3),
            entry_files_hint=best_rule.get("entry_files_hint", []),
            matched_rule_id=best_rule.get("id", ""),
            matched_keywords=best_hits,
            from_llm=False,
        )

    def _fallback_result(self, task: str) -> IntentResult:
        """无规则命中时的最低置信度兜底。"""
        # 简单启发：后端词多 → L4_service，前端词多 → L5_frontend
        frontend_hints = {"前端", "页面", "react", "组件", "frontend", "navigation", "sidebar"}
        backend_hints = {"service", "api", "后端", "backend", "python", "fastapi"}

        task_lower = task.lower()
        f_score = sum(1 for w in frontend_hints if w in task_lower)
        b_score = sum(1 for w in backend_hints if w in task_lower)

        if f_score > b_score:
            return IntentResult(
                layer="L5_frontend", operation="modify_config",
                confidence=0.25, entry_files_hint=["frontend/src/"],
                matched_rule_id="fallback_frontend", matched_keywords=[],
            )
        return IntentResult(
            layer="L4_service", operation="modify_logic",
            confidence=0.20, entry_files_hint=["backend/app/services/"],
            matched_rule_id="fallback_backend", matched_keywords=[],
        )

    # ── LLM 分类（第1轮，小 prompt） ─────────────────────────────────────────

    def _llm_classify(self, task: str, local_hint: IntentResult) -> Optional[IntentResult]:
        """
        调用 LLM 做意图分类（小 prompt，约 400 tokens）。

        关键约束：
          - LLM 只被允许输出 layer 标签和 operation 标签
          - 禁止 LLM 输出任何文件路径（路径由 arch_resolver 确定性生成）
          - LLM 的回答必须是合法的 JSON

        失败时静默降级，返回 None（调用方会回退到本地结果）。
        """
        try:
            # 构建简短的 layers 摘要（约 200 tokens）
            layers_summary = self._build_layers_summary()

            system_prompt = """你是项目架构分类助手。根据用户任务描述，
从给定的架构层列表中选择最合适的层和操作类型。
输出格式必须是 JSON，且只包含以下字段：
{"layer": "层ID", "operation": "操作类型", "confidence": 0.0~1.0}
严禁输出任何文件路径。严禁在 JSON 之外添加任何文字。"""

            user_prompt = f"""架构层列表（简版）：
{layers_summary}

操作类型选项：create / modify_config / modify_logic / debug / delete / deploy / test / review

用户任务描述：
{task}

本地预判（供参考，可以推翻）：layer={local_hint.layer}, operation={local_hint.operation}, confidence={local_hint.confidence:.2f}

请输出 JSON："""

            response = self._call_llm(system_prompt, user_prompt)
            if not response:
                return None

            return self._parse_llm_response(response, task)

        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ [意图分类第1轮] LLM 调用失败（降级到本地结果）：{exc}", flush=True)
            return None

    def _build_layers_summary(self) -> str:
        """构建 layers.yaml 的简短摘要（用于 LLM prompt，约 200 tokens）。"""
        layers_data = self._layers_data or {}
        layers = layers_data.get("layers", {})
        lines = []
        for layer_id, layer_def in layers.items():
            label = layer_def.get("label", layer_id)
            kws = layer_def.get("keywords", [])[:4]  # 只取前4个关键词
            lines.append(f"- {layer_id}: {label}（关键词示例：{', '.join(kws)}）")
        return "\n".join(lines)

    def _call_llm(self, system: str, user: str) -> Optional[str]:
        """
        调用 LLM 做意图分类兜底（EP-132：修复 ProviderFactory.get_default() Bug）。

        使用 auto_detect("intent_classification") 路由到 bailian_plus（qwen3-32b）。
        置信度不足时才调用，约 400 tokens 的小 prompt。
        """
        sys.path.insert(0, str(_HERE.parent))
        sys.path.insert(0, str(_HERE))
        try:
            from mms.providers.factory import auto_detect  # type: ignore[import]
        except ImportError:
            try:
                from mms.providers.factory import auto_detect  # type: ignore[no-redef]
            except ImportError:
                return None

        try:
            # EP-132：使用 intent_classification 任务类型，路由到 bailian_plus
            provider = auto_detect("intent_classification")
            # fallback: config.yaml → runner.max_tokens.intent_routing (default=200)
            _max_tok = int(getattr(_cfg, "runner_max_tokens_intent_routing", 200)) if _cfg else 200
            full_prompt = f"{system}\n\n{user}"
            return provider.complete(full_prompt, max_tokens=_max_tok)
        except Exception:  # noqa: BLE001
            return None

    def _parse_llm_response(self, response: str, task: str) -> Optional[IntentResult]:
        """解析 LLM 返回的 JSON，提取 layer / operation / confidence。"""
        import json
        import re

        # 提取 JSON 块
        json_match = re.search(r"\{[^{}]+\}", response, re.DOTALL)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())
        except (json.JSONDecodeError, ValueError):
            return None

        layer = data.get("layer", "")
        operation = data.get("operation", "")
        confidence = float(data.get("confidence", 0.5))

        # 验证 layer 是否合法
        layers = (self._layers_data or {}).get("layers", {})
        if layer not in layers:
            return None

        # 从 layers.yaml 中获取入口文件
        entry_files = layers.get(layer, {}).get("entry_files", [])

        return IntentResult(
            layer=layer,
            operation=operation,
            confidence=round(confidence, 3),
            entry_files_hint=entry_files,
            matched_rule_id="llm_round1",
            matched_keywords=[],
            from_llm=True,
        )


# ── EP-131：磁盘路径验证 + 计划摘要 ──────────────────────────────────────────

def disk_validate_confidence(
    intent_result: IntentResult,
    root: Optional[Path] = None,
) -> IntentResult:
    """
    EP-131：基于 entry_files_hint 的磁盘路径验证，修正置信度。

    规则：
      - hint 中有 ≥ 50% 的路径在磁盘存在 → 置信度 +0.10（不超过 0.95）
      - hint 中 0% 路径存在且 hint 非空    → 置信度 × 0.5（强制降到灰区，最低 0.1）
      - hint 为空                          → 不修正（返回原 result）

    背景：有效的意图识别推断的文件路径应该"物理可达"。
    若所有推断路径不存在，说明意图匹配可能走错了层。

    Args:
        intent_result: 待验证的意图结果
        root:          项目根目录（默认从 _ROOT 全局变量获取）

    Returns:
        修正后的 IntentResult（不修改原对象）
    """
    project_root = root or _ROOT
    hints = intent_result.entry_files_hint
    if not hints:
        return intent_result

    exist_count = 0
    for hint in hints:
        # 支持目录路径和文件路径
        p = project_root / hint
        if p.exists():
            exist_count += 1

    total = len(hints)
    exist_ratio = exist_count / total

    new_confidence = intent_result.confidence
    if exist_ratio >= 0.5:
        new_confidence = min(intent_result.confidence + 0.10, 0.95)
    elif exist_ratio == 0.0:
        new_confidence = max(intent_result.confidence * 0.5, 0.10)

    if abs(new_confidence - intent_result.confidence) < 0.001:
        return intent_result

    # 返回修正后的新对象（不修改原对象）
    import dataclasses
    return dataclasses.replace(intent_result, confidence=round(new_confidence, 3))


def build_intent_plan_line(intent_result: IntentResult, unit_id: str = "") -> str:
    """
    EP-131：为单个 Unit 生成人类可读的计划摘要行。
    零 LLM 消耗，由确定性规则生成。

    示例输出：
      "U2 [capable] L4_service/modify_logic (confidence=0.72 ⚠灰区) unit_runner.py"

    Args:
        intent_result: 意图分类结果
        unit_id:       Unit ID（可选，用于展示）

    Returns:
        单行摘要字符串
    """
    grey_low = 0.60
    grey_high = 0.85
    is_grey = grey_low <= intent_result.confidence < grey_high

    grey_tag = " ⚠灰区" if is_grey else ""
    unit_prefix = f"{unit_id} " if unit_id else ""
    files_str = ", ".join(intent_result.entry_files_hint[:3])
    if len(intent_result.entry_files_hint) > 3:
        files_str += f" (+{len(intent_result.entry_files_hint) - 3})"

    return (
        f"{unit_prefix}[{intent_result.layer}/{intent_result.operation}]"
        f" confidence={intent_result.confidence:.2f}{grey_tag}"
        f"  ← {intent_result.matched_rule_id}"
        f"  files: {files_str}"
    )


# ── CLI 入口（调试用）────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    task = " ".join(sys.argv[1:]) or "把导航栏精简为只保留本体管理平台"
    classifier = IntentClassifier()

    print(f"\n任务：{task}\n")

    # 纯本地匹配
    local = classifier.local_match_only(task)
    print(f"[本地匹配]")
    print(f"  layer      = {local.layer}")
    print(f"  operation  = {local.operation}")
    print(f"  confidence = {local.confidence:.3f}  {'✅ 跳过LLM' if local.skip_llm_round1 else '⚠ 需LLM补充'}")
    print(f"  命中规则   = {local.matched_rule_id}")
    print(f"  命中关键词 = {local.matched_keywords}")
    print(f"  入口文件   = {json.dumps(local.entry_files_hint, ensure_ascii=False)}")
