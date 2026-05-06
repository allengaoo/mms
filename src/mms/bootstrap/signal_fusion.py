"""
src/mms/bootstrap/signal_fusion.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五路信号融合推断架构层与代码对象语义类型

实现 OntologyRegistry 中定义的两个 Function：
  fn_infer_layer              → infer_layer()
  fn_detect_code_object_type  → detect_code_object_type()

设计原则：
  - 纯函数，无副作用，不读写磁盘
  - 规则从 FunctionRegistry 的 signal_rules 字段加载（YAML 驱动）
  - 内置规则作为 fallback（YAML 未配置时生效）
  - 每路信号独立评分，最终加权投票
  - YAML-driven Override Pass：在五路信号之前短路高置信度框架规则

版本：v1.1 | 更新于：2026-05-02 | YAML Override Pass
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml as _yaml

# ─── 数据类 ──────────────────────────────────────────────────────────────────

LAYERS = ["CC", "PLATFORM", "DOMAIN", "APP", "ADAPTER"]

CODE_OBJECT_TYPES = [
    "Controller", "Service", "Repository", "Entity",
    "Config", "Util", "Test", "Unknown",
]

MEMORY_NODE_TYPES = {
    "Controller": ("pattern",  "ADAPTER", "warm"),
    "Service":    ("pattern",  "APP",     "warm"),
    "Repository": ("pattern",  "DOMAIN",  "warm"),
    "Entity":     ("pattern",  "DOMAIN",  "warm"),
    "Config":     ("decision", "PLATFORM","warm"),
    "Util":       ("skip",     "CC",      "cold"),
    "Test":       ("skip",     "APP",     "cold"),
    "Unknown":    ("skip",     "CC",      "cold"),
}


_PROFILES_YAML = Path(__file__).resolve().parents[3] / "assets" / "bootstrap_profiles" / "signal_weights.yaml"

# 默认基准权重（不依赖全局可变状态，仅用于无 profile 时的 fallback）
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "path": 0.25, "name": 0.25, "annotation": 0.30,
    "inheritance": 0.10, "import": 0.10,
}

# YAML 文件只读缓存（内容不可变，进程生命周期内安全）
_profiles_cache: Optional[Dict[str, Any]] = None


def _load_profiles() -> Dict[str, Any]:
    """懒加载 signal_weights.yaml，结果缓存为只读（不修改已加载数据）。"""
    global _profiles_cache
    if _profiles_cache is None:
        try:
            with open(_PROFILES_YAML, encoding="utf-8") as f:
                raw = _yaml.safe_load(f)
            _profiles_cache = raw or {}
        except Exception:
            _profiles_cache = {}
    return _profiles_cache


def get_signal_weights(
    profile: Optional[str] = None,
    overrides: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """返回归一化的信号权重字典（无副作用的纯函数）。

    优先级（从高到低）：
      1. overrides 字典中指定的单个权重键值
      2. profile 对应的模板权重（来自 signal_weights.yaml）
      3. _DEFAULT_WEIGHTS 基准权重

    Args:
        profile:   模板名（如 "java_spring_boot"、"python_fastapi"、"go_gin"）
        overrides: 精细覆盖单个权重（如 {"annotation": 0.45}）

    Returns:
        归一化后的 {signal_name: weight} 字典（新对象，不修改任何全局状态）
    """
    profiles = _load_profiles()
    weights = dict(_DEFAULT_WEIGHTS)  # 始终从拷贝开始，不修改模块常量

    if profile and profile in profiles:
        tmpl = profiles[profile].get("weights", {})
        if tmpl:
            for k in weights:
                if k in tmpl:
                    weights[k] = float(tmpl[k])

    if overrides:
        for k, v in overrides.items():
            if k in weights:
                weights[k] = float(v)

    total = sum(weights.values())
    if total > 0:
        weights = {k: v / total for k, v in weights.items()}
    return weights


def get_strong_path_patterns(profile: Optional[str] = None) -> Optional[Dict[str, List[str]]]:
    """从 profile 中加载 strong_path_patterns（无副作用的纯函数）。

    若 profile 未定义 strong_path_patterns，返回 None（调用方继续使用内置常量）。

    Args:
        profile: 模板名（如 "java_spring_boot"、"python_fastapi"）

    Returns:
        {layer: [keyword, ...]} 或 None（使用内置 _PATH_STRONG_PATTERNS）
    """
    if not profile:
        return None
    profiles = _load_profiles()
    if profile not in profiles:
        return None
    patterns = profiles[profile].get("strong_path_patterns")
    if not patterns or not isinstance(patterns, dict):
        return None
    return {layer: list(keywords) for layer, keywords in patterns.items()}


@dataclass
class SignalBreakdown:
    path_score:        float = 0.0
    name_score:        float = 0.0
    annotation_score:  float = 0.0
    inheritance_score: float = 0.0
    import_score:      float = 0.0
    signature_score:   float = 0.0   # 第 6 路：方法签名信号（Phase 3 新增）

    def total(self, weights: Optional[Dict[str, float]] = None) -> float:
        w = weights or _DEFAULT_WEIGHTS
        return (
            self.path_score        * w.get("path",        0.25) +
            self.name_score        * w.get("name",        0.25) +
            self.annotation_score  * w.get("annotation",  0.30) +
            self.inheritance_score * w.get("inheritance", 0.10) +
            self.import_score      * w.get("import",      0.10) +
            self.signature_score   * w.get("signature",   0.00)  # 默认 0，profile 激活
        )


@dataclass
class LayerInference:
    inferred_layer: str = "UNKNOWN"
    confidence: float = 0.0
    signal_breakdown: SignalBreakdown = field(default_factory=SignalBreakdown)
    all_scores: Dict[str, float] = field(default_factory=dict)


@dataclass
class ObjectTypeMapping:
    code_object_type: str = "Unknown"
    memory_node_type: str = "skip"
    suggested_tier:   str = "cold"
    suggested_layer:  str = "CC"


# ─── 内置信号规则库（从 fn_infer_layer.yaml 提取，作为默认值）──────────────

_PATH_PATTERNS: Dict[str, List[str]] = {
    "ADAPTER":  ["controller", "handler", "router", "route", "endpoint",
                 "view", "rest", "api", "adapter", "web", "http", "resource",
                 "routes", "graphql", "grpc", "amqp_rpc", "nats_rpc", "rmq_rpc",
                 "delivery", "transport", "presentation"],
    "APP":      ["service", "usecase", "use_case", "application",
                 "orchestrat", "workflow", "manager", "command", "query", "saga",
                 "crud", "interactor"],
    "DOMAIN":   ["domain", "model", "entity", "aggregate", "repository",
                 "repo", "store", "dao", "mapper", "schema", "request", "response"],
    "PLATFORM": ["config", "configuration", "auth", "security", "middleware",
                 "filter", "interceptor", "logging", "metric", "provider",
                 "core", "infra", "infrastructure", "db", "logger",
                 "postgres", "redis", "kafka", "rabbitmq", "grpcserver",
                 "httpserver", "jwt", "pkg"],
    "CC":       ["exception", "error", "constant", "common", "base",
                 "abstract", "util", "helper", "test", "spec", "alembic"],
}

_NAME_SUFFIXES: Dict[str, List[str]] = {
    "ADAPTER":  ["Controller", "Handler", "Router", "View",
                 "Resource", "Endpoint", "Rest", "Api",
                 "Resolver", "Delivery",          # Go/GraphQL 惯用名
                 # API DTO / 请求响应 Schema（接口适配层，不是领域层）
                 "Request", "Response", "DTO", "Dto",
                 "Schema", "Schemas",
                 "ViewModel", "Form", "Payload",
                 "Serializer",                    # Django REST
                 ],
    "APP":      ["Service", "UseCase", "Interactor",
                 "Orchestrator", "Manager", "Facade", "Application",
                 "Usecase",                       # Go 惯用
                 "ServiceImpl", "UseCaseImpl", "InteractorImpl",
                 "OrchestratorImpl", "ManagerImpl", "FacadeImpl"],  # Java Impl 惯用
    "DOMAIN":   ["Repository", "Repo", "DAO", "Store",
                 "Mapper", "Entity", "Aggregate", "ValueObject",
                 "RepositoryImpl", "RepoImpl", "DAOImpl", "StoreImpl",
                 "MapperImpl"],                   # Java Repository Impl 惯用
    "PLATFORM": ["Config", "Configuration", "Filter",
                 "Interceptor", "Provider", "Factory", "Auth", "Security",
                 "Logger", "Postgres", "Database", "Client",  # Go infra
                 "Connection", "Server",           # Go server structs
                 "Middleware", "Dependency",       # FastAPI 特有
                 ],
    "CC":       ["Exception", "Error",
                 "Util", "Helper", "Constant", "Test", "Spec"],
}

# 继承关系：框架基类 → 架构层映射（无需命名匹配）
_BASE_CLASS_LAYER_HINTS: Dict[str, Tuple[str, float]] = {
    # Python ORM 基类 → DOMAIN（数据库实体，属于领域层）
    "SQLModel":    ("DOMAIN",   0.8),
    "Base":        ("DOMAIN",   0.5),
    "DeclarativeBase": ("DOMAIN", 0.8),
    # Pydantic BaseModel 是弱信号（API Schema 和 Domain ValueObject 都会继承）
    # 路径信号（schemas/ → ADAPTER）优先级高于此继承信号
    "BaseModel":   ("DOMAIN",   0.4),
    # Python FastAPI 配置
    "BaseSettings": ("PLATFORM", 0.9),
    "Settings":     ("PLATFORM", 0.7),
    # Java Spring
    "JpaRepository": ("DOMAIN", 0.9),
    "CrudRepository": ("DOMAIN", 0.9),
    "PagingAndSortingRepository": ("DOMAIN", 0.9),
    # Go / generic
    "Repository": ("DOMAIN", 0.8),
    "struct":     ("UNKNOWN", 0.0),   # Go 通用 struct，不单独提升
    "interface":  ("UNKNOWN", 0.0),   # Go interface，不单独提升
}

_NAME_PREFIXES: Dict[str, List[str]] = {
    # Base/Abstract 前缀不足以确定层级（可能是任何层的基类），保持 empty
}

_ANNOTATION_PATTERNS: Dict[str, List[str]] = {
    "ADAPTER": [
        r"@RestController", r"@Controller",
        r"@router\b", r"@app\.(get|post|put|delete|patch)",
        r"@(Get|Post|Put|Delete|Patch)\(",
        r"gin\.Context", r"@RequestMapping",
        r"@(Api|Resource)\b",
    ],
    "APP": [
        r"@Service\b", r"@Component\b",
        r"@Injectable\b", r"@UseCase\b",
        r"@Transactional\b",
    ],
    "DOMAIN": [
        r"@Repository\b", r"@Mapper\b",
        r"@Entity\b", r"@Table\b", r"@Document\b",
        r"@dataclass\b", r"@Embeddable\b",
    ],
    "PLATFORM": [
        r"@Configuration\b", r"@ConfigurationProperties",
        r"@EnableWebMvc", r"@SpringBootApplication",
        r"@EnableSecurity", r"@Bean\b",
    ],
}


# ─── YAML-driven Override Pass ────────────────────────────────────────────────

@dataclass
class OverrideRule:
    """单条 ast_overrides 规则（从 match_conditions.yaml 加载）。"""
    rule_id: str
    force_layer: str
    force_object_type: str
    confidence: float
    bases_contains: Optional[str] = None       # 基类名包含该字符串
    annotation_contains: Optional[str] = None  # 注解列表中任一包含该字符串
    name_suffix: Optional[str] = None          # 类名以该字符串结尾
    priority: int = 0                          # 来源包的优先级（base=0，栈专属>0）


def load_overrides(project_root: Path, detected_stacks: Optional[List[str]] = None) -> List[OverrideRule]:
    """
    从 seed_packs/{stack}/match_conditions.yaml 中收集所有 ast_overrides 规则。

    优先级规则：
      - base 包规则 priority=0（最低）
      - 栈专属包规则 priority=10（覆盖 base）
    同一个类命中多条规则时，取 confidence 最高且 priority 最高的规则。
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return []

    # 确定要加载的 seed_packs 路径集合
    seed_packs_root = project_root / "seed_packs"
    if not seed_packs_root.exists():
        # 回退到 MMS 自身的 seed_packs 目录（已迁移至 src/mms/bootstrap/seed_packs/）
        _mms_root = Path(__file__).resolve().parent.parent.parent.parent
        seed_packs_root = _mms_root / "src" / "mms" / "bootstrap" / "seed_packs"
    if not seed_packs_root.exists():
        return []

    stacks_to_load = set(detected_stacks or []) | {"base"}
    rules: List[OverrideRule] = []

    for pack_dir in seed_packs_root.iterdir():
        if not pack_dir.is_dir():
            continue
        mc_file = pack_dir / "match_conditions.yaml"
        if not mc_file.exists():
            continue

        stack_id = pack_dir.name
        priority = 0 if stack_id == "base" else 10

        # 只加载 base + 当前检测到的栈
        if stack_id not in stacks_to_load and stack_id != "base":
            continue

        try:
            data = yaml.safe_load(mc_file.read_text(encoding="utf-8")) or {}
        except Exception:
            continue

        for rule_dict in data.get("ast_overrides", []):
            rule = OverrideRule(
                rule_id=rule_dict.get("rule_id", "UNNAMED"),
                force_layer=rule_dict.get("force_layer", "UNKNOWN"),
                force_object_type=rule_dict.get("force_object_type", "Unknown"),
                confidence=float(rule_dict.get("confidence", 0.8)),
                bases_contains=rule_dict.get("bases_contains"),
                annotation_contains=rule_dict.get("annotation_contains"),
                name_suffix=rule_dict.get("name_suffix"),
                priority=priority,
            )
            rules.append(rule)

    return rules


