# EP 类型模板：运维 / 部署 / 调试环境

> 适用场景：本地调试环境配置、K8s 部署、Docker Compose、端口转发、镜像构建、集成测试环境搭建

---

## 必读文件（Cursor @mention 列表）

```
@docs/context/MASTER_INDEX.md
@docs/context/SESSION_HANDOFF.md
@.cursor/rules/env-k8s-testing.mdc
@deploy/docker-compose.app.yml
```

---

## 关键约束摘要

1. **MySQL 端口**：K8s 内 MySQL 必须通过 `kubectl port-forward` 到 **3307**，不得直接使用 OrbStack 代理的 3306（会导致 asyncmy 1045 错误）
2. **DATABASE_URL**：本地调试时固定为 `mysql+asyncmy://root:password123@127.0.0.1:3307/mdp`
3. **镜像不变**：运维类 EP 原则上不构建新镜像；如需代码变更，必须在 Scope 中明确说明并指定镜像版本
4. **隔离原则**：本地调试服务（uvicorn/vite dev）与 K8s Pod 共享同一 MySQL，数据写入互相可见
5. **不修改业务代码**：运维 EP 仅修改配置文件、脚本、环境变量；若需修改业务代码，应拆分为独立 EP

---

## EP 类型声明

**运维 / 调试**

---

## 自定义要求

<!--
在此填写环境背景、目标状态、约束条件。
示例：
  环境：OrbStack K8s，命名空间 mdp，MySQL port-forward 3307
  目标：在不重建镜像的情况下，宿主机热重载调试后端 API
  约束：不改动 K8s Pod 内的服务；Redis 已通过 NodePort 暴露
-->

---

## Surprises & Discoveries
<!-- 实施过程中的意外发现（完成后填写）
格式：
- 现象：...
  证据：...（命令输出 / 错误信息片段）
-->

---

## Decision Log
<!-- 每个关键决策（完成后填写）
格式：
- Decision: [做了什么决定]
  Rationale: [为什么；有哪些备选方案被排除]
  Date: YYYY-MM-DD
-->

---

## Outcomes & Retrospective
<!-- EP 完成后填写
- 达成了什么（与 Purpose 对照）
- 偏差（未完成的 Unit 或范围变更）
- 给下一个 Agent 的教训
-->

---

## Scope

> ⚠️ **此节为必填项**，mms precheck 解析此表格以建立基线。节名必须为 `## Scope`。
> 运维类 EP 若某 Unit 无代码变更文件，「涉及文件」可填 `（脚本/命令，无代码变更）`。

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U0   | 环境前提检查 | `（命令验证，无代码变更）` |
| U1   | MySQL 端口转发配置 | `（kubectl 命令，无代码变更）` |
| U2   | 创建本地调试环境文件 | `backend/.env.local` |
| U3   | 本地后端启动（uvicorn --reload） | `（uvicorn 命令，无代码变更）` |
| U4   | 本地前端启动（Vite HMR） | `frontend/vite.config.ts` |
| U5   | 快速启动脚本（可选） | `scripts/dev-local.sh` |

---

## Testing Plan

> ⚠️ **此节为必填项**，mms precheck 解析此列表。
> 运维/调试类 EP 通常无新增测试文件，使用以下固定格式：

（本 EP 为运维/调试类，无新增自动化测试文件；验收通过以下手动验证清单完成）

**手动验收检查清单**：
- [ ] `kubectl port-forward svc/mysql -n mdp 3307:3306` 正常运行
- [ ] `curl http://localhost:8000/health` 返回 `{"code": 200, ...}`
- [ ] `http://localhost:5173` 页面正常加载，登录 `admin@mdp.com` 成功
- [ ] 修改后端 `.py` 文件，uvicorn 自动重载（无需重启）
- [ ] 修改前端 `.tsx` 文件，浏览器自动热更新（无需刷新）
