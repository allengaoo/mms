# Memoria Phase 0 PoC 报告

> 状态：决策门完成 · 已测版本：`main@63f0289` 与 `v0.4.0`
> 环境：macOS + OrbStack / Docker 29.4.0

## 已确认的 API 事实

- 官方 `POST /v1/memories` 文档只声明 `content`、固定集合 `memory_type` 和 `session_id`，**没有声明通用自定义 metadata 输入**。
- 版本 API 已公开：`/v1/snapshots`（创建、diff、rollback）和 `/v1/branches`（创建、checkout、diff、merge）。
- 自托管 API 监听 `8100`，MatrixOne 监听 `6001`；健康检查为 `/health` 和 `/health/instance`。
- Memoria 公开 issue #211 记录了空 content / 非法 memory_type 可写入的问题，因此未来适配器必须做客户端校验，不能依赖服务端兜底。

来源：

- <https://github.com/matrixorigin/Memoria>
- <https://github.com/matrixorigin/Memoria/blob/main/skills/api-reference/SKILL.md>
- <https://github.com/matrixorigin/Memoria/blob/main/skills/deployment/SKILL.md>
- <https://github.com/matrixorigin/Memoria/issues/211>

## PoC 实现

- `setup_runtime.sh`：下载并固定官方源码 commit，不把第三方源码提交到 MMS 仓库。
- `docker-compose.yml`：启动 MatrixOne、Memoria API 和本地确定性 embedding stub。
- `embedding_stub.py`：只用于验证 API 管道和延迟；**不能用于判断语义检索质量**。
- `test_roundtrip.py`：用 20 个真实 MMS 节点探测原生 metadata 往返，同时验证 JSON content envelope 的确定性投影方案。
- `test_versioning.py`：验证 snapshot → 修改 → rollback，以及 branch → checkout → merge。
- `test_retrieval.py`：全量导入 MMS 节点，执行 20 条固定查询并记录 P95；召回质量结论必须换真实 embedding 后才能成立。

## 第一轮实测结果（2026-07-14）

- 20 个真实节点经 JSON content envelope 全字段往返成功：**20/20**。
- 同一批节点通过请求中的 `metadata` 字段探测，原生 metadata 往返：**0/20**。服务接受未知字段但读取结果不包含它，属于静默丢弃。
- `AC-ARCH-04` 被 Memoria 的敏感内容规则阻断，错误为 `contains sensitive content (password_assign)`；72 个候选节点中 71 个可导入、1 个被阻断。
- snapshot 创建失败：`HTTP 500: no column found for name: snapshot_name`。因此 branch/merge/rollback 流程被前置阻塞，当前固定版本不能满足版本控制决策门。
- 使用确定性本地 embedding stub 时，20 条查询 P95 为 **34.24ms**；该数字只证明本地 API 管道延迟，不能证明语义召回质量。
- 当前 MMS `MemoryInjector` 基线对 20 条固定查询的命中数为 **0/20**，原因是现有双索引断层；在 Phase 2 修复索引前，无法计算有意义的 Memoria vs MMS 召回重叠。
- 常驻内存：MatrixOne **1.357GiB**、Memoria API **22.44MiB**、embedding stub **15.31MiB**，合计约 **1.40GiB**，满足 `< 2GB` 暂定标准，但 MatrixOne 空载 CPU 采样约 17%，需要继续观察。

## 暂定判断

当前最关键的风险不是部署，而是**本体字段和 LinkType 是否可查询地保存**：

1. 如果服务实测确认自定义 metadata 被忽略，只把完整本体 envelope 编码进 `content` 虽然可以无损保存，但结构化过滤、反向边查询和局部更新都会退化；
2. 将边表示为独立 memory 记录可以保留关系，但缺少原生按 metadata 精确过滤时，反向查询只能依赖全文检索或在 MMS 侧维护旁路索引；
3. 因此“内容可无损往返”不等于“动态本体兼容”。Go/No-Go 必须同时看关系查询与分支合并一致性。

## 稳定版复测（2026-07-14）

复测组合：`Memoria v0.4.0 + MatrixOne 3.0.17`，使用独立数据目录，未复用第一轮 schema。

- 原生 metadata 仍为 **0/20**，稳定版同样接受字段但读取时静默丢弃；
- JSON content envelope 仍为 **20/20**，证明可作为不透明内容保存，但不能提供结构化本体查询；
- snapshot → 写入 → rollback、branch → checkout → 写入 → main → merge 全流程通过。API 会规范化含连字符的名称，客户端必须使用创建响应返回的 canonical name；
- 固定 embedding stub 下检索 P95 为 **25.298ms**；
- Phase 2 后 Markdown 基线已从 0/20 修复为 20/20 有结果；当前 stub 不具备语义质量，不能证明 Memoria 召回不低于新基线；
- LinkType 精确反向查询、备份恢复与真实 embedding 召回仍未达标。

稳定版排除了第一轮 snapshot schema 漂移问题，但没有排除最关键的动态本体阻塞：ObjectType、LinkType、provenance 和 AST pointer 不能作为可查询 metadata 原生往返。

## 决策门结果

| 验证项 | 标准 | 结果 | 状态 |
|---|---:|---:|---|
| 20 节点原生 metadata 往返 | 20/20 | 0/20（静默丢弃） | ❌ |
| JSON envelope 往返 | 20/20 | 20/20 | ✅ |
| snapshot / rollback | 零丢失 | v0.4.0 全流程通过 | ✅ |
| branch / merge | 零丢失 | v0.4.0 全流程通过 | ✅ |
| 单次关系查询 | < 100ms | 待实现 | ⏳ |
| 检索 P95 | < 500ms | 25.298ms（stub） | ✅ |
| 语义召回 | 不低于基线 | stub 无法与已修复的 20/20 Markdown 基线比较 | ⏳ |
| 常驻内存 | < 2GB | 约 1.40GiB | ✅ |
| 备份恢复 | < 10 分钟且零差异 | 待执行 | ⏳ |

**最终结论：No-Go（不进入 Phase 4/5）。**

该结论不是因为部署或版本 API：稳定组合已经证明两者可用。阻塞原因是：

1. 自定义本体 metadata 在两个版本上均 0/20，属于稳定的产品能力缺口；
2. JSON envelope 只能证明“内容不丢”，不能满足 LinkType 精确查询、局部更新与本体投影合并；
3. 使用 MMS 旁路数据库补齐这些能力会形成第二事实源，抵消采用 Memoria 统一底层存储的主要收益；
4. stub 检索不能证明达到 Phase 2 后的真实 Markdown 基线。

只有 Memoria 提供可查询的任意 metadata/关系扩展，或项目明确接受“Memoria 只做 blob 版本库、MMS 继续维护完整索引”的新架构决策后，才能重新开启 Phase 4。