def apply_override(
    class_name: str,
    bases: List[str],
    annotations: List[str],
    override_rules: List[OverrideRule],
) -> Optional[Tuple[LayerInference, "ObjectTypeMapping"]]:
    """
    对单个类应用 Override Pass。

    如果命中任何规则，返回 (LayerInference, ObjectTypeMapping)；否则返回 None。
    多规则命中时：priority 高者优先，priority 相同则 confidence 高者优先。
    """
    candidates: List[Tuple[int, float, OverrideRule]] = []

    annot_str = " ".join(annotations)

    for rule in override_rules:
        hit = True

        # bases_contains 条件（AND 关系）
        if rule.bases_contains is not None:
            if not any(rule.bases_contains in b for b in bases):
                hit = False

        # annotation_contains 条件（AND 关系）
        if hit and rule.annotation_contains is not None:
            if rule.annotation_contains not in annot_str:
                hit = False

        # name_suffix 条件（AND 关系）
        if hit and rule.name_suffix is not None:
            if not class_name.endswith(rule.name_suffix):
                hit = False

        if hit:
            candidates.append((rule.priority, rule.confidence, rule))

    if not candidates:
        return None

    # 取优先级最高、置信度最高的规则
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _, conf, best_rule = candidates[0]

    breakdown = SignalBreakdown(
        path_score=0.0, name_score=0.0,
        annotation_score=0.0, inheritance_score=conf,
        import_score=0.0,
    )
    layer_inf = LayerInference(
        inferred_layer=best_rule.force_layer,
        confidence=conf,
        signal_breakdown=breakdown,
        all_scores={best_rule.force_layer: conf},
    )
    mem_type, mem_layer, mem_tier = MEMORY_NODE_TYPES.get(
        best_rule.force_object_type, ("pattern", best_rule.force_layer, "warm")
    )
    obj_map = ObjectTypeMapping(
        code_object_type=best_rule.force_object_type,
        memory_node_type=mem_type,
        suggested_tier=mem_tier,
        suggested_layer=mem_layer,
    )
    return layer_inf, obj_map


