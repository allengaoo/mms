# Bootstrap Advanced 集成测试报告

**时间**: 2026-05-02 20:54:10  |  **结果**: 27/27 通过  |  **耗时**: 4.5s

---

## G 组：框架覆盖规则（YAML Override Pass）

### ✅ [G-01] FastAPI 项目 --dry-run 正常完成
- **命令**: `mulan bootstrap --dry-run --root <fastapi_tmp>`
- **exit code**: 0
  - ✅ exit=0 正常返回（期望: exit 0）
  - ✅ 包含 AST 扫描结果（期望: AST）
  - ✅ 完成摘要存在（期望: Bootstrap）

### ✅ [G-02] Spring Boot 项目 --dry-run 扫描到 Java 类
- **命令**: `mulan bootstrap --dry-run --root <spring_tmp>`
- **exit code**: 0
  - ✅ exit=0 正常返回（期望: exit 0）
  - ✅ 完成摘要存在（期望: Bootstrap）

### ✅ [G-03] --skip-doc-absorb 标志被 CLI 接受
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ exit=0 不报未知参数错误（期望: exit 0）
  - ✅ 输出含跳过文档扫描提示（期望: 跳过）

### ✅ [G-04] --skip-seeds 跳过种子包注入
- **命令**: `mulan bootstrap --dry-run --skip-seeds`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 含跳过种子包提示（期望: 跳过）

### ✅ [G-05] --skip-memory-gen 跳过记忆生成
- **命令**: `mulan bootstrap --dry-run --skip-memory-gen`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 含跳过记忆生成提示（期望: 跳过）

### ✅ [G-06] --skip-ast 跳过 AST 及后续步骤
- **命令**: `mulan bootstrap --dry-run --skip-ast`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 含 skip-ast 相关提示（期望: 跳过）
  - ✅ 不含 Step 5 推断输出（期望: 无 Step5）

### ✅ [G-07] 所有 skip 标志组合使用不崩溃
- **命令**: `mulan bootstrap --dry-run --skip-ast --skip-seeds --skip-doc-absorb`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 不含 Traceback（期望: 无崩溃）

## H 组：边界与错误恢复场景

### ✅ [H-01] 空项目 bootstrap 不崩溃
- **命令**: `mulan bootstrap --dry-run --root /tmp/empty`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 不含 Traceback（期望: 无崩溃）
  - ✅ 完成摘要存在（期望: 摘要）

### ✅ [H-02] 单类项目 bootstrap 正常
- **命令**: `mulan bootstrap --dry-run --root <single_class>`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ AST 扫描到至少 1 个文件（期望: 扫描文件）

### ✅ [H-03] 循环依赖项目正常完成
- **命令**: `mulan bootstrap --dry-run --root <circular>`
- **exit code**: 0
  - ✅ exit=0 不因循环依赖崩溃（期望: exit 0）
  - ✅ 不含 Traceback（期望: 无崩溃）

### ✅ [H-04] 全低置信度时记忆生成为 0
- **命令**: `mulan bootstrap --dry-run --root <low_confidence>`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 不含 Traceback（期望: 无崩溃）
  - ✅ 生成 0 条或推断结果为空提示（期望: 0条记忆）

### ✅ [H-05] 不存在的 --root 目录给出友好提示
- **命令**: `mulan bootstrap --dry-run --root /not/exist`
- **exit code**: 0
  - ✅ 不含裸 Traceback（友好错误）（期望: 友好提示）

### ✅ [H-06] bootstrap --help 显示所有选项
- **命令**: `mulan bootstrap --help`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 含 --dry-run（期望: --dry-run）
  - ✅ 含 --skip-ast（期望: --skip-ast）
  - ✅ 含 --root（期望: --root）

### ✅ [H-07] 50 类项目 bootstrap < 30 秒
- **命令**: `mulan bootstrap --dry-run --root <50_classes>`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 30 秒内完成（期望: 耗时 0.1s）
  - ✅ 扫描到类（期望: 扫描类）

