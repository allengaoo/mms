

# 木兰（Mulan）系统 TDD 落地详细实施规范

## 阶段一：建立物理沙箱与隔离测试基建

**工程依据**：木兰系统强依赖文件读写。共享测试目录会导致状态污染（State Pollution）。必须通过 Pytest Fixtures 提供每次运行即抛弃的“无菌室”。

*   **目标修改文件**：

    *   `tests/conftest.py`

    *   `tests/fixtures/spring-boot-demo/` (需创建基础结构)

*   **Cursor 提示词模板**：

    > `@tests/conftest.py` 请利用 pytest 的 `tmp_path` 机制，实现一个名为 `isolated_spring_boot` 的 fixture。要求：读取与当前文件同级的 `fixtures/spring-boot-demo` 目录，使用 `shutil.copytree` 将其完整复制到临时目录，并返回临时目录的 `Path` 对象。确保所有测试修改只发生在这个临时副本中。

*   **代码契约与约束**：

    *   绝对禁止在 `tests/fixtures/` 的原始目录中执行写操作。

    *   靶机结构必须包含真实的特征文件（如 `pom.xml`、带有 `@RestController` 的 Controller）。

*   **验收标准**：

    *   运行 `pytest tests/conftest.py` 无错误。手动检查临时目录在测试结束后能被垃圾回收。

---

## 阶段二：下钻确定性底座的纯函数测试

**工程依据**：测试系统的物理层算法（脱敏、哈希、图遍历），必须剥离所有 LLM I/O，追求 100% 确定性和毫秒级执行。

*   **目标修改文件**：

    *   `tests/analysis/test_ast_skeleton.py`

    *   `tests/memory/test_graph_resolver.py`

    *   `tests/core/test_sanitize.py`

*   **Cursor 提示词模板**：

    > `@tests/core/test_sanitize.py` 帮我针对 `SanitizationGate` 编写基于 `@pytest.mark.parametrize` 的数据驱动单元测试。请构造 5 组极端的包含敏感信息（AWS AK/SK、JWT 格式 Token、内网 10.x.x.x IP）的代码片段。断言：1. 敏感词被精准替换为 `[REDACTED_*]`；2. 代码前后的缩进和无关字符完全不变。不允许有任何外部网络请求。

*   **代码契约与约束**：

    *   `test_graph_resolver.py` 中必须直接在内存里实例化 `MemoryNode` 和 `Edge` 列表，禁止读取磁盘上的 Markdown 文件，验证纯算法（BFS）。

    *   `test_ast_skeleton.py` 必须断言代码加入空行/注释后`compute_semantic_hash` 结果不变。

*   **验收标准**：

    *   执行此阶段测试总耗时严格 < 1 秒。

---

## 阶段三：控制流与大模型协议的录制回放 (VCR Integration)

**工程事实**：LLM 输出具有不确定性。通过 VCR 录制机制，将概率层转换为本地的 JSON/YAML 卡带，以测试木兰内部的状态机与容错逻辑。

*   **目标修改文件**：

    *   `tests/dag/test_task_decomposer.py`

    *   `tests/execution/test_autonomous_runner.py`

*   **Cursor 提示词模板**：

    > `@tests/dag/test_task_decomposer.py` 引入 `pytest-vcr`。编写测试 `test_decompose_task_success`，利用 VCR 录制 `qwen3-32b` 对“新增订单导出 API 并添加审计日志”的正常拆解响应。然后，编写测试 `test_decompose_task_retry_on_bad_json`，要求读取手动损坏的卡带（破坏 JSON 结构），断言系统触发了 `AIUFeedback` 并发起 3-Strike 重试机制，且未产生全局 Panic。注意配置 VCR 过滤 `Authorization` header。

*   **代码契约与约束**：

    *   VCR 配置必须包含 `filter_headers=['Authorization']`，严禁在提交的卡带（Cassettes）中泄露百炼 API Key。

    *   死锁测试：对于 `autonomous_runner`，强制 Mock 工具层一直报错，断言循环能在 `max_turns` 时抛出 `MaxTurnsExceeded` 异常中断。

*   **验收标准**：

    *   断网环境下，运行 `pytest tests/dag/` 和 `tests/execution/` 必须全绿通过。

---

## 阶段四：零阻力接管的冷启动宏观验证

**工程事实**：验证 Bootstrap v2 能否在无 LLM 介入的情况下，通过多路信号融合和框架强覆盖，精准解构陌生企业项目。

*   **目标修改文件**：

    *   `tests/bootstrap/test_bootstrap_populator.py`