# ─── 信号评分器 ───────────────────────────────────────────────────────────────

_PATH_STRONG_PATTERNS: Dict[str, List[str]] = {
    # 这些目录名单独出现就具有高置信度，路径信号评分 1.0（权重 0.25 → 贡献 0.25，超过 0.25 阈值）
    "ADAPTER":  [
        "controller", "handler", "router", "endpoint",
        # API DTO / 请求响应 Schema（属于接口适配层，不属于领域层）
        "schemas", "schema", "dto", "dtos",
        "request", "requests", "response", "responses",
        # MVC / MVP 视图层
        "serializer", "serializers", "view", "views",
        # GraphQL / gRPC 适配
        "resolver", "resolvers", "grpc",
    ],
    "APP":      ["service", "usecase", "use_case", "application", "app"],
    "DOMAIN":   [
        "entity", "aggregate", "domain", "repository",
        # 注意：model/ 是弱信号，不在强信号中（Pydantic model 可能是 ADAPTER）
    ],
    "PLATFORM": [
        "config", "configuration", "infrastructure", "infra",
        # FastAPI 特有目录
        "middleware", "middlewares", "dependency", "dependencies",
        "event", "events", "lifespan",
        # Spring Boot 特有
        "aspect", "aop", "interceptor",
        # 通用平台能力
        "security", "auth", "authentication", "authorization",
        "logging", "log", "exception", "error",
    ],
}


