"""
corpus_loader.py — 统一语料加载器
===================================
负责从 data/corpus/ 软链目录中加载所有文档，
切分成固定大小的 chunk，供三个检索器共同使用。

设计原则：
  - 单一责任：只负责加载和切分，不做任何检索逻辑
  - 确定性：相同输入始终产生相同 chunk 列表（chunk_id 固定）
  - 可扩展：新增语料路径只需改 config/systems.yaml，无需改此文件
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List


_BENCHMARK_DIR = Path(__file__).parent.parent
_PROJECT_ROOT = _BENCHMARK_DIR.parent.parent.parent


@dataclass
class Chunk:
    """单个文档片段"""
    chunk_id: str           # 唯一 ID（文件路径哈希 + 序号）
    source_file: str        # 相对于项目根的文件路径
    content: str            # 片段文本内容
    char_start: int         # 在原文件中的起始字符位置
    char_end: int           # 在原文件中的结束字符位置
    tokens_est: int         # 估算 token 数（chars // 4）

    # 从文档 frontmatter 提取的元数据（记忆文件特有）
    memory_id: str = ""     # 如 MEM-DB-002
    layer: str = ""         # 如 L2_infrastructure
    tags: List[str] = None  # 如 ["kafka", "avro"]

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class CorpusLoader:
    """
    从配置的语料路径加载所有文档并切分 chunk。

    用法：
        loader = CorpusLoader(corpus_paths=["data/corpus/context",
                                            "data/corpus/memories"])
        chunks = loader.load_all()
    """

    def __init__(
        self,
        corpus_paths: List[str],
        extensions: List[str] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        self.corpus_paths = corpus_paths
        self.extensions = extensions or [".md"]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._benchmark_dir = _BENCHMARK_DIR

    def _resolve_path(self, rel_path: str) -> Path:
        """将相对路径（相对于 benchmark/）解析为绝对路径，跟随软链"""
        p = self._benchmark_dir / rel_path
        # resolve() 会跟随软链，返回真实绝对路径
        try:
            return p.resolve()
        except OSError:
            return p

    def _iter_files(self) -> Iterator[Path]:
        """遍历所有语料目录下的文档文件"""
        seen = set()
        for rel_path in self.corpus_paths:
            abs_path = self._resolve_path(rel_path)
            if not abs_path.exists():
                continue
            for ext in self.extensions:
                for fpath in sorted(abs_path.rglob(f"*{ext}")):
                    # 跳过私有目录和 _system 目录
                    parts = fpath.parts
                    if any(p.startswith("_") or p == "private" for p in parts):
                        continue
                    real = str(fpath.resolve())
                    if real not in seen:
                        seen.add(real)
                        yield fpath

    def _extract_frontmatter(self, content: str) -> dict:
        """
        提取 YAML frontmatter（--- ... --- 或首行 key: value 格式）。
        返回 memory_id / layer / tags 字段。
        """
        meta = {"memory_id": "", "layer": "", "tags": []}
        # 尝试 --- frontmatter
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        body = fm_match.group(1) if fm_match else content[:400]

        id_m = re.search(r'^id:\s*(\S+)', body, re.MULTILINE)
        if id_m:
            meta["memory_id"] = id_m.group(1).strip('"\'')

        layer_m = re.search(r'^layer:\s*(\S+)', body, re.MULTILINE)
        if layer_m:
            meta["layer"] = layer_m.group(1).strip('"\'')

        tags_m = re.search(r'^tags:\s*\[([^\]]*)\]', body, re.MULTILINE)
        if tags_m:
            raw_tags = tags_m.group(1)
            meta["tags"] = [t.strip().strip('"\'') for t in raw_tags.split(",") if t.strip()]

        return meta

    def _make_chunk_id(self, file_path: str, idx: int) -> str:
        """生成确定性的 chunk ID"""
        h = hashlib.md5(file_path.encode()).hexdigest()[:8]
        return f"{h}_{idx:04d}"

    def _split_into_chunks(self, content: str, meta: dict, source_file: str) -> List[Chunk]:
        """
        将文档内容切分为固定大小的 chunk（含重叠）。
        按段落边界优先切分，避免在句子中间截断。
        """
        chunks = []
        # 按双换行分段
        paragraphs = re.split(r'\n\n+', content)
        current = ""
        current_start = 0
        pos = 0

        for para in paragraphs:
            if len(current) + len(para) + 2 <= self.chunk_size:
                if current:
                    current += "\n\n" + para
                else:
                    current = para
                    current_start = pos
            else:
                if current:
                    chunk_id = self._make_chunk_id(source_file, len(chunks))
                    chunks.append(Chunk(
                        chunk_id=chunk_id,
                        source_file=source_file,
                        content=current,
                        char_start=current_start,
                        char_end=current_start + len(current),
                        tokens_est=len(current) // 4,
                        memory_id=meta.get("memory_id", ""),
                        layer=meta.get("layer", ""),
                        tags=meta.get("tags", []),
                    ))
                    # 重叠：取上一个 chunk 的末尾 overlap 字符
                    overlap_text = current[-self.chunk_overlap:] if self.chunk_overlap else ""
                    current = overlap_text + para if overlap_text else para
                    current_start = pos - len(overlap_text)
                else:
                    current = para
                    current_start = pos
            pos += len(para) + 2

        # 最后一个 chunk
        if current.strip():
            chunk_id = self._make_chunk_id(source_file, len(chunks))
            chunks.append(Chunk(
                chunk_id=chunk_id,
                source_file=source_file,
                content=current,
                char_start=current_start,
                char_end=current_start + len(current),
                tokens_est=len(current) // 4,
                memory_id=meta.get("memory_id", ""),
                layer=meta.get("layer", ""),
                tags=meta.get("tags", []),
            ))

        return chunks

    def load_all(self) -> List[Chunk]:
        """加载所有语料文件，返回 chunk 列表"""
        all_chunks: List[Chunk] = []
        for fpath in self._iter_files():
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if not content.strip():
                continue

            # 相对于项目根的路径（用于展示）
            try:
                rel = str(fpath.relative_to(_PROJECT_ROOT))
            except ValueError:
                rel = str(fpath)

            meta = self._extract_frontmatter(content)
            chunks = self._split_into_chunks(content, meta, rel)
            all_chunks.extend(chunks)

        return all_chunks

    def stats(self) -> dict:
        """返回语料统计信息"""
        chunks = self.load_all()
        files = set(c.source_file for c in chunks)
        total_chars = sum(c.char_end - c.char_start for c in chunks)
        return {
            "n_files": len(files),
            "n_chunks": len(chunks),
            "total_chars": total_chars,
            "total_tokens_est": total_chars // 4,
            "avg_chunk_chars": total_chars // max(len(chunks), 1),
        }
