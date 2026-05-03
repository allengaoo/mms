"""
efficiency.py — 效率指标计算
==============================
实现 3 个效率指标：
  - context_tokens   上下文 token 估算
  - info_density     有效信息密度（核心：小模型场景最重要）
  - actionability    可执行性等级（0-3 中立量表）
"""
from __future__ import annotations

from typing import List

from schema import ActionabilityLevel


def context_tokens(retrieval_result, gt, cfg: dict) -> int:
    """
    上下文 token 估算。

    公式：ContextTokens_i = floor(|context_i|_chars / char_per_token)
    char_per_token 默认 4（中英混合通用估算）。
    """
    return retrieval_result.context_tokens_est


def info_density(retrieval_result, gt, cfg: dict) -> float:
    """
    有效信息密度。

    公式：InfoDensity = Recall@K / max(ContextTokens / token_unit, 0.1)
    token_unit 默认 1000（每千 token 的信息价值）。

    设计意图：
      小参数模型注意力窗口有限（约 4000 token），
      高密度意味着"每个 token 都在做有用的事"。
      本体系统注入少量精确内容，密度高；
      Markdown Index 注入整个 Manifest，大量无关内容，密度低。
    """
    from metrics.accuracy import recall_at_k as calc_recall
    rc = calc_recall(retrieval_result, gt, cfg)
    tokens = max(retrieval_result.context_tokens_est, 1)
    token_unit = cfg.get("params", {}).get("token_unit", 1000)
    denominator = max(tokens / token_unit, 0.1)
    return round(rc / denominator, 4)


def actionability(retrieval_result, gt, cfg: dict) -> ActionabilityLevel:
    """
    可执行性等级（0-3 中立量表）。

    Level 0：返回内容与 GT 架构层无关
    Level 1：返回相关领域的文档片段（GT 层相关）
    Level 2：返回相关且磁盘有效的文件路径
    Level 3：返回可直接执行的命令（cli_usage 或记忆文件中的命令示例）

    设计说明：
      三个系统都使用同一量表，不因"有没有 ActionDef"而二元化。
      RAG 系统若检索到包含 ```bash``` 代码块的记忆文件，同样可以得到 Level 3。
    """
    if not retrieval_result.docs:
        return ActionabilityLevel(level=0, reason="无检索结果")

    from pathlib import Path
    _ROOT = Path(__file__).parent.parent.parent.parent  # benchmark/src/metrics → mms root

    # ── Level 3：有可执行命令 ────────────────────────────────────────────
    # 本体系统：executable_cmds 非空
    if getattr(retrieval_result, "executable_cmds", []):
        return ActionabilityLevel(level=3, reason="ActionDef 提供了可执行命令")

    # 任意系统：文档内容中含有 ```bash 代码块
    for doc in retrieval_result.docs[:5]:
        if "```bash" in doc.content or "```shell" in doc.content:
            return ActionabilityLevel(level=3, reason="记忆文件包含可执行命令示例")
        # 检查类似 "python3 scripts/mms/cli.py" 的命令行
        import re
        if re.search(r'(python3?|mms|kubectl|curl|docker)\s+\S+', doc.content):
            return ActionabilityLevel(level=3, reason="文档包含命令行示例")

    # ── Level 2：有磁盘有效路径 ─────────────────────────────────────────
    from metrics.accuracy import _path_match
    for doc in retrieval_result.docs[:5]:
        path = _ROOT / doc.source_file
        if path.exists() or path.is_dir():
            # 检查是否和 GT layer 相关
            from metrics.accuracy import _infer_layer_from_docs
            predicted_layer = (
                retrieval_result.layer
                or _infer_layer_from_docs(retrieval_result.docs)
            )
            if predicted_layer == gt.layer:
                return ActionabilityLevel(level=2, reason=f"返回有效路径且层命中 ({predicted_layer})")
            else:
                return ActionabilityLevel(level=2, reason=f"返回有效路径（层不完全匹配）")

    # ── Level 1：内容相关（GT 层相关的关键词出现在内容中）─────────────────
    layer_keywords = {
        "L0_mms": ["mms", "trace", "synthesize", "ep_wizard", "unit_runner"],
        "L5_frontend": ["react", "zustand", "component", "navigation", "前端"],
        "L5_api": ["router", "endpoint", "response_model", "fastapi"],
        "L4_service": ["service", "ctx", "securitycontext", "session"],
        "L4_worker": ["worker", "jobexecutionscope", "ingestion"],
        "L3_ontology": ["objecttypedef", "ontology", "action", "本体"],
        "L2_database": ["session", "transaction", "alembic", "mysql"],
        "L2_messaging": ["kafka", "avro", "schema", "topic"],
        "L1_security": ["rbac", "permission", "tenant", "audit"],
        "Ops": ["docker", "k8s", "kubectl", "deploy", "镜像"],
    }
    kws = layer_keywords.get(gt.layer, [])
    combined_content = " ".join(doc.content[:300] for doc in retrieval_result.docs[:5]).lower()
    if any(kw.lower() in combined_content for kw in kws):
        return ActionabilityLevel(level=1, reason=f"内容包含 {gt.layer} 相关关键词")

    return ActionabilityLevel(level=0, reason="返回内容与任务层无关")