def _score_path(
    file_path: str,
    name_patterns: Optional[Dict] = None,
    strong_patterns: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, float]:
    """路径信号：目录名关键词匹配评分（各层 0~1）。

    强信号（entity/aggregate/repository 等明确目录）→ 1.0；
    弱信号（model/dto/impl 等共享目录）→ 0.4；
    两类均可叠加（上限 1.0）。

    Args:
        file_path:       源文件路径
        name_patterns:   弱信号路径模式（来自 signal_rules 自定义规则或内置 _PATH_PATTERNS）
        strong_patterns: 强信号路径模式（来自 profile 的 strong_path_patterns 或内置
                         _PATH_STRONG_PATTERNS）。profile 中定义时完全替换内置强信号列表，
                         以适配不同技术栈的目录约定（如 java_spring_boot / python_fastapi）。
    """
    patterns = name_patterns or _PATH_PATTERNS
    effective_strong = strong_patterns if strong_patterns is not None else _PATH_STRONG_PATTERNS
    parts = Path(file_path).parts
    path_str = "/".join(parts).lower()
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}

    # 弱信号路径模式（0.4）
    for layer, keywords in patterns.items():
        for kw in keywords:
            if kw in path_str:
                scores[layer] = min(1.0, scores[layer] + 0.4)

    # 强信号路径模式（1.0，可独立超过 0.25 阈值）
    for layer, keywords in effective_strong.items():
        for kw in keywords:
            if kw in path_str:
                scores[layer] = 1.0
                break

    return scores


def _score_name(class_name: str,
                suffix_patterns: Optional[Dict] = None,
                prefix_patterns: Optional[Dict] = None) -> Dict[str, float]:
    """命名信号：类名后缀/前缀匹配评分。"""
    suffixes = suffix_patterns or _NAME_SUFFIXES
    prefixes = prefix_patterns or _NAME_PREFIXES
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}
    for layer, suf_list in suffixes.items():
        for suf in suf_list:
            if class_name.endswith(suf):
                scores[layer] = 1.0
                break
    for layer, pre_list in prefixes.items():
        for pre in pre_list:
            if class_name.startswith(pre):
                scores[layer] = max(scores[layer], 0.7)
                break
    return scores


def _score_annotations(annotations: List[str],
                        annot_patterns: Optional[Dict] = None) -> Dict[str, float]:
    """注解/装饰器信号：模式匹配（权重最高，显式声明）。"""
    patterns = annot_patterns or _ANNOTATION_PATTERNS
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}
    annot_str = " ".join(annotations)
    for layer, pat_list in patterns.items():
        for pat in pat_list:
            if re.search(pat, annot_str):
                scores[layer] = 1.0
                break
    return scores