*   **Cursor 提示词模板**：

    > `@tests/bootstrap/test_bootstrap_populator.py` 结合 `@tests/conftest.py` 中的 `isolated_spring_boot` fixture，新增测试用例 `test_bootstrap_on_spring_boot`。执行 `bootstrap_project`。硬性断言：1. 生成的 `ast_index.json` 包含 `UserController`；2. `Framework Override Pass` 生效，将 `UserController` 的 layer 强制锁定为 `ADAPTER`（置信度 1.0）；3. 成功生成至少 1 个 `MEM-BOOT-*.md` 文件。

*   **代码契约与约束**：

    *   测试过程中必须触发 `signal_fusion.py` 中的 `load_overrides` 逻辑，验证 YAML 驱动的规则被正确挂载。

*   **验收标准**：

    *   针对靶机冷启动的集成测试顺利完成，证明多语言物理骨架提取逻辑闭环。

---

## 阶段五：安全门控的反向攻击防御 (Negative Testing)

**工程事实**：安全验证层（Layer 4）是企业防线的底座，必须通过红蓝对抗（注入脏代码）来测试其熔断有效性。

*   **目标修改文件**：

    *   `tests/analysis/test_arch_check.py`

    *   `tests/workflow/test_migration_gate.py`

*   **Cursor 提示词模板**：

    > `@tests/analysis/test_arch_check.py` 实施架构红线反向测试。在沙箱中创建一个 `OrderController.java`，在文件顶部插入 `import javax.persistence.Entity;` 并在方法中返回该 Entity 实体。执行 `run_arch_check`，断言系统必须抛出架构违规（对应规约 AC-JAV-01 污染层约束），并且能够从异常体中提取出违规的代码行号。

*   **代码契约与约束**：

    *   `test_migration_gate.py` 必须验证非对称迁移。如果 ORM 加了字段，但迁移脚本只有 `up()` 没有 `down()`，必须抛出 `MigrationAlignmentError` 阻断。

*   **验收标准**：

    *   所有恶意注入的代码均被 Layer 4 精准拦截并报错，未流入下一步合并阶段。

---

## 阶段六：自学习与图谱演进测试

**工程事实**：验证 Layer 5 的知识蒸馏是否具备降噪能力，以及图谱是否能基于访问频率实现物理级的衰减剪枝。

*   **目标修改文件**：

    *   `tests/analysis/test_seed_absorber.py`

    *   `tests/memory/test_entropy_scan.py`

*   **Cursor 提示词模板**：

    > `@tests/memory/test_entropy_scan.py` 编写图谱衰减测试 `test_edge_decay_and_pruning`。在内存中初始化一个 `MemoryGraph`，手动创建一条 `cites` 边，设置其 `last_accessed_ep` 为当前 `ep_id` 的 25 个轮次之前。执行 `mulan gc` 触发衰减扫描。断言：1. 该边的 `weight` 从 1.0 衰减（例如 * 0.8）；2. 将权重强制修改为 0.1 后再次执行 GC，断言该边被物理删除。

*   **代码契约与约束**：

    *   对于 `test_seed_absorber.py`，必须用 VCR 录制喂入充满情绪化噪音（“你是一个优秀的 AI”）的 Markdown 文件，断言输出的 `constraints.yaml` 只保留强类型规约，实现 100% 噪音滤除。

*   **验收标准**：

    *   系统具备明确的自愈（降噪）与遗忘（剪枝）特征。

---

## 阶段七：E2E 真实评测与 Pass@1 闭环

**工程事实**：前 6 阶段保证了工厂机器运转正常，最后必须用端到端执行来验证产品质量（代码测试通过率）。

*   **目标修改文件**：

    *   `benchmark/v2/layer1_swebench/runner.py`

*   **Cursor 提示词模板**：

    > `@benchmark/v2/layer1_swebench/runner.py` 完善 E2E 执行闭环。利用指定的企业 Issue 测试集（如 `mall_order_cases.yaml`），设计双轨测试：Track 1（Baseline）：禁用木兰上下文注入（跳过 Layer 2），让 `qwen3-coder-next` 裸写；Track 2（Mulan-Enhanced）：执行标准 `mulan ep run --auto-confirm`。分别提取沙箱内的 `pytest` 退出码。最终报告需要对比两者的 `Pass@1` 成功率差异。

*   **代码契约与约束**：

    *   不要断言 LLM 生成的具体代码字符串。

    *   只检查最终状态`exit_code == 0` 以及 `arch_check` 全绿。

*   **验收标准**：

    *   自动化生成类似 `Mulan Context Pass@1: 60% (vs Baseline: 25%)` 的 Markdown 报告。证明木兰架构带来了真实的工程产出提升。