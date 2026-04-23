# Debug / Hotfix Manifest

> 适用：Bug 诊断 / 性能问题 / Hotfix EP
> 补充加载：`@docs/hotfix/ISSUE-REGISTRY.md`
> **维护者**：@gaobin · 最后更新：EP-102

---

## 红线约束（诊断时最易绕弯）

1. **先查已知故障表**：先查 `troubleshooting.mdc` 和 `ISSUE-REGISTRY.md`，80% 问题有记录，禁止重复踩坑。
2. **不用管道符运行命令**：宿主机 shell 命令避免 `|` 管道符（Cursor 终端兼容性问题）。
3. **MySQL 连接用 3307**：宿主机连 MySQL 必须用 `kubectl port-forward svc/mysql -n mdp 3307:3306`，不用 OrbStack 自动暴露的 3306（认证插件冲突）。
4. **健康检查先行**：验证任何功能前，先 `curl http://localhost:8000/health` 确认后端可达。
5. **保留原始错误信息**：诊断时不要过早 `except` 吃掉异常；开启 `structlog` debug 级别后再复现。

---

## 常用诊断命令

```bash
# 查看后端 Pod 实时日志
kubectl logs -n mdp deployment/mdp-backend --tail=100

# 查看后端 Pod 状态
kubectl get pods -n mdp

# MySQL port-forward（宿主机测试用）
kubectl port-forward svc/mysql -n mdp 3307:3306

# 后端健康检查
curl -s http://localhost:8000/health

# 查看 Kafka 消费位移
kubectl exec -n mdp deploy/kafka -- kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group mdp-ingestion
```

---

## 已知故障速查

| 错误特征 | 根因 | 修复路径 |
|:---|:---|:---|
| `1045 Access denied (asyncmy)` | 认证插件 `caching_sha2_password` 不兼容 | port-forward 3307；MySQL 设 `mysql_native_password` |
| `Future attached to different loop` | pytest-asyncio 每测新 loop，engine 绑旧 loop | 检查 `_reinit_app_db_engine` conftest fixture |
| `InvalidRequestError: A transaction is already begun` | `session.execute()` 后又调 `session.begin()` | 改用 Strategy A（begin-first）|
| `rows_affected` 恒为 0 | `base.py` 用了 `or` 处理数值，或 JobExecutionScope 未正确累积 | 检查 `scope.rows_affected += len(batch)` |
| Avro 序列化静默失败 | 含原生 PG 类型未归一化 | 调用 `normalize_record(row)` |
| 前端 API 调用后跳 `/login` | 拦截器把 201 当错误（应判 `code < 200 or code >= 300`）| 修复 `request.ts` 拦截器 |

---

## 必读文件

| 文件 | 说明 | 优先级 |
|:---|:---|:---|
| `docs/hotfix/ISSUE-REGISTRY.md` | 全量故障清单与状态 | 必须 |
| `.cursor/rules/troubleshooting.mdc` | 按错误码/现象索引的排查手册 | 必须 |
| `docs/architecture/e2e_traceability.md §{N}` | 按故障所属域加载对应切片，快速定位关键文件 | 定位根因时 |
| `.cursor/rules/dependency-compat.mdc` | 依赖版本兼容矩阵 | 环境问题时 |
| `.cursor/rules/env-k8s-testing.mdc` | K8s 环境测试步骤 | 集成测试时 |

---

## 关键决策点

| 遇到 X | 选 A 而非 B | 理由 |
|:---|:---|:---|
| 新故障已修复 | 在 `ISSUE-REGISTRY.md` 新增条目 | 避免后人重复排查 |
| 临时绕过 vs 根因修复 | 优先根因修复 | 临时绕过必须标 `# FIXME(EP-NNN)` 并开 Issue |
| 宿主机 MySQL 连接 | 3307 port-forward | 3306 OrbStack 代理有认证兼容问题 |
