# 木兰（Mulan）Benchmark 报告 vv2.0

> 评测时间：2026-04-26T01:42:26

## 综合得分

**69.9%** — ████████████████████░░░░░░░░░░ 69.9%

![WARN](https://img.shields.io/badge/score-69%25-yellow)

## 评测层摘要

| 层 | 名称 | 得分 | 通过/总数 |
|----|------|------|----------|
| L2 | 记忆质量评测（Layer 2） | `0.4500` | 3/8 |
| L3 | 安全门控评测（Layer 3） | `0.9474` | 43/46 |

---

### Layer 2: 记忆质量评测（Layer 2）

| 指标 | 值 |
|------|-----|
| 综合得分 | `0.4500` █████████░░░░░░░░░░░ 45.0% |
| 任务总数 | 8 |
| 通过 | 3 |
| 跳过 | 5 |
| 失败 | 0 |
| 耗时 | 0.01s |

**详细指标：**

| 指标名 | 值 |
|--------|-----|
| `d1.recall_pass_rate` | `0.0000` |
| `d2.injection_pass_rate` | `0.0000` |
| `d4.drift_detection_rate` | `1.0000` |
| `overall.score` | `0.4500` |

---

### Layer 3: 安全门控评测（Layer 3）

| 指标 | 值 |
|------|-----|
| 综合得分 | `0.9474` ██████████████████░░ 94.7% |
| 任务总数 | 46 |
| 通过 | 43 |
| 跳过 | 0 |
| 失败 | 3 |
| 耗时 | 0.02s |

**详细指标：**

| 指标名 | 值 |
|--------|-----|
| `sanitize.detection_rate` | `0.9444` |
| `sanitize.false_positive_rate` | `0.0000` |
| `sanitize.critical_misses` | `1.0000` |
| `sanitize.pass_rate` | `0.9615` |
| `migration.block_accuracy` | `1.0000` |
| `arch.detection_rate` | `0.8333` |
| `overall.weighted_score` | `0.9474` |

<details>
<summary>失败任务（3 条）</summary>

| 任务 ID | 得分 | 错误 |
|---------|------|------|
| `san_san_ak_005` | 0.00 |  |
| `arc_arc_ac3_002` | 0.00 |  |
| `arc_arc_ac4_001` | 0.00 |  |

</details>

---

## 配置

```json
{
  "level": "FAST",
  "domains": [
    "generic_python"
  ],
  "dry_run": false,
  "llm_available": false,
  "max_tasks": null
}
```
