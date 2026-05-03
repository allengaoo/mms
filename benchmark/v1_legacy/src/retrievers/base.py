"""
base.py — 检索器抽象基类
===========================
所有检索器必须实现此接口，保证评估器可以统一调用。

扩展说明：
    新增检索系统时，继承 BaseRetriever，实现 retrieve() 方法，
    然后在 registry.py 的 RETRIEVERS 字典中注册即可。
    无需修改评估器或报告器。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from schema import RetrievalResult


class BaseRetriever(ABC):
    """
    检索器统一接口。

    每个检索器负责：
      1. retrieve(query, top_k) → RetrievalResult
      2. 在 RetrievalResult 中填写所有可用的性能字段
      3. 计算 context_chars / context_tokens_est

    禁止在检索器中调用 LLM（保证 benchmark 可复现性）。
    """

    def __init__(self, system_name: str, cfg: Dict[str, Any]):
        self.system_name = system_name
        self.cfg = cfg

    @abstractmethod
    def retrieve(self, query: str, query_id: str, top_k: int = 5) -> RetrievalResult:
        """
        执行检索并返回结果。

        Args:
            query:    用户自然语言任务描述
            query_id: 对应 queries.yaml 中的 query_id（用于 JSONL 记录）
            top_k:    返回文档数量上限

        Returns:
            RetrievalResult（必须填写 latency_ms 和 context_tokens_est）
        """

    def _make_result(self, query_id: str) -> RetrievalResult:
        """创建空结果对象的工厂方法"""
        return RetrievalResult(system=self.system_name, query_id=query_id)

    @staticmethod
    def _now_ms() -> float:
        return time.perf_counter() * 1000

    @staticmethod
    def _estimate_tokens(text: str, ratio: int = 4) -> int:
        return len(text) // ratio

    @staticmethod
    def _extract_memory_id(source_file: str) -> str:
        """从文件路径提取记忆 ID，如 MEM-DB-002 / AD-002"""
        import re
        m = re.search(r'(MEM-[A-Z]+-\d+|AD-\d+|BIZ-\d+|ENV-\d+)', source_file)
        return m.group(1) if m else ""
