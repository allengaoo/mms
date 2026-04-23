# MMS Benchmark — 三种检索系统对比评估

> **研究命题**：在小参数模型辅助复杂工程软件开发时，
> 基于动态本体驱动的记忆系统（MMS-OG）相比传统 Markdown 文本索引
> 和混合 RAG（ES BM25 + Milvus 向量），能否以更低的上下文 token 消耗
> 实现更高的检索命中准确率？

---

## 快速开始

```bash
cd scripts/mms/benchmark

# 第一步：构建 ES + Milvus 索引（一次性，约 3-5 分钟）
python run_indexer.py

# 第二步：运行全部系统评估（约 2-5 分钟）
python run_benchmark.py

# 只运行 Markdown + Ontology（跳过 RAG，约 10 秒）
python run_benchmark.py --systems markdown ontology

# 重新生成最新报告（不重新评估）
python run_benchmark.py --report-only

# 查看帮助
python run_benchmark.py --help
```

---

## 三个参与系统

| 系统 | 标签 | 核心算法 | 数据源 | 外部依赖 |
|:---|:---|:---|:---|:---|
| `markdown` | Markdown Index | BM25 关键词匹配 | `docs/context/` + `docs/memory/shared/` | 无 |
| `hybrid_rag` | Hybrid RAG | ES BM25 + Milvus HNSW + RRF 融合 | 同上 | ES 19200, Milvus 19530, Bailian API |
| `ontology` | 本体 MMS | intent_map 规则 + 磁盘验证路径 | `docs/memory/ontology/` | 无 |

**公平性保证**：三个系统使用相同的语料库（统一软链到 `data/corpus/`），
差异只来自索引方式，而非数据覆盖范围。

---

## 测试数据集（data/queries.yaml）

30 条任务，分 5 个类别：

| 类别 | 条数 | 特点 | 计入主评估 |
|:---|:---:|:---|:---:|
| A — 原子任务 | 8 | 单层单文件，三系统差距最小（公平基线）| ✅ |
| B — 跨层任务 | 7 | 涉及 2+ 架构层，典型工程软件场景 | ✅ |
| C — 约束感知 | 5 | 需精确定位特定约束记忆 | ✅ |
| D — MMS 工具 | 5 | 本体专属规则场景 | ✅ |
| ADV — 对抗样本 | 5 | 关键词歧义/意图混淆，单独分析 | ❌ |

**任务设计原则**：措辞模拟真实用户语言（不直接使用 intent_map 关键词），
Ground Truth 独立于任何检索系统（基于"工程师必须打开哪些文件"的客观判断）。

---

## 指标说明与公式

### 准确性指标

**Layer Accuracy（架构层命中率）**
```
LayerAcc = Σ 1[ŷ_layer == y*_layer] / N

ŷ_layer：系统预测的架构层（如 L0_mms、L4_service）
y*_layer：Ground Truth 层
N：测试任务总数
```

**Op Accuracy（操作类型准确率）**
```
OpAcc = Σ 1[ŷ_op == y*_op] / N
```

**Recall@K（关键文件召回率，K=5）**
```
Recall@K = (1/N) * Σ |TopK_i ∩ F*_i| / |F*_i|

TopK_i：检索返回的前 K 个文件
F*_i：GT key_files（工程师必须打开的文件）
路径匹配：前缀匹配（GT 目录时，返回文件属于该目录即命中）
```

**MRR（平均倒数排名）**
```
MRR = (1/N) * Σ 1/rank_i

rank_i：第一个 GT 文件在 Top-K 中的排名（从 1 开始，未命中→∞→贡献 0）
```

**Path Validity（路径有效率 — 反幻觉指标）**
```
PathValidity = Σ|{f ∈ R_i : exists(f)}| / Σ|R_i|

exists(f)：Path(f).exists() or Path(f).is_dir()
```

**Memory Recall（约束记忆命中率）**
```
MemRecall = (1/N) * Σ |{m ∈ R_i : m.id ∈ M*_i}| / max(|M*_i|, 1)

M*_i：GT key_memory_ids（如 MEM-DB-002）
```

### 效率指标

**Context Tokens（上下文 token 估算）**
```
ContextTokens_i = floor(|context_i|_chars / 4)

4 字符 ≈ 1 token（中英混合文本通用估算）
越少越好
```

**Info Density（有效信息密度 — 核心指标 🔑）**
```
InfoDensity_i = Recall@K_i / max(ContextTokens_i / 1000, 0.1)

设计意图：
  小参数模型注意力窗口有限（约 4000 token），
  高密度 = 每个 token 都在做有用的事。
  分母最小值 0.1 防止零除。
越高越好
```

