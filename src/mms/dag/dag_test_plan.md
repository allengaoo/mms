# DAG 层完整测试计划

> 版本：v1.0 | 2026-05-04  
> 范围：`src/mms/dag/` 全模块  
> 测试框架：pytest 7.4+，pytest-mock，filelock  
> 测试根目录：`tests/dag/`（在 `.gitignore` 中，仅本地执行）

---

## 1. 测试分层策略

DAG 层测试严格遵循 TDD 分层，不同层次的测试有明确的职责边界：

```
┌─────────────────────────────────────────────────────────────────┐
│  层次 4：E2E 集成测试（tests/integration/）                      │
│  跨层链路：EP YAML → synthesizer → task_decomposer → unit_runner│
│  使用真实项目（java/go/python sample projects）                  │
├─────────────────────────────────────────────────────────────────┤
│  层次 3：DAG 子系统集成（tests/dag/）                            │
│  多模块协作：Registry → Decomposer → CostEstimator → Runner     │
│  使用 tmp_path，不依赖外部 LLM（用 pytest-vcr 录制）             │
├─────────────────────────────────────────────────────────────────┤
│  层次 2：模块单元测试（tests/dag/）                              │
│  单模块纯算法：各自隔离，mock 所有外部依赖                        │
│  确定性：不触发网络 / 文件系统（除 tmp_path）                     │
├─────────────────────────────────────────────────────────────────┤
│  层次 1：TDD 底座（tests/dag/ 当前已实现）                       │
│  关键路径算法：CBO anti-toxic、A3 new-file fix、RBO OCP、decay   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 当前已实现测试（39 tests）

### 2.1 `tests/dag/test_cost_and_atomicity.py`（14 tests）

| 测试类 | 测试名 | 验证目标 |
|--------|--------|----------|
| `TestCBOAntiToxicFeedback` | `test_extreme_low_success_rate_capped_at_10pct` | success_rate=0% → history_factor ≤ 1.1 |
| | `test_typical_low_success_rate_10pct` | success_rate=10% → budget ≤ base × 1.1 |
| | `test_high_success_rate_minimal_penalty` | success_rate=90% → 增幅 ≤ 2% |
| | `test_history_factor_formula_exact` | 白盒：公式 min(1+(1-rate)×0.1, 1.1) |
| `TestA3NewFileParadox` | `test_new_file_same_dir_as_connected_files_passes` | **P0 修复**：同目录新文件不报警 |
| | `test_new_file_same_dir_passes_even_with_multiple_new` | 多个同目录新文件均通过 |
| | `test_new_file_different_dir_warns` | 孤立新目录 → is_warning=True |
| | `test_all_new_files_fallback_to_track_b` | 全新文件 → Track B 同层通过 |
| | `test_all_new_files_different_layers_track_b_warns` | 全新文件跨层 → Track B 警告 |
| | `test_existing_files_disconnected_warns` | 边界：in_degree 孤立节点处理 |
| | `test_real_existing_files_disconnected_warns` | 两个连通分量 → 真实架构警告 |
| | `test_single_file_always_passes` | 单文件始终通过 |
| | `test_empty_files_always_passes` | 空列表始终通过 |
| | `test_validate_unit_with_new_file_no_false_positive` | 完整链路无假阳性 |

### 2.2 `tests/dag/test_aiu_registry_v2.py`（13 tests）

| 测试类 | 测试名 | 验证目标 |
|--------|--------|----------|
| `TestBuiltinRBORules` | `test_get_rbo_rules_returns_at_least_12` | ≥12 核心规则，ID 完整 |
| | `test_each_rule_has_required_keys` | 全部 dict key 与 Decomposer 兼容 |
| | `test_rule_aiu_type_is_valid_enum` | aiu_type 是合法 AIUType Enum |
| | `test_rule_keywords_is_non_empty_list` | 每条规则至少 1 个关键词 |
| | `test_rule_token_budget_is_positive_int` | token_budget > 0 |
| | `test_rule_model_hint_is_valid` | model_hint ∈ {fast, capable} |
| | `test_rules_sorted_by_exec_order` | 规则按 exec_order 有序 |
| | `test_builtin_enum_types_all_present` | 所有 AIUType 均已注册 |
| `TestOCPExtension` | `test_custom_yaml_with_existing_type_adds_rbo_rule` | 自定义 YAML 覆盖 rbo_triggers |
| | `test_registry_reload_picks_up_new_yaml` | 新实例加载新增 YAML 文件 |
| `TestDecomposerIntegration` | `test_task_decomposer_loads_rbo_rules_from_registry` | Decomposer 初始化 ≥12 规则 |
| | `test_should_decompose_rbo_triggers_correctly` | 低/高置信度阈值判断正确 |
| | `test_rbo_decompose_returns_valid_steps` | RBO 命中返回合法 steps |

### 2.3 `tests/dag/test_feedback_store.py`（12 tests）

| 测试类 | 测试名 | 验证目标 |
|--------|--------|----------|
| `TestDecayWindow` | `test_old_failures_evicted_by_new_successes` | 旧失败被淘汰，success_rate=1.0 |
| | `test_old_successes_evicted_by_new_failures` | 旧成功被淘汰，success_rate=0.0 |
| | `test_mixed_window_accurate_rate` | 5成功+5失败，rate=0.5 |
| | `test_window_boundary_exact` | 精确边界：7条，窗口5，最后5条有效 |
| | `test_no_records_returns_none` | 空 store 查询不崩溃 |
| | `test_multiple_aiu_types_independent_windows` | 多类型窗口互不干扰 |
| | `test_disk_persistence_and_reload` | 新实例从磁盘重载，统计一致 |
| `TestFileLockConcurrency` | `test_multithread_concurrent_writes_all_recorded` | 5线程×100条，磁盘完整 |
| | `test_multithread_no_duplicate_aiu_ids` | 4线程×25条，无数据竞争 |
| | `test_lock_file_created_on_write` | FileLock .lock 文件正确创建 |
| | `test_multiprocess_concurrent_writes` | 3进程×50条，跨进程 FileLock 生效 |
| | `test_multiprocess_data_isolation_by_process` | 每进程写入量精确匹配 |

---

## 3. 已实现测试（P1/P2 全部完成）

> ✅ = 已实现  |  🔲 = 待实现（P3，低优先级）

### P1 — 已完成

#### 3.1 `tests/dag/test_task_decomposer.py`（✅ 36 tests）

**目标**：验证 `TaskDecomposer` 的完整分解逻辑（非 RBO 路径）

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| LLM 路径 | `test_decompose_llm_path_assigns_sequential_ids` | LLM 返回的 steps 分配 aiu_1, aiu_2... |
| | `test_decompose_llm_path_clears_depends_on` | half-preserve: depends_on 始终 =[] |
| | `test_decompose_llm_path_sorted_by_exec_order` | 按 exec_order 排序 |
| RBO 路径 | `test_rbo_triggers_on_schema_keywords` | "新增字段" → SCHEMA_ADD_FIELD |
| | `test_rbo_triggers_on_route_keywords` | "api endpoint" → ROUTE_ADD_ENDPOINT |
| | `test_rbo_miss_falls_back_to_llm` | 无关键词 → 走 LLM 分解 |
| 回退 | `test_fallback_on_llm_failure` | LLM 超时/异常 → fallback step |
| | `test_fallback_step_has_capable_model` | fallback step 使用 capable 模型 |
| 边界 | `test_single_step_task_no_decompose` | 单步任务不强制分解 |
| | `test_parse_llm_response_malformed_json` | 解析失败不崩溃 |

**运行方式**：
```bash
# 使用 pytest-vcr 录制（避免真实 LLM 调用）
PYTHONPATH=src pytest tests/dag/test_task_decomposer.py -v
```

#### 3.2 `tests/dag/test_aiu_cost_estimator.py`（✅ 26 tests）

**目标**：覆盖 `AIUCostEstimator.estimate_step()` 全部代码路径

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| 基础估算 | `test_estimate_single_file_base_cost` | 0 文件 = base_cost × layer_factor |
| | `test_estimate_multi_file_cost_adds_per_file` | 每增加 1 文件 +FILE_OVERHEAD |
| | `test_estimate_caps_at_token_max` | 结果不超过 _TOKEN_MAX |
| | `test_estimate_floors_at_token_min` | 结果不低于 _TOKEN_MIN |
| 层因子 | `test_layer_factor_domain_vs_infra` | DOMAIN factor ≠ INFRA factor |
| | `test_layer_factor_cross_layer_uses_max` | 跨层取最大因子 |
| 模型选择 | `test_model_hint_fast_when_budget_small` | budget ≤ 4000 → fast |
| | `test_model_hint_capable_when_budget_large` | budget > 4000 → capable |
| 历史因子 | `test_history_factor_capped_10pct` | ←（已在 test_cost_and_atomicity 覆盖）|

#### 3.3 `tests/dag/test_atomicity_check_full.py`（✅ 41 tests）

**目标**：补充 A1/A2/A4 检查器的覆盖 + validate_unit 完整链路

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| A1 文件数量 | `test_a1_single_file_passes` | 1 文件 → passed |
| | `test_a1_five_files_passes` | 5 文件 → passed |
| | `test_a1_eleven_files_warns` | 11 文件 → is_warning |
| | `test_a1_twenty_files_fails` | 20 文件 → passed=False |
| A2 层级 | `test_a2_single_layer_passes` | 同层文件 → passed |
| | `test_a2_cross_business_layer_warns` | 业务层 + 基础层 → is_warning |
| A3 完整 | `test_a3_code_graph_unavailable_uses_track_b` | 图不存在 → Track B |
| 组合 | `test_validate_unit_all_checks_aggregated` | validate_unit 三项均通过 → is_atomic |
| | `test_validate_unit_score_calculation` | score 计算公式正确 |

### P2 — 已完成

#### 3.4 `tests/dag/test_aiu_registry_ocp_extended.py`（✅ 12 tests）

**目标**：验证 `schemas/aius/custom/` 子目录扩展机制

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| custom 子目录 | `test_custom_subdir_yaml_loaded` | custom/ 下 YAML 被加载 |
| | `test_custom_overrides_builtin` | custom/ 覆盖内置定义（优先级） |
| 格式容错 | `test_malformed_yaml_skipped_gracefully` | 格式错误 YAML 静默跳过 |
| | `test_missing_id_field_skipped` | 无 id 字段的条目跳过 |

#### 3.5 `tests/dag/test_feedback_suggest.py`（✅ 14 tests）

**目标**：验证 `AIUFeedbackStore.suggest()` 策略逻辑

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| 样本不足 | `test_suggest_below_min_samples_returns_default` | <3 条 → 返回 default |
| 低成功率 | `test_suggest_low_success_upgrades_model` | rate<0.5 → model_hint=capable |
| token 低估 | `test_suggest_underestimated_tokens_upsizes` | actual >> estimated → 提升 budget |
| token 高估 | `test_suggest_overestimated_tokens_downsizes` | actual << estimated → 降低 budget |
| 置信度 | `test_suggest_confidence_increases_with_samples` | 样本越多 confidence 越高 |

#### 3.6 `tests/dag/test_unit_runner_feedback.py`

**目标**：验证 `unit_runner.py` 与 `AIUFeedbackStore` 的集成

| 测试场景 | 测试名 | 验证目标 |
|----------|--------|----------|
| 成功执行 | `test_success_records_feedback` | 执行成功 → record(success=True) |
| 失败执行 | `test_failure_records_feedback_with_level` | 执行失败 → record(success=False, feedback_level>0) |
| 重试 | `test_retry_increments_attempts` | 重试 2 次 → attempts=2 |
| 最大 feedback 级别 | `test_get_max_feedback_level_returns_highest` | 多次失败 → 返回最高级别 |

### P3 — 待实现（低优先级，依赖外部资源）

#### P3 已覆盖替代方案

当前 `test_task_decomposer.py` 使用 `unittest.mock.patch` 覆盖了 LLM 路径的核心逻辑，包括 `_llm_decompose`、`_parse_llm_response` 等。VCR 录制可在未来需要端到端回归测试时补充。

### VCR 录制测试（依赖真实 LLM）

#### 3.7 `tests/dag/test_decomposer_vcr.py`

**目标**：使用 `pytest-vcr` 录制真实 LLM 响应，验证端到端分解链路

```bash
# 首次录制（需要 API Key）
VCR_RECORD_MODE=new_episodes PYTHONPATH=src pytest tests/dag/test_decomposer_vcr.py -v