def _score_inheritance(bases: List[str], parent_layers: Dict[str, str]) -> Dict[str, float]:
    """继承信号：父类/接口名关键词 + 父类已知层级 + 框架基类 hint。"""
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}
    for base in bases:
        # 1. 框架基类直接映射（最高优先级）
        if base in _BASE_CLASS_LAYER_HINTS:
            layer, confidence = _BASE_CLASS_LAYER_HINTS[base]
            if layer in scores:  # 跳过 "UNKNOWN" 等非有效层
                scores[layer] = max(scores[layer], confidence)
            continue

        # 2. 父类已有推断层时采用
        if base in parent_layers:
            layer = parent_layers[base]
            if layer in scores:
                scores[layer] = max(scores[layer], 0.9)
            continue

        # 3. 父类名关键词匹配（降级处理）
        for layer, suf_list in _NAME_SUFFIXES.items():
            for suf in suf_list:
                if base.endswith(suf):
                    scores[layer] = max(scores[layer], 0.6)
    return scores


def _score_imports(class_name: str,
                   in_degree: int,
                   out_degree_by_layer: Dict[str, int]) -> Dict[str, float]:
    """
    导入信号：根据依赖图中的入度/出度推断层级。

    规则：
      - 高入度（被大量类依赖）→ 更可能是底层（DOMAIN/PLATFORM）
      - 大量依赖 DOMAIN 层类 → 自身可能是 APP 层
      - 大量依赖 APP 层类    → 自身可能是 ADAPTER 层
    """
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}

    # 高入度 → 底层信号
    if in_degree >= 5:
        scores["DOMAIN"]   = max(scores["DOMAIN"],   0.5)
        scores["PLATFORM"] = max(scores["PLATFORM"], 0.4)
    elif in_degree >= 3:
        scores["DOMAIN"] = max(scores["DOMAIN"], 0.3)

    # 出度方向 → 调用方层级
    domain_deps  = out_degree_by_layer.get("DOMAIN",  0)
    platform_deps = out_degree_by_layer.get("PLATFORM", 0)
    adapter_deps = out_degree_by_layer.get("ADAPTER", 0)

    if domain_deps >= 2:
        scores["APP"] = max(scores["APP"], 0.4)
    if domain_deps >= 1 and platform_deps >= 1:
        scores["APP"] = max(scores["APP"], 0.3)
    if adapter_deps >= 1:
        scores["CC"] = max(scores["CC"], 0.2)

    return scores


# ─── Phase 3: 第 6 路信号 — 方法签名信号 ─────────────────────────────────────

# 方法名关键词 → 层级映射（通用、跨语言）
_METHOD_SIGNATURE_PATTERNS: Dict[str, List[str]] = {
    "ADAPTER": [
        # HTTP/REST 入口
        "handle", "dispatch", "process_request", "on_request",
        # gRPC/消息队列
        "on_message", "consume", "on_event",
        # CLI
        "run_command", "invoke",
        # 前端事件
        "on_click", "on_submit", "render",
    ],
    "APP": [
        # 用例编排
        "execute", "run", "orchestrate", "coordinate",
        # 事务边界
        "create", "update", "delete",  # 注意：放 APP 而非 DOMAIN，因为包含外部调用
        # 工作流
        "send_notification", "publish_event", "emit",
        # 任务/调度
        "perform", "process", "schedule",
    ],
    "DOMAIN": [
        # 领域行为（无 IO 依赖）
        "validate", "calculate", "compute", "check",
        "is_valid", "can_", "should_",
        # 工厂方法
        "create_", "build_", "from_",
        # 仓储接口
        "find_by", "get_by", "list_by", "save", "remove",
    ],
    "PLATFORM": [
        # 数据库操作
        "query", "insert", "update_record", "delete_record", "fetch",
        # 缓存
        "cache_get", "cache_set", "cache_delete",
        # 外部调用
        "call_api", "send_request", "post_to",
        # 配置/连接
        "connect", "disconnect", "initialize", "setup",
    ],
    "CC": [
        # 工具方法
        "format", "parse", "convert", "serialize", "deserialize",
        "encode", "decode", "hash", "encrypt", "decrypt",
        # 日志/监控
        "log", "trace", "metric",
        # 错误处理
        "handle_error", "wrap_exception",
    ],
}


def _score_method_signature(
    methods: List[dict],
    sig_patterns: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, float]:
    """
    方法签名信号（Phase 3 第 6 路）：基于方法名关键词推断架构层。

    算法：
      1. 将类的所有方法名转小写，拼接为一个词袋
      2. 对每个层的关键词列表进行匹配，统计命中数
      3. 命中率（hits / total_keywords）作为层级得分（max 1.0）
      4. 空方法列表时所有层得分为 0（不产生误导信号）

    与注解信号相比，方法签名置信度更低（需要语言约定作为先验），
    适合作为辅助信号，在 profile 中通过 weights.signature 激活。

    Args:
        methods:      方法字典列表，每个字典必须包含 'name' 键
        sig_patterns: 自定义方法名关键词字典，None 时使用内置 _METHOD_SIGNATURE_PATTERNS

    Returns:
        每个层的得分字典，值范围 [0.0, 1.0]
    """
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS}
    if not methods:
        return scores

    patterns = sig_patterns or _METHOD_SIGNATURE_PATTERNS
    method_names_lower = [
        m.get("name", "").lower()
        for m in methods
        if isinstance(m, dict) and m.get("name")
    ]
    if not method_names_lower:
        return scores

    method_blob = " ".join(method_names_lower)

    for layer, keywords in patterns.items():
        if layer not in scores:
            continue
        hits = sum(
            1 for kw in keywords
            if kw in method_blob or any(name.startswith(kw) or kw in name for name in method_names_lower)
        )
        if keywords:
            scores[layer] = min(1.0, hits / len(keywords))

    return scores