### ✅ [H-08] 对 MMS 自身 bootstrap 无 Traceback
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 不含 Traceback（期望: 无崩溃）

## I 组：报告字段完整性与输出格式

### ✅ [I-01] 6 步流程标题全部出现
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ Step 1/6 技术栈嗅探（期望: Step1）
  - ✅ Step 2/6 种子包注入（期望: Step2）
  - ✅ Step 3/6 AST（期望: Step3）
  - ✅ Step 4/6 依赖图（期望: Step4）
  - ✅ Step 5/6 推断（期望: Step5）
  - ✅ Step 6/6 记忆生成（期望: Step6）

### ✅ [I-02] 摘要包含耗时信息
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ 含耗时（秒）（期望: 时间戳）
  - ✅ 含 '零 LLM 调用'（期望: 零LLM）

### ✅ [I-03] 摘要包含 AST 扫描统计（文件数/类数/方法数）
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ 含文件计数（期望: 文件数）
  - ✅ 含类计数（期望: 类数）
  - ✅ 含方法计数（期望: 方法数）

### ✅ [I-04] 摘要包含依赖图统计（节点/边/循环）
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ 含节点计数（期望: 节点）
  - ✅ 含边计数（期望: 边）
  - ✅ 含循环依赖计数（期望: 循环）

### ✅ [I-05] dry-run 摘要含 dry-run 模式提示
- **命令**: `mulan bootstrap --dry-run --root <tmp>`
- **exit code**: 0
  - ✅ 含 dry-run 提示（期望: dry-run）

### ✅ [I-06] 摘要包含项目根目录路径
- **命令**: `mulan bootstrap --dry-run --skip-doc-absorb`
- **exit code**: 0
  - ✅ 含根目录字符串（期望: 根目录）

### ✅ [I-07] skip-ast 时摘要含 AST 为 0 或跳过提示
- **命令**: `mulan bootstrap --dry-run --skip-ast`
- **exit code**: 0
  - ✅ exit=0（期望: exit 0）
  - ✅ 含跳过或 0 文件提示（期望: 0文件）

## J 组：幂等性与增量运行

### ✅ [J-01] 连续两次 --dry-run 都 exit=0
- **命令**: `mulan bootstrap --dry-run (×2)`
- **exit code**: 0
  - ✅ 第 1 次 exit=0（期望: exit0_run1）
  - ✅ 第 2 次 exit=0（期望: exit0_run2）
  - ✅ 两次输出结构相似（期望: 一致）

### ✅ [J-02] --skip-ast 后完整运行正常
- **命令**: `skip-ast → full`
- **exit code**: 0
  - ✅ skip-ast exit=0（期望: skip_ok）
  - ✅ 完整运行 exit=0（期望: full_ok）
  - ✅ 完整运行含 Step 3/6（期望: Step3）

### ✅ [J-03] dry-run 后无 MEM-BOOT-*.md 写入临时目录
- **命令**: `mulan bootstrap --dry-run --root <tmp>`
- **exit code**: 0
  - ✅ dry-run exit=0（期望: exit 0）
  - ✅ 无 MEM-BOOT-*.md 文件（期望: 实际有 0 个文件）

### ✅ [J-04] 两个不同 --root 目录各自独立运行
- **命令**: `mulan bootstrap --root <tmp1> && --root <tmp2>`
- **exit code**: 0
  - ✅ tmp1 exit=0（期望: exit0_1）
  - ✅ tmp2 exit=0（期望: exit0_2）

### ✅ [J-05] --root 指向外部目录时不修改 MMS 自身记忆文件
- **命令**: `mulan bootstrap --dry-run --root /tmp/xxx`
- **exit code**: 0
  - ✅ MMS 自身 MEM-BOOT 文件数不变（期望: before=2 after=2）

---
*测试完成于 2026-05-02 20:54:10*