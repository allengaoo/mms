"""
aiu_types.py — 原子意图单元（Atomic Intent Unit）数据结构定义

AIU 是 MMS 代码生成的最小可执行单元，类比数据库查询优化器中的"算子"。
每个 AIU 只做一件事，可独立验证，上下文 ≤ 4000 tokens（8B 模型可直接执行）。

AIU 分类（6 大族，28 种）：
  族 A: 结构定义类（Schema Operators）      — A1-A6
  族 B: 逻辑流控制类（Control Flow）         — B1-B5
  族 C: 数据读写类（Data Access）            — C1-C5
  族 D: 接口与路由类（Interface）             — D1-D5
  族 E: 事件与基础设施类（Infrastructure）    — E1-E4
  族 F: 质量保障类（Validation）             — F1-F3

与 DagUnit 的关系：
  DagUnit 是"文件级"执行单元（涉及 1-2 个文件）。
  AIU 是 DagUnit 内部的"语义级"子步骤（一个操作类型）。
  DagUnit.aiu_steps = List[AIUStep]

EP-129 | 2026-04-22
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ── AIU 类型枚举 ─────────────────────────────────────────────────────────────

class AIUType(str, Enum):
    """
    28 种原子意图单元类型。
    命名规则：{族}_{动作}_{对象}
    """

    # 族 A：结构定义类（Schema Operators）
    SCHEMA_ADD_FIELD         = "SCHEMA_ADD_FIELD"         # A1: SQLModel 新增字段 + migration
    SCHEMA_MODIFY_FIELD      = "SCHEMA_MODIFY_FIELD"      # A2: 字段类型/索引变更
    SCHEMA_ADD_RELATION      = "SCHEMA_ADD_RELATION"      # A3: 新增 ORM relationship
    CONTRACT_ADD_REQUEST     = "CONTRACT_ADD_REQUEST"     # A4: 新增 Pydantic Request Schema
    CONTRACT_ADD_RESPONSE    = "CONTRACT_ADD_RESPONSE"    # A5: 新增 Pydantic Response Schema
    CONTRACT_MODIFY_RESPONSE = "CONTRACT_MODIFY_RESPONSE" # A6: 修改 Response Schema 字段

    # 族 B：逻辑流控制类（Control Flow Operators）
    LOGIC_ADD_CONDITION    = "LOGIC_ADD_CONDITION"    # B1: 新增业务条件判断（if/elif）
    LOGIC_ADD_BRANCH       = "LOGIC_ADD_BRANCH"       # B2: 新增策略分支（状态机迁移）
    LOGIC_ADD_LOOP         = "LOGIC_ADD_LOOP"         # B3: 新增批处理逻辑（for 循环）
    LOGIC_EXTRACT_METHOD   = "LOGIC_EXTRACT_METHOD"   # B4: 抽取方法（重构）
    LOGIC_ADD_GUARD        = "LOGIC_ADD_GUARD"        # B5: 新增前置校验（raise DomainException）

    # 族 C：数据读写类（Data Access Operators）
    QUERY_ADD_SELECT    = "QUERY_ADD_SELECT"    # C1: 新增 Repository.find 查询方法
    QUERY_ADD_FILTER    = "QUERY_ADD_FILTER"    # C2: 新增查询过滤条件
    MUTATION_ADD_INSERT = "MUTATION_ADD_INSERT" # C3: 新增 Repository.create 方法
    MUTATION_ADD_UPDATE = "MUTATION_ADD_UPDATE" # C4: 新增 Repository.update 方法
    MUTATION_ADD_DELETE = "MUTATION_ADD_DELETE" # C5: 新增软删除逻辑

    # 族 D：接口与路由类（Interface Operators）
    ROUTE_ADD_ENDPOINT  = "ROUTE_ADD_ENDPOINT"  # D1: 新增 FastAPI 路由
    ROUTE_ADD_PERMISSION = "ROUTE_ADD_PERMISSION" # D2: 新增 @require_permission 守卫
    FRONTEND_ADD_PAGE   = "FRONTEND_ADD_PAGE"   # D3: 新增 React 页面组件
    FRONTEND_ADD_STORE  = "FRONTEND_ADD_STORE"  # D4: 新增 Zustand Store
    FRONTEND_BIND_API   = "FRONTEND_BIND_API"   # D5: 前端绑定后端 API（service.ts）

    # 族 E：事件与基础设施类（Infrastructure Operators）
    EVENT_ADD_PRODUCER  = "EVENT_ADD_PRODUCER"  # E1: 新增 Kafka 事件发布
    EVENT_ADD_CONSUMER  = "EVENT_ADD_CONSUMER"  # E2: 新增 Kafka Consumer
    CACHE_ADD_READ      = "CACHE_ADD_READ"      # E3: 新增 @cached 读缓存
    CONFIG_MODIFY       = "CONFIG_MODIFY"       # E4: 修改 SystemConfig / Feature Flag

    # 族 F：质量保障类（Validation Operators）
    TEST_ADD_UNIT        = "TEST_ADD_UNIT"        # F1: 新增 pytest 单元测试
    TEST_ADD_INTEGRATION = "TEST_ADD_INTEGRATION" # F2: 新增集成测试
    DOC_SYNC             = "DOC_SYNC"             # F3: 更新 e2e_traceability / page_map


# ── AIU 族分类 ───────────────────────────────────────────────────────────────

AIU_FAMILY: Dict[str, List[AIUType]] = {
    "A_schema": [
        AIUType.SCHEMA_ADD_FIELD,
        AIUType.SCHEMA_MODIFY_FIELD,
        AIUType.SCHEMA_ADD_RELATION,
        AIUType.CONTRACT_ADD_REQUEST,
        AIUType.CONTRACT_ADD_RESPONSE,
        AIUType.CONTRACT_MODIFY_RESPONSE,
    ],
    "B_control_flow": [
        AIUType.LOGIC_ADD_CONDITION,
        AIUType.LOGIC_ADD_BRANCH,
        AIUType.LOGIC_ADD_LOOP,
        AIUType.LOGIC_EXTRACT_METHOD,
        AIUType.LOGIC_ADD_GUARD,
    ],
    "C_data_access": [
        AIUType.QUERY_ADD_SELECT,
        AIUType.QUERY_ADD_FILTER,
        AIUType.MUTATION_ADD_INSERT,
        AIUType.MUTATION_ADD_UPDATE,
        AIUType.MUTATION_ADD_DELETE,
    ],
    "D_interface": [
        AIUType.ROUTE_ADD_ENDPOINT,
        AIUType.ROUTE_ADD_PERMISSION,
        AIUType.FRONTEND_ADD_PAGE,
        AIUType.FRONTEND_ADD_STORE,
        AIUType.FRONTEND_BIND_API,
    ],
    "E_infrastructure": [
        AIUType.EVENT_ADD_PRODUCER,
        AIUType.EVENT_ADD_CONSUMER,
        AIUType.CACHE_ADD_READ,
        AIUType.CONFIG_MODIFY,
    ],
    "F_validation": [
        AIUType.TEST_ADD_UNIT,
        AIUType.TEST_ADD_INTEGRATION,
        AIUType.DOC_SYNC,
    ],
}

# AIU 类型 → 所属族名（反向索引）
AIU_TO_FAMILY: Dict[AIUType, str] = {
    aiu: family
    for family, aius in AIU_FAMILY.items()
    for aiu in aius
}

# ── AIU 层级映射 ─────────────────────────────────────────────────────────────

# 每种 AIU 主要影响哪个架构层（用于 token 预算 + 文件优先级）
AIU_LAYER_MAP: Dict[AIUType, str] = {
    AIUType.SCHEMA_ADD_FIELD:         "L3_domain",
    AIUType.SCHEMA_MODIFY_FIELD:      "L3_domain",
    AIUType.SCHEMA_ADD_RELATION:      "L3_domain",
    AIUType.CONTRACT_ADD_REQUEST:     "L5_interface",
    AIUType.CONTRACT_ADD_RESPONSE:    "L5_interface",
    AIUType.CONTRACT_MODIFY_RESPONSE: "L5_interface",
    AIUType.LOGIC_ADD_CONDITION:      "L4_application",
    AIUType.LOGIC_ADD_BRANCH:         "L4_application",
    AIUType.LOGIC_ADD_LOOP:           "L4_application",
    AIUType.LOGIC_EXTRACT_METHOD:     "L4_application",
    AIUType.LOGIC_ADD_GUARD:          "L4_application",
    AIUType.QUERY_ADD_SELECT:         "L3_domain",
    AIUType.QUERY_ADD_FILTER:         "L3_domain",
    AIUType.MUTATION_ADD_INSERT:      "L3_domain",
    AIUType.MUTATION_ADD_UPDATE:      "L3_domain",
    AIUType.MUTATION_ADD_DELETE:      "L3_domain",
    AIUType.ROUTE_ADD_ENDPOINT:       "L5_interface",
    AIUType.ROUTE_ADD_PERMISSION:     "L5_interface",
    AIUType.FRONTEND_ADD_PAGE:        "L5_interface",
    AIUType.FRONTEND_ADD_STORE:       "L4_application",
    AIUType.FRONTEND_BIND_API:        "L5_interface",
    AIUType.EVENT_ADD_PRODUCER:       "L2_infrastructure",
    AIUType.EVENT_ADD_CONSUMER:       "L2_infrastructure",
    AIUType.CACHE_ADD_READ:           "L2_infrastructure",
    AIUType.CONFIG_MODIFY:            "L1_platform",
    AIUType.TEST_ADD_UNIT:            "testing",
    AIUType.TEST_ADD_INTEGRATION:     "testing",
    AIUType.DOC_SYNC:                 "docs",
}

# ── AIU 执行顺序（类比 DB 层级依赖）────────────────────────────────────────────

# 数字越小越先执行，相同数字可并行
AIU_EXEC_ORDER: Dict[AIUType, int] = {
    # 结构定义最先（其他 AIU 依赖它）
    AIUType.SCHEMA_ADD_FIELD:         1,
    AIUType.SCHEMA_MODIFY_FIELD:      1,
    AIUType.SCHEMA_ADD_RELATION:      1,
    AIUType.CONTRACT_ADD_REQUEST:     1,
    AIUType.CONTRACT_ADD_RESPONSE:    1,
    AIUType.CONTRACT_MODIFY_RESPONSE: 1,
    # 数据读写层依赖结构定义
    AIUType.QUERY_ADD_SELECT:         2,
    AIUType.QUERY_ADD_FILTER:         2,
    AIUType.MUTATION_ADD_INSERT:      2,
    AIUType.MUTATION_ADD_UPDATE:      2,
    AIUType.MUTATION_ADD_DELETE:      2,
    # 业务逻辑层依赖数据读写
    AIUType.LOGIC_ADD_CONDITION:      3,
    AIUType.LOGIC_ADD_BRANCH:         3,
    AIUType.LOGIC_ADD_LOOP:           3,
    AIUType.LOGIC_EXTRACT_METHOD:     3,
    AIUType.LOGIC_ADD_GUARD:          3,
    # 基础设施可与业务逻辑并行
    AIUType.EVENT_ADD_PRODUCER:       3,
    AIUType.EVENT_ADD_CONSUMER:       3,
    AIUType.CACHE_ADD_READ:           3,
    AIUType.CONFIG_MODIFY:            2,
    # 接口层依赖服务层
    AIUType.ROUTE_ADD_ENDPOINT:       4,
    AIUType.ROUTE_ADD_PERMISSION:     4,
    AIUType.FRONTEND_ADD_PAGE:        4,
    AIUType.FRONTEND_ADD_STORE:       4,
    AIUType.FRONTEND_BIND_API:        5,
    # 质量保障最后
    AIUType.TEST_ADD_UNIT:            6,
    AIUType.TEST_ADD_INTEGRATION:     7,
    AIUType.DOC_SYNC:                 8,
}

# ── 数据结构定义 ─────────────────────────────────────────────────────────────

@dataclass
class AIUStep:
    """
    原子意图单元（Atomic Intent Unit）的单个步骤。

    作为 DagUnit.aiu_steps 的元素存在，代表 DagUnit 内的一个原子操作。
    """

    aiu_id: str                          # 步骤 ID，如 "aiu_1", "aiu_2"
    aiu_type: str                        # AIUType 的字符串值（向后兼容）
    description: str                     # 自然语言描述，如"在 ObjectType 模型新增 is_active 字段"
    layer: str                           # 所属架构层
    target_files: List[str]              # 此步骤涉及的文件（子集于 DagUnit.files）
    depends_on: List[str]                # 前置 AIU step ID 列表
    exec_order: int                      # 执行顺序（同序可并行）
    token_budget: int = 4000             # token 预算（8B 模型阈值）
    model_hint: str = "fast"             # 推荐执行模型
    status: str = "pending"             # pending|in_progress|done|skipped|failed
    retry_count: int = 0                 # 当前重试次数
    feedback_level: int = 0             # 已触发的 Feedback 级别（0=未触发，1/2/3）
    split_from: Optional[str] = None    # 若为 Level 3 分裂产生，记录原始 AIU ID
    error_pattern: Optional[str] = None # 最近一次失败的错误模式分类
    actual_tokens: Optional[int] = None  # 实际消耗 token 数（执行后记录）
    completed_at: Optional[str] = None   # ISO 8601 完成时间

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AIUStep":
        known = set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @property
    def aiu_type_enum(self) -> Optional[AIUType]:
        """将字符串转换为枚举值，不存在则返回 None。"""
        try:
            return AIUType(self.aiu_type)
        except ValueError:
            return None

    @property
    def family(self) -> Optional[str]:
        """返回所属族名。"""
        t = self.aiu_type_enum
        if t is None:
            return None
        return AIU_TO_FAMILY.get(t)

    def is_schema_type(self) -> bool:
        """是否为结构定义类（族 A），Level 2 回退时优先插入这类 AIU。"""
        t = self.aiu_type_enum
        if t is None:
            return False
        return t in AIU_FAMILY.get("A_schema", [])

    def can_be_split(self) -> bool:
        """是否可以被 Level 3 分裂（已分裂过的不再分裂）。"""
        return self.split_from is None and self.feedback_level < 3


@dataclass
class AIUPlan:
    """
    一个 DagUnit 的完整 AIU 执行计划。

    由 task_decomposer.py 生成，存储于 DagUnit.aiu_steps。
    """

    dag_unit_id: str                       # 所属 DagUnit ID
    steps: List[AIUStep]                   # 有序的 AIU 步骤列表
    decomposed_by: str = "rbo"             # "rbo" | "llm"（分解方式）
    confidence: float = 1.0                # 分解置信度（RBO=1.0, LLM=0.6-0.9）
    original_task: str = ""                # 原始任务描述（用于调试）

    def to_dict(self) -> dict:
        return {
            "dag_unit_id": self.dag_unit_id,
            "steps": [s.to_dict() for s in self.steps],
            "decomposed_by": self.decomposed_by,
            "confidence": self.confidence,
            "original_task": self.original_task,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AIUPlan":
        steps = [AIUStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            dag_unit_id=d.get("dag_unit_id", ""),
            steps=steps,
            decomposed_by=d.get("decomposed_by", "rbo"),
            confidence=float(d.get("confidence", 1.0)),
            original_task=d.get("original_task", ""),
        )

    @property
    def pending_steps(self) -> List[AIUStep]:
        return [s for s in self.steps if s.status == "pending"]

    @property
    def done_steps(self) -> List[AIUStep]:
        return [s for s in self.steps if s.status == "done"]

    @property
    def failed_steps(self) -> List[AIUStep]:
        return [s for s in self.steps if s.status == "failed"]

    def get_executable_steps(self) -> List[AIUStep]:
        """返回所有前置依赖已完成的 pending 步骤。"""
        done_ids = {s.aiu_id for s in self.done_steps}
        return [
            s for s in self.pending_steps
            if all(dep in done_ids for dep in s.depends_on)
        ]

    def get_step(self, aiu_id: str) -> Optional[AIUStep]:
        for s in self.steps:
            if s.aiu_id == aiu_id:
                return s
        return None

    def insert_before(self, target_aiu_id: str, new_step: AIUStep) -> None:
        """在指定 AIU 之前插入新步骤（Level 2 回退使用）。"""
        idx = next((i for i, s in enumerate(self.steps) if s.aiu_id == target_aiu_id), None)
        if idx is not None:
            # 新步骤作为 target 的前置依赖
            if target_aiu_id not in new_step.depends_on:
                pass  # 不自动修改 depends_on，由调用方设置
            self.steps.insert(idx, new_step)

    def replace_with_split(
        self, target_aiu_id: str, part_a: AIUStep, part_b: AIUStep
    ) -> None:
        """将指定 AIU 分裂为两个（Level 3 回退使用）。"""
        idx = next((i for i, s in enumerate(self.steps) if s.aiu_id == target_aiu_id), None)
        if idx is not None:
            self.steps.pop(idx)
            self.steps.insert(idx, part_b)
            self.steps.insert(idx, part_a)


# ── 错误模式分类（Feedback 分析用）────────────────────────────────────────────

class AIUErrorPattern(str, Enum):
    """
    AIU 执行失败的错误模式分类。
    用于 Level 1/2/3 回退策略的决策依据。
    """
    IMPORT_ERROR       = "IMPORT_ERROR"       # 模块/函数未找到 → Level 1
    MISSING_FIELD      = "MISSING_FIELD"      # 字段/属性不存在 → Level 2 (插入 SCHEMA_ADD_FIELD)
    MISSING_SCHEMA     = "MISSING_SCHEMA"     # Pydantic Schema 未定义 → Level 2 (插入 CONTRACT_ADD_*)
    ARCH_VIOLATION     = "ARCH_VIOLATION"     # arch_check 违规 → Level 1 (上下文补充约束)
    TEST_ASSERTION     = "TEST_ASSERTION"     # pytest 断言失败 → Level 1
    SYNTAX_ERROR       = "SYNTAX_ERROR"       # Python 语法错误 → Level 1
    LOGIC_CONFLICT     = "LOGIC_CONFLICT"     # 逻辑冲突（如重复定义）→ Level 3 (分裂)
    CONTEXT_OVERFLOW   = "CONTEXT_OVERFLOW"   # LLM 上下文不足 → Level 1 (扩充 budget)
    UNKNOWN            = "UNKNOWN"            # 未分类 → Level 1


# 错误模式 → 建议 Feedback 级别
ERROR_TO_FEEDBACK_LEVEL: Dict[AIUErrorPattern, int] = {
    AIUErrorPattern.IMPORT_ERROR:     1,
    AIUErrorPattern.MISSING_FIELD:    2,
    AIUErrorPattern.MISSING_SCHEMA:   2,
    AIUErrorPattern.ARCH_VIOLATION:   1,
    AIUErrorPattern.TEST_ASSERTION:   1,
    AIUErrorPattern.SYNTAX_ERROR:     1,
    AIUErrorPattern.LOGIC_CONFLICT:   3,
    AIUErrorPattern.CONTEXT_OVERFLOW: 1,
    AIUErrorPattern.UNKNOWN:          1,
}


def classify_error(error_msg: str) -> AIUErrorPattern:
    """
    从错误信息文本中分类错误模式。
    用于 Feedback Analysis 决定回退级别。

    注：关键词匹配按优先级顺序排列，越具体的模式越靠前。
    匹配规则维护于 _ERROR_PATTERNS（可在外部替换以便测试）。
    """
    if not error_msg or not error_msg.strip():
        return AIUErrorPattern.UNKNOWN

    msg_lower = error_msg.lower()

    for pattern, keywords in _ERROR_PATTERNS:
        if any(kw in msg_lower for kw in keywords):
            return pattern

    return AIUErrorPattern.UNKNOWN


# 错误分类规则表（优先级从高到低，可在单元测试中 mock 替换）
# 形式：List[Tuple[AIUErrorPattern, Tuple[str, ...]]]
_ERROR_PATTERNS: List[Tuple["AIUErrorPattern", Tuple[str, ...]]] = [
    (
        AIUErrorPattern.IMPORT_ERROR,
        ("importerror", "modulenotfounderror", "cannot import", "no module named"),
    ),
    (
        AIUErrorPattern.MISSING_FIELD,
        ("has no attribute", "attributeerror", "field not found", "column not found", "no such column"),
    ),
    (
        AIUErrorPattern.MISSING_SCHEMA,
        ("schema not found", "pydantic", "validation error", "responseschema", "requestschema"),
    ),
    (
        AIUErrorPattern.ARCH_VIOLATION,
        ("arch_check", "ac-1", "ac-2", "ac-3", "ac-4", "ac-5", "ac-6", "architecture violation"),
    ),
    (
        AIUErrorPattern.SYNTAX_ERROR,
        ("syntaxerror", "invalid syntax", "unexpected token", "indentationerror"),
    ),
    (
        AIUErrorPattern.LOGIC_CONFLICT,
        ("already defined", "duplicate", "redefinition", "conflict"),
    ),
    (
        AIUErrorPattern.CONTEXT_OVERFLOW,
        ("context length", "token limit", "max tokens", "too long", "truncated"),
    ),
    (
        AIUErrorPattern.TEST_ASSERTION,
        # "failed" 过于宽泛，改为更具体的断言相关词
        ("assertionerror", "assert ", "assertion failed", "expected ", "test failed"),
    ),
]


# ── RBO 覆盖的高频 AIU 类型（P0 阶段实现）────────────────────────────────────

# 这 12 种是最高频的 AIU，RBO 规则优先处理
RBO_COVERED_AIU_TYPES: List[AIUType] = [
    AIUType.SCHEMA_ADD_FIELD,         # 最高频：新增字段
    AIUType.CONTRACT_ADD_RESPONSE,    # 高频：新增响应模型
    AIUType.CONTRACT_ADD_REQUEST,     # 高频：新增请求模型
    AIUType.MUTATION_ADD_INSERT,      # 高频：新增 CRUD create
    AIUType.MUTATION_ADD_UPDATE,      # 高频：新增 CRUD update
    AIUType.QUERY_ADD_SELECT,         # 高频：新增查询方法
    AIUType.ROUTE_ADD_ENDPOINT,       # 高频：新增 API 路由
    AIUType.ROUTE_ADD_PERMISSION,     # 高频：新增权限守卫
    AIUType.LOGIC_ADD_GUARD,          # 高频：新增前置校验
    AIUType.TEST_ADD_UNIT,            # 高频：补充单元测试
    AIUType.DOC_SYNC,                 # 中频：文档同步
    AIUType.CONFIG_MODIFY,            # 中频：配置变更
]
