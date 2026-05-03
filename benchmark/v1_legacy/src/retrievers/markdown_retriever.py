"""
markdown_retriever.py — Markdown Index 检索器
===============================================
代表 pageindex 风格：对所有语料文档做 BM25 关键词匹配。
不依赖外部服务，完全本地运行。

算法：
    1. 将 query 分词（中英文混合）
    2. 对每个 chunk 计算 TF-IDF 近似 BM25 得分
    3. 返回 Top-K chunk
    4. 上下文 = 所有 Top-K chunk 的内容拼接
"""
from __future__ import annotations

import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))  # mms root

from schema import RetrievalResult, RetrievedDoc
from corpus_loader import Chunk, CorpusLoader
from .base import BaseRetriever


class MarkdownRetriever(BaseRetriever):
    """
    BM25 Markdown 检索器。

    特点：
      - 无外部服务依赖
      - 第一次调用时懒加载语料（缓存 chunk 列表和 IDF 表）
      - 与 HybridRAG 使用相同语料，公平对比
    """

    # BM25 参数
    _K1 = 1.5
    _B = 0.75

    def __init__(self, system_name: str, cfg: Dict[str, Any]):
        super().__init__(system_name, cfg)
        self._chunks: Optional[List[Chunk]] = None
        self._idf: Optional[Dict[str, float]] = None
        self._avgdl: float = 0.0

    def _ensure_loaded(self) -> None:
        if self._chunks is not None:
            return
        sys_cfg = self.cfg["systems"]["markdown"]
        retrieval = sys_cfg["retrieval"]
        loader = CorpusLoader(
            corpus_paths=sys_cfg["corpus"]["paths"],
            extensions=sys_cfg["corpus"]["extensions"],
            chunk_size=retrieval["chunk_size"],
            chunk_overlap=retrieval["chunk_overlap"],
        )
        self._chunks = loader.load_all()
        self._build_idf()

    def _tokenize(self, text: str) -> List[str]:
        """中英文混合分词：中文按字，英文按词"""
        text = text.lower()
        zh_chars = re.findall(r'[\u4e00-\u9fff]', text)
        en_words = re.findall(r'[a-z0-9_\-\.]{2,}', text)
        return zh_chars + en_words

    def _build_idf(self) -> None:
        """构建 IDF 表"""
        df: Dict[str, int] = {}
        N = len(self._chunks)
        doc_lengths = []
        for chunk in self._chunks:
            tokens = set(self._tokenize(chunk.content))
            for t in tokens:
                df[t] = df.get(t, 0) + 1
            doc_lengths.append(len(self._tokenize(chunk.content)))

        self._avgdl = sum(doc_lengths) / max(N, 1)
        self._idf = {
            t: math.log((N - cnt + 0.5) / (cnt + 0.5) + 1)
            for t, cnt in df.items()
        }
        self._doc_lengths = doc_lengths

    def _bm25_score(self, query_tokens: List[str], chunk_idx: int) -> float:
        """计算单个 chunk 的 BM25 得分"""
        chunk = self._chunks[chunk_idx]
        doc_tokens = self._tokenize(chunk.content)
        tf_map = Counter(doc_tokens)
        dl = self._doc_lengths[chunk_idx]
        score = 0.0
        for qt in query_tokens:
            if qt not in self._idf:
                continue
            tf = tf_map.get(qt, 0)
            idf = self._idf[qt]
            numerator = tf * (self._K1 + 1)
            denominator = tf + self._K1 * (1 - self._B + self._B * dl / max(self._avgdl, 1))
            score += idf * numerator / max(denominator, 1e-9)
        return score

    def retrieve(self, query: str, query_id: str, top_k: int = 5) -> RetrievalResult:
        t_start = self._now_ms()
        self._ensure_loaded()

        query_tokens = self._tokenize(query)
        # 计算所有 chunk 的 BM25 得分
        scored = [
            (i, self._bm25_score(query_tokens, i))
            for i in range(len(self._chunks))
        ]
        scored.sort(key=lambda x: -x[1])
        top = scored[:top_k]

        docs = []
        context_parts = []
        for rank, (idx, score) in enumerate(top):
            chunk = self._chunks[idx]
            mem_id = self._extract_memory_id(chunk.source_file) or chunk.memory_id
            docs.append(RetrievedDoc(
                doc_id=chunk.source_file,
                content=chunk.content,
                score=round(score, 4),
                source_file=chunk.source_file,
            ))
            context_parts.append(f"[{chunk.source_file}]\n{chunk.content}")

        context = "\n\n---\n\n".join(context_parts)
        t_end = self._now_ms()

        result = self._make_result(query_id)
        result.docs = docs
        result.latency_ms = round(t_end - t_start, 2)
        result.context_chars = len(context)
        result.context_tokens_est = self._estimate_tokens(context)
        return result
