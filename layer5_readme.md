# Layer 5：自学习层（Self-Learning）

> **最后更新**：2026-07-19 | v3.1 Seed Pack | Superpowers 原始记忆层

## 1. 架构定位

Layer 5 把 EP 执行结果、工程文档、调试经验和外部方法论转化为可检索、可治理的长期记忆。它不直接训练模型；所谓“自学习”是一个受控的知识闭环：

```text
执行证据 / 工程文档 / 外部规范
  → 提取候选知识
  → 草稿与质量门禁
  → 人工或规则审核
  → MemoryRepository 写入 shared/
  → MEMORY_INDEX 增量更新
  → 后续任务重新注入
```

## 2. 核心模块

```text
src/mms/memory/
├── dream.py               git + EP 日志 → 结构化草稿 → promote
├── entropy_scan.py        孤儿、幽灵、低频、过时、重复记忆扫描
├── freshness_checker.py   AST fingerprint 漂移检测
├── graph_health.py        孤岛、矛盾、图结构质量
├── task_matcher.py        历史任务与命中记忆复用
└── private.py             私有草稿工作区与人工提升

src/mms/analysis/
└── seed_absorber.py       URL/文件 → v3.1 Seed Pack

src/mms/bootstrap/
└── v31_seed_installer.py  always_inject 发现、安装与流程门禁加载

docs/memory/seed_packs/
└── superpowers_sdlc/      Agentic SDLC 原始记忆层
```

## 3. autoDream 闭环

```mermaid
flowchart LR
    GIT[Git commits] --> DREAM[dream.py]
    EP[EP Surprises / Decisions / Outcomes] --> DREAM
    DREAM --> QWEN[qwen3-32b distillation]
    QWEN --> FILTER{质量筛选}
    FILTER -->|无新知识| NONE[NO_NEW_KNOWLEDGE]
    FILTER -->|具体可执行| DRAFT[private/dream/DRAFT-*.md]
    DRAFT --> REVIEW[人工 promote]
    REVIEW --> REPO[MemoryRepository.put]
    REPO --> SHARED[shared/{layer}/]
    REPO --> INDEX[MEMORY_INDEX.json]
```

筛选标准：

- 保存新的反模式、不显而易见的设计决策、可重复的工程坑
- 跳过常规实现、已存在根因、重复约束
- 拒绝“要写测试”“保持代码质量”等空洞建议
- `SKL-SP-003 / SP-LEARN-001` 要求草稿具体、可执行、可验证
- promote 对疑似空洞草稿给出额外人工确认

## 4. v3.1 Seed Pack

标准结构：

```text
docs/memory/seed_packs/{name}/
├── meta.yaml               包身份、来源、layer_affinity、always_inject
├── constraints.yaml        可执行/提示性规则
└── memories/
    ├── AD-*.md              Decision
    ├── PAT-*.md             Pattern / AntiPattern
    └── SKL-*.md             Skill
```

安装选择：

```text
selected packs = detected_stacks 映射包 ∪ meta.always_inject=true 的包
```

`install_v31_packs()` 保留原始 front-matter，通过 Repository API 写入 `shared/{layer}/`，同时更新 Schema v5 索引。种子模板本身不是运行时节点；`shared/` 副本才参与 injector 检索。

## 5. Superpowers 原始记忆层

`superpowers_sdlc` 从 `obra/superpowers` 蒸馏出 11 条跨语言工程方法记忆，并设置 `always_inject: true`：

| 类型 | 记忆 | 内容 |
| --- | --- | --- |
| Decision | `AD-SP-001/002` | 先设计后实现；Spec→Plan→Implement→Review |
| Pattern | `PAT-SP-001~004/006` | TDD、纵深校验、根因调试、完成前验证、条件等待 |
| AntiPattern | `PAT-SP-005` | 禁止测试 mock 占位；禁止测试专用生产 API |
| Skill | `SKL-SP-001~003` | SDD、对照计划评审、可吸收技能写作 |

层映射：

- `CC`：设计决策、SDD、技能写作
- `PLATFORM`：纵深校验、根因追溯
- `CC_testing`：TDD、反 mock、条件等待
- `CC_governance`：完成前验证、代码评审

它是叠加在 FastAPI / Spring / Go / NestJS 技术包之上的**方法层本体**，不替代框架 API 与编码细节。

## 6. 记忆生命周期

```text
hot → warm → cold → archive
```

- `Repository.update_stats()` 更新访问计数与 tier
- `run_gc()` 重建唯一索引并执行熵扫描
- `--apply-gc` 才会实际降级/归档；默认只报告
- `freshness_checker` 使用 parser-independent fingerprint 检测代码锚点漂移
- 删除/归档通过 Repository 完成，禁止直接改写 `shared/`

## 7. 质量与安全边界

- 所有正式记忆必须通过 front-matter validator
- 正式写入统一走 `MemoryRepository`
- 未知 metadata 必须可往返，不得被存储层静默丢弃
- Seed Pack 来源、日期、类型与层亲和性必须可追溯
- 外部知识不能直接覆盖主记忆；先成为 seed/draft，再经安装或 promote
- Memoria PoC 因 metadata 往返不完整判定 No-Go，当前继续使用 Markdown 后端

## 8. 常用命令

```bash
mulan dream --ep EP-NNN
mulan dream --list
mulan dream --promote

mulan seed list
mulan seed ingest <url-or-file>

mulan gc
mulan gc --apply-gc
mulan validate --changed-only
python scripts/migrate_index_v5.py
```

## 9. 测试

```bash
pytest tests/test_v31_seed_installer.py -q
pytest tests/test_gc_loop.py tests/test_graph_cache.py -q
pytest tests/test_markdown_repository.py tests/test_no_bypass_writes.py -q
```
