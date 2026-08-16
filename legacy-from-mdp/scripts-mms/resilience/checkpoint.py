"""
断点续传（Checkpoint）机制

用途：蒸馏等长任务中断后，可从最后一个成功步骤继续，无需重头开始。

文件格式（JSON，存于 _system/checkpoints/{trace_id}.json）：
{
  "trace_id": "MMS-20260411-a1b2c3",
  "ep_id":    "EP-108",
  "op":       "distillation",
  "started_at": "2026-04-11T10:00:00Z",
  "updated_at": "2026-04-11T10:05:00Z",
  "total_sections": 5,
  "processed_sections": ["摘要", "教训"],
  "pending_sections":   ["决策", "模式"],
  "partial_results":    [...]
}

用法：
  python scripts/memory_distill.py --ep EP-108
  # 中断后：
  python scripts/memory_distill.py --ep EP-108 --resume MMS-20260411-a1b2c3
"""
import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_MEMORY_ROOT = Path(__file__).parent.parent.parent.parent / "docs" / "memory"
_CHECKPOINT_DIR = _MEMORY_ROOT / "_system" / "checkpoints"


def _now_iso() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


class CheckpointState:
    """断点状态的数据容器，提供便利方法"""

    def __init__(self, data: Dict[str, Any]) -> None:
        self._data = data

    @property
    def trace_id(self) -> str:
        return self._data["trace_id"]

    @property
    def ep_id(self) -> Optional[str]:
        return self._data.get("ep_id")

    @property
    def processed_sections(self) -> List[str]:
        return self._data.get("processed_sections", [])

    @property
    def pending_sections(self) -> List[str]:
        return self._data.get("pending_sections", [])

    @property
    def partial_results(self) -> list:
        return self._data.get("partial_results", [])

    def is_section_done(self, section: str) -> bool:
        return section in self.processed_sections

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._data)


class Checkpoint:
    """
    断点续传管理器。

    Example:
        cp = Checkpoint()
        # 保存断点
        cp.save(trace_id, {
            "ep_id": "EP-108",
            "op": "distillation",
            "total_sections": 5,
            "processed_sections": ["摘要"],
            "pending_sections": ["教训", "决策"],
            "partial_results": [...]
        })

        # 恢复断点
        state = cp.load("MMS-20260411-a1b2c3")
        if state:
            print(f"从 {state.processed_sections} 之后继续")

        # 完成后清理
        cp.complete(trace_id)
    """

    def __init__(self, checkpoint_dir: Optional[Path] = None) -> None:
        self._dir = checkpoint_dir or _CHECKPOINT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, trace_id: str) -> Path:
        return self._dir / f"{trace_id}.json"

    def save(self, trace_id: str, state: Dict[str, Any]) -> None:
        """原子性保存断点状态（写 .tmp 后 rename）"""
        data = dict(state)
        data["trace_id"] = trace_id
        data["updated_at"] = _now_iso()
        if "started_at" not in data:
            data["started_at"] = data["updated_at"]

        target = self._path(trace_id)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(target)

    def load(self, trace_id: str) -> Optional[CheckpointState]:
        """
        加载断点状态。文件不存在时返回 None（非错误）。
        """
        path = self._path(trace_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return CheckpointState(data)

    def complete(self, trace_id: str) -> None:
        """任务成功完成，删除断点文件"""
        path = self._path(trace_id)
        if path.exists():
            path.unlink()

    def list_incomplete(self) -> List[str]:
        """列出所有未完成的断点 trace_id"""
        return [p.stem for p in self._dir.glob("*.json")]