# ─── fn_infer_layer 实现 ──────────────────────────────────────────────────────

def infer_layer(
    file_path: str,
    class_name: str,
    annotations: Optional[List[str]] = None,
    bases: Optional[List[str]] = None,
    parent_layers: Optional[Dict[str, str]] = None,
    in_degree: int = 0,
    out_degree_by_layer: Optional[Dict[str, int]] = None,
    signal_rules: Optional[Dict] = None,
    weights: Optional[Dict[str, float]] = None,
    strong_path_patterns: Optional[Dict[str, List[str]]] = None,
    methods: Optional[List[dict]] = None,
) -> LayerInference:
    """
    六路信号融合推断架构层（纯函数，无全局状态副作用）。

    Phase 3 新增第 6 路：方法签名信号（method_signature），
    默认权重为 0（由 profile 的 weights.signature 激活）。

    实现 fn_infer_layer Function（assets/ontology_schema/functions/fn_infer_layer.yaml）。

    Args:
        file_path:            文件路径（用于路径信号）
        class_name:           类名（用于命名信号）
        annotations:          类级注解/装饰器列表（用于注解信号）
        bases:                父类/接口列表（用于继承信号）
        parent_layers:        已推断的父类层级字典 {class_name: layer}（用于继承信号）
        in_degree:            被多少类依赖（用于导入信号）
        out_degree_by_layer:  按层分组的出度 {layer: count}（用于导入信号）
        signal_rules:         来自 FunctionRegistry 的自定义信号规则（覆盖内置规则）
        weights:              信号权重字典（来自 get_signal_weights()），None 时使用默认权重。
                              通过 infer_all() 的 weights_profile 参数注入，不依赖全局状态。
        strong_path_patterns: 强信号路径模式，来自 profile 的 strong_path_patterns 字段。
                              None 时使用内置 _PATH_STRONG_PATTERNS 常量。
                              通过 infer_all() 的 weights_profile 参数自动注入，实现
                              "每个 profile 定制强信号目录约定"的效果。
        methods:              方法字典列表（含 name 键），用于第 6 路方法签名信号。
                              默认权重为 0，需 profile 的 weights.signature > 0 激活。

    Returns:
        LayerInference: 推断结果，含层级、置信度和分项得分（含 signature_score）
    """
    annotations = annotations or []
    bases = bases or []
    parent_layers = parent_layers or {}
    out_degree_by_layer = out_degree_by_layer or {}

    # 确定本次推断使用的权重（显式注入 > 默认值）
    w = weights if weights is not None else _DEFAULT_WEIGHTS

    # 加载自定义规则（YAML 驱动覆盖）
    custom_path   = (signal_rules or {}).get("path_patterns")
    custom_name   = (signal_rules or {}).get("name_patterns")
    custom_annot  = (signal_rules or {}).get("annotation_patterns")
    custom_sig    = (signal_rules or {}).get("method_signature_patterns")

    # 六路信号评分（strong_path_patterns 来自 profile，None 时退回内置常量）
    path_scores  = _score_path(file_path, custom_path, strong_path_patterns)
    name_scores  = _score_name(class_name, custom_name)
    annot_scores = _score_annotations(annotations, custom_annot)
    inh_scores   = _score_inheritance(bases, parent_layers)
    imp_scores   = _score_imports(class_name, in_degree, out_degree_by_layer)
    sig_scores   = _score_method_signature(methods or [], custom_sig)  # Phase 3

    # 加权融合（使用注入的权重，不再硬编码）
    wp   = w.get("path",        0.25)
    wn   = w.get("name",        0.25)
    wa   = w.get("annotation",  0.30)
    wi   = w.get("inheritance", 0.10)
    wm   = w.get("import",      0.10)
    ws   = w.get("signature",   0.00)  # 默认关闭，profile 激活

    all_scores: Dict[str, float] = {}
    breakdown = SignalBreakdown()

    for layer in LAYERS:
        ps  = path_scores.get(layer, 0.0)
        ns  = name_scores.get(layer, 0.0)
        as_ = annot_scores.get(layer, 0.0)
        is_ = inh_scores.get(layer, 0.0)
        im_ = imp_scores.get(layer, 0.0)
        sg_ = sig_scores.get(layer, 0.0)
        all_scores[layer] = ps * wp + ns * wn + as_ * wa + is_ * wi + im_ * wm + sg_ * ws

    # ── Stage 1b: Framework Override Pass (soft floor) ───────────────────────
    # 当框架基类（SQLModel/BaseModel/BaseSettings 等）匹配时，
    # 继承信号本身置信度极高（0.7~0.9），但 0.10 权重使其被压制。
    # 此处以框架基类推断的层级作为最低下限（soft override）。
    for base in (bases or []):
        if base in _BASE_CLASS_LAYER_HINTS:
            fw_layer, fw_conf = _BASE_CLASS_LAYER_HINTS[base]
            if fw_layer in all_scores and fw_conf > all_scores[fw_layer]:
                all_scores[fw_layer] = fw_conf

    # ── Stage 2: 冲突检测（Phase 4 新增）────────────────────────────────────
    # 当最高分与次高分差值 < 阈值时，检查是否属于已知冲突对。
    # 实现 inference_rules.yaml Stage 2 的 ambiguity_threshold = 0.15 规则。
    _AMBIGUITY_THRESHOLD = 0.15
    _CONFLICT_PAIRS = frozenset([
        frozenset(["ADAPTER", "DOMAIN"]),
        frozenset(["APP", "DOMAIN"]),
        frozenset(["ADAPTER", "APP"]),
    ])

    sorted_layers = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
    best_layer = sorted_layers[0][0]
    best_score = sorted_layers[0][1]
    inference_ambiguous = False

    if len(sorted_layers) >= 2:
        second_layer = sorted_layers[1][0]
        second_score = sorted_layers[1][1]
        gap = best_score - second_score

        if gap < _AMBIGUITY_THRESHOLD and best_score >= 0.25:
            pair = frozenset([best_layer, second_layer])
            if pair in _CONFLICT_PAIRS:
                # 冲突检测：优先采用路径信号 tiebreaker
                path_best = path_scores.get(best_layer, 0.0)
                path_second = path_scores.get(second_layer, 0.0)
                if path_second > path_best:
                    # 路径信号支持次高分层，切换为次高分
                    best_layer = second_layer
                    best_score = second_score
                # 标记为模糊（提交给 schema_evolution_report）
                inference_ambiguous = True

    # 分项得分记录（取最终确定的 best_layer 的分量）
    breakdown.path_score        = path_scores.get(best_layer, 0.0)
    breakdown.name_score        = name_scores.get(best_layer, 0.0)
    breakdown.annotation_score  = annot_scores.get(best_layer, 0.0)
    breakdown.inheritance_score = inh_scores.get(best_layer, 0.0)
    breakdown.import_score      = imp_scores.get(best_layer, 0.0)
    breakdown.signature_score   = sig_scores.get(best_layer, 0.0)  # Phase 3

    min_conf = 0.25  # 与 fn_infer_layer.yaml 的 min_confidence 对齐
    inferred = best_layer if best_score >= min_conf else "UNKNOWN"

    result = LayerInference(
        inferred_layer=inferred,
        confidence=round(best_score, 3),
        signal_breakdown=breakdown,
        all_scores={k: round(v, 3) for k, v in all_scores.items()},
    )
    # 冲突标记（供 schema_evolution_report 收集）
    if inference_ambiguous:
        result.all_scores["_ambiguous"] = 1.0  # type: ignore[assignment]
    return result


