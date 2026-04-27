---
id: AC-ARCH-01
layer: CC
tier: hot
type: arch_constraint
language: all
pack: cross_cutting
about_concepts: [circular-dependency, module-dependency, architecture, design-principles]
cites_files: []
created_at: "2026-04-27"
---

# 模块/包之间禁止循环依赖，架构依赖方向必须单向

## 约束（Constraint）

软件系统中，模块（或包、命名空间）之间的依赖关系必须是**有向无环图（DAG）**。任何形式的循环依赖都必须立即消除。

## 各语言检测方法

```bash
# Python：使用 pydeps 可视化依赖图
pip install pydeps
pydeps src/myapp --noshow --max-bacon 2

# Java：使用 ArchUnit 在测试中强制约束
@AnalyzeClasses(packages = "com.example")
class ArchitectureTest {
    @ArchTest
    static final ArchRule no_cycles = slices()
        .matching("com.example.(*)..")
        .should().beFreeOfCycles();
}

# Go：使用 go mod graph 检查 + godepgraph
go mod graph | grep -v "go " | grep "^example.com"
godepgraph -s example.com/myapp | dot -Tpng -o deps.png

# TypeScript：使用 eslint-plugin-import 的 no-cycle 规则
# .eslintrc.js
rules: { "import/no-cycle": ["error", { maxDepth: 5 }] }
```

## 消除方法

1. **提取共享层**：将相互依赖的公共代码提取到独立的 `shared`/`common` 模块
2. **引入接口/事件**：用事件总线或依赖倒置接口打破循环（A 依赖 interface，B 实现 interface）
3. **合并模块**：如果两个模块总是相互依赖，它们可能本来就是同一个模块

## 参考

- 《Clean Architecture》Robert Martin - 无环依赖原则（ADP）
- ArchUnit：https://www.archunit.org/
