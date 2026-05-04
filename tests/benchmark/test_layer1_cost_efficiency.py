"""
tests/benchmark/test_layer1_cost_efficiency.py — Track A vs Track B 成本效率对比基准

目标：
  量化两条执行轨道在不同任务复杂度下的「成本效率比 (Cost Efficiency Ratio)」：
  - 成功率 (Pass@1)
  - 单次成功消耗 Token 数
  - 单次成功耗时 (s)
  - 综合成本评分 = 成功率 / (Token * 单价 + 时延 * 计算成本)

报告输出：
  - 在 CI 中作为基准记录，用于趋势追踪（历史对比）
  - 本地 Eval 模式下调用真实 LLM 获取真实数据

设计原则：
  - CI 模式（MMS_CI_MODE=1）下全部使用 Mock 数据，确保测试确定性
  - 测试本身不断言「成本绝对值」，只验证「报告结构完整性」
  - 真实成本数据通过 --benchmark-json 输出供外部工具追踪
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

_CI_MODE = os.environ.get("MMS_CI_MODE") == "1"

# Token 定价（元/千 tokens，用于成本计算）
_TOKEN_PRICE_PER_K = {
    "qwen3-coder-next": 0.004,   # Track A 小模型
    "qwen3-32b": 0.02,           # Track B 推理大模型
    "default": 0.01,
}


# ─── 数据类 ───────────────────────────────────────────────────────────────────

@dataclass
class TrackRunRecord:
    """单次轨道执行记录。"""
    track: str              # "A" 或 "B"
    model: str
    task_name: str
    success: bool
    tokens_input: int = 0
    tokens_output: int = 0
    elapsed_s: float = 0.0
    attempts: int = 1       # Track A 重试次数
    turns: int = 0          # Track B 轮次
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return self.tokens_input + self.tokens_output

    @property
    def cost_yuan(self) -> float:
        """估算成本（元）"""
        price_per_k = _TOKEN_PRICE_PER_K.get(self.model, _TOKEN_PRICE_PER_K["default"])
        return self.total_tokens / 1000 * price_per_k

    def to_dict(self) -> Dict:
        return {
            "track": self.track,
            "model": self.model,
            "task": self.task_name,
            "success": self.success,
            "total_tokens": self.total_tokens,
            "cost_yuan": round(self.cost_yuan, 4),
            "elapsed_s": round(self.elapsed_s, 2),
            "attempts": self.attempts,
            "turns": self.turns,
        }


@dataclass
class CostEfficiencyReport:
    """成本效率对比报告。"""
    records: List[TrackRunRecord] = field(default_factory=list)

    def add(self, record: TrackRunRecord) -> None:
        self.records.append(record)

    def track_stats(self, track: str) -> Dict:
        """计算指定轨道的统计指标。"""
        track_records = [r for r in self.records if r.track == track]
        if not track_records:
            return {"track": track, "count": 0}

        success_records = [r for r in track_records if r.success]
        pass_rate = len(success_records) / len(track_records)
        avg_tokens = sum(r.total_tokens for r in track_records) / len(track_records)
        avg_cost = sum(r.cost_yuan for r in track_records) / len(track_records)
        avg_elapsed = sum(r.elapsed_s for r in track_records) / len(track_records)

        # 成功记录的指标（排除失败带来的额外开销）
        avg_tokens_on_success = (
            sum(r.total_tokens for r in success_records) / len(success_records)
            if success_records else 0
        )

        return {
            "track": track,
            "count": len(track_records),
            "pass_rate": round(pass_rate, 3),
            "avg_tokens_all": round(avg_tokens),
            "avg_tokens_on_success": round(avg_tokens_on_success),
            "avg_cost_yuan": round(avg_cost, 4),
            "avg_elapsed_s": round(avg_elapsed, 2),
            # Cost per Success (CPS)：每次成功任务的综合成本
            "cost_per_success": round(
                avg_cost / pass_rate if pass_rate > 0 else float("inf"), 4
            ),
        }

    def comparison_table(self) -> Dict:
        """生成 Track A vs Track B 的完整对比表。"""
        return {
            "track_a": self.track_stats("A"),
            "track_b": self.track_stats("B"),
            "recommendation": self._recommend(),
        }

    def _recommend(self) -> str:
        """根据成本效率给出轨道推荐。"""
        a = self.track_stats("A")
        b = self.track_stats("B")

        if not a.get("count") or not b.get("count"):
            return "数据不足，无法给出推荐"

        a_cps = a.get("cost_per_success", float("inf"))
        b_cps = b.get("cost_per_success", float("inf"))
        a_pr = a.get("pass_rate", 0)
        b_pr = b.get("pass_rate", 0)

        if b_pr - a_pr > 0.2 and b_cps < a_cps * 3:
            return "推荐 Track B（大模型自治）：成功率显著更高，成本差异可接受"
        elif a_cps < b_cps * 0.5:
            return "推荐 Track A（小模型流水线）：成本效率更优，适合标准化任务"
        else:
            return "两者差异不显著：建议按任务复杂度动态路由（简单→Track A，复杂→Track B）"

    def to_json(self) -> str:
        return json.dumps(
            {
                "records": [r.to_dict() for r in self.records],
                "comparison": self.comparison_table(),
            },
            ensure_ascii=False,
            indent=2,
        )

    def print_report(self) -> None:
        print("\n" + "═" * 60)
        print("  Layer 1 Track A vs Track B 成本效率对比报告")
        print("═" * 60)
        comp = self.comparison_table()
        for track_key in ("track_a", "track_b"):
            stats = comp[track_key]
            label = "Track A（小模型流水线）" if track_key == "track_a" else "Track B（大模型自治）"
            print(f"\n  {label}")
            if not stats.get("count"):
                print("    （无数据）")
                continue
            print(f"    样本数:         {stats['count']}")
            print(f"    成功率:         {stats['pass_rate']:.1%}")
            print(f"    平均 Token:     {stats['avg_tokens_all']:,}")
            print(f"    平均成本:       ¥{stats['avg_cost_yuan']:.4f}")
            print(f"    平均耗时:       {stats['avg_elapsed_s']:.1f}s")
            print(f"    单次成功成本:   ¥{stats['cost_per_success']:.4f}  ← CPS 核心指标")
        print(f"\n  💡 {comp['recommendation']}")
        print("═" * 60 + "\n")


# ─── Mock 数据生成（CI 模式） ────────────────────────────────────────────────

def _mock_track_a_record(task: str, success: bool = True) -> TrackRunRecord:
    return TrackRunRecord(
        track="A",
        model="qwen3-coder-next",
        task_name=task,
        success=success,
        tokens_input=1200,
        tokens_output=800,
        elapsed_s=15.0,
        attempts=1 if success else 3,
    )


def _mock_track_b_record(task: str, success: bool = True) -> TrackRunRecord:
    return TrackRunRecord(
        track="B",
        model="qwen3-32b",
        task_name=task,
        success=success,
        tokens_input=8000,
        tokens_output=3000,
        elapsed_s=45.0,
        turns=6 if success else 10,
    )


# ─── 测试类 ───────────────────────────────────────────────────────────────────

class TestCostEfficiencyReport:
    """验证报告数据结构和计算逻辑（纯单元测试，无 LLM 调用）。"""

    def test_single_record_stats(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("P-001", success=True))
        stats = report.track_stats("A")

        assert stats["count"] == 1
        assert stats["pass_rate"] == 1.0
        assert stats["avg_tokens_all"] == 2000  # 1200 + 800
        assert stats["avg_cost_yuan"] >= 0

    def test_pass_rate_calculation(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("task1", success=True))
        report.add(_mock_track_a_record("task2", success=True))
        report.add(_mock_track_a_record("task3", success=False))
        stats = report.track_stats("A")
        assert abs(stats["pass_rate"] - 2 / 3) < 0.01

    def test_cost_per_success(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("task1", success=True))
        report.add(_mock_track_a_record("task2", success=False))
        stats = report.track_stats("A")
        # CPS = avg_cost / pass_rate（pass_rate=0.5，所以 CPS = 2 * avg_cost）
        assert stats["cost_per_success"] > stats["avg_cost_yuan"]

    def test_comparison_table_structure(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("task1"))
        report.add(_mock_track_b_record("task1"))
        comp = report.comparison_table()
        assert "track_a" in comp
        assert "track_b" in comp
        assert "recommendation" in comp
        assert isinstance(comp["recommendation"], str)

    def test_empty_track_stats(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("task1"))
        stats = report.track_stats("B")  # B 没有记录
        assert stats["count"] == 0

    def test_to_json_valid(self):
        report = CostEfficiencyReport()
        report.add(_mock_track_a_record("task1"))
        report.add(_mock_track_b_record("task1"))
        json_str = report.to_json()
        data = json.loads(json_str)
        assert "records" in data
        assert "comparison" in data
        assert len(data["records"]) == 2

    def test_track_a_token_price(self):
        rec = _mock_track_a_record("task")
        # qwen3-coder-next: 2000 token * 0.004/K = 0.008 元
        assert abs(rec.cost_yuan - 0.008) < 0.001

    def test_track_b_token_price(self):
        rec = _mock_track_b_record("task")
        # qwen3-32b: 11000 token * 0.02/K = 0.22 元
        assert abs(rec.cost_yuan - 0.22) < 0.01


class TestCostEfficiencyBenchmark:
    """
    成本效率基准测试（含 mock 数据的完整流程验证）。

    在 CI 模式下使用 Mock 数据，验证整个报告生成流程。
    在本地 Eval 模式下可接入真实执行数据。
    """

    @pytest.mark.benchmark
    def test_mock_benchmark_full_report(self):
        """使用 Mock 数据生成完整报告，验证结构和推荐逻辑。"""
        report = CostEfficiencyReport()

        # 模拟 Track A：5 个任务，4 成功（Pass@1 = 80%）
        tasks = ["P-001_add_field", "P-002_add_endpoint", "P-003_add_method",
                 "J-001_add_field", "G-001_add_field"]
        for i, task in enumerate(tasks):
            report.add(_mock_track_a_record(task, success=(i < 4)))

        # 模拟 Track B：5 个任务，5 全成功（Pass@1 = 100%），但成本更高
        for task in tasks:
            report.add(_mock_track_b_record(task, success=True))

        report.print_report()
        comp = report.comparison_table()

        # 验证 Track A 成功率 = 80%
        assert comp["track_a"]["pass_rate"] == pytest.approx(0.8, abs=0.01)
        # 验证 Track B 成功率 = 100%
        assert comp["track_b"]["pass_rate"] == 1.0
        # 验证 Track B 的 Token 消耗更高（大模型）
        assert comp["track_b"]["avg_tokens_all"] > comp["track_a"]["avg_tokens_all"]
        # 验证推荐语不为空
        assert len(comp["recommendation"]) > 10

    @pytest.mark.benchmark
    def test_cps_metric_is_valid(self):
        """
        验证 CPS（Cost per Success）是核心指标，
        且 Track B 在高成功率下 CPS 可能接近 Track A。
        """
        report = CostEfficiencyReport()
        # Track A: 成功率 50%，低成本
        report.add(_mock_track_a_record("task1", success=True))
        report.add(_mock_track_a_record("task2", success=False))
        # Track B: 成功率 100%，高成本（但 CPS 可能相当）
        report.add(_mock_track_b_record("task1", success=True))
        report.add(_mock_track_b_record("task2", success=True))

        a_cps = report.track_stats("A")["cost_per_success"]
        b_cps = report.track_stats("B")["cost_per_success"]

        # Track B 虽然单次贵，但因为 100% 成功率，CPS 未必高于 Track A（50%成功）
        # 这是 CPS 指标的核心价值所在
        print(f"\n  Track A CPS: ¥{a_cps:.4f}")
        print(f"  Track B CPS: ¥{b_cps:.4f}")
        assert a_cps > 0
        assert b_cps > 0

    @pytest.mark.benchmark
    def test_json_output_for_ci_tracking(self, tmp_path: Path):
        """
        验证 JSON 报告输出格式，用于 CI 趋势追踪。
        在真实流水线中，此 JSON 会被存储为 CI artifact。
        """
        report = CostEfficiencyReport()
        for task in ["P-001", "P-002", "J-001"]:
            report.add(_mock_track_a_record(task))
            report.add(_mock_track_b_record(task))

        report_path = tmp_path / "cost_efficiency_report.json"
        report_path.write_text(report.to_json(), encoding="utf-8")

        # 验证文件可被正确解析
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(data["records"]) == 6
        assert data["comparison"]["track_a"]["count"] == 3
        assert data["comparison"]["track_b"]["count"] == 3
        assert "recommendation" in data["comparison"]
