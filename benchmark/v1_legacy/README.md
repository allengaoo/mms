# Benchmark v1 Legacy — 已废弃

> ⚠️ **本目录下的代码已废弃，仅供历史参考。当前生产 Benchmark 请使用 `benchmark/v2/`。**

## 废弃原因


| 维度   | v1 (本目录)                           | v2 (../v2/)                      |
| ---- | ---------------------------------- | -------------------------------- |
| 评测目标 | 检索质量对比（BM25 vs Hybrid RAG vs 本体路由） | 全栈工具链评测（安全 / 记忆质量 / 代码生成）        |
| 依赖   | 需 ES/Milvus + 向量索引                 | Layer 3 完全离线；Layer 2 D1/D4 离线可运行 |
| 扩展性  | 固定指标，新增场景需修改代码                     | YAML 驱动，添加 case 无需改代码            |
| 状态   | 最后运行：2026-04-22                    | 活跃维护中                            |


## 运行方式（仅历史参考）

```bash
# 已不再维护，仅供参考
cd benchmark/v1_legacy
python run_benchmark.py --systems ontology markdown
```

## 结构

```
v1_legacy/
├── src/                    # 评测核心（检索器、评测器、指标、报告）
│   ├── schema.py
│   ├── evaluator.py
│   ├── retrievers/
│   └── metrics/
├── data/                   # 测试数据（queries.yaml、corpus memories、reference_code）
├── config/                 # 指标权重和系统配置
├── run_benchmark.py        # 主入口（已废弃）
├── run_codegen.py          # 代码生成评测入口（已废弃）
└── run_indexer.py          # ES/Milvus 索引构建（已废弃）
```

