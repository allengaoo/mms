#!/usr/bin/env python3
"""
run_indexer.py — 索引构建入口
语料变化时重跑此脚本以重建 ES + Milvus 索引。

用法：
    python run_indexer.py           # 增量（已存在则跳过）
    python run_indexer.py --rebuild # 强制重建（删除旧索引后重建）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from indexer import build_all

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 MMS Benchmark ES + Milvus 索引")
    parser.add_argument("--rebuild", action="store_true", help="强制删除并重建索引")
    args = parser.parse_args()

    print("=" * 60)
    print("MMS Benchmark Indexer")
    print("=" * 60)
    result = build_all(rebuild=args.rebuild)
    print("\n✅ 索引构建完成")