# ─── fn_detect_code_object_type 实现 ──────────────────────────────────────────

def detect_code_object_type(
    class_name: str,
    annotations: Optional[List[str]] = None,
    methods: Optional[List[dict]] = None,
    layer_inference: Optional[LayerInference] = None,
) -> ObjectTypeMapping:
    """
    基于推断层级和方法签名确定代码对象的语义类型。

    实现 fn_detect_code_object_type Function。
    """
    annotations = annotations or []
    methods = methods or []
    inferred_layer = layer_inference.inferred_layer if layer_inference else "UNKNOWN"

    annot_str = " ".join(annotations)
    method_names = [m.get("name", "") for m in methods if isinstance(m, dict)]
    method_str = " ".join(method_names).lower()

    code_type = "Unknown"

    if inferred_layer == "ADAPTER":
        has_http = bool(re.search(r"@(Get|Post|Put|Delete|Patch|RestController|Controller|router|app\.)", annot_str))
        if has_http or any(s in class_name for s in ["Controller", "Handler", "Router", "View"]):
            code_type = "Controller"
        elif any(s in class_name for s in ["Client", "Adapter", "Gateway"]):
            code_type = "Controller"  # 广义 ADAPTER 都归为 Controller
        else:
            code_type = "Controller"

    elif inferred_layer == "APP":
        code_type = "Service"

    elif inferred_layer == "DOMAIN":
        is_entity = bool(re.search(r"@(Entity|Table|Document|dataclass|Embeddable)", annot_str))
        is_repo   = any(s in class_name for s in ["Repository", "Repo", "DAO", "Store", "Mapper"])
        if is_repo:
            code_type = "Repository"
        elif is_entity or any(s in class_name for s in ["Entity", "Aggregate", "ValueObject", "Model"]):
            code_type = "Entity"
        else:
            code_type = "Entity"  # DOMAIN 层默认归 Entity

    elif inferred_layer == "PLATFORM":
        code_type = "Config"

    elif inferred_layer == "CC":
        if any(s in class_name for s in ["Exception", "Error"]):
            code_type = "Util"  # 异常类：生成 Util 记忆或跳过
        elif any(s in class_name for s in ["Test", "Spec", "Mock"]):
            code_type = "Test"
        else:
            code_type = "Util"

    mem_type, mem_layer, mem_tier = MEMORY_NODE_TYPES.get(code_type, ("skip", "CC", "cold"))
    return ObjectTypeMapping(
        code_object_type=code_type,
        memory_node_type=mem_type,
        suggested_tier=mem_tier,
        suggested_layer=mem_layer,
    )


