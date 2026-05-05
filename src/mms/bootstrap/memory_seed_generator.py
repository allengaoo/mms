"""
src/mms/bootstrap/memory_seed_generator.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
初始记忆生成器（Bootstrap Action Rule 07 的实现）

为每个被识别出的核心 CodeClass 生成初始 MemoryNode（MEM-BOOT-*.md），
自动填充：
  - layer / tier（来自 fn_detect_code_object_type）
  - cites_files（所在文件路径）
  - about_concepts（来自 inferred_layer + class_name 关键词）
  - ast_pointer（文件路径 + 类名 + fingerprint）
  - tags（从类名拆解 + 层级标签）

版本：v1.0 | 创建于：2026-04-30 | Bootstrap v2
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from mms.bootstrap.signal_fusion import LayerInference, ObjectTypeMapping

# ─── 数据类 ──────────────────────────────────────────────────────────────────

@dataclass
class GeneratedMemory:
    memory_id: str
    file_path: Path
    content: str
    layer: str
    tier: str
    class_fqn: str


@dataclass
class GeneratorReport:
    generated: List[GeneratedMemory] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)  # skipped class_fqns
    layer_distribution: Dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.generated)


# ─── 标签提取 ─────────────────────────────────────────────────────────────────

def _extract_tags(class_name: str, layer: str, code_type: str) -> List[str]:
    """从类名拆解关键词作为 tags。"""
    # 驼峰/帕斯卡命名拆分
    words = re.sub(r"([A-Z])", r" \1", class_name).strip().split()
    tags = [w.lower() for w in words if len(w) > 2]

    # 添加层级和类型标签
    layer_tags = {
        "ADAPTER":  ["rest-api", "http-adapter"],
        "APP":      ["application-service", "use-case"],
        "DOMAIN":   ["domain-model"],
        "PLATFORM": ["infrastructure", "cross-cutting"],
        "CC":       ["cross-cutting"],
    }
    type_tags = {
        "Controller": ["controller", "rest-endpoint"],
        "Service":    ["service", "business-logic"],
        "Repository": ["repository", "data-access"],
        "Entity":     ["entity", "domain-object"],
        "Config":     ["configuration"],
    }
    tags.extend(layer_tags.get(layer, []))
    tags.extend(type_tags.get(code_type, []))
    return sorted(set(tags))


def _extract_about_concepts(class_name: str, layer: str) -> List[str]:
    """从类名提取 DomainConcept 关键词（用于 about 边建立）。"""
    words = re.sub(r"([A-Z])", r" \1", class_name).strip().split()
    concepts = [w.lower() for w in words if len(w) > 3]

    layer_concepts = {
        "ADAPTER":  ["rest-api"],
        "APP":      ["application-service"],
        "DOMAIN":   ["domain-model", "business-logic"],
        "PLATFORM": ["infrastructure"],
        "CC":       ["cross-cutting"],
    }
    concepts.extend(layer_concepts.get(layer, []))
    return sorted(set(concepts))


# ─── 记忆 Markdown 生成 ───────────────────────────────────────────────────────

# Bootstrap 内部层名 → MemoryNode schema 规范层名（memory_node.yaml enum v4.0 细粒度 ID）
# Bootstrap 使用 DDD 术语（ADAPTER/APP/DOMAIN），schema v4.0 使用细粒度 ID
_SCHEMA_LAYER_MAP = {
    "ADAPTER":  "L5_api",            # HTTP controller / gRPC handler / CLI adapter → API 接口层
    "APP":      "L4_service",        # Application service / use case orchestrator → 应用服务层
    "DOMAIN":   "L3_ontology",       # Domain entity / repository / aggregate → 领域层（本体语义）
    "PLATFORM": "L2_infrastructure", # Database client / config / message broker → 基础设施层
    "CC":       "CC_architecture",   # Cross-cutting: util / exception / logging → 横切架构层
    "UNKNOWN":  "CC_architecture",   # Fallback
}

# 目录名仍保留 Bootstrap 语义（便于开发者理解层级归属）
_LAYER_DIR_NAMES = {
    "ADAPTER":  "ADAPTER",
    "APP":      "APP",
    "DOMAIN":   "DOMAIN",
    "PLATFORM": "PLATFORM",
    "CC":       "CC",
}

def _compute_fingerprint(methods: List[dict]) -> str:
    """基于方法签名列表计算 AST fingerprint（SHA-256 前 16 字符）。

    对方法名+签名字符串排序后做哈希，使 fingerprint 对方法顺序不敏感，
    但对方法增删和签名变更敏感，满足漂移检测需求。
    """
    if not methods:
        return ""
    sigs = sorted(
        f"{m.get('name', '')}:{m.get('signature', '')}"
        for m in methods
        if isinstance(m, dict) and m.get("name")
    )
    content = "\n".join(sigs)
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


_TYPE_DESCRIPTIONS = {
    "Controller": "REST 适配层入口，负责接收 HTTP 请求并委托给应用服务层",
    "Service":    "应用服务层，编排领域逻辑，实现业务用例",
    "Repository": "数据访问层，封装持久化操作，实现领域层与数据库的隔离",
    "Entity":     "领域实体，承载核心业务状态与不变式",
    "Config":     "平台配置，定义横切基础设施（安全/配置/Bean 注册等）",
}


def _render_memory_md(
    memory_id: str,
    class_name: str,
    file_path: str,
    layer: str,
    tier: str,
    code_type: str,
    tags: List[str],
    about_concepts: List[str],
    fingerprint: str,
    methods: List[dict],
    bases: List[str],
    annotations: List[str],
    layer_confidence: float,
) -> str:
    """渲染 MEM-BOOT-*.md 的完整内容。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # front-matter
    tags_yaml = "[" + ", ".join(tags[:8]) + "]"
    about_yaml = "[" + ", ".join(about_concepts[:5]) + "]"
    bases_str = ", ".join(bases[:3]) if bases else "—"
    annot_str = ", ".join(annotations[:3]) if annotations else "—"

    # 方法摘要（最多展示 5 个）
    method_lines = []
    for m in methods[:5]:
        if not isinstance(m, dict):
            continue
        name = m.get("name", "")
        sig  = m.get("signature", "()")
        is_async = "async " if m.get("is_async") else ""
        if name:
            method_lines.append(f"  - `{is_async}{name}{sig}`")
    methods_md = "\n".join(method_lines) if method_lines else "  - （无公开方法）"
    if len(methods) > 5:
        methods_md += f"\n  - _...共 {len(methods)} 个方法_"

    type_desc = _TYPE_DESCRIPTIONS.get(code_type, f"{code_type} 类型代码对象")

    schema_layer = _SCHEMA_LAYER_MAP.get(layer, layer)

    content = f"""\
---
id: {memory_id}
type: pattern
layer: {schema_layer}
tier: {tier}
tags: {tags_yaml}
cites_files:
  - {file_path}
about_concepts: {about_yaml}
impacts: []
derived_from: []
ast_pointer:
  file_path: {file_path}
  class_name: {class_name}
  fingerprint: {fingerprint or ""}
  drift: false
provenance:
  trigger_type: bootstrap_v2
  generated_at: {now}
  layer_confidence: {layer_confidence:.2f}
version: 1
created_at: {now}
---
# {class_name} — {type_desc}

> **自动生成**：由 `mulan bootstrap` v2 扫描代码库生成，基于五路信号融合（置信度 {layer_confidence:.0%}）。
> 请在积累实际使用经验后，用 `mulan distill` 或 `mulan private` 完善此记忆。

## 代码位置

- 文件：`{file_path}`
- 继承：{bases_str}
- 注解：{annot_str}

## 公开方法

{methods_md}

## 架构职责

此类属于 **{layer}** 层的 **{code_type}** 类型。{type_desc}。

- 修改此类时，请同步更新相关 MemoryNode 的 `cites_files` 和 `about_concepts`。
- 如此类发生接口契约变更，请运行 `mulan ast-diff` 检测影响范围。
"""
    return content


