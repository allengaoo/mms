# Legacy Snapshot from MDP Monorepo

归档来源：`allengaoo/ontology-system-ADSF-Driven`（本地目录 `mdp-enterprise-version-build-with-cursor`）

归档目的：MDP 仓库去 MMS 化时，将原嵌入式记忆系统代码与知识库完整备份到本独立仓库，便于回溯。

## 目录说明

| 路径 | 原 MDP 路径 | 说明 |
|------|-------------|------|
| `scripts-mms/` | `scripts/mms/` | 嵌入式 MMS CLI / runner / benchmark / tests |
| `docs-memory/` | `docs/memory/` | MMS 知识库（ontology / templates / shared / _system） |
| `mms-wrapper.sh` | `mms`（仓库根入口脚本） | 根目录 `mms` 包装器 |
| `env.memory.example` | `.env.memory.example` | LLM / 记忆环境变量示例 |

## 注意

- 本目录为**只读历史快照**，不作为当前 `mms` 主线代码。
- 当前独立 MMS 工程的主实现见仓库根目录（`cli.py` / `src/` / `backend/` 等）。
- 归档日期：2026-08-16