# ─── 批量推断（供 Bootstrap 使用）────────────────────────────────────────────

def infer_all(
    ast_index: Dict[str, dict],
    code_graph_in_degrees: Optional[Dict[str, int]] = None,
    code_graph_out_by_layer: Optional[Dict[str, Dict[str, int]]] = None,
    signal_rules: Optional[Dict] = None,
    min_confidence: float = 0.25,
    project_root: Optional[Path] = None,
    detected_stacks: Optional[List[str]] = None,
    override_rules: Optional[List[OverrideRule]] = None,
    weights_profile: Optional[str] = None,
    weights_overrides: Optional[Dict[str, float]] = None,
) -> Dict[str, Tuple[LayerInference, ObjectTypeMapping]]:
    """
    对 ast_index 中所有类批量推断层级和对象类型。

    执行顺序：
      1. YAML Override Pass（高置信度框架规则短路，零误判）
      2. 六路信号融合推断（针对未命中 Override 的类，使用 weights_profile 权重）
         第 6 路（method_signature）默认权重为 0，通过 profile weights.signature 激活

    Args:
        ast_index:               build_ast_index() 的输出
        code_graph_in_degrees:   {class_fqn: in_degree}（可选，来自代码图）
        code_graph_out_by_layer: {class_fqn: {layer: count}}（可选）
        signal_rules:            自定义信号规则（来自 FunctionRegistry）
        min_confidence:          最低置信度阈值
        project_root:            项目根目录（用于加载 Override 规则）
        detected_stacks:         已检测到的技术栈（用于过滤 Override 规则）
        override_rules:          直接传入已加载的规则列表（优先于 project_root 加载）
        weights_profile:         信号权重模板名（如 "java_spring_boot"、"python_fastapi"）
                                 None 时使用 _active_weights 全局权重
        weights_overrides:       精细覆盖单个权重键（与 weights_profile 合并）

    Returns:
        {class_fqn: (LayerInference, ObjectTypeMapping)}
    """
    # 计算本次调用的权重和强信号路径模式（纯函数，不修改全局状态）
    active_weights = get_signal_weights(weights_profile, weights_overrides)
    active_strong_patterns = get_strong_path_patterns(weights_profile)
    in_degrees   = code_graph_in_degrees or {}
    out_by_layer = code_graph_out_by_layer or {}
    results: Dict[str, Tuple[LayerInference, ObjectTypeMapping]] = {}

    # 加载 YAML Override 规则
    _override_rules: List[OverrideRule]
    if override_rules is not None:
        _override_rules = override_rules
    elif project_root is not None:
        _override_rules = load_overrides(project_root, detected_stacks)
    else:
        _override_rules = []

    override_hits = 0
    signal_inferred = 0

    # 两轮推断：第一轮推断父类层级 → 第二轮用继承信号
    parent_layers: Dict[str, str] = {}

    for file_path, file_data in ast_index.items():
        for cls in file_data.get("classes", []):
            name = cls.get("name", "")
            if not name:
                continue
            fqn = f"{file_path}::{name}"
            bases = cls.get("bases", [])
            annotations = cls.get("annotations", [])

            # ── Pass 1: YAML Override（短路）──────────────────────────────────
            override_result = apply_override(
                class_name=name,
                bases=bases,
                annotations=annotations,
                override_rules=_override_rules,
            )
            if override_result is not None:
                layer_inf, obj_map = override_result
                results[fqn] = (layer_inf, obj_map)
                if layer_inf.confidence >= min_confidence:
                    parent_layers[name] = layer_inf.inferred_layer
                override_hits += 1
                continue

            # ── Pass 2: 六路信号融合推断（显式注入权重和强信号模式，无全局状态依赖）──
            layer_inf = infer_layer(
                file_path=file_path,
                class_name=name,
                annotations=annotations,
                bases=bases,
                parent_layers=parent_layers,
                in_degree=in_degrees.get(fqn, 0),
                out_degree_by_layer=out_by_layer.get(fqn, {}),
                signal_rules=signal_rules,
                weights=active_weights,
                strong_path_patterns=active_strong_patterns,
                methods=cls.get("methods", []),  # Phase 3: 第 6 路方法签名信号
            )
            if layer_inf.confidence >= min_confidence:
                parent_layers[name] = layer_inf.inferred_layer

            obj_map = detect_code_object_type(
                class_name=name,
                annotations=annotations,
                methods=cls.get("methods", []),
                layer_inference=layer_inf,
            )
            results[fqn] = (layer_inf, obj_map)
            signal_inferred += 1

    return results
