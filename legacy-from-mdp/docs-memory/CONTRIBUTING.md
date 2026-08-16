# MDP Memory System — 贡献规范

> 版本：v2.1 | 更新：2026-04-11 | EP-108

本文档规定了团队成员向记忆系统贡献知识的标准流程和规范。
**违反以下规则可能导致记忆污染或索引损坏。**

---

## 1. 核心原则

| 原则 | 说明 |
|:---|:---|
| 工具管理 | `MEMORY_INDEX.json` 和 `_system/` 下的文件**禁止手工修改**，由工具自动维护 |
| 原子性 | 所有写入通过 `mms.core.writer.atomic_write` 完成，防止半写入损坏 |
| 版本追踪 | 每个记忆文件必须有 `version` 字段，每次修改必须 +1 |
| Schema 校验 | 提交前必须通过 `scripts/mms/validate.py` 校验 |

---

## 2. 记忆 ID 命名规范

| 前缀 | 类型 | 示例 | 说明 |
|:---|:---|:---|:---|
| `MEM-L-NNN` | lesson | `MEM-L-025` | 经验教训（从 EP 失败/成功提炼） |
| `MEM-E-NNN` | error | `MEM-E-003` | 已知错误与修复方案 |
| `AD-NNN` | decision | `AD-009` | 架构决策（影响范围广） |
| `PAT-NNN` | pattern | `PAT-001` | 设计模式（从 ≥2 条 lesson 提炼） |
| `SKL-NNN` | skill | `SKL-001` | 可复用技能（从 ≥3 条 pattern 提炼） |

**编号规则**：
- 查看对应目录最大 ID，在其基础上 +1
- 禁止跳号（跳号需在 PR 描述中说明原因）

---

## 3. 新增记忆的标准流程

### 3.1 自动新增（推荐）

EP 完成后运行蒸馏工具，自动从 EP 记录中提炼新记忆：

```bash
# EP 完成后
python scripts/memory_distill.py --ep EP-NNN

# 查看生成的新记忆（在 docs/memory/shared/ 对应目录下）
git status docs/memory/

# 审查内容是否准确（人工核查）
# 确认后提交
git add docs/memory/
git commit -m "memory: 从 EP-NNN 蒸馏 N 条新记忆"
```

### 3.2 手工新增

当需要手工记录重要知识时：

```bash
# 1. 确定 Layer 和 Dimension（参考 config.yaml）
# 2. 在对应目录新建文件
# 示例：L2 层 D6 维度（消息队列相关）

cat > docs/memory/shared/L2_infrastructure/D6_messaging/MEM-L-025.md << 'EOF'
---
id: MEM-L-025
layer: L2
dimension: D6
type: lesson
tier: warm
tags: [kafka, partition, consumer-group]
source_ep: EP-108
created_at: "2026-04-11"
last_accessed: "2026-04-11"
access_count: 0
related_memories: [MEM-L-010]
also_in: []
version: 1
---

# MEM-L-025 · <标题>

## WHERE（在哪个模块/场景中）
...

## WHAT（发生了什么）
...

## WHY（根本原因）
...

## HOW（解决方案）
...

## WHEN（触发条件）
...
EOF

# 3. 校验
python scripts/mms/validate.py --file MEM-L-025

# 4. 更新索引（工具自动完成，手工不要触碰 MEMORY_INDEX.json）
python scripts/memory_gc.py --update-index-only

# 5. 提交
git add docs/memory/
git commit -m "memory: 手工新增 MEM-L-025 Kafka 分区记忆"
```

---

## 4. 修改已有记忆

修改记忆时，**必须递增 `version` 字段**：

```yaml
# 修改前
version: 2

# 修改后
version: 3
```

**冲突处理规范**：
- 如果 git merge 时出现 `version` 冲突，取较大值
- 合并双方的 `tags` 列表（取并集）
- 合并双方的 `related_memories` 列表（取并集）
- `access_count` 取较大值

---

## 5. 禁止操作清单

| ❌ 禁止 | ✅ 替代方案 |
|:---|:---|
| 手工编辑 `MEMORY_INDEX.json` | 运行 `python scripts/memory_gc.py` |
| 手工修改 `_system/circuit_state.json` | 运行 `python scripts/mms/resilience/circuit_breaker.py reset` |
| 删除记忆文件（直接删除）| 修改 `tier: archive` 后运行 GC |
| 复制已有 ID 给新记忆 | 检查目录最大 ID，严格递增 |
| 提交未通过 Schema 校验的文件 | 运行 `python scripts/mms/validate.py` 修复后提交 |

---

## 6. PR Checklist

提交包含记忆系统变更的 PR 时，请确认：

- [ ] 所有新增 MEM-*.md 通过 Schema 校验（`python scripts/mms/validate.py`）
- [ ] 新增/修改的记忆包含正确的 `version` 字段
- [ ] `MEMORY_INDEX.json` 由工具生成，未手工修改
- [ ] 新记忆的 `source_ep` 指向有效的 EP 编号
- [ ] 修改已有记忆时，`version` 已递增
- [ ] PR 描述中说明了新增/修改了哪些记忆及原因

---

## 7. 安装开发环境钩子

```bash
# 安装 pre-commit hook（首次克隆仓库后执行）
python scripts/mms/ci_hook.py install

# 验证安装成功
ls -la .git/hooks/pre-commit
```

---

## 8. 常用命令速查

```bash
# 查看记忆系统状态
python scripts/memory_gc.py --dry-run

# 蒸馏新记忆（EP 结束后）
python scripts/memory_distill.py --ep EP-NNN

# 断点续传
python scripts/memory_distill.py --ep EP-NNN --resume MMS-YYYYMMDD-xxxxxx

# 查看未完成的蒸馏任务
python scripts/memory_distill.py --list-incomplete

# 校验所有记忆文件
python scripts/mms/validate.py

# 批量添加 version 字段（迁移用）
python scripts/mms/validate.py --migrate-add-version

# 重置熔断器（Ollama 重启后）
python -c "
import sys; sys.path.insert(0, 'scripts')
from mms.resilience.circuit_breaker import CircuitBreaker
CircuitBreaker('deepseek-r1:8b').reset()
print('✅ 熔断器已重置')
"
```
