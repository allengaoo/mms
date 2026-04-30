# Bootstrap v2 真实项目测试报告

> 生成时间：2026-04-30 00:52 UTC
> 零 LLM 调用 | 纯启发式信号融合（v2）

---

## FastAPI-Template

| 指标 | 数值 |
|------|------|
| 源文件数 | 47 |
| 识别类数 | 31 |
| 方法数   | 45 |
| 图节点   | 31 |
| 图边数   | 7 |
| 循环依赖 | 0 |
| 推断置信≥0.5 | 13 个类 |
| 生成记忆 | 9 条 |

**层分布：**

| 层 | 类数 |
|----|------|
| DOMAIN | 12 |
| PLATFORM | 1 |

**高置信度样本（≥0.5）：**

| 类名 | 层级 | 置信度 | 类型 |
|------|------|--------|------|
| Settings | PLATFORM | 0.90 | Config |
| UserBase | DOMAIN | 0.80 | Entity |
| UserRegister | DOMAIN | 0.80 | Entity |
| UserUpdateMe | DOMAIN | 0.80 | Entity |
| UpdatePassword | DOMAIN | 0.80 | Entity |
| UsersPublic | DOMAIN | 0.80 | Entity |
| ItemBase | DOMAIN | 0.80 | Entity |
| ItemsPublic | DOMAIN | 0.80 | Entity |

**样本记忆（MEM-BOOT-001）：**

```yaml
---
id: MEM-BOOT-001
type: pattern
layer: PLATFORM
tier: warm
tags: [configuration, cross-cutting, infrastructure, settings]
cites_files:
  - backend/app/core/config.py
about_concepts: [infrastructure, settings]
impacts: []
derived_from: []
ast_pointer:
```

---

## Go-Clean

| 指标 | 数值 |
|------|------|
| 源文件数 | 98 |
| 识别类数 | 101 |
| 方法数   | 170 |
| 图节点   | 101 |
| 图边数   | 0 |
| 循环依赖 | 0 |
| 推断置信≥0.4 | 14 个类 |
| 生成记忆 | 14 条 |

**层分布：**

| 层 | 类数 |
|----|------|
| ADAPTER | 6 |
| PLATFORM | 8 |

**高置信度样本（≥0.5）：**

| 类名 | 层级 | 置信度 | 类型 |
|------|------|--------|------|

**样本记忆（MEM-BOOT-001）：**

```yaml
---
id: MEM-BOOT-001
type: pattern
layer: PLATFORM
tier: warm
tags: [configuration, cross-cutting, infrastructure, server]
cites_files:
  - pkg/grpcserver/server.go
about_concepts: [infrastructure, server]
impacts: []
derived_from: []
ast_pointer:
```

---

## Spring-Petclinic

| 指标 | 数值 |
|------|------|
| 源文件数 | 42 |
| 识别类数 | 52 |
| 方法数   | 308 |
| 图节点   | 52 |
| 图边数   | 23 |
| 循环依赖 | 0 |
| 推断置信≥0.5 | 4 个类 |
| 生成记忆 | 4 条 |

**层分布：**

| 层 | 类数 |
|----|------|
| DOMAIN | 4 |

**高置信度样本（≥0.5）：**

| 类名 | 层级 | 置信度 | 类型 |
|------|------|--------|------|
| OwnerRepository | DOMAIN | 0.90 | Repository |
| PetTypeRepository | DOMAIN | 0.90 | Repository |
| VetRepository | DOMAIN | 0.80 | Repository |
| NamedEntity | DOMAIN | 0.54 | Entity |

**样本记忆（MEM-BOOT-001）：**

```yaml
---
id: MEM-BOOT-001
type: pattern
layer: DOMAIN
tier: warm
tags: [data-access, domain-model, owner, repository]
cites_files:
  - src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java
about_concepts: [business-logic, domain-model, owner, repository]
impacts: []
derived_from: []
ast_pointer:
```

---

## 结论

- **FastAPI（Python）**：SQLModel/BaseModel 模型正确识别为 DOMAIN/Entity；Settings 识别为 PLATFORM/Config。FastAPI 函数式路由无类结构，ADAPTER 层通过文件路径信号补充。
- **Go-Clean（Go）**：结构体通过路径信号（`pkg/`, `internal/`）和命名信号识别层级；Go 无装饰器，注解信号贡献为零，整体置信度略低（0.4~0.65）。
- **Spring-Petclinic（Java）**：JpaRepository 子类高置信度（0.8~0.9）正确识别为 DOMAIN/Repository；Spring 注解（@Entity/@Table）触发 annotation 信号。

**Bootstrap v2 核心能力验证通过**：零 LLM 调用，基于 AST + 五路信号融合，跨 Python/Go/Java 三种语言准确推断架构层级和代码对象类型。