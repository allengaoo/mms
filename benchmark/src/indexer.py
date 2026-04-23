"""
indexer.py — ES + Milvus 索引构建
===================================
一次性运行：将语料 chunk 索引到 Elasticsearch 和 Milvus。
索引名/collection 名使用独立命名空间（mms_bm_*），不影响 MDP 生产数据。

运行方式：
    python run_indexer.py [--rebuild]

扩展说明：
    - 语料变化时：运行 run_indexer.py --rebuild 重建索引
    - 修改 chunk 参数：改 config/systems.yaml retrieval.chunk_size
    - 修改向量维度：改 config/systems.yaml infrastructure.embedding.dimension
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import List, Optional

# ── 路径设置 ────────────────────────────────────────────────────────────────
_BENCH_DIR = Path(__file__).parent.parent
_MMS_DIR = _BENCH_DIR.parent
sys.path.insert(0, str(_MMS_DIR))

import yaml
from corpus_loader import Chunk, CorpusLoader

# ── 依赖导入（带降级处理）────────────────────────────────────────────────────
try:
    from elasticsearch import Elasticsearch, helpers as es_helpers
    _ES_OK = True
except ImportError:
    _ES_OK = False

try:
    from pymilvus import (
        connections as mv_connections,
        Collection, CollectionSchema, FieldSchema, DataType,
        utility as mv_utility,
    )
    _MV_OK = True
except ImportError:
    _MV_OK = False

try:
    from providers.bailian import BailianEmbedProvider
    _EMBED_OK = True
except ImportError:
    _EMBED_OK = False


def _load_config() -> dict:
    cfg_path = _BENCH_DIR / "config" / "systems.yaml"
    return yaml.safe_load(cfg_path.read_text())


# ── Elasticsearch 索引 ────────────────────────────────────────────────────────

def build_es_index(chunks: List[Chunk], cfg: dict, rebuild: bool = False) -> dict:
    """
    将 chunk 列表索引到 Elasticsearch。
    返回索引统计信息。
    """
    if not _ES_OK:
        return {"status": "skip", "reason": "elasticsearch-py not installed"}

    es_cfg = cfg["infrastructure"]["elasticsearch"]
    idx_name = es_cfg["index_name"]
    es = Elasticsearch(
        f"http://{es_cfg['host']}:{es_cfg['port']}",
        request_timeout=es_cfg["timeout"],
    )

    if not es.ping():
        return {"status": "error", "reason": "Elasticsearch not reachable"}

    # 重建索引
    if rebuild and es.indices.exists(index=idx_name):
        es.indices.delete(index=idx_name)
        print(f"  [ES] 已删除旧索引 {idx_name}")

    if not es.indices.exists(index=idx_name):
        mappings = {
            "mappings": {
                "properties": {
                    "chunk_id":    {"type": "keyword"},
                    "source_file": {"type": "keyword"},
                    "content":     {"type": "text", "analyzer": "standard"},
                    "memory_id":   {"type": "keyword"},
                    "layer":       {"type": "keyword"},
                    "tags":        {"type": "keyword"},
                    "tokens_est":  {"type": "integer"},
                    "char_start":  {"type": "integer"},
                    "char_end":    {"type": "integer"},
                }
            }
        }
        es.indices.create(index=idx_name, body=mappings)
        print(f"  [ES] 创建索引 {idx_name}")

    # 批量写入
    t0 = time.time()
    actions = [
        {
            "_index": idx_name,
            "_id": c.chunk_id,
            "_source": {
                "chunk_id": c.chunk_id,
                "source_file": c.source_file,
                "content": c.content,
                "memory_id": c.memory_id,
                "layer": c.layer,
                "tags": c.tags,
                "tokens_est": c.tokens_est,
                "char_start": c.char_start,
                "char_end": c.char_end,
            },
        }
        for c in chunks
    ]
    ok, errors = es_helpers.bulk(es, actions, raise_on_error=False)
    elapsed = time.time() - t0

    return {
        "status": "ok",
        "index": idx_name,
        "n_indexed": ok,
        "n_errors": len(errors) if isinstance(errors, list) else errors,
        "elapsed_s": round(elapsed, 2),
    }


# ── Milvus Collection ─────────────────────────────────────────────────────────

def build_milvus_collection(
    chunks: List[Chunk],
    cfg: dict,
    rebuild: bool = False,
    embed_fn=None,
) -> dict:
    """
    将 chunk 列表向量化并写入 Milvus。
    embed_fn: Callable[[str], List[float]]，不传则使用 BailianEmbedProvider。
    """
    if not _MV_OK:
        return {"status": "skip", "reason": "pymilvus not installed"}

    mv_cfg = cfg["infrastructure"]["milvus"]
    emb_cfg = cfg["infrastructure"]["embedding"]
    col_name = mv_cfg["collection_name"]
    dim = emb_cfg["dimension"]
    batch_size = emb_cfg["batch_size"]

    mv_connections.connect("default", host=mv_cfg["host"], port=str(mv_cfg["port"]))

    if not mv_utility.has_collection(col_name):
        pass
    elif rebuild:
        mv_utility.drop_collection(col_name)
        print(f"  [Milvus] 已删除旧 collection {col_name}")
    else:
        # 已存在且不重建，直接返回
        col = Collection(col_name)
        return {
            "status": "ok (existing)",
            "collection": col_name,
            "n_entities": col.num_entities,
        }

    # 创建 collection
    fields = [
        FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema("chunk_id", DataType.VARCHAR, max_length=64),
        FieldSchema("source_file", DataType.VARCHAR, max_length=512),
        FieldSchema("memory_id", DataType.VARCHAR, max_length=64),
        FieldSchema("layer", DataType.VARCHAR, max_length=64),
        FieldSchema("tokens_est", DataType.INT32),
        FieldSchema("content_preview", DataType.VARCHAR, max_length=4096),
        FieldSchema("embedding", DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="MMS Benchmark Documents")
    col = Collection(col_name, schema)
    print(f"  [Milvus] 创建 collection {col_name} (dim={dim})")

    # 创建 HNSW 索引
    col.create_index(
        "embedding",
        {
            "index_type": mv_cfg["index_type"],
            "metric_type": mv_cfg["metric_type"],
            "params": mv_cfg["index_params"],
        },
    )

    # 初始化 embedding 函数
    if embed_fn is None:
        if not _EMBED_OK:
            return {"status": "error", "reason": "BailianEmbedProvider not available"}
        provider = BailianEmbedProvider()
        embed_fn = provider.embed

    # 分批 embedding + 写入
    t0 = time.time()
    n_inserted = 0
    errors = []

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i: i + batch_size]
        texts = [c.content for c in batch]
        try:
            vectors = [embed_fn(t) for t in texts]
        except Exception as e:
            errors.append(str(e))
            print(f"  [Milvus] Embedding batch {i//batch_size} 失败: {e}")
            continue

        data = [
            [c.chunk_id for c in batch],
            [c.source_file[:510] for c in batch],
            [c.memory_id[:62] for c in batch],
            [c.layer[:62] for c in batch],
            [c.tokens_est for c in batch],
            # 截断到 4000 字符，Milvus VARCHAR 按 UTF-8 字节计，中文 3 字节/字
            # 4000 字符 × 最大 3 字节 = 12000 字节 < 4096 × 3，安全裕量足够
            [c.content[:1300] for c in batch],
            vectors,
        ]
        col.insert(data)
        n_inserted += len(batch)
        print(f"  [Milvus] 已写入 {n_inserted}/{len(chunks)} chunks...")

    col.flush()
    col.load()
    elapsed = time.time() - t0

    return {
        "status": "ok",
        "collection": col_name,
        "n_inserted": n_inserted,
        "n_errors": len(errors),
        "elapsed_s": round(elapsed, 2),
    }


# ── 主入口 ───────────────────────────────────────────────────────────────────

def build_all(rebuild: bool = False) -> dict:
    """
    构建全部索引，返回统计信息字典。
    在 run_indexer.py 中调用。
    """
    cfg = _load_config()
    sys_cfg = cfg["systems"]["hybrid_rag"]
    corpus_paths = sys_cfg["corpus"]["paths"]
    chunk_size = sys_cfg["retrieval"]["chunk_size"]
    chunk_overlap = sys_cfg["retrieval"]["chunk_overlap"]

    print("\n[Indexer] 加载语料...")
    loader = CorpusLoader(
        corpus_paths=corpus_paths,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    chunks = loader.load_all()
    corpus_stats = loader.stats()
    print(f"  语料: {corpus_stats['n_files']} 个文件 → {corpus_stats['n_chunks']} 个 chunk"
          f"  (~{corpus_stats['total_tokens_est']} tokens)")

    print("\n[Indexer] 构建 Elasticsearch 索引...")
    es_stats = build_es_index(chunks, cfg, rebuild=rebuild)
    print(f"  ES: {es_stats}")

    print("\n[Indexer] 构建 Milvus 向量索引（含 Embedding API 调用，需要几分钟）...")
    mv_stats = build_milvus_collection(chunks, cfg, rebuild=rebuild)
    print(f"  Milvus: {mv_stats}")

    result = {
        "corpus": corpus_stats,
        "elasticsearch": es_stats,
        "milvus": mv_stats,
    }

    # 保存索引统计到 results/
    results_dir = _BENCH_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = results_dir / f"index_stats_{ts}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[Indexer] 索引统计已保存: {out.relative_to(_BENCH_DIR)}")
    return result
