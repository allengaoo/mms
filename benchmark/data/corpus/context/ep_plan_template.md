# EP-{NNN}_{Feature} 执行计划

> 复制本模板创建新 EP 的执行计划文件。Runtime 声明节须在 Plan 阶段完成。

---

## 1. 需求摘要

- **EP 类型**：[后端 API / 数据管道 / 前端 / 本体 / 权限安全 / 运维部署 / 全栈]
- **一句话目标**：[描述本次 EP 要完成的核心功能]
- **涉及文件（范围）**：[列出预计修改的文件路径]

---

## 2. Runtime 声明（Plan 阶段填写，执行前确认）

> **为什么在 Plan 阶段声明**：提前明确运行时成本，避免代码完成后遗漏迁移/重建步骤。

| 维度 | 是否涉及 | 说明 |
|:---|:---|:---|
| 🗄️ **DB 迁移（Alembic）** | 是 / 否 | 若修改 `backend/app/models/`，需生成迁移脚本并在 mdp + mdp_test 两库执行 |
| 🔧 **后端镜像重建** | 是 / 否 | 若改动 `backend/app/` 任何代码，需重建 `mdp-backend` |
| 🖥️ **前端镜像重建** | 是 / 否 | 若改动 `frontend/src/`，需先 `rm -rf dist` 再重建 `mdp-frontend` |
| ⚙️ **环境变量变更** | 是 / 否 | 若新增 Settings 字段，需更新 `docker-compose.app.yml` env 段 + K8s ConfigMap |
| 🔌 **Kafka/Schema 变更** | 是 / 否 | 若新增 Topic 或 Avro Schema，需在 K8s 内创建/注册 |
| 🌱 **种子数据** | 是 / 否 | 若新增角色/默认配置，需运行对应 seed 脚本 |

**部署命令入口**（代码完成后执行）：`@.cursor/commands/deploy-after-code.md`

---

## 2.5 Testing Plan（Plan 阶段填写 — EP-110 契约）

> 依据 `testing_gen.mdc §0 Testing Contract`，在 Plan 阶段提前声明测试覆盖计划。
> 此节留空视为 **测试覆盖缺失**，Quality Gate §8 将标记 FAIL。

| 测试类型 | 文件路径 | 覆盖目标 |
| :--- | :--- | :--- |
| 后端单元测试 | `tests/unit/services/.../test_xxx.py` | [列出需要覆盖的 Service 方法] |
| 后端集成测试 | `tests/integration/api/test_xxx.py` | [列出需要覆盖的 Endpoint] |
| Polyfactory | `tests/factories/xxx.py` | [列出需新建的 Factory 类] |
| 前端组件测试 | `src/.../___tests___/xxx.test.tsx` | [列出需要覆盖的组件] |
| MSW Handler | `src/test/mocks/handlers.ts` | [列出需新增的 endpoint mock] |
| E2E 测试 | `e2e/.../xxx.spec.ts` | [如涉及新用户流程，列出场景] |

**覆盖率目标**：后端 Service ≥ 80%；关键路径（Auth / RLS / Quota）100%

---

## 3. 任务拆分（Units）

### Unit 1：[名称]

- **目标**：
- **涉及文件**：
- **实现要点**：

### Unit 2：[名称]

- **目标**：
- **涉及文件**：
- **实现要点**：

> 根据实际需要增减 Unit。

---

## 4. 验收标准

- [ ] [功能验收项 1]
- [ ] [功能验收项 2]
- [ ] Runtime 收尾清单全部执行完毕（见 ep-starter.md 步骤 2）
- [ ] `curl -s http://localhost:8000/health` 返回正常
- [ ] 使用 `admin@mdp.com` 登录并走关键路径，无报错

---

## 5. 执行日志

> 执行过程中记录实际发生的问题和决策，供 LESSONS_LEARNED.md 参考。

- [日期] Unit 1 完成
- [日期] 遇到问题：[描述]，解决方案：[描述]
