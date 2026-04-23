# DevOps Manifest

> 适用：Docker 镜像构建 / K8s 部署 / CI / 端口转发 EP
> 补充加载：`@.cursor/commands/deploy-after-code.md`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（部署时最易犯错）

1. **先改代码再构建**：代码变更后必须重建镜像；不要用 `kubectl cp` 热替换文件（不可复现）。
2. **构建上下文路径**：在 `backend/` 目录下执行 `docker build .`，不要在项目根目录用 `-f backend/Dockerfile .`（`requirements.txt` 路径问题）。
3. **容器名查清再 set-image**：`kubectl set image` 前先用 `kubectl get deployment xxx -o jsonpath='{.spec.template.spec.containers[*].name}'` 确认容器名，MDP 后端容器名是 `api` 而非 `mdp-backend`。
4. **MySQL port-forward 独立执行**：`kubectl port-forward` 不要与其他命令用 `&&` 串联，需要独立运行（后台保持）。
5. **验证顺序**：镜像推送 → `kubectl rollout restart` → 等待 Pod Ready → 健康检查 → 登录验证。

---

## 标准部署流程

```bash
# Step 1: 构建后端镜像（在 backend/ 目录下）
cd backend
docker build -t mdp-backend:ep{NNN} .

# Step 2: 加载到 K8s（OrbStack 本地集群）
kubectl -n mdp set image deployment/mdp-backend api=mdp-backend:ep{NNN}

# Step 3: 等待滚动更新
kubectl rollout status deployment/mdp-backend -n mdp

# Step 4: 健康检查
curl -s http://localhost:8000/health

# Step 5（MySQL 宿主机测试需要）
kubectl port-forward svc/mysql -n mdp 3307:3306
```

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `.cursor/commands/deploy-after-code.md` | 完整部署后验证流程 | 必须 |
| `.cursor/rules/env-k8s-testing.mdc` | OrbStack K8s 环境说明 | 必须 |
| `.cursor/rules/devops_gen.mdc` | Dockerfile/Compose/K8s 生成规范 | 涉及配置变更时 |
| `deploy/` | K8s manifests 目录 | 变更部署配置时 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 本地开发（频繁改动） | 宿主机 uvicorn + npm dev | 无需重建镜像，热重载更快 |
| 集成测试 / 最终验收 | Docker 镜像 + K8s | 与生产环境一致，避免环境差异 |
| 容器 name 不确定时 | `kubectl get deployment -o jsonpath` 查询 | 硬猜容器名会导致 set-image 失败 |
| 前端仅改 `.tsx` | 重建 `mdp-frontend` 镜像 | Vite 打包后静态文件需更新到 nginx |

---

## 环境变量变更触发规则（强制）

> 当任意 EP 在 `backend/app/core/config.py` 新增了 `Settings` 字段时，必须同步以下步骤。

**触发条件**：`backend/app/core/config.py` 新增了带 `alias` 的 `Field()`（即新环境变量）。

**必须执行的动作**：

### Docker Compose 栈
```bash
# 编辑 deploy/docker-compose.app.yml，在 backend service 的 environment 段中追加：
#   NEW_VAR: "default_value"
# 然后重启（不要污染宿主机 DATABASE_URL）：
env -u DATABASE_URL -u REDIS_URL docker compose -f deploy/docker-compose.app.yml up -d mdp-backend
```

### K8s 栈
```bash
# 编辑 ConfigMap（或直接 patch）：
kubectl edit configmap mdp-backend-config -n mdp
# 追加：NEW_VAR: "default_value"
# 然后重启 deployment 让新变量生效：
kubectl rollout restart deployment/mdp-backend -n mdp
```

**EP Plan Runtime 声明模板**（在 EP plan 文件中填写）：
```
| ⚙️ 环境变量变更 | 是 | 新增 ICEBERG_TABLE_PREFIX，默认值 "mdp_" |
```

**注意**：若新变量有默认值，且默认值即为期望行为，可只更新文档，不强制修改 compose/K8s（但仍建议显式声明避免混淆）。
