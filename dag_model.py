"""
dag_model.py — MMS DAG 数据结构定义与持久化

DAG（有向无环图）用于将复杂跨层 EP 分解为原子 Unit，
由 capable model 生成逻辑执行计划，small model 逐 Unit 执行。

设计原则（EP-117）：
- 所有状态持久化到 docs/memory/_system/dag/{EP-NNN}.json（git 追踪）
- 状态传递通过 git commit（Unit 完成 → commit → 下一个 Unit 读当前 git 状态）
- 与 config.yaml dag.atomicity_thresholds 保持一致
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_DAG_DIR = _ROOT / "docs" / "memory" / "_system" / "dag"
_HERE = Path(__file__).resolve().parent

try:
    import sys as _sys
    _sys.path.insert(0, str(_HERE))
    from mms_config import cfg as _cfg  # type: ignore[import]
except Exception:
    _cfg = None  # type: ignore[assignment]

# ── 常量 ──────────────────────────────────────────────────────────────────────

VALID_STATUSES = ("pending", "in_progress", "done", "skipped")
VALID_LAYERS = (
    "L1_platform", "L2_infrastructure", "L3_domain",
    "L4_application", "L5_interface", "cross_cutting",
    "testing", "docs", "infra", "unknown",
)
VALID_MODEL_HINTS = ("8b", "16b", "capable", "fast")

# 层的执行顺序（数字越小越先执行，相同可并行）
LAYER_ORDER: Dict[str, int] = {
    "L3_domain": 1,
    "L2_infrastructure": 1,
    "L4_application": 2,
    "L5_interface": 3,
    "cross_cutting": 1,
    "testing": 4,
    "docs": 5,
    "infra": 1,
    "unknown": 3,
}


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class DagUnit:
    """DAG 中的单个执行单元（对应 EP 中的一个 Unit）"""

    id: str                              # "U1", "U2" 等
    title: str                           # 一句话描述
    layer: str                           # 所属架构层
    files: List[str]                     # 涉及文件路径（业务 + 测试）
    depends_on: List[str]                # 前置 Unit ID 列表
    order: int                           # 执行批次（同 order 可并行）
    status: str = "pending"              # pending|in_progress|done|skipped
    model_hint: str = "capable"          # 建议执行模型
    atomicity_score: float = 0.0         # 0.0-1.0，越高越原子
    git_commit: Optional[str] = None     # 完成时的 commit hash
    completed_at: Optional[str] = None   # ISO 8601 完成时间
    test_files: List[str] = field(default_factory=list)  # 测试文件路径
    # EP-129：AIU 子步骤计划（渐进式意图分解产出）
    # 空列表 = 未经 AIU 分解，直接作为整体执行（向后兼容）
    aiu_steps: List[dict] = field(default_factory=list)  # List[AIUStep.to_dict()]
    aiu_feedback_log: List[dict] = field(default_factory=list)  # Feedback 回退记录

    def is_executable(self, done_ids: List[str]) -> bool:
        """判断该 Unit 的所有依赖是否已完成"""
        return all(dep in done_ids for dep in self.depends_on)

    def is_atomic_for_model(self, model: str) -> bool:
        """根据模型类型判断是否满足原子化阈值"""
        if model == "8b":
            # fallback: config.yaml → dag.atomicity_thresholds.score_threshold_8b (default=0.75)
            thr = float(getattr(_cfg, "dag_score_threshold_8b", 0.75)) if _cfg else 0.75
            return self.atomicity_score >= thr
        if model == "16b":
            # fallback: config.yaml → dag.atomicity_thresholds.score_threshold_16b (default=0.50)
            thr = float(getattr(_cfg, "dag_score_threshold_16b", 0.50)) if _cfg else 0.50
            return self.atomicity_score >= thr
        return True  # capable model 无原子化约束

    def has_aiu_plan(self) -> bool:
        """是否已经生成 AIU 子步骤计划。"""
        return len(self.aiu_steps) > 0

    def get_aiu_plan(self) -> Optional[object]:
        """
        将 aiu_steps 反序列化为 AIUPlan 对象。
        返回 None 如果未分解或 aiu_types 模块不可用。
        """
        if not self.aiu_steps:
            return None
        try:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parent))
            from aiu_types import AIUPlan  # type: ignore[import]
            return AIUPlan.from_dict({
                "dag_unit_id": self.id,
                "steps": self.aiu_steps,
                "decomposed_by": "stored",
                "confidence": 1.0,
                "original_task": self.title,
            })
        except ImportError:
            return None

    def set_aiu_plan(self, plan: object) -> None:
        """将 AIUPlan 序列化存储到 aiu_steps。"""
        try:
            self.aiu_steps = [s.to_dict() for s in plan.steps]  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DagUnit":
        known = set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        # 向后兼容：旧 JSON 没有 aiu_steps / aiu_feedback_log 字段
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


@dataclass
class DagState:
    """整个 EP 的 DAG 执行状态"""

    ep_id: str
    generated_at: str
    orchestrator_model: str
    units: List[DagUnit]
    overall_status: str = "pending"  # pending|in_progress|done

    # ── 查询方法 ────────────────────────────────────────────────────────────

    def done_ids(self) -> List[str]:
        """已完成的 Unit ID 列表"""
        return [u.id for u in self.units if u.status == "done"]

    def pending_units(self) -> List[DagUnit]:
        """所有 pending 状态的 Unit"""
        return [u for u in self.units if u.status == "pending"]

    def in_progress_units(self) -> List[DagUnit]:
        """所有 in_progress 状态的 Unit"""
        return [u for u in self.units if u.status == "in_progress"]

    def executable_units(self) -> List[DagUnit]:
        """当前可执行（依赖已满足）的 Unit，按 order 排序"""
        done = self.done_ids()
        return sorted(
            [u for u in self.units
             if u.status == "pending" and u.is_executable(done)],
            key=lambda u: u.order,
        )

    def next_executable(self, model: str = "capable") -> Optional[DagUnit]:
        """
        获取下一个可执行的 Unit。
        若指定 model（8b/16b），优先返回原子化满足该模型的 Unit。
        """
        candidates = self.executable_units()
        if not candidates:
            return None
        if model in ("8b", "16b"):
            atomic = [u for u in candidates if u.is_atomic_for_model(model)]
            return atomic[0] if atomic else candidates[0]
        return candidates[0]

    def get_batch_groups(self) -> List[List[DagUnit]]:
        """将 Unit 按 order 分组（同组可并行）"""
        groups: Dict[int, List[DagUnit]] = {}
        for u in self.units:
            groups.setdefault(u.order, []).append(u)
        return [groups[k] for k in sorted(groups.keys())]

    def progress(self) -> Tuple[int, int]:
        """返回 (done_count, total_count)"""
        done = sum(1 for u in self.units if u.status in ("done", "skipped"))
        return done, len(self.units)

    # ── 状态变更 ────────────────────────────────────────────────────────────

    def mark_in_progress(self, unit_id: str) -> None:
        """标记 Unit 为执行中"""
        unit = self._get_unit(unit_id)
        unit.status = "in_progress"
        self._update_overall()

    def mark_done(self, unit_id: str, commit_hash: Optional[str] = None) -> None:
        """标记 Unit 为完成，记录 commit hash 和完成时间"""
        unit = self._get_unit(unit_id)
        unit.status = "done"
        unit.git_commit = commit_hash
        unit.completed_at = datetime.now(timezone.utc).isoformat()
        self._update_overall()

    def mark_skipped(self, unit_id: str) -> None:
        unit = self._get_unit(unit_id)
        unit.status = "skipped"
        self._update_overall()

    def reset_unit(self, unit_id: str) -> None:
        """回退 Unit 状态为 pending"""
        unit = self._get_unit(unit_id)
        unit.status = "pending"
        unit.git_commit = None
        unit.completed_at = None
        self._update_overall()

    def _get_unit(self, unit_id: str) -> DagUnit:
        for u in self.units:
            if u.id == unit_id:
                return u
        raise ValueError(f"Unit {unit_id!r} not found in DAG for {self.ep_id}")

    def _update_overall(self) -> None:
        done, total = self.progress()
        if done == total:
            self.overall_status = "done"
        elif any(u.status == "in_progress" for u in self.units):
            self.overall_status = "in_progress"
        elif done > 0:
            self.overall_status = "in_progress"
        else:
            self.overall_status = "pending"

    # ── 持久化 ──────────────────────────────────────────────────────────────

    def save(self) -> Path:
        """持久化到 docs/memory/_system/dag/{EP-NNN}.json"""
        _DAG_DIR.mkdir(parents=True, exist_ok=True)
        ep_norm = self.ep_id.upper()
        path = _DAG_DIR / f"{ep_norm}.json"
        data = {
            "ep_id": self.ep_id,
            "generated_at": self.generated_at,
            "orchestrator_model": self.orchestrator_model,
            "overall_status": self.overall_status,
            "units": [u.to_dict() for u in self.units],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, ep_id: str) -> "DagState":
        """从磁盘加载 DAG 状态"""
        ep_norm = ep_id.upper()
        path = _DAG_DIR / f"{ep_norm}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"DAG 状态文件不存在：{path}\n"
                f"请先运行：mms unit generate --ep {ep_norm}"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        units = [DagUnit.from_dict(u) for u in data.get("units", [])]
        return cls(
            ep_id=data["ep_id"],
            generated_at=data["generated_at"],
            orchestrator_model=data.get("orchestrator_model", "unknown"),
            units=units,
            overall_status=data.get("overall_status", "pending"),
        )

    @classmethod
    def exists(cls, ep_id: str) -> bool:
        ep_norm = ep_id.upper()
        return (_DAG_DIR / f"{ep_norm}.json").exists()

    def to_dict(self) -> dict:
        return {
            "ep_id": self.ep_id,
            "generated_at": self.generated_at,
            "orchestrator_model": self.orchestrator_model,
            "overall_status": self.overall_status,
            "units": [u.to_dict() for u in self.units],
        }


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def _default_orchestrator_model() -> str:
    """从 factory 动态获取 dag_orchestration 的模型名，避免硬编码。"""
    try:
        from providers.factory import auto_detect  # type: ignore[import]
        p = auto_detect("dag_orchestration")
        return getattr(p, "model_name", "dag_orchestration")
    except Exception:
        return "dag_orchestration"


def make_dag_state(
    ep_id: str,
    units_data: List[dict],
    orchestrator_model: Optional[str] = None,
) -> DagState:
    """
    从原始 dict 列表构造 DagState。

    units_data 格式：
    [{"id": "U1", "title": "...", "layer": "L4_application",
      "files": ["..."], "depends_on": [], "model_hint": "8b"}]
    """
    units = []
    for d in units_data:
        layer = d.get("layer", "unknown")
        # 若未指定 order，从 layer 推断
        order = d.get("order") or LAYER_ORDER.get(layer, 3)
        unit = DagUnit(
            id=d.get("id", "U?"),
            title=d.get("title", ""),
            layer=layer,
            files=d.get("files", []),
            depends_on=d.get("depends_on", []),
            order=order,
            status=d.get("status", "pending"),
            model_hint=d.get("model_hint", "capable"),
            atomicity_score=float(d.get("atomicity_score", 0.0)),
            test_files=d.get("test_files", []),
        )
        units.append(unit)

    return DagState(
        ep_id=ep_id.upper(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        orchestrator_model=orchestrator_model or _default_orchestrator_model(),
        units=units,
    )
