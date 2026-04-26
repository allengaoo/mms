"""
task_matcher.py — 任务相似度匹配器（MMS 三级检索漏斗 · 第一级）

算法：无向量、无全文检索引擎
  1. 从任务描述中提取标签集（中文词块 + 英文词 + 模板类型 + 记忆层标签）
  2. 对历史任务列表按 Jaccard(tags_A, tags_B) × time_weight 降序排列
  3. 返回相似度 ≥ threshold 的最优命中，携带已验证的 hit_files / hit_memories

数据文件：docs/memory/_system/task_history.jsonl
  每行一条 JSON，格式见 TaskRecord 类的字段说明。

用法（内部模块，由 synthesizer.py 调用）：
  from mms.memory.task_matcher import TaskMatcher
  matcher = TaskMatcher()
  hit = matcher.find_similar("修复用户登录 401", template="ep-debug")
  if hit:
      # 直接复用 hit.hit_files / hit.hit_memories
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

_ROOT = Path(__file__).resolve().parents[2]
_SYSTEM_DIR = _ROOT / "docs" / "memory" / "_system"
_HISTORY_FILE = _SYSTEM_DIR / "task_history.jsonl"

# ── 停用词（过滤噪音，避免降低区分度） ───────────────────────────────────────
_STOP_WORDS = {
    # 英文
    "the", "and", "for", "with", "from", "that", "this", "are", "not", "api",
    "def", "use", "via", "new", "add", "fix", "get", "set", "run", "can",
    "will", "has", "was", "had", "have", "but", "its", "all", "one", "two",
    # 中文虚词
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "都", "而",
    "及", "与", "或", "从", "对", "到", "把", "被", "为", "让", "使",
    "等", "其", "这", "那", "也", "还", "已", "很", "更", "最", "时",
}

# ── 模板类型 → 固定标签（通用 5 层架构，提升跨任务模板聚合精度） ─────────────
_TEMPLATE_TAGS: Dict[str, List[str]] = {
    "ep-backend-api":   ["backend", "api", "service", "endpoint", "ADAPTER", "APP"],
    "ep-frontend":      ["frontend", "react", "store", "component", "ADAPTER"],
    "ep-ontology":      ["ontology", "object", "link", "action", "DOMAIN"],
    "ep-data-pipeline": ["pipeline", "connector", "worker", "ingestion", "DOMAIN", "ADAPTER"],
    "ep-debug":         ["debug", "fix", "error", "trace", "PLATFORM", "ADAPTER"],
    "ep-devops":        ["devops", "deploy", "k8s", "docker", "compose", "helm",
                         "kubectl", "port-forward", "orbstack", "cicd", "ops", "ADAPTER"],
    "ep-others":        ["refactor", "migrate", "security", "performance", "optimize",
                         "test", "coverage", "doc", "documentation", "cleanup",
                         "重构", "迁移", "安全", "性能", "优化", "测试", "文档", "CC"],
}


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class TaskRecord:
    """历史任务的持久化格式（task_history.jsonl 中的单行 JSON）。"""

    ts: str                          # ISO-8601 时间戳，用于时间衰减计算
    task: str                        # 原始用户任务描述
    template: Optional[str]          # EP 模板名（可为 None）
    tags: List[str]                  # 归一化标签集（用于 Jaccard 计算）
    hit_memories: List[str]          # 本次命中/使用的记忆 ID 列表
    hit_files: List[str]             # 本次命中/使用的真实文件路径列表
    author: Optional[str] = None     # 可选：任务提交者（团队协作时区分用户）

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TaskRecord":
        return TaskRecord(
            ts=d.get("ts", ""),
            task=d.get("task", ""),
            template=d.get("template"),
            tags=d.get("tags", []),
            hit_memories=d.get("hit_memories", []),
            hit_files=d.get("hit_files", []),
            author=d.get("author"),
        )


@dataclass
class MatchResult:
    """相似任务命中结果。"""

    record: TaskRecord               # 命中的历史任务记录
    similarity: float                # 加权相似度得分 [0.0, 1.0]
    common_tags: List[str]           # 共同标签（便于调试/日志）


# ── 核心模块 ──────────────────────────────────────────────────────────────────

class TaskMatcher:
    """
    任务相似度匹配器。

    算法说明
    --------
    1. 标签提取：中文词块（≥2字）+ 英文 CamelCase/snake_case 词（≥3字） + 模板固定标签
    2. Jaccard 相似度：|A∩B| / |A∪B|（集合运算，O(n) 时间）
    3. 时间衰减：score = jaccard × time_weight
         - 距今 ≤ recent_days：weight=1.0
         - 距今 ≤ medium_days：weight=medium_weight（默认 0.7）
         - 更早：weight=old_weight（默认 0.4）
    4. 阈值过滤：score ≥ threshold（默认 0.30）

    配置参数由调用方传入，与 config.yaml 的 synthesize 节对齐。
    """

    def __init__(
        self,
        history_file: Path = _HISTORY_FILE,
        history_top_x: int = 10,
        shared_top_y: int = 20,
        similarity_threshold: float = 0.30,
        recent_days: int = 7,
        medium_days: int = 30,
        medium_weight: float = 0.7,
        old_weight: float = 0.4,
        max_history_records: int = 500,
    ) -> None:
        self.history_file = history_file
        self.history_top_x = history_top_x
        self.shared_top_y = shared_top_y
        self.threshold = similarity_threshold
        self.recent_days = recent_days
        self.medium_days = medium_days
        self.medium_weight = medium_weight
        self.old_weight = old_weight
        self.max_history_records = max_history_records

    # ── 公共 API ──────────────────────────────────────────────────────────────

    def extract_tags(self, task: str, template: Optional[str] = None) -> List[str]:
        """
        从任务描述中提取归一化标签集。

        规则：
        - 中文词块（≥2 个连续汉字）
        - 英文词（≥3 字符，CamelCase 拆分、去下划线）
        - 模板固定标签（来自 _TEMPLATE_TAGS）
        - 全部转小写，去重，过滤停用词
        """
        tags: set = set()

        # 中文词块
        for zh in re.findall(r"[\u4e00-\u9fff]{2,}", task):
            if zh not in _STOP_WORDS:
                tags.add(zh)

        # 英文词（含 camelCase 拆分）
        # 先按非字母数字分割，再对 CamelCase 做二次拆分
        raw_words = re.split(r"[^A-Za-z0-9]+", task)
        for w in raw_words:
            # CamelCase 拆分：UserLogin → ["User", "Login"]
            parts = re.sub(r"([A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$))", r" \1", w).split()
            for p in parts:
                low = p.lower()
                if len(low) >= 3 and low not in _STOP_WORDS:
                    tags.add(low)

        # 模板固定标签
        if template and template in _TEMPLATE_TAGS:
            tags.update(_TEMPLATE_TAGS[template])

        return sorted(tags)

    def find_similar(
        self,
        task: str,
        template: Optional[str] = None,
        author: Optional[str] = None,
    ) -> Optional[MatchResult]:
        """
        在历史记录中查找与当前任务最相似的条目。

        查找策略（两阶段）：
        1. 优先从当前用户（author）最近 history_top_x 条记录中搜索
        2. 若未命中，从全量最近 shared_top_y 条记录中搜索

        返回：最高得分且 ≥ threshold 的 MatchResult；无命中时返回 None
        """
        records = self._load_records()
        if not records:
            return None

        current_tags = set(self.extract_tags(task, template))
        now = datetime.now(timezone.utc)

        # 阶段一：按 author 过滤个人最近 x 条
        personal = [
            r for r in records
            if author is None or r.author == author
        ][-self.history_top_x:]

        hit = self._best_match(personal, current_tags, now)
        if hit:
            return hit

        # 阶段二：全量最近 y 条（含他人记录）
        shared = records[-self.shared_top_y:]
        return self._best_match(shared, current_tags, now)

    def append_record(self, record: TaskRecord) -> None:
        """
        将新任务记录追加到 task_history.jsonl。
        超出 max_history_records 时，滚动删除最旧的记录。
        """
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        records = self._load_records()
        records.append(record)

        # 超限时保留最新的 max_history_records 条
        if len(records) > self.max_history_records:
            records = records[-self.max_history_records:]

        lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in records]
        self.history_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def build_record(
        self,
        task: str,
        template: Optional[str],
        hit_memories: List[str],
        hit_files: List[str],
        author: Optional[str] = None,
    ) -> TaskRecord:
        """构造 TaskRecord，自动填充 ts 和 tags。"""
        return TaskRecord(
            ts=datetime.now(timezone.utc).isoformat(),
            task=task,
            template=template,
            tags=self.extract_tags(task, template),
            hit_memories=hit_memories,
            hit_files=hit_files,
            author=author,
        )

    # ── 内部方法 ─────────────────────────────────────────────────────────────

    def _load_records(self) -> List[TaskRecord]:
        """从 task_history.jsonl 加载所有记录，跳过损坏的行。"""
        if not self.history_file.exists():
            return []
        records = []
        for line in self.history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(TaskRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                # 跳过损坏行，保持健壮性
                continue
        return records

    def _time_weight(self, ts_str: str, now: datetime) -> float:
        """根据历史记录时间戳计算衰减权重。"""
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            days_ago = (now - ts).days
        except (ValueError, OverflowError):
            return self.old_weight  # 解析失败时使用最低权重

        if days_ago <= self.recent_days:
            return 1.0
        if days_ago <= self.medium_days:
            return self.medium_weight
        return self.old_weight

    def _jaccard(self, a: set, b: set) -> float:
        """计算两个标签集的 Jaccard 相似度。"""
        if not a or not b:
            return 0.0
        intersection = len(a & b)
        union = len(a | b)
        return intersection / union if union > 0 else 0.0

    def _best_match(
        self,
        candidates: List[TaskRecord],
        current_tags: set,
        now: datetime,
    ) -> Optional[MatchResult]:
        """在候选列表中找出得分最高且 ≥ threshold 的命中记录。"""
        best: Optional[MatchResult] = None
        best_score = -1.0

        for record in candidates:
            if not record.tags:
                continue
            hist_tags = set(record.tags)
            jaccard = self._jaccard(current_tags, hist_tags)
            weight = self._time_weight(record.ts, now)
            score = jaccard * weight

            if score >= self.threshold and score > best_score:
                best_score = score
                best = MatchResult(
                    record=record,
                    similarity=round(score, 4),
                    common_tags=sorted(current_tags & hist_tags),
                )

        return best


# ── CLI 入口（调试用） ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    task = " ".join(sys.argv[1:]) or "修复用户登录 401 认证失败"
    matcher = TaskMatcher()
    tags = matcher.extract_tags(task, "ep-debug")
    print(f"任务: {task}")
    print(f"标签: {tags}")

    hit = matcher.find_similar(task, "ep-debug")
    if hit:
        print(f"\n命中! 相似度={hit.similarity}, 共同标签={hit.common_tags}")
        print(f"  历史任务: {hit.record.task}")
        print(f"  文件: {hit.record.hit_files}")
        print(f"  记忆: {hit.record.hit_memories}")
    else:
        print("\n未命中历史任务（将使用第二/三级检索）")
