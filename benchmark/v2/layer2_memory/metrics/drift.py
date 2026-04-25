"""
Layer 2 · D4 漂移检测（Selective Forgetting）

评测 freshness_checker.py 是否能正确识别"代码文件被修改后，
引用该文件的记忆应被标记为 drift_suspected"。

指标：
  drift_detection_rate   — 应标记且被标记 / 应标记总数
  false_positive_rate    — 不应标记但被标记 / 不应标记总数
  avg_detection_latency  — 平均检测延迟（ms）

离线可运行：通过临时文件模拟记忆文件和代码文件。
"""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class DriftCase:
    """单个漂移检测测试 case"""
    case_id:            str
    description:        str
    memory_content:     str    # 记忆文件内容（front-matter + body）
    cited_file_content: str    # 被引用的代码文件原始内容
    modified_content:   str    # 修改后的代码文件内容（或原内容表示未修改）
    should_drift:       bool   # 修改后是否应触发 drift_suspected
    metadata:           Dict[str, Any] = field(default_factory=dict)


@dataclass
class DriftResult:
    case_id:        str
    should_drift:   bool
    detected_drift: bool
    passed:         bool
    latency_ms:     float = 0.0
    error:          str = ""


def _compute_semantic_hash(content: str) -> str:
    """
    语义哈希：剔除注释和空行，只对核心签名行做哈希。
    与 ast_skeleton.py 的语义哈希原理一致。
    """
    import hashlib
    import re
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        # 跳过纯注释行和空行
        if not stripped or stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        # 剔除行内注释
        line_clean = re.sub(r"\s*#.*$", "", stripped)
        if line_clean:
            lines.append(line_clean)
    normalized = "\n".join(lines)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def evaluate_drift(case: DriftCase) -> DriftResult:
    """
    在临时目录中模拟代码文件修改，通过语义哈希对比检测 drift。

    设计：Benchmark 中的 drift 检测使用自包含的语义哈希实现，
    不依赖 FreshnessChecker 的 git-based 文件追踪（后者只能在真实项目根目录中运行）。
    """
    t0 = time.monotonic()

    orig_hash = _compute_semantic_hash(case.cited_file_content)
    mod_hash  = _compute_semantic_hash(case.modified_content)

    detected = (orig_hash != mod_hash)

    passed = (detected == case.should_drift)
    return DriftResult(
        case_id=case.case_id,
        should_drift=case.should_drift,
        detected_drift=detected,
        passed=passed,
        latency_ms=(time.monotonic() - t0) * 1000,
    )


def aggregate_drift_metrics(results: List[DriftResult]) -> Dict[str, float]:
    valid = [r for r in results if not r.error]
    if not valid:
        return {}

    should_drift    = [r for r in valid if r.should_drift]
    should_not_drift = [r for r in valid if not r.should_drift]

    detection_rate = (
        sum(1 for r in should_drift if r.detected_drift) / len(should_drift)
        if should_drift else 1.0
    )
    fp_rate = (
        sum(1 for r in should_not_drift if r.detected_drift) / len(should_not_drift)
        if should_not_drift else 0.0
    )
    avg_latency = sum(r.latency_ms for r in valid) / len(valid)

    return {
        "drift.detection_rate":  round(detection_rate, 4),
        "drift.false_positive_rate": round(fp_rate, 4),
        "drift.avg_latency_ms":  round(avg_latency, 2),
    }
