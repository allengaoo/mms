"""
task_decomposer.py — 任务分解器（AIU 序列生成）

将用户任务描述分解为有序的原子意图单元（AIU）序列。
类比数据库查询优化器的 Logical Plan → Physical Plan 阶段。

分解策略（两阶段，RBO 优先）：
  阶段 1  RBO（Rule-Based Optimizer）:
          基于关键词规则匹配 12 种高频 AIU 类型。
          无 LLM 调用，零延迟，100% 确定性。
          覆盖约 70% 的常见开发任务。

  阶段 2  LLM 兜底（仅在 RBO miss 时触发）:
          RBO 无法分解时，调用 qwen3-coder-next 分解。
          输入：任务描述 + AIU 类型列表。
          输出：JSON {steps: [{aiu_type, description, target_files, depends_on}]}。

触发条件（由调用方控制）：
  - intent.confidence < 0.6（粗粒度意图识别置信度低）
  - 任务描述包含"且/以及/另外/同时/并且"等并列连词
  - 任务描述长度 > 100 字符且涉及多个层

与 DagUnit 的关系：
  DagUnit 已经存在时，task_decomposer 为其生成 AIUPlan（子步骤）。
  DagUnit 不存在时，可独立使用（synthesizer 场景）。

EP-129 | 2026-04-22
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent

try:
    sys.path.insert(0, str(_HERE))
    from mms.dag.aiu_types import (  # type: ignore[import]
        AIUType, AIUStep, AIUPlan, AIU_EXEC_ORDER, AIU_LAYER_MAP,
        RBO_COVERED_AIU_TYPES,
    )
    from mms.utils.mms_config import cfg as _cfg  # type: ignore[import]
except ImportError:
    try:
        from mms.dag.aiu_types import (  # type: ignore[import]
            AIUType, AIUStep, AIUPlan, AIU_EXEC_ORDER, AIU_LAYER_MAP,
            RBO_COVERED_AIU_TYPES,
        )
    except ImportError:
        raise
    _cfg = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _cfg_float(attr: str, default: float) -> float:
    if _cfg is None:
        return default
    return float(getattr(_cfg, attr, default))


def _cfg_int(attr: str, default: int) -> int:
    if _cfg is None:
        return default
    return int(getattr(_cfg, attr, default))


def _token_budget_fast() -> int:
    """返回 fast 模型的 token budget（从 cfg 读取，默认 2000）。"""
    return _cfg_int("runner_token_budget_fast", 2000)


def _token_budget_capable() -> int:
    """返回 capable 模型的 token budget（从 cfg 读取，默认 4000）。"""
    return _cfg_int("runner_token_budget_capable", 4000)


def _cfg_bool(attr: str, default: bool) -> bool:
    if _cfg is None:
        return default
    return bool(getattr(_cfg, attr, default))


# ── 常量（优先从 mms_config 读取，硬编码为 fallback）──────────────────────────

# 任务分解触发条件：意图置信度低于此值时自动触发
DECOMPOSE_CONFIDENCE_THRESHOLD: float = _cfg_float("decomposer_confidence_threshold", 0.6)

# 任务描述超过此长度时，如果涉及多层，自动触发分解
LONG_TASK_THRESHOLD: int = _cfg_int("decomposer_long_task_threshold", 80)

# LLM 兜底分解的最大 token 数
LLM_DECOMPOSE_MAX_TOKENS: int = _cfg_int("decomposer_llm_max_tokens", 2000)

# 是否对所有 RBO 命中结果强制追加 TEST_ADD_UNIT（可按 operation 类型关闭）
AUTO_APPEND_TEST: bool = _cfg_bool("decomposer_auto_append_test", True)

# 不追加测试的操作类型（即使 AUTO_APPEND_TEST=True）
NO_TEST_OPERATIONS = frozenset({"review", "doc_sync", "debug_read_only"})

# 任务描述中触发分解的并列连词
CONJUNCTION_PATTERNS = [
    "且", "以及", "另外", "同时", "并且", "还需要", "另需", "同步",
    "and ", " and", "also", "additionally", "furthermore",
]


# ── RBO 规则库 ────────────────────────────────────────────────────────────────

# 每条 RBO 规则：{keywords, aiu_type, description_template, layer, files_patterns}
RBO_RULES: List[Dict] = [
    {
        "id": "rbo_schema_add_field",
        "aiu_type": AIUType.SCHEMA_ADD_FIELD,
        "keywords": [
            "新增字段", "添加字段", "加字段", "新增列", "add field", "add column",
            "新增属性", "添加属性", "扩展模型",
        ],
        "description_template": "在 {model} 模型新增字段，生成 Alembic migration",
        "token_budget": 3000,
        "model_hint": "fast",
        "files_hint": ["backend/app/domain/", "backend/alembic/versions/"],
    },
    {
        "id": "rbo_contract_add_response",
        "aiu_type": AIUType.CONTRACT_ADD_RESPONSE,
        "keywords": [
            "响应模型", "response model", "responseSchema", "返回结构",
            "返回字段", "response schema", "pydantic response",
        ],
        "description_template": "新增 {entity} 的 Pydantic Response Schema",
        "token_budget": _token_budget_fast(),
        "model_hint": "fast",
        "files_hint": ["backend/app/api/v1/schemas/"],
    },
    {
        "id": "rbo_contract_add_request",
        "aiu_type": AIUType.CONTRACT_ADD_REQUEST,
        "keywords": [
            "请求模型", "request model", "requestSchema", "请求体",
            "入参", "request schema", "pydantic request",
        ],
        "description_template": "新增 {entity} 的 Pydantic Request Schema",
        "token_budget": _token_budget_fast(),
        "model_hint": "fast",
        "files_hint": ["backend/app/api/v1/schemas/"],
    },
    {
        "id": "rbo_mutation_insert",
        "aiu_type": AIUType.MUTATION_ADD_INSERT,
        "keywords": [
            "新增", "创建", "create", "insert", "添加记录", "写入",
            "新建", "保存", "持久化",
        ],
        "description_template": "在 {entity} Repository 新增 create 方法",
        "token_budget": 3500,
        "model_hint": "fast",
        "files_hint": ["backend/app/domain/", "backend/app/services/control/"],
    },
    {
        "id": "rbo_mutation_update",
        "aiu_type": AIUType.MUTATION_ADD_UPDATE,
        "keywords": [
            "更新", "修改", "update", "edit", "变更", "改变状态",
            "批量更新", "部分更新",
        ],
        "description_template": "在 {entity} Service 新增 update 方法",
        "token_budget": 3500,
        "model_hint": "fast",
        "files_hint": ["backend/app/services/control/"],
    },
    {
        "id": "rbo_query_select",
        "aiu_type": AIUType.QUERY_ADD_SELECT,
        "keywords": [
            "查询", "列表", "list", "select", "搜索", "过滤",
            "分页查询", "查找", "检索",
        ],
        "description_template": "在 {entity} Repository 新增查询方法",
        "token_budget": 3000,
        "model_hint": "fast",
        "files_hint": ["backend/app/domain/", "backend/app/services/control/"],
    },
    {
        "id": "rbo_route_add_endpoint",
        "aiu_type": AIUType.ROUTE_ADD_ENDPOINT,
        "keywords": [
            "api", "endpoint", "接口", "路由", "router", "handler",
            "http", "get/post/put/delete", "restful",
        ],
        "description_template": "在 {module} 模块新增 FastAPI {method} 路由",
        "token_budget": 3500,
        "model_hint": "fast",
        "files_hint": ["backend/app/api/v1/endpoints/"],
    },
    {
        "id": "rbo_route_permission",
        "aiu_type": AIUType.ROUTE_ADD_PERMISSION,
        "keywords": [
            "权限", "permission", "rbac", "require_permission",
            "授权", "access control", "鉴权",
        ],
        "description_template": "为 {endpoint} 添加 @require_permission 权限守卫",
        "token_budget": 1500,
        "model_hint": "fast",
        "files_hint": ["backend/app/api/v1/endpoints/", "backend/app/core/rbac.py"],
    },
    {
        "id": "rbo_logic_guard",
        "aiu_type": AIUType.LOGIC_ADD_GUARD,
        "keywords": [
            "校验", "validate", "validation", "前置检查", "参数检查",
            "输入验证", "raise exception", "抛出异常",
        ],
        "description_template": "在 {method} 方法新增前置校验逻辑",
        "token_budget": _token_budget_fast(),
        "model_hint": "fast",
        "files_hint": ["backend/app/services/control/"],
    },
    {
        "id": "rbo_test_unit",
        "aiu_type": AIUType.TEST_ADD_UNIT,
        "keywords": [
            "测试", "test", "pytest", "单元测试", "unit test",
            "mock", "补充测试", "test case",
        ],
        "description_template": "为 {module} 补充 pytest 单元测试",
        "token_budget": 3000,
        "model_hint": "fast",
        "files_hint": ["backend/tests/unit/", "scripts/mms/tests/"],
    },
    {
        "id": "rbo_doc_sync",
        "aiu_type": AIUType.DOC_SYNC,
        "keywords": [
            "文档", "docs", "e2e_traceability", "frontend_page_map",
            "同步文档", "更新文档", "doc sync",
        ],
        "description_template": "同步更新架构文档（e2e_traceability / frontend_page_map）",
        "token_budget": 1500,
        "model_hint": "fast",
        "files_hint": [
            "docs/architecture/e2e_traceability.md",
            "docs/architecture/frontend_page_map.md",
        ],
    },
    {
        "id": "rbo_config_modify",
        "aiu_type": AIUType.CONFIG_MODIFY,
        "keywords": [
            "配置", "feature flag", "systemconfig", "开关", "config",
            "feature toggle", "环境变量", "系统配置",
        ],
        "description_template": "修改系统配置 / Feature Flag",
        "token_budget": 1500,
        "model_hint": "fast",
        "files_hint": ["backend/app/core/", "docs/memory/ontology/arch_schema/"],
    },
]


# ── LLM 分解 Prompt ───────────────────────────────────────────────────────────

_LLM_DECOMPOSE_SYSTEM = """\
你是 MDP 平台的任务分解专家。将用户的软件开发任务描述分解为原子意图单元（AIU）序列。

