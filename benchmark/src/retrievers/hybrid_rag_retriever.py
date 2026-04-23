"""
hybrid_rag_retriever.py — Hybrid RAG 检索器（ES BM25 + Milvus 向量 + RRF）
============================================================================
代表当前主流生产级 RAG 系统：
  1. Elasticsearch BM25 全文检索 → Top-N 候选
  2. Milvus 向量语义检索（Bailian text-embedding-v3）→ Top-N 候选
  3. Reciprocal Rank Fusion (RRF) 融合两路排名 → 最终 Top-K

RRF 公式：
    score(d) = Σ_{r ∈ {ES, MV}} 1 / (k + rank_r(d))
    其中 k=60（标准值），rank 从 1 开始，未出现的文档 rank → ∞（贡献 0）

设计：
  - ES 和 Milvus 各自先取 es_top_k / mv_top_k 个候选（通常 10 个）
  - RRF 合并后取最终 Top-K（通常 5 个）
  - 详细记录 es_scores / milvus_distances / rrf_scores 供后续分析
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from schema import RetrievalResult, RetrievedDoc
from .base import BaseRetriever

try:
    from elasticsearch import Elasticsearch
    _ES_OK = True
except ImportError:
    _ES_OK = False

try:
    from pymilvus import connections as mv_connections, Collection
    _MV_OK = True
except ImportError:
    _MV_OK = False

try:
    from providers.bailian import BailianEmbedProvider
    _EMBED_OK = True
except ImportError:
    _EMBED_OK = False


class HybridRAGRetriever(BaseRetriever):
    """
    混合 RAG 检索器：ES BM25 + Milvus HNSW + RRF 融合。
    """

    def __init__(self, system_name: str, cfg: Dict[str, Any]):
        super().__init__(system_name, cfg)
        self._es: Optional[Any] = None
        self._mv_col: Optional[Any] = None
        self._embed_provider: Optional[Any] = None
        self._ready = False

    def _ensure_connected(self) -> None:
        if self._ready:
            return

        es_cfg = self.cfg["infrastructure"]["elasticsearch"]
        mv_cfg = self.cfg["infrastructure"]["milvus"]

        # Elasticsearch
        if _ES_OK:
            self._es = Elasticsearch(
                f"http://{es_cfg['host']}:{es_cfg['port']}",
                request_timeout=es_cfg["timeout"],
            )

        # Milvus
        if _MV_OK:
            mv_connections.connect(
                "default",
                host=mv_cfg["host"],
                port=str(mv_cfg["port"]),
            )
            try:
                self._mv_col = Collection(mv_cfg["collection_name"])
                self._mv_col.load()
            except Exception:
                self._mv_col = None

        # Embedding
        if _EMBED_OK:
            self._embed_provider = BailianEmbedProvider()

        self._ready = True

    def _es_search(
        self, query: str, index: str, top_k: int
    ) -> Tuple[List[Tuple[str, float, str]], float]:
        """
        ES BM25 检索。
        返回 ([(doc_id, score, content), ...], latency_ms)
        """
        if not self._es:
            return [], 0.0
        t0 = time.perf_counter()
        try:
            resp = self._es.search(
                index=index,
                body={
                    "query": {"match": {"content": query}},
                    "size": top_k,
                    "_source": ["chunk_id", "source_file", "content",
                                "memory_id", "layer", "tokens_est"],
                },
            )
            hits = resp["hits"]["hits"]
            results = [
                (
                    h["_source"]["source_file"],
                    h["_score"],
                    h["_source"]["content"],
                    h["_source"].get("memory_id", ""),
                )
                for h in hits
            ]
        except Exception:
            results = []
        latency = (time.perf_counter() - t0) * 1000
        return results, round(latency, 2)

    def _milvus_search(
        self, query: str, collection_name: str, top_k: int, search_params: dict
    ) -> Tuple[List[Tuple[str, float, str]], float, float]:
        """
        Milvus 向量检索。
        返回 ([(doc_id, distance, content), ...], embed_latency_ms, search_latency_ms)
        """
        if not self._mv_col or not self._embed_provider:
            return [], 0.0, 0.0

        # Embedding
        t0 = time.perf_counter()
        try:
            vec = self._embed_provider.embed(query)
        except Exception:
            return [], 0.0, 0.0
        embed_latency = (time.perf_counter() - t0) * 1000

        # 向量搜索
        t1 = time.perf_counter()
        results = []
        try:
            results_raw = self._mv_col.search(
                data=[vec],
                anns_field="embedding",
                param=search_params,
                limit=top_k,
                output_fields=["source_file", "content_preview", "memory_id"],
            )
            for hit in results_raw[0]:
                # pymilvus entity 字段通过属性访问，不是 dict.get()
                try:
                    sf = getattr(hit.entity, "source_file", None) or ""
                    cp = getattr(hit.entity, "content_preview", None) or ""
                    mid = getattr(hit.entity, "memory_id", None) or ""
                except Exception:
                    sf, cp, mid = "", "", ""
                results.append((sf, hit.distance, cp, mid))
        except Exception as e:
            # 记录到 stderr，不静默
            import sys
            print(f"  [Milvus search error]: {e}", file=sys.stderr)
        search_latency = (time.perf_counter() - t1) * 1000

        return results, round(embed_latency, 2), round(search_latency, 2)

    def _rrf_merge(
        self,
        es_results: list,
        mv_results: list,
        k: int = 60,
        top_n: int = 5,
    ) -> List[Dict]:
        """
        Reciprocal Rank Fusion 融合两路结果。

        公式：score(d) = Σ_{r ∈ {ES,MV}} 1/(k + rank_r(d))
              rank 从 1 开始，文档不出现则贡献 0。

        返回：[{doc_id, rrf_score, es_rank, mv_rank, content, memory_id}, ...]
        """
        # 建立文档 → 内容的映射
        doc_content: Dict[str, str] = {}
        doc_memory: Dict[str, str] = {}

        # ES 排名
        es_rank: Dict[str, int] = {}
        for rank, item in enumerate(es_results, start=1):
            doc_id = item[0]
            es_rank[doc_id] = rank
            doc_content[doc_id] = item[2]
            doc_memory[doc_id] = item[3] if len(item) > 3 else ""

        # Milvus 排名
        mv_rank: Dict[str, int] = {}
        for rank, item in enumerate(mv_results, start=1):
            doc_id = item[0]
            mv_rank[doc_id] = rank
            if doc_id not in doc_content:
                doc_content[doc_id] = item[2]
                doc_memory[doc_id] = item[3] if len(item) > 3 else ""

        # 所有出现的文档
        all_docs = set(es_rank.keys()) | set(mv_rank.keys())

        merged = []
        for doc_id in all_docs:
            rrf_es = 1.0 / (k + es_rank[doc_id]) if doc_id in es_rank else 0.0
            rrf_mv = 1.0 / (k + mv_rank[doc_id]) if doc_id in mv_rank else 0.0
            merged.append({
                "doc_id": doc_id,
                "rrf_score": round(rrf_es + rrf_mv, 6),
                "es_rank": es_rank.get(doc_id),
                "mv_rank": mv_rank.get(doc_id),
                "es_score": es_results[es_rank[doc_id] - 1][1] if doc_id in es_rank else None,
                "mv_distance": mv_results[mv_rank[doc_id] - 1][1] if doc_id in mv_rank else None,
                "content": doc_content.get(doc_id, ""),
                "memory_id": doc_memory.get(doc_id, ""),
            })

        merged.sort(key=lambda x: -x["rrf_score"])
        return merged[:top_n]

    def retrieve(self, query: str, query_id: str, top_k: int = 5) -> RetrievalResult:
        t_start = self._now_ms()
        self._ensure_connected()

        sys_cfg = self.cfg["systems"]["hybrid_rag"]
        retrieval = sys_cfg["retrieval"]
        es_cfg = self.cfg["infrastructure"]["elasticsearch"]
        mv_cfg = self.cfg["infrastructure"]["milvus"]

        es_top_k = retrieval.get("es_top_k", 10)
        mv_top_k = retrieval.get("mv_top_k", 10)
        rrf_k = retrieval.get("rrf_k", 60)

        # ES 检索
        es_results, es_latency = self._es_search(
            query, es_cfg["index_name"], es_top_k
        )

        # Milvus 检索
        search_params = mv_cfg.get("search_params", {"ef": 64})
        mv_results, embed_latency, mv_latency = self._milvus_search(
            query, mv_cfg["collection_name"], mv_top_k, search_params
        )

        # RRF 融合
        merged = self._rrf_merge(es_results, mv_results, k=rrf_k, top_n=top_k)

        # 构建返回结果
        docs = []
        context_parts = []
        rrf_scores = []
        es_scores_list = []
        mv_distances_list = []

        for item in merged:
            mem_id = item["memory_id"] or self._extract_memory_id(item["doc_id"])
            docs.append(RetrievedDoc(
                doc_id=item["doc_id"],
                content=item["content"],
                score=item["rrf_score"],
                source_file=item["doc_id"],
                es_score=item.get("es_score"),
                milvus_distance=item.get("mv_distance"),
                rrf_rank_es=item.get("es_rank"),
                rrf_rank_mv=item.get("mv_rank"),
            ))
            context_parts.append(f"[{item['doc_id']}]\n{item['content']}")
            rrf_scores.append(item["rrf_score"])
            if item.get("es_score") is not None:
                es_scores_list.append(item["es_score"])
            if item.get("mv_distance") is not None:
                mv_distances_list.append(item["mv_distance"])

        context = "\n\n---\n\n".join(context_parts)
        t_end = self._now_ms()

        result = self._make_result(query_id)
        result.docs = docs
        result.latency_ms = round(t_end - t_start, 2)
        result.embed_latency_ms = embed_latency
        result.es_latency_ms = es_latency
        result.milvus_latency_ms = mv_latency
        result.context_chars = len(context)
        result.context_tokens_est = self._estimate_tokens(context)
        return result
