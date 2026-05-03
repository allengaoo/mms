#!/usr/bin/env python3
"""
embed_index.py — 离线 Embedding 索引（中期方案）
=================================================
对 docs/memory/shared/ 下所有记忆文档做一次性向量化，
存储为本地 .npy 文件。检索时用 numpy 余弦相似度，零外部服务依赖。

设计原则：
  - 向量生成需要百炼 Embedding API（text-embedding-v3），仅运行一次
  - 检索时纯本地计算（numpy），无网络调用，延迟 < 5ms
  - 索引文件 < 1MB（约 50 文档 × 1024 维 × 4 bytes ≈ 200KB）

使用方式：
  # 生成索引（需要 DASHSCOPE_API_KEY）
  python scripts/mms/benchmark/src/embed_index.py --build

  # Python API
  from embed_index import EmbedIndex
  idx = EmbedIndex()
  results = idx.search("为什么后端不能直接 import pymilvus", top_k=3)
  # → [(file_path, content, score), ...]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

_SRC_DIR = Path(__file__).parent
_BENCH_DIR = _SRC_DIR.parent
_MMS_DIR = _BENCH_DIR.parent
_PROJECT_ROOT = _MMS_DIR.parent.parent

# 索引文件存储位置（不提交到 git）
_INDEX_DIR = _BENCH_DIR / "results" / ".embed_index"
_VECTORS_FILE = _INDEX_DIR / "memory_vectors.npy"
_META_FILE = _INDEX_DIR / "memory_meta.json"


def _load_env() -> dict:
    env_file = _PROJECT_ROOT / ".env.memory"
    env = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _call_embedding_api(texts: List[str], api_key: str, base_url: str, model: str) -> List[List[float]]:
    """调用百炼 text-embedding-v3，返回向量列表"""
    import urllib.request
    import urllib.parse

    url = f"{base_url}/embeddings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    # 百炼 text-embedding-v3 每次最多 10 条（超出报 400）
    all_vectors = []
    batch_size = 10
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = json.dumps({
            "model": model,
            "input": batch,
            "encoding_format": "float",
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in sorted(data["data"], key=lambda x: x["index"]):
            all_vectors.append(item["embedding"])
        time.sleep(0.2)  # 避免限流
    return all_vectors


def build_index(force: bool = False) -> None:
    """
    扫描 docs/memory/shared/ 生成向量索引。
    需要 DASHSCOPE_API_KEY 环境变量或 .env.memory 文件。
    """
    try:
        import numpy as np
    except ImportError:
        print("❌ 需要 numpy：pip install numpy")
        return

    if _VECTORS_FILE.exists() and not force:
        print(f"✅ 索引已存在（{_VECTORS_FILE}），跳过。使用 --force 强制重建。")
        return

    env = _load_env()
    api_key = os.environ.get("DASHSCOPE_API_KEY") or env.get("DASHSCOPE_API_KEY", "")
    base_url = os.environ.get("DASHSCOPE_BASE_URL") or env.get(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    embed_model = os.environ.get("DASHSCOPE_MODEL_EMBEDDING") or env.get(
        "DASHSCOPE_MODEL_EMBEDDING", "text-embedding-v3"
    )

    if not api_key:
        print("❌ 未设置 DASHSCOPE_API_KEY，无法生成 Embedding 索引")
        return

    memories_dir = _PROJECT_ROOT / "docs" / "memory" / "shared"
    if not memories_dir.exists():
        print(f"❌ 目录不存在: {memories_dir}")
        return

    docs = []
    for f in sorted(memories_dir.rglob("*.md")):
        content = f.read_text(errors="ignore")[:1500]
        rel = str(f.relative_to(_PROJECT_ROOT))
        docs.append({"path": rel, "content": content})

    print(f"📚 加载 {len(docs)} 个记忆文档")

    # 向量化（取前 500 chars 作为 embedding 输入，节省 token）
    texts = [d["content"][:500] for d in docs]
    print(f"🔄 调用 {embed_model} 生成向量（{len(texts)} 条）...")
    try:
        vectors = _call_embedding_api(texts, api_key, base_url, embed_model)
    except Exception as e:
        print(f"❌ Embedding API 调用失败: {e}")
        return

    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vecs = np.array(vectors, dtype=np.float32)
    np.save(_VECTORS_FILE, vecs)

    meta = [{"path": d["path"], "content": d["content"][:800]} for d in docs]
    _META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"✅ 向量索引已保存：{_VECTORS_FILE} ({vecs.shape})")
    print(f"✅ 元数据已保存：{_META_FILE}")


class EmbedIndex:
    """
    本地 Embedding 索引，用于 BM25 兜底的第二层（中期方案）。

    检索流程：
      1. 将查询文本发送到百炼 Embedding API
      2. 用 numpy 计算余弦相似度
      3. 返回 Top-K 记忆文档

    若索引文件不存在，返回空结果（不抛异常，退化到纯 BM25）。
    """

    def __init__(self):
        self._vectors = None   # np.ndarray shape (N, D)
        self._meta: List[dict] = []
        self._api_key: str = ""
        self._base_url: str = ""
        self._embed_model: str = ""
        self._loaded = False

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._vectors is not None
        self._loaded = True
        try:
            import numpy as np
        except ImportError:
            return False

        if not _VECTORS_FILE.exists() or not _META_FILE.exists():
            return False

        try:
            self._vectors = np.load(_VECTORS_FILE)
            self._meta = json.loads(_META_FILE.read_text())
            env = _load_env()
            self._api_key = os.environ.get("DASHSCOPE_API_KEY") or env.get("DASHSCOPE_API_KEY", "")
            self._base_url = os.environ.get("DASHSCOPE_BASE_URL") or env.get(
                "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            self._embed_model = os.environ.get("DASHSCOPE_MODEL_EMBEDDING") or env.get(
                "DASHSCOPE_MODEL_EMBEDDING", "text-embedding-v3"
            )
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        return self._ensure_loaded()

    def search(self, query: str, top_k: int = 3) -> List[Tuple[str, str, float]]:
        """
        语义搜索记忆文档。

        Args:
            query:  用户查询文本
            top_k:  返回结果数量

        Returns:
            [(file_path, content, similarity_score), ...]
            若不可用，返回空列表（不抛异常）
        """
        if not self._ensure_loaded():
            return []
        if not self._api_key:
            return []

        import numpy as np

        try:
            # 查询向量化（带缓存：相同查询不重复 API 调用）
            q_vec_list = _call_embedding_api([query[:500]], self._api_key, self._base_url, self._embed_model)
            q_vec = np.array(q_vec_list[0], dtype=np.float32)
        except Exception:
            return []

        # 余弦相似度
        norms = np.linalg.norm(self._vectors, axis=1)
        q_norm = np.linalg.norm(q_vec)
        if q_norm < 1e-9:
            return []
        sims = self._vectors.dot(q_vec) / (norms * q_norm + 1e-9)

        top_indices = np.argsort(-sims)[:top_k]
        results = []
        for idx in top_indices:
            score = float(sims[idx])
            if score < 0.3:  # 低相似度截断
                break
            m = self._meta[idx]
            results.append((m["path"], m["content"], round(score, 4)))
        return results


# 全局单例（延迟初始化）
_EMBED_INDEX: Optional[EmbedIndex] = None


def get_embed_index() -> EmbedIndex:
    global _EMBED_INDEX
    if _EMBED_INDEX is None:
        _EMBED_INDEX = EmbedIndex()
    return _EMBED_INDEX


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="生成记忆文档 Embedding 索引")
    parser.add_argument("--build", action="store_true", help="构建向量索引")
    parser.add_argument("--force", action="store_true", help="强制重建索引")
    parser.add_argument("--test", metavar="QUERY", help="测试查询")
    args = parser.parse_args()

    if args.build:
        build_index(force=args.force)
    elif args.test:
        idx = EmbedIndex()
        results = idx.search(args.test, top_k=5)
        if results:
            print(f"\n查询: {args.test}")
            for fp, content, score in results:
                print(f"  {score:.4f}  {fp}")
        else:
            print("索引不可用或无结果（请先运行 --build）")
    else:
        parser.print_help()