每个 AIU 只做一件事，最多涉及 2 个文件，上下文 ≤ 4000 tokens。
AIU 必须按执行顺序排列（结构定义 → 数据读写 → 业务逻辑 → 接口路由 → 测试 → 文档）。

可用的 AIU 类型：
{aiu_types_list}

输出格式（JSON，不要输出任何其他内容）：
{{
  "steps": [
    {{
      "aiu_type": "类型字符串（从上面列表选择）",
      "description": "一句话描述这个步骤做什么",
      "target_files": ["文件路径1", "文件路径2"],
      "depends_on": ["前置 aiu_id，如 aiu_1"],
      "token_budget": 数字（1000-4000）,
      "model_hint": "fast 或 capable"
    }}
  ],
  "decomposed_by": "llm",
  "confidence": 0.7
}}
"""

_LLM_DECOMPOSE_USER = """\
任务描述：{task}

相关上下文（意图分类结果）：
- 主影响层：{layer}
- 操作类型：{operation}
- 置信度：{confidence}

请将此任务分解为 AIU 步骤序列。
"""


# ── 主类 ─────────────────────────────────────────────────────────────────────

class TaskDecomposer:
    """
    任务分解器：将任务描述分解为 AIUPlan（AIU 步骤序列）。

    两阶段策略：
      1. RBO（规则驱动）：关键词匹配 12 种高频 AIU
      2. LLM 兜底：RBO miss 时调用 LLM 分解
    """

    def __init__(self) -> None:
        self._rbo_rules = RBO_RULES

    @staticmethod
    def should_decompose(task: str, confidence: float) -> bool:
        """
        判断是否需要触发 AIU 分解。

        触发条件（满足任一）：
          1. 意图置信度 < 0.6
          2. 任务描述包含并列连词（"且/以及/另外"等）
          3. 任务描述长度 > 80 字符且 RBO 能匹配多种类型
        """
        if confidence < DECOMPOSE_CONFIDENCE_THRESHOLD:
            return True

        task_lower = task.lower()
        for conj in CONJUNCTION_PATTERNS:
            if conj in task_lower:
                return True

        if len(task) > LONG_TASK_THRESHOLD:
            # 粗略检查是否涉及多个 AIU 类型关键词
            matched_rules = 0
            for rule in RBO_RULES:
                if any(kw in task_lower for kw in rule["keywords"]):
                    matched_rules += 1
                    if matched_rules >= 2:
                        return True

        return False

    def decompose(
        self,
        task: str,
        dag_unit_id: str,
        layer: str = "L4_application",
        operation: str = "modify_logic",
        confidence: float = 0.5,
        files_hint: Optional[List[str]] = None,
    ) -> AIUPlan:
        """
        分解任务描述为 AIUPlan。

        Args:
            task: 用户任务描述
            dag_unit_id: 所属 DagUnit ID
            layer: 粗粒度意图识别的层
            operation: 粗粒度意图识别的操作类型
            confidence: 粗粒度意图识别的置信度
            files_hint: DagUnit 中声明的涉及文件列表

        Returns:
            AIUPlan（含有序 AIU 步骤列表）
        """
        # 暂存 operation 供 _rbo_decompose 判断是否追加 TEST
        self._current_operation = operation

        # Phase 1: RBO 分解
        rbo_steps, rbo_confidence = self._rbo_decompose(task, files_hint or [])

        if rbo_steps:
            plan = AIUPlan(
                dag_unit_id=dag_unit_id,
                steps=self._assign_ids_and_order(rbo_steps),
                decomposed_by="rbo",
                confidence=rbo_confidence,
                original_task=task,
            )
            return plan

        # Phase 2: LLM 兜底
        llm_steps, llm_confidence = self._llm_decompose(task, layer, operation, confidence)

        if llm_steps:
            plan = AIUPlan(
                dag_unit_id=dag_unit_id,
                steps=self._assign_ids_and_order(llm_steps),
                decomposed_by="llm",
                confidence=llm_confidence,
                original_task=task,
            )
            return plan

        # Fallback: 返回单步骤 Plan（等同于不分解）
        fallback_step = AIUStep(
            aiu_id="aiu_1",
            aiu_type=AIUType.LOGIC_ADD_CONDITION.value,
            description=f"执行任务：{task[:80]}",
            layer=layer,
            target_files=files_hint or [],
            depends_on=[],
            exec_order=3,
            token_budget=_token_budget_capable(),
            model_hint="capable",
        )
        return AIUPlan(
            dag_unit_id=dag_unit_id,
            steps=[fallback_step],
            decomposed_by="fallback",
            confidence=0.3,
            original_task=task,
        )

    def _rbo_decompose(
        self, task: str, files_hint: List[str]
    ) -> Tuple[List[AIUStep], float]:
        """
        RBO（规则驱动）分解：关键词匹配 → AIU 步骤列表。

        Returns:
            (steps, confidence)，steps 为空时表示 RBO miss
        """
        task_lower = task.lower()
        matched: List[Tuple[int, Dict]] = []  # (hit_count, rule)

        for rule in self._rbo_rules:
            hits = sum(1 for kw in rule["keywords"] if kw in task_lower)
            if hits > 0:
                matched.append((hits, rule))

        if not matched:
            return [], 0.0

        # 按命中数降序排序，去重（同类型只保留命中最多的）
        matched.sort(key=lambda x: -x[0])
        seen_types: set = set()
        deduped = []
        for hit_count, rule in matched:
            aiu_type = rule["aiu_type"]
            if aiu_type not in seen_types:
                seen_types.add(aiu_type)
                deduped.append((hit_count, rule))

        # 构建 AIUStep 列表（按执行顺序排序）
        steps: List[AIUStep] = []
        for hit_count, rule in deduped:
            aiu_type_val: AIUType = rule["aiu_type"]
            layer = AIU_LAYER_MAP.get(aiu_type_val, "L4_application")
            exec_order = AIU_EXEC_ORDER.get(aiu_type_val, 3)

            # 确定目标文件：优先从 files_hint 中匹配，否则用规则默认
            target_files = self._match_files(files_hint, rule.get("files_hint", []))

            step = AIUStep(
                aiu_id="",  # 稍后由 _assign_ids_and_order 填充
                aiu_type=aiu_type_val.value,
                description=rule["description_template"],
                layer=layer,
                target_files=target_files,
                depends_on=[],  # 稍后由 _assign_ids_and_order 设置依赖
                exec_order=exec_order,
                token_budget=rule.get("token_budget", 3000),
                model_hint=rule.get("model_hint", "fast"),
            )
            steps.append(step)

        # 按配置决定是否追加测试 Unit（排除 review/doc_sync 类纯文档操作）
        test_types = {AIUType.TEST_ADD_UNIT.value, AIUType.TEST_ADD_INTEGRATION.value}
        _operation = getattr(self, "_current_operation", "")
        _should_append_test = (
            AUTO_APPEND_TEST
            and _operation not in NO_TEST_OPERATIONS
        )
        if _should_append_test and not any(s.aiu_type in test_types for s in steps) and len(steps) > 0:
            test_rule = next(
                (r for r in self._rbo_rules if r["aiu_type"] == AIUType.TEST_ADD_UNIT),
                None
            )
            if test_rule:
                steps.append(AIUStep(
                    aiu_id="",
                    aiu_type=AIUType.TEST_ADD_UNIT.value,
                    description="为本次变更补充 pytest 单元测试",
                    layer="testing",
                    target_files=self._match_files(files_hint, test_rule.get("files_hint", [])),
                    depends_on=[],
                    exec_order=AIU_EXEC_ORDER[AIUType.TEST_ADD_UNIT],
                    token_budget=test_rule.get("token_budget", 3000),
                    model_hint=test_rule.get("model_hint", "fast"),
                ))

        # 置信度：命中规则数 / 可能的最大规则数
        confidence = min(len(deduped) / max(len(RBO_COVERED_AIU_TYPES), 1) * 4, 1.0)
        return steps, round(confidence, 2)

    def _llm_decompose(
        self,
        task: str,
        layer: str,
        operation: str,
        confidence: float,
    ) -> Tuple[List[AIUStep], float]:
        """
        LLM 兜底分解。调用 qwen3-coder-next 分解任务。

        Returns:
            (steps, confidence)
        """
        try:
            sys.path.insert(0, str(_HERE))
            from mms.providers.factory import get_provider_for_task  # type: ignore[import]
        except ImportError:
            return [], 0.0

        aiu_types_list = "\n".join(
            f"  - {t.value}: {t.name}" for t in AIUType
        )
        system_prompt = _LLM_DECOMPOSE_SYSTEM.format(aiu_types_list=aiu_types_list)
        user_prompt = _LLM_DECOMPOSE_USER.format(
            task=task,
            layer=layer,
            operation=operation,
            confidence=confidence,
        )

        try:
            provider = get_provider_for_task("code_generation")
            if provider is None:
                return [], 0.0
            raw = provider.complete(
                system_prompt + "\n\n" + user_prompt,
                max_tokens=LLM_DECOMPOSE_MAX_TOKENS,
            )
            return self._parse_llm_response(raw)
        except Exception as exc:
            logger.warning("TaskDecomposer LLM 分解失败: %s", exc, exc_info=True)
            return [], 0.0

    def _parse_llm_response(self, raw: str) -> Tuple[List[AIUStep], float]:
        """解析 LLM 返回的 JSON 为 AIUStep 列表。"""
        if not raw or not raw.strip():
            logger.debug("TaskDecomposer LLM 返回空响应")
            return [], 0.0

        # 优先提取 ```json ... ``` 代码块；不存在时再用 raw_decode 精确解析
        code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if code_block:
            candidate = code_block.group(1).strip()
        else:
            # raw_decode 从第一个 '{' 开始，避免贪婪匹配多 JSON 的问题
            brace_start = raw.find("{")
            if brace_start == -1:
                return [], 0.0
            candidate = raw[brace_start:]

        try:
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(candidate)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("TaskDecomposer JSON 解析失败: %s", exc)
            return [], 0.0

        if not isinstance(data, dict):
            return [], 0.0

        steps_data = data.get("steps", [])
        if not steps_data:
            return [], 0.0

        steps: List[AIUStep] = []
        valid_types = {t.value for t in AIUType}

        for s in steps_data:
            aiu_type_str = s.get("aiu_type", "")
            if aiu_type_str not in valid_types:
                continue

            aiu_type_val = AIUType(aiu_type_str)
            layer = AIU_LAYER_MAP.get(aiu_type_val, "L4_application")
            exec_order = AIU_EXEC_ORDER.get(aiu_type_val, 3)

            step = AIUStep(
                aiu_id="",  # 稍后填充
                aiu_type=aiu_type_str,
                description=s.get("description", f"执行 {aiu_type_str}"),
                layer=layer,
                target_files=s.get("target_files", []),
                depends_on=s.get("depends_on", []),
                exec_order=exec_order,
                token_budget=int(s.get("token_budget", 3000)),
                model_hint=s.get("model_hint", "fast"),
            )
            steps.append(step)

        llm_confidence = float(data.get("confidence", 0.7))
        return steps, llm_confidence

    @staticmethod
    def _match_files(dag_files: List[str], hint_prefixes: List[str]) -> List[str]:
        """
        从 DagUnit.files 中过滤出匹配 hint_prefixes 前缀的文件。

        - dag_files 为空时：只返回 hint_prefixes 中确实是文件（非目录）的项，
          避免将目录路径误传为目标文件。
        - 有 dag_files 时：优先按前缀过滤；无匹配则返回前两个真实文件。
        """
        if not dag_files:
            # 过滤掉目录/不存在路径，只保留文件
            real_files = [
                p for p in hint_prefixes
                if p and (_ROOT / p).is_file()
            ]
            return real_files if real_files else [p for p in hint_prefixes if p][:2]

        matched = [
            f for f in dag_files
            if any(f.startswith(prefix) for prefix in hint_prefixes)
        ]
        return matched if matched else dag_files[:2]

    @staticmethod
    def _assign_ids_and_order(steps: List[AIUStep]) -> List[AIUStep]:
        """
        为步骤分配 aiu_id 并设置依赖关系（按 exec_order 前后依赖）。

        策略：
          - 按 exec_order 升序排序
          - 同 exec_order 的步骤可并行（无相互依赖）
          - 高 order 的步骤依赖所有低 order 的步骤
        """
        # 按执行顺序排序
        steps.sort(key=lambda s: s.exec_order)

        # 分配 aiu_id
        for i, step in enumerate(steps, 1):
            step.aiu_id = f"aiu_{i}"

        # 设置依赖关系
        order_groups: Dict[int, List[str]] = {}
        for step in steps:
            order_groups.setdefault(step.exec_order, []).append(step.aiu_id)

        sorted_orders = sorted(order_groups.keys())
        for i, order in enumerate(sorted_orders):
            if i == 0:
                # 第一组无依赖
                continue
            prev_order = sorted_orders[i - 1]
            prev_ids = order_groups[prev_order]
            for step in steps:
                if step.exec_order == order and not step.depends_on:
                    step.depends_on = list(prev_ids)

        return steps


# ── EP-130 新增：动态 Token-Fit 上下文打包 ───────────────────────────────────

# 上下文打包的各部分优先级（降级时按优先级截断）
_CONTEXT_PRIORITIES = [
    "task_description",   # 1. 任务描述（必留）
    "ontology_constraints",  # 2. Ontology 约束（必留）
    "ast_direct",         # 3. 目标文件 AST 骨架（必留）
    "ast_neighbors",      # 4. 邻居文件 AST 骨架（可截断）
    "memory_context",     # 5. 历史记忆上下文（可截断）
]

# 各部分的字符/token 近似换算（len // 4）
_CHARS_PER_TOKEN = 4

_CONTEXT_SECTION_HEADERS = {
    "task_description":     "=== TASK ===",
    "ontology_constraints": "=== SEMANTIC CONSTRAINTS (ONTOLOGY) ===",
    "ast_direct":           "=== PHYSICAL SKELETON (AST: Direct Files) ===",
    "ast_neighbors":        "=== PHYSICAL SKELETON (AST: Context Files) ===",
    "memory_context":       "=== MEMORY CONTEXT ===",
}


def build_constrained_context(
    task_description: str,
    aiu_step,
    intent_result=None,
    memory_context: str = "",
    token_budget: int = 4000,
) -> str:
    """
    EP-130 双轨上下文打包：将 AST 骨架 + Ontology 约束 + 记忆上下文
    动态裁剪至 token_budget，使用 aider 风格的二分搜索 Token-Fit 策略。

    Args:
        task_description: 原始任务描述文本
        aiu_step: AIUStep 对象（含 target_files, token_budget 等）
        intent_result: fn_classify_intent 的输出（用于 arch_resolver 双轨路由）
        memory_context: injector 注入的历史记忆字符串
        token_budget: 最大 token 预算（优先用 aiu_step.token_budget）

    Returns:
        格式化的上下文字符串，保证 ≤ token_budget tokens
    """
    actual_budget = getattr(aiu_step, "token_budget", None) or token_budget
    target_files = list(getattr(aiu_step, "target_files", []) or [])

    # ── 获取 AST 骨架 ─────────────────────────────────────────────────────────
    ast_direct = ""
    ast_neighbors = ""
    ontology_hints: List[str] = []

    if target_files:
        try:
            sys.path.insert(0, str(_HERE))
            from mms.analysis.arch_resolver import ArchResolver  # type: ignore[import]
            resolver = ArchResolver()

            if intent_result is not None:
                dual_result = resolver.resolve_with_ast_skeleton(
                    intent_result,
                    token_budget=actual_budget // 2,
                )
                ast_direct = dual_result.get("ast_skeleton", "")
                ontology_hints = dual_result.get("ontology_constraints", [])
            else:
                from mms.memory.repo_map import RepoMap  # type: ignore[import]
                rm = RepoMap()
                ast_direct = rm.build_context(
                    target_files=target_files,
                    token_budget=actual_budget // 2,
                    include_neighbors=False,
                )
                ast_neighbors = rm.build_context(
                    target_files=target_files,
                    token_budget=actual_budget // 4,
                    include_neighbors=True,
                )
                # 去掉 ast_direct 中已有的文件
                if ast_direct and ast_neighbors:
                    for line in ast_direct.split("\n"):
                        if line.strip() and not line.startswith("⋮"):
                            ast_neighbors = ast_neighbors.replace(line, "").strip()
        except Exception:
            pass  # 静默降级，不影响流程

    # ── 构建各部分内容 ───────────────────────────────────────────────────────
    sections = {
        "task_description": task_description,
        "ontology_constraints": "\n".join(
            f"[{h}]" for h in ontology_hints
        ) if ontology_hints else "",
        "ast_direct": ast_direct,
        "ast_neighbors": ast_neighbors,
        "memory_context": memory_context,
    }

    # ── 动态 Token-Fit（按优先级填充）──────────────────────────────────────────
    result_parts = []
    remaining_budget = actual_budget

    for section_key in _CONTEXT_SECTION_HEADERS.keys():
        content = sections.get(section_key, "")
        if not content:
            continue

        header = _CONTEXT_SECTION_HEADERS[section_key]
        full_section = f"{header}\n{content}"
        section_tokens = len(full_section) // _CHARS_PER_TOKEN

        if remaining_budget <= 0:
            break

        if section_tokens <= remaining_budget:
            result_parts.append(full_section)
            remaining_budget -= section_tokens
        else:
            # 截断到剩余预算
            max_chars = remaining_budget * _CHARS_PER_TOKEN
            truncated = full_section[:max_chars]
            if truncated.strip():
                result_parts.append(truncated + "\n[...截断，超出 token 预算...]")
            remaining_budget = 0
            break

    return "\n\n".join(result_parts)


# ── CLI 快速测试 ──────────────────────────────────────────────────────────────

def _demo() -> None:
    """快速演示：将几个典型任务分解为 AIU 序列。"""
    decomposer = TaskDecomposer()

    demo_tasks = [
        ("为对象类型新增批量导出 API，同时要补充权限控制和单元测试", "L4_application", "modify_logic", 0.45),
        ("修复 Kafka 消费者丢消息的问题", "L2_infrastructure", "debug", 0.72),
        ("新增前端页面，绑定对象列表 API，使用 Zustand 管理状态", "L5_interface", "create", 0.40),
        ("把导航栏精简为只保留本体管理模块", "L5_interface", "modify_config", 0.85),
    ]

    for task, layer, op, conf in demo_tasks:
        print(f"\n{'='*60}")
        print(f"任务: {task}")
        print(f"意图: layer={layer}, op={op}, conf={conf}")
        print(f"触发分解: {TaskDecomposer.should_decompose(task, conf)}")

        plan = decomposer.decompose(task, "U_demo", layer, op, conf)
        print(f"分解方式: {plan.decomposed_by} (置信度={plan.confidence})")
        print(f"AIU 步骤数: {len(plan.steps)}")
        for step in plan.steps:
            deps = f" ← {step.depends_on}" if step.depends_on else ""
            print(f"  [{step.aiu_id}] {step.aiu_type:<30} budget={step.token_budget} model={step.model_hint}{deps}")


if __name__ == "__main__":
    _demo()