# ─── 主生成器 ─────────────────────────────────────────────────────────────────

def generate_seed_memories(
    inference_results: Dict[str, Tuple[LayerInference, ObjectTypeMapping]],
    ast_index: Dict[str, dict],
    output_dir: Path,
    min_confidence: float = 0.5,
    max_per_layer: int = 10,
    dry_run: bool = False,
    id_prefix: str = "MEM-BOOT",
    existing_fingerprints: Optional[Dict[str, str]] = None,
) -> GeneratorReport:
    """
    为推断结果中的核心类生成初始 MemoryNode 文件。

    Args:
        inference_results:  signal_fusion.infer_all() 的输出
        ast_index:          build_ast_index() 的输出（取方法和指纹）
        output_dir:         输出根目录（docs/memory/shared/）
        min_confidence:     置信度阈值（低于此值跳过）
        max_per_layer:      每层最多生成的记忆数
        dry_run:            不写文件，只返回报告
        id_prefix:          记忆 ID 前缀

    Returns:
        GeneratorReport
    """
    report = GeneratorReport()
    layer_counts: Dict[str, int] = {}
    counter = 1
    _existing_fps = existing_fingerprints or {}

    # 按层+in_degree 排序，优先处理核心类
    def priority_key(item: Tuple[str, Tuple[LayerInference, ObjectTypeMapping]]) -> float:
        fqn, (layer_inf, _) = item
        return layer_inf.confidence

    sorted_items = sorted(inference_results.items(), key=priority_key, reverse=True)

    # 构建 AST 数据快速查找索引
    class_data_index: Dict[str, dict] = {}
    for file_path, file_data in ast_index.items():
        for cls in (file_data.get("classes") or []):
            name = cls.get("name", "")
            fqn = f"{file_path}::{name}"
            class_data_index[fqn] = {**cls, "file_path": file_path}

    for class_fqn, (layer_inf, obj_map) in sorted_items:
        # 跳过低置信度
        if layer_inf.confidence < min_confidence:
            report.skipped.append(class_fqn)
            continue

        # 跳过 skip 类型（Util/Test 等）
        if obj_map.memory_node_type == "skip":
            report.skipped.append(class_fqn)
            continue

        layer = obj_map.suggested_layer
        # 每层上限检查
        if layer_counts.get(layer, 0) >= max_per_layer:
            report.skipped.append(class_fqn)
            continue

        # 获取类详细数据
        cls_data = class_data_index.get(class_fqn, {})
        class_name = cls_data.get("name", class_fqn.split("::")[-1])
        file_path = cls_data.get("file_path", class_fqn.split("::")[0])

        memory_id = f"{id_prefix}-{counter:03d}"
        counter += 1

        tags = _extract_tags(class_name, layer, obj_map.code_object_type)
        about_concepts = _extract_about_concepts(class_name, layer)

        methods_list = cls_data.get("methods", [])
        # 计算真实 fingerprint（方法签名哈希），用于漂移检测
        fingerprint = cls_data.get("fingerprint", "") or _compute_fingerprint(methods_list)

        # 增量幂等检查：若已有同类名记忆且 fingerprint 相同，跳过生成
        # 注意：fingerprint 可能为 "" (无方法类)，两者均为 "" 时也视为未变化
        if class_name in _existing_fps and _existing_fps.get(class_name, "MISSING") == fingerprint:
            report.skipped.append(class_fqn)
            continue

        content = _render_memory_md(
            memory_id=memory_id,
            class_name=class_name,
            file_path=file_path,
            layer=layer,
            tier=obj_map.suggested_tier,
            code_type=obj_map.code_object_type,
            tags=tags,
            about_concepts=about_concepts,
            fingerprint=fingerprint,
            methods=methods_list,
            bases=cls_data.get("bases", []),
            annotations=cls_data.get("annotations", []),
            layer_confidence=layer_inf.confidence,
        )

        # 确定输出路径（docs/memory/shared/{LAYER}/MEM-BOOT-NNN.md）
        layer_dir = output_dir / layer
        out_path = layer_dir / f"{memory_id}.md"

        if not dry_run:
            layer_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")

        report.generated.append(GeneratedMemory(
            memory_id=memory_id,
            file_path=out_path,
            content=content,
            layer=layer,
            tier=obj_map.suggested_tier,
            class_fqn=class_fqn,
        ))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    report.layer_distribution = dict(layer_counts)
    return report