# 后续回放（无需 API Key）
PYTHONPATH=src pytest tests/dag/test_decomposer_vcr.py -v
```

| 测试场景 | VCR cassette | 验证目标 |
|----------|-------------|----------|
| Java 增加字段 | `cassettes/java_add_field.yaml` | 返回 ≥1 步，含 SCHEMA_ADD_FIELD |
| Go 新增 API | `cassettes/go_add_route.yaml` | 返回 ROUTE_ADD_ENDPOINT |
| Python 复合任务 | `cassettes/python_complex.yaml` | 返回 ≥3 步，类型多样 |

---

## 4. 测试执行手册

### 4.1 快速验证（开发时）

```bash
# 仅运行 DAG 层单元测试（<5s）
PYTHONPATH=src pytest tests/dag/ -v --tb=short

# 只运行某个文件
PYTHONPATH=src pytest tests/dag/test_cost_and_atomicity.py -v

# 只运行某个测试类
PYTHONPATH=src pytest tests/dag/test_feedback_store.py::TestDecayWindow -v
```

### 4.2 覆盖率统计

```bash
PYTHONPATH=src pytest tests/dag/ \
  --cov=mms.dag \
  --cov-report=term-missing \
  --cov-report=html:htmlcov/dag/ \
  -v
```

**覆盖率状态（P1/P2 完成后）**：

| 模块 | 实现前覆盖 | 当前估算 | 主要剩余未覆盖路径 |
|------|---------|------|----------------|
| `atomicity_check.py` | ~70% | ~92% | check_a4 arch_check 细节分支 |
| `aiu_cost_estimator.py` | ~60% | ~88% | `_rank_files_by_complexity` 边界 |
| `aiu_registry.py` | ~75% | ~93% | `_load_extended_yaml` 部分分支 |
| `task_decomposer.py` | ~40% | ~82% | `build_constrained_context`（独立工具函数） |
| `aiu_feedback.py` | ~65% | ~88% | `record_unit_feedback` 三级回退 |

### 4.3 CI/CD 集成建议

```yaml
# .github/workflows/test.yml 推荐配置
test-dag-layer:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Install deps
      run: pip install -r requirements.txt pytest pytest-mock
    - name: Run DAG unit tests
      run: PYTHONPATH=src pytest tests/dag/ -v --tb=short -x
      # -x: 首个失败即停止（快速反馈）
