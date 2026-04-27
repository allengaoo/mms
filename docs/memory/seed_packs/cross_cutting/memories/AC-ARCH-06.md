---
id: AC-ARCH-06
layer: CC
tier: warm
type: lesson
language: all
pack: cross_cutting
about_concepts: [technical-debt, todo-comment, issue-tracking, code-quality]
cites_files: []
created_at: "2026-04-27"
---

# 生产代码中 TODO 注释超过 2 周必须转化为 Issue/Task

## 教训（Lesson）

`// TODO: fix later` 类注释是技术债务的最大来源之一。研究表明，超过 70% 的 TODO 注释在提交后永远不会被处理。

## 规范

```python
# ❌ 禁止：没有跟踪 ID 的 TODO（无责任人、无期限）
# TODO: fix this later
# FIXME: this is broken
# HACK: temporary workaround

# ✅ 正确：TODO 必须包含跟踪 ID 和截止日期
# TODO(#1234, @张三, 2026-05-01): 使用 selectinload 替代懒加载，解决 N+1 问题
# FIXME(#5678): 当 quantity 为负数时会产生负库存，待 v2.1 处理
```

## CI 检测脚本

```bash
# 检测无跟踪 ID 的 TODO（在 CI 中运行，超过阈值则 Warning）
rg "TODO(?!.*#\d+)" --type py --type java --type go --type ts \
  | grep -v "test_\|_test.go\|conftest" \
  | wc -l
```

## 自动化工具

- **todo-to-issue**（GitHub Action）：自动将 `TODO(#NEW)` 注释转为 GitHub Issue
- **SonarQube**：统计 TODO 密度，超过阈值时 Quality Gate 失败

## 意义

TODO 注释超量是项目健康度下降的早期信号：
- 反映开发者在时间压力下做出的妥协
- 累积后形成"破窗效应"（其他人觉得 TODO 是可以接受的）
- 高 TODO 密度的文件往往是 bug 最密集的文件
