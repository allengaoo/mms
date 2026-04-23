"""
原子性文件写入器

策略：先写 .tmp 临时文件，成功后 os.rename()（POSIX 原子操作）。
保证：写入中途崩溃不会产生半写入的损坏文件。

适用场景：
  - MEM-*.md 记忆文件写入
  - MEMORY_INDEX.json 索引更新
  - Checkpoint 断点保存
  - Circuit Breaker 状态持久化
"""
import os
import tempfile
from pathlib import Path


def atomic_write(path, content: str, encoding: str = "utf-8") -> None:
    """
    原子性写入文本文件。

    写入流程：
      1. 写入同目录下的 {filename}.tmp
      2. os.rename() 原子替换（POSIX 保证）
      3. 原文件（如存在）被安全替换

    Args:
        path:     目标文件路径（父目录必须存在）
        content:  要写入的文本内容
        encoding: 文件编码（默认 utf-8）

    Raises:
        OSError: 磁盘空间不足、权限不足等 I/O 错误

    Example:
        atomic_write(Path("docs/memory/MEM-L-025.md"), content)
        atomic_write(Path(tempfile.gettempdir()) / "test.json", content)  # 临时文件使用 tempfile
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(content, encoding=encoding)
        os.rename(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path, data: dict, indent: int = 2) -> None:
    """
    原子性写入 JSON 文件（确保 ensure_ascii=False 保留中文）。
    """
    import json
    content = json.dumps(data, ensure_ascii=False, indent=indent)
    atomic_write(path, content)
