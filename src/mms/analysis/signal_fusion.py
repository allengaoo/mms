"""
src/mms/analysis/signal_fusion.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五路信号融合引擎：推断 CodeClass 的架构层归属和语义对象类型

实现 fn_infer_layer 和 fn_detect_code_object_type 两个 Ontology Function。

五路信号：
  1. 路径信号   (path_score)        25%
  2. 命名信号   (name_score)        25%
  3. 注解信号   (annotation_score)  30%（最高权重，因为注解是显式声明）
  4. 继承信号   (inheritance_score) 10%
  5. 导入信号   (import_score)      10%

无 LLM，纯规则引擎，100% 确定性。

版本：v1.0 | 创建于：2026-04-30 | Bootstrap v2
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# 架构层枚举（通用 5 层 + CC）
LAYERS = ["CC", "PLATFORM", "DOMAIN", "APP", "ADAPTER", "UNKNOWN"]

# 代码对象语义类型
CODE_OBJECT_TYPES = ["Controller", "Service", "Repository", "Entity",
                     "Config", "Util", "Unknown"]

# ─── 信号规则库（从 fn_infer_layer.yaml 内联，避免 YAML 读取依赖）──────────────

_PATH_PATTERNS: Dict[str, List[str]] = {
    "ADAPTER":  ["controller", "handler", "router", "route", "endpoint",
                 "view", "rest", "api", "adapter", "web", "http", "grpc",
                 "graphql", "proto", "presentation"],
    "APP":      ["service", "usecase", "use_case", "application",
                 "orchestrat", "workflow", "manager", "command", "query",
                 "interactor", "facade", "saga"],
    "DOMAIN":   ["domain", "model", "entity", "aggregate", "repository",
                 "repo", "store", "dao", "mapper", "value_object"],
    "PLATFORM": ["config", "configuration", "auth", "security", "middleware",
                 "filter", "interceptor", "logging", "metric", "monitor",
                 "infra", "infrastructure", "shared", "common/platform"],
    "CC":       ["exception", "error", "constant", "util", "helper",
                 "base", "abstract", "common", "core"],
}

_NAME_SUFFIXES: Dict[str, List[str]] = {
    "ADAPTER":  ["Controller", "Handler", "Router", "View", "Resource",
                 "Endpoint", "Rest", "GrpcService", "GraphQLResolver",
                 "Servlet", "Action"],
    "APP":      ["Service", "UseCase", "Interactor", "Orchestrator",
                 "Manager", "Facade", "CommandHandler", "QueryHandler",
                 "ApplicationService"],
    "DOMAIN":   ["Repository", "Repo", "DAO", "Store", "Mapper",
                 "Entity", "Aggregate", "ValueObject", "DomainService"],
    "PLATFORM": ["Config", "Configuration", "Filter", "Interceptor",
                 "Provider", "Factory", "Registry", "Client", "Adapter",
                 "Gateway"],
    "CC":       ["Exception", "Error", "Base", "Abstract", "Util",
                 "Helper", "Constant", "Utils"],
}

_NAME_PREFIXES: Dict[str, List[str]] = {
    "CC": ["Base", "Abstract"],
}

_ANNOTATION_PATTERNS: Dict[str, List[str]] = {
    "ADAPTER": [
        r"@RestController", r"@Controller", r"@RequestMapping",
        r"@router\.", r"@app\.(get|post|put|delete|patch|head|options)",
        r"@(Get|Post|Put|Delete|Patch|Head)\(",
        r"gin\.Context", r"echo\.Context",
        r"@Resource", r"@Path\(",
    ],
    "APP": [
        r"@Service", r"@Component(?!Scan)", r"@Injectable",
        r"@UseCase", r"@ApplicationService",
        r"@Transactional",
    ],
    "DOMAIN": [
        r"@Repository", r"@Mapper", r"@Entity", r"@Table\(",
        r"@Document", r"@Aggregate",
        r"@dataclass",    # Python dataclass 通常是领域实体
        r"dataclass",
    ],
    "PLATFORM": [
        r"@Configuration", r"@ConfigurationProperties",
        r"@EnableWebMvc", r"@SpringBootApplication",
        r"@EnableAutoConfiguration",
        r"@Bean",
    ],
}

# 对象类型 → 通用 5 层 映射
_OBJECT_TYPE_TO_LAYER: Dict[str, str] = {
    "Controller": "ADAPTER",
    "Service":    "APP",
    "Repository": "DOMAIN",
    "Entity":     "DOMAIN",
    "Config":     "PLATFORM",
    "Util":       "CC",
    "Unknown":    "UNKNOWN",
}

# 对象类型 → MemoryNode type 映射
_OBJECT_TYPE_TO_MEMORY_TYPE: Dict[str, str] = {
    "Controller": "pattern",
    "Service":    "pattern",
    "Repository": "pattern",
    "Entity":     "pattern",
    "Config":     "decision",
    "Util":       "skip",
    "Unknown":    "skip",
}

# 对象类型 → 建议 tier
_OBJECT_TYPE_TO_TIER: Dict[str, str] = {
    "Controller": "warm",
    "Service":    "warm",
    "Repository": "warm",
    "Entity":     "hot",    # 领域实体是核心
    "Config":     "cold",
    "Util":       "cold",
    "Unknown":    "cold",
}

# 信号权重
_WEIGHTS = {
    "path":        0.25,
    "name":        0.25,
    "annotation":  0.30,
    "inheritance": 0.10,
    "import":      0.10,
}


# ─── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class SignalBreakdown:
    path_score:        float = 0.0
    name_score:        float = 0.0
    annotation_score:  float = 0.0
    inheritance_score: float = 0.0
    import_score:      float = 0.0

    def weighted_total(self) -> float:
        return (
            self.path_score        * _WEIGHTS["path"] +
            self.name_score        * _WEIGHTS["name"] +
            self.annotation_score  * _WEIGHTS["annotation"] +
            self.inheritance_score * _WEIGHTS["inheritance"] +
            self.import_score      * _WEIGHTS["import"]
        )


@dataclass
class LayerScore:
    layer: str
    score: float  # 0.0~1.0


@dataclass
class LayerInference:
    inferred_layer: str
    confidence: float
    signal_breakdown: SignalBreakdown
    all_scores: List[LayerScore] = field(default_factory=list)


@dataclass
class ObjectTypeMapping:
    code_object_type: str
    memory_node_type: str
    suggested_tier: str
    suggested_layer: str


# ─── 信号计算函数 ─────────────────────────────────────────────────────────────

def _score_path(file_path: str) -> Dict[str, float]:
    """路径信号：根据目录名关键词打分。"""
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS[:-1]}
    path_lower = file_path.lower().replace("\\", "/")

    for layer, patterns in _PATH_PATTERNS.items():
        for p in patterns:
            if p in path_lower:
                # 精确的目录段匹配得分更高
                if f"/{p}/" in path_lower or path_lower.startswith(p + "/"):
                    scores[layer] = max(scores[layer], 1.0)
                else:
                    scores[layer] = max(scores[layer], 0.7)

    return scores


def _score_name(class_name: str) -> Dict[str, float]:
    """命名信号：根据类名前缀/后缀关键词打分。"""
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS[:-1]}

    for layer, suffixes in _NAME_SUFFIXES.items():
        for suffix in suffixes:
            if class_name.endswith(suffix):
                scores[layer] = max(scores[layer], 1.0)
                break

    for layer, prefixes in _NAME_PREFIXES.items():
        for prefix in prefixes:
            if class_name.startswith(prefix) and len(class_name) > len(prefix):
                scores[layer] = max(scores[layer], 0.8)
                break

    return scores


def _score_annotations(annotations: List[str]) -> Dict[str, float]:
    """注解信号：根据类级注解/装饰器打分（权重最高）。"""
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS[:-1]}
    annot_str = " ".join(annotations)

    for layer, patterns in _ANNOTATION_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, annot_str):
                scores[layer] = max(scores[layer], 1.0)

    return scores


def _score_inheritance(
    bases: List[str],
    class_name_map: Optional[Dict[str, str]] = None,
) -> Dict[str, float]:
    """
    继承信号：根据父类名称推断。
    class_name_map: 项目内已知类的 {name: inferred_object_type} 映射。
    """
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS[:-1]}
    if not bases:
        return scores

    for base in bases:
        base_clean = base.split("<")[0].strip()   # 去掉泛型参数

        # 父类名称中的关键词推断
        for layer, suffixes in _NAME_SUFFIXES.items():
            for suffix in suffixes:
                if base_clean.endswith(suffix):
                    scores[layer] = max(scores[layer], 0.9)

        # 如果父类在当前项目中，采用父类的推断结果（降低置信度）
        if class_name_map and base_clean in class_name_map:
            parent_type = class_name_map[base_clean]
            parent_layer = _OBJECT_TYPE_TO_LAYER.get(parent_type, "UNKNOWN")
            if parent_layer != "UNKNOWN":
                scores[parent_layer] = max(scores[parent_layer], 0.8)

    return scores


def _score_imports(
    imports: List[str],
    code_graph_in_degrees: Optional[Dict[str, int]] = None,
    class_fqn: Optional[str] = None,
) -> Dict[str, float]:
    """
    导入信号：分析依赖方向。
    - 被很多类依赖（高 in_degree）→ 底层（DOMAIN/PLATFORM）
    - 自身导入了很多类 → 偏上层（ADAPTER/APP）
    """
    scores: Dict[str, float] = {layer: 0.0 for layer in LAYERS[:-1]}

    if code_graph_in_degrees and class_fqn:
        in_deg = code_graph_in_degrees.get(class_fqn, 0)
        # 被多处依赖 → 更可能是底层核心模块
        if in_deg >= 5:
            scores["DOMAIN"] = max(scores["DOMAIN"], 0.6)
            scores["PLATFORM"] = max(scores["PLATFORM"], 0.4)
        elif in_deg >= 3:
            scores["DOMAIN"] = max(scores["DOMAIN"], 0.4)

    return scores


def _pick_winner(layer_scores: Dict[str, float]) -> tuple:
    """选出得分最高的层，返回 (layer, confidence)。"""
    if not layer_scores:
        return "UNKNOWN", 0.0

    sorted_layers = sorted(layer_scores.items(), key=lambda x: x[1], reverse=True)
    best_layer, best_score = sorted_layers[0]

    if best_score < 0.01:
        return "UNKNOWN", 0.0

    # 计算置信度：最高分 vs 第二高分的差距
    second_score = sorted_layers[1][1] if len(sorted_layers) > 1 else 0.0
    confidence = best_score * (1.0 - 0.3 * (second_score / best_score if best_score > 0 else 0))
    confidence = min(confidence, 1.0)

    return best_layer, round(confidence, 3)


# ─── 主函数：fn_infer_layer ───────────────────────────────────────────────────

def infer_layer(
    class_name: str,
    file_path: str,
    annotations: Optional[List[str]] = None,
    bases: Optional[List[str]] = None,
    imports: Optional[List[str]] = None,
    class_name_map: Optional[Dict[str, str]] = None,
    code_graph_in_degrees: Optional[Dict[str, int]] = None,
    class_fqn: Optional[str] = None,
) -> LayerInference:
    """
    fn_infer_layer 的 Python 实现。

    五路信号融合推断 CodeClass 的架构层归属。
    对应 docs/memory/ontology/functions/fn_infer_layer.yaml 的定义。

    Args:
        class_name:             类名（如 "UserController"）
        file_path:              文件路径（如 "src/controllers/user.py"）
        annotations:            类级注解/装饰器列表
        bases:                  父类列表
        imports:                文件级 import 的类名列表
        class_name_map:         项目已知类 {name: inferred_object_type}（供继承信号使用）
        code_graph_in_degrees:  代码图中各类的入度 {class_fqn: int}（供导入信号使用）
        class_fqn:              全限定类名（用于查询 in_degree）

    Returns:
        LayerInference 对象
    """
    annotations = annotations or []
    bases = bases or []
    imports = imports or []

    # 计算各路信号得分
    path_scores  = _score_path(file_path)
    name_scores  = _score_name(class_name)
    annot_scores = _score_annotations(annotations)
    inh_scores   = _score_inheritance(bases, class_name_map)
    imp_scores   = _score_imports(imports, code_graph_in_degrees, class_fqn)

    # 合并：对每个层求加权总分
    layers_to_check = [l for l in LAYERS if l != "UNKNOWN"]
    combined: Dict[str, float] = {}
    for layer in layers_to_check:
        combined[layer] = (
            path_scores.get(layer, 0.0)  * _WEIGHTS["path"] +
            name_scores.get(layer, 0.0)  * _WEIGHTS["name"] +
            annot_scores.get(layer, 0.0) * _WEIGHTS["annotation"] +
            inh_scores.get(layer, 0.0)   * _WEIGHTS["inheritance"] +
            imp_scores.get(layer, 0.0)   * _WEIGHTS["import"]
        )

    best_layer, confidence = _pick_winner(combined)

    breakdown = SignalBreakdown(
        path_score=path_scores.get(best_layer, 0.0),
        name_score=name_scores.get(best_layer, 0.0),
        annotation_score=annot_scores.get(best_layer, 0.0),
        inheritance_score=inh_scores.get(best_layer, 0.0),
        import_score=imp_scores.get(best_layer, 0.0),
    )

    all_scores = [
        LayerScore(layer=l, score=round(s, 3))
        for l, s in sorted(combined.items(), key=lambda x: x[1], reverse=True)
    ]

    return LayerInference(
        inferred_layer=best_layer,
        confidence=confidence,
        signal_breakdown=breakdown,
        all_scores=all_scores,
    )


# ─── 主函数：fn_detect_code_object_type ──────────────────────────────────────

def detect_code_object_type(
    class_name: str,
    annotations: Optional[List[str]] = None,
    methods: Optional[List[dict]] = None,
    layer_inference: Optional[LayerInference] = None,
) -> ObjectTypeMapping:
    """
    fn_detect_code_object_type 的 Python 实现。

    在层推断结果基础上，进一步判断代码对象的语义类型。

    Returns:
        ObjectTypeMapping 对象
    """
    annotations = annotations or []
    methods = methods or []
    layer = layer_inference.inferred_layer if layer_inference else "UNKNOWN"

    code_object_type = "Unknown"

    if layer == "ADAPTER":
        # 区分 Controller vs Adapter/Gateway
        has_http = any(
            re.search(pat, " ".join(annotations))
            for pat in _ANNOTATION_PATTERNS["ADAPTER"]
        )
        if has_http or any(
            class_name.endswith(s) for s in ["Controller", "Handler", "View", "Router"]
        ):
            code_object_type = "Controller"
        else:
            code_object_type = "Controller"   # ADAPTER 层默认归 Controller

    elif layer == "APP":
        code_object_type = "Service"

    elif layer == "DOMAIN":
        # 区分 Entity vs Repository
        annot_str = " ".join(annotations)
        is_entity = (
            re.search(r"@Entity|@Table|@Document|@dataclass|dataclass", annot_str)
            or any(class_name.endswith(s) for s in ["Entity", "Aggregate", "ValueObject", "Model"])
        )
        is_repo = any(
            class_name.endswith(s) for s in ["Repository", "Repo", "DAO", "Store", "Mapper"]
        )
        if is_repo:
            code_object_type = "Repository"
        elif is_entity:
            code_object_type = "Entity"
        else:
            code_object_type = "Entity"   # DOMAIN 层默认归 Entity

    elif layer == "PLATFORM":
        code_object_type = "Config"

    elif layer == "CC":
        # CC 层：工具类和异常不生成记忆
        code_object_type = "Util"

    else:
        code_object_type = "Unknown"

    suggested_layer = _OBJECT_TYPE_TO_LAYER.get(code_object_type, "UNKNOWN")
    memory_node_type = _OBJECT_TYPE_TO_MEMORY_TYPE.get(code_object_type, "skip")
    suggested_tier = _OBJECT_TYPE_TO_TIER.get(code_object_type, "cold")

    return ObjectTypeMapping(
        code_object_type=code_object_type,
        memory_node_type=memory_node_type,
        suggested_tier=suggested_tier,
        suggested_layer=suggested_layer,
    )
