# Phase 5 — 切换与清理

> 分支：`feature/memoria-cutover`
> 预估：2–3 人周 · 前置依赖：Phase 4 验收指标全部达标（14 天对账零差异、影子读 > 99%、检索指标达标）
> 目标：Memoria 成为主后端，Markdown 降级为可 Git diff 的导出格式。**整个阶段保留一键回退开关。**

> **状态：停止（2026-07-14）。** Phase 4 未通过准入门，因此不执行后端切换、Markdown 只读化或旧路径清理。

---

## 任务 5.1 读流量切换

### 工作内容

1. `CompositeRepository` 支持 `memory.backend: memoria-primary`：读走 Memoria，写主 Memoria、副 Markdown（双写方向反转，Markdown 变为备份）；
2. 切换前置检查脚本 `scripts/cutover_precheck.py`：自动验证 Phase 4 全部准入指标（读取对账/影子读日志与指标留档），任一不达标拒绝切换；
3. 切换后观察期（建议 ≥ 1 周）：影子读方向反转（以 Memoria 结果返回，比对 Markdown），继续记录差异。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/composite_repo.py` | 修改：`memoria-primary` 模式 |
| `src/mms/adapters/__init__.py` | 修改：工厂新模式 |
| `scripts/cutover_precheck.py` | 新建 |
| `docs/memory/_system/config.yaml` | 修改：backend 切换 |

### 达到的标准

- 切换动作只改一行配置，无代码变更、无停机；
- 观察期内反向影子读一致率 > 99.5%；
- `MemoryInjector`、`MemoryGraph`、CLI、诊断页面（`memory_viz`）在新后端下功能与表现无差异。

### 如何验证

```bash
python scripts/cutover_precheck.py          # 退出码 0 才允许改配置
pytest tests/ -x                             # 全量测试（backend=memoria-primary）
python -m mms.cli bootstrap tests/fixtures/spring-boot-demo && open 诊断页面人工核对
```

回退演练（必做）：切到 `memoria-primary` → 执行若干写入 → 切回 `dual` → 对账零差异。

---

## 任务 5.2 Markdown 导出与 Git 工作流保留

### 工作内容

Markdown 的「可读、可 Git diff」是现有工作流的核心价值（Canvas 反面证据第一条），切主后以导出形式保留：

1. `mulan memory export`：从 Memoria 全量导出为现有目录结构的 Markdown（front-matter 格式与 `FrontMatterProjection` 一致），供 Git 提交与人工审查；
2. 副写 Markdown 即持续导出——确认双写反转已覆盖此需求后，export 命令定位为「全量重建/修复」工具；
3. 文档更新：`layer2_readme.md`、`mem_readme.md` 说明新的数据流（Memoria 主存 → Markdown 导出视图）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/cli.py` | 修改：export 子命令 |
| `layer2_readme.md`、`src/mms/memory/mem_readme.md`、`README.md` | 修改：架构文档同步 |

### 达到的标准

- `export` 产物与切换前的 Markdown 库逐文件语义等价（front-matter 字段一致，正文一致）；
- 删除全部本地 Markdown 后执行 export，可完整重建（灾备验证）。

### 如何验证

- 导出对比脚本：`diff -r`（或逐 front-matter 比对）导出目录与 Git 中最后一次双写快照；
- 灾备演练：临时目录中删除 shared/ → export → `verify --index` 零告警 → `MemoryGraph` 加载节点数一致。

---

## 任务 5.3 历史清理与耦合移除

### 工作内容

1. 移除过渡期代码：重试队列反转逻辑中不再需要的分支、`shadow_read` 相关日志采样降频或关闭；
2. `IncrementalIndexer` 的角色重估：若 Memoria 检索完全覆盖注入路径，`MEMORY_INDEX.json` 降级为导出产物之一（由 export 重建），`core/indexer.py` 写路径退役；若诊断页面仍依赖则保留只读用途——以观察期数据决定，结论写入本文件后再动工；
3. 版本管理正式启用：`mulan memory snapshot/rollback` 开放对主后端操作（解除 Phase 4.5 的演练限制），并在重大操作（批量 GC、schema 迁移脚本）前自动打快照；
4. 归档 `spike/` 目录（保留报告，删除实验代码）。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `src/mms/adapters/composite_repo.py` | 修改：清理过渡逻辑 |
| `src/mms/core/indexer.py`、`src/mms/core/reader.py` | 视观察期结论修改 |
| `src/mms/memory/entropy_scan.py`、`scripts/migrate_*.py` | 修改：操作前自动快照 |
| `spike/` | 归档 |

### 达到的标准

- 批量 GC、迁移脚本执行前自动产生快照，且 `rollback` 演练可恢复；
- 代码中无 dead code（过渡分支、废弃索引写路径）残留，`rg "shadow_read|retry_queue"` 的存留引用均有明确用途。

### 如何验证

- 快照自动化测试：跑一次 entropy_scan 淘汰流程 → `mulan memory history` 确认快照存在 → rollback → 节点恢复；
- `pytest tests/ -x` 全绿 + 人工 code review 清理清单。

---

## 任务 5.4 运维固化

### 工作内容

1. `deploy/memoria/` 补齐运维脚本：`backup.sh`（MatrixOne 数据卷导出 + 保留策略）、`restore.sh`、健康检查；
2. 备份自动化：本机 launchd/cron 每日备份，保留最近 7 天 + 每周 1 份；
3. `deploy/memoria/RUNBOOK.md`：启动/停止/升级/备份恢复/常见故障（连接拒绝、磁盘满、版本不兼容）处置手册。

### 涉及文件

| 文件 | 操作 |
|---|---|
| `deploy/memoria/backup.sh`、`restore.sh`、`healthcheck.sh` | 新建 |
| `deploy/memoria/RUNBOOK.md` | 新建 |

### 达到的标准

- 全新机器（仅有 OrbStack）按 RUNBOOK 从零部署 + 恢复备份 < 30 分钟；
- 备份-恢复演练后对账零差异。

### 如何验证

- 在干净环境（新容器命名空间）按 RUNBOOK 逐步执行一遍，计时并修订文档；
- `python scripts/reconcile_memoria.py` 零差异。

---

## Phase 5 整体验收

- [ ] 观察期（≥ 1 周）反向影子读一致率 > 99.5%，无功能回归报告；
- [ ] 灾备演练通过：删库重建（export）与备份恢复均零差异；
- [ ] 全部文档（README、layer2_readme、mem_readme、RUNBOOK）与实际架构一致；
- [ ] 最终回退方案存档：切回 `dual` 或 `markdown` 的操作步骤 + 数据对齐脚本，在 RUNBOOK 中长期保留。