```

### 4.4 测试隔离原则

所有 DAG 层测试必须遵守以下隔离规则：

1. **文件系统**：使用 `tmp_path` fixture，不读写项目内的真实文件（除 VCR cassettes）
2. **外部 LLM**：默认使用 `unittest.mock.patch` 模拟，VCR 测试单独标记
3. **全局状态**：`AIURegistry` 测试每次用新实例，禁止复用全局单例
4. **进程隔离**：多进程测试通过 `subprocess.Popen` 启动完全独立的进程

---

## 5. 关键测试场景矩阵

下表列出 DAG 层每个核心能力的测试覆盖状态（✅ 已实现 / 🔲 待实现 / ❌ 不适用）：

| 能力 | 算法正确性 | 边界条件 | 并发安全 | 持久化 | OCP 扩展 | LLM 集成 |
|------|-----------|---------|---------|-------|---------|---------|
| CBO 成本估算 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| A3 内聚性检查 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| A1/A2/A4 检查器 | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Feedback 衰减 | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| FileLock 安全 | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| RBO 规则加载 | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| LLM 分解路径 | ✅ | ✅ | ❌ | ❌ | ❌ | 🔲 |
| Suggest 策略 | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |

---

## 6. 风险与缺口分析

### 高风险缺口（应优先填补）

**R1：`task_decomposer.py` 覆盖率过低（约 40%）**
- LLM 分解路径未测试，错误解析（malformed JSON）可能导致静默失败
- **行动**：实现 `test_task_decomposer.py`（P1 第一优先）

**R2：`suggest()` 策略未测试**
- `suggest()` 是 `unit_runner` 的上游决策依据，但当前没有测试
- 逻辑错误会导致每个 unit 都使用次优配置（token budget 过低/过高）
- **行动**：实现 `test_feedback_suggest.py`（P2 第一优先）

**R3：A1/A2 检查器无覆盖**
- `validate_unit()` 聚合三个检查，A1/A2 错误可能被 A3 测试掩盖
- **行动**：实现 `test_atomicity_check_full.py`（P1）

### 已消除风险

- ✅ **R-old1：A3 假阳性**（新文件悖论）— 已修复 + 7 场景测试
- ✅ **R-old2：CBO 毒性正反馈**（history_factor 无上限）— 4 个精确公式测试
- ✅ **R-old3：FileLock 跨进程竞争**— 5线程×100条 + 3进程×50条 并发测试
- ✅ **R-old4：RBO 规则硬编码**（OCP 违反）— YAML 驱动 + OCP 扩展 12 场景测试
- ✅ **R1：TaskDecomposer 覆盖率过低**（约40%）— 36 tests 覆盖 RBO/LLM/Fallback/解析容错
- ✅ **R2：suggest() 策略未测试**— 14 tests 覆盖样本/低成功率/token误差/置信度全路径
- ✅ **R3：A1/A2/A4 检查器无覆盖**— 41 tests 覆盖全部检查器和 validate_unit 链路

### 当前状态

**总测试数：168 tests / 168 passed**（执行时间 < 2 秒）

| 文件 | tests | 优先级 |
|------|-------|--------|
| `test_cost_and_atomicity.py` | 14 | P0 底座 |
| `test_aiu_registry_v2.py` | 13 | P0 底座 |
| `test_feedback_store.py` | 12 | P0 底座 |
| `test_task_decomposer.py` | 36 | P1 |
| `test_aiu_cost_estimator.py` | 26 | P1 |
| `test_atomicity_check_full.py` | 41 | P1 |
| `test_aiu_registry_ocp_extended.py` | 12 | P2 |
| `test_feedback_suggest.py` | 14 | P2 |

---

*文档由 Mulan AI Agent 生成，与 tests/dag/ 下的测试套件保持同步。*  
*最后更新：2026-05-04，完成 P1/P2 全部测试实施。*