**Actionability（可执行性 — 0-3 中立量表）**
```
Level 0：返回无关内容（与 GT 架构层无关）
Level 1：返回相关领域文档片段
Level 2：返回相关且磁盘有效的文件路径
Level 3：返回可直接执行的命令（cli_usage 或文档中的命令示例）

说明：三系统使用同一量表。RAG 系统若记忆文件含命令示例同样可得 Level 3，
      不因"没有 ActionDef"而被惩罚为 0。
```

### RRF 融合公式（仅 Hybrid RAG）

```
score(d) = Σ_{r ∈ {ES, MV}} 1 / (k + rank_r(d))

k = 60（标准 RRF 参数）
rank：文档在各路结果中的排名（从 1 开始）
未出现的文档贡献 0
```

### 统计显著性检验

```
二元指标（layer_accuracy / op_accuracy）：McNemar 检验
  χ² = (|b01 - b10| - 1)² / (b01 + b10)
  b01 = A错B对的对数，b10 = A对B错的对数
  α = 0.05

连续指标（recall_at_k / mrr / info_density 等）：Wilcoxon 符号秩检验
  W = Σ rank(|di|) · sign(di)
  正态近似 z 统计量，双侧检验
  α = 0.05

注意：N=25 样本量较小，不显著（p≥0.05）的结论同样重要。
```

---

## 数据存储结构

```
scripts/mms/benchmark/results/
├── raw_YYYYMMDD_HHMMSS.jsonl     ← 每条任务×每系统的完整原始结果（边跑边写）
├── stats_YYYYMMDD_HHMMSS.json    ← 聚合统计（含分位数、分类分解、显著性检验）
├── report_YYYYMMDD_HHMMSS.md     ← 可读 Markdown 报告（含公式和存储说明）
└── index_stats_YYYYMMDD.json     ← 索引构建统计（run_indexer.py 产生）
```

**raw_*.jsonl 每行字段：**

```
query_id / category / system    — 任务标识
task                            — 用户原始输入（自然语言）
gt_layer / gt_operation         — Ground Truth 架构层和操作类型
gt_key_files                    — GT 关键文件列表（工程师必须打开的文件）
gt_key_memory_ids               — GT 约束记忆 ID 列表（如 MEM-DB-002）

layer_correct / op_correct      — 层/操作命中（布尔）
recall_at_k                     — Recall@5 值（0.0-1.0）
mrr                             — MRR 值（0.0-1.0）
path_validity                   — 路径有效率（0.0-1.0）
memory_recall                   — 约束记忆命中率（0.0-1.0）
context_tokens                  — 上下文 token 估算
info_density                    — 有效信息密度
actionability.level             — 可执行性等级（0-3）

latency_ms                      — 端到端耗时（ms）
embed_latency_ms                — Embedding API 耗时（仅 hybrid_rag）
es_latency_ms                   — ES 查询耗时（仅 hybrid_rag）
milvus_latency_ms               — Milvus 查询耗时（仅 hybrid_rag）

confidence                      — 分类置信度（仅 ontology）
matched_rule                    — 命中的规则 ID（仅 ontology）
from_llm                        — 是否触发 LLM 兜底（仅 ontology）
executable_cmds                 — 可执行命令列表（仅 ontology 且 ActionDef 匹配时）
returned_file_paths             — 检索返回的文件路径列表
error                           — 检索失败时的错误信息
```

---

## 扩展指引

| 扩展场景 | 需要修改 | 无需修改 |
|:---|:---|:---|
| 新增测试任务 | `data/queries.yaml` | 全部代码 |
| 新增指标 | `config/metrics.yaml` + `src/metrics/*.py`（加一函数）| 检索器、数据结构 |
| 修改 MRR 的 K 值 | `config/metrics.yaml` → `mrr.params.k` | 全部代码 |
| 新增第四种检索系统 | `src/retrievers/new_retriever.py` + `registry.py` 一行 | 评估器、报告器 |
| 修改 RRF k 参数 | `config/systems.yaml` → `hybrid_rag.retrieval.rrf_k` | 全部代码 |
| 修改报告格式 | `src/reporter.py` | 数据、指标、检索器 |
| 更换统计检验方法 | `config/metrics.yaml` → `statistical_test.method` | 全部代码 |
| 禁用某个系统 | `config/systems.yaml` → `xxx.enabled: false` | 全部代码 |

---

## 隔离说明（不影响 MDP）

- ES 索引名：`mms_bm_docs`（MDP 生产索引不含此名称）
- Milvus collection 名：`mms_bm_docs`（MDP 生产 collection 不含此名称）
- 所有产物在 `results/` 目录，已加入 `.gitignore`
- 运行 `python run_indexer.py --rebuild` 可随时清理重建

---

*EP-129 | 2026-04-20*
