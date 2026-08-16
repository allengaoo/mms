# Unit 执行上下文： U1
> token 预算：16,000 (capable) | 文件：1 个
> 架构层：unknown


## 任务

**MySQL 端口转发：（全程保持）**




### 层边界契约（unknown）
（未找到对应层节，请参考 docs/context/layer_contracts.md）

### DAG 层依赖规则
DAG 层依赖规则（Unit 排序参考）

跨层变更时，Unit 执行顺序必须遵循以下依赖链：

```
数据模型（L3 SQLModel） → 服务方法（L4 Service） → API Endpoint（L5） → 前端页面
                                    ↓
                          测试文件（与业务文件同 Unit）
                                    ↓
                          文档更新（e2e_traceability / frontend_page_map）
```

**并行规则**：同一层的多个 Unit 可并行（例如：同时修改两个不相关的 Service 方法），不同层的 Unit 必须串行（下层完成后才能做上层）。

---

*EP-116 · 2026-04-16*

## 涉及文件摘要

# kubectl port-forward svc/mysql -n mdp 3307:3306
（文件不存在，可能是本 Unit 需要新建的文件）

### 相关记忆约束（来自 docs/memory/MEMORY.md）

- [控制面/数据面严格分离（架构基线）](shared/cross_cutting/decisions/AD-003.md) — services/control 只写 MySQL；向量/搜索写入必须通过 services/dispatch 发 Kafka 事件
- [CR 审批流状态必须持久化到 MySQL](shared/L3_domain/governance/MEM-L-019.md) — Redis 只用于加速读，写操作必须先写 MySQL 再更新 Redis
- [宿主机测试数据源配置](shared/L2_infrastructure/environment/ENV-002.md) — 宿主机跑集成测试时 MySQL/PostgreSQL 端口转发配置
## 验证命令

```bash
python3 scripts/mms/arch_check.py --ci
```

---
*token 使用：~225 / 16,000 (capable)*
