"""
原子性文件写入器

策略：先写 .tmp 临时文件，成功后 os.rename()（POSIX 原子操作）。
保证：写入中途崩溃不会产生半写入的损坏文件。

SanitizationGate（脱敏屏障）：
  在写入 docs/memory/ 路径下的文件前，自动扫描并替换敏感凭证。
  可通过环境变量 MMS_SANITIZE_DISABLE=1 关闭（仅用于测试/调试）。

适用场景：
  - MEM-*.md 记忆文件写入
  - MEMORY_INDEX.json 索引更新
  - Checkpoint 断点保存
  - Circuit Breaker 状态持久化
"""
import os
import tempfile
from pathlib import Path

# SanitizationGate 对 docs/memory/ 路径下的文件强制生效
_MEMORY_PATH_MARKER = str(Path("docs") / "memory")


def _should_sanitize(path: Path) -> bool:
    """判断路径是否属于记忆库，需要脱敏扫描"""
    if os.environ.get("MMS_SANITIZE_DISABLE") == "1":
        return False
    path_str = str(path)
    return _MEMORY_PATH_MARKER in path_str or "shared" in path_str


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

    # SanitizationGate：对记忆库路径执行脱敏扫描
    if _should_sanitize(path):
        try:
            from mms.core.sanitize import sanitize_or_raise
            content = sanitize_or_raise(content, path_hint=str(path))
        except ImportError:
            pass  # sanitize 模块不可用时静默跳过

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
