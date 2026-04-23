# MMS — Memory Management System

> **AI Agent-driven Structured Knowledge Management for Complex Software Engineering**
>
> MMS accumulates engineering lessons, injects relevant context before each task,
> scans architectural constraints, and controls documentation entropy —
> all using plain text, no vector database required, zero mandatory third-party runtime.

[![CI](https://github.com/allengaoo/mms/actions/workflows/ci.yml/badge.svg)](https://github.com/allengaoo/mms/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Why MMS?

Modern AI coding agents (like Cursor / Copilot) are stateless — they forget everything between sessions.
MMS solves this by acting as a **persistent, structured memory layer** that:

| Problem | MMS Solution |
|---------|-------------|
| AI re-makes the same mistakes | Structured memory with severity tags |
| AI hallucinates architecture rules | `arch_check.py` mechanical constraint scanner |
| Irrelevant context wastes tokens | 3-level retrieval funnel (< 4k tokens/task) |
| Cold start on new projects | `mms bootstrap` — AST skeleton + seed packs in < 1s |
| Docs drift from code | AST Diff + ontology auto-sync in `postcheck` |

---

## Quick Start

### 1. Install

```bash
# Core (no LLM required for most features)
pip install pyyaml structlog

# For Bailian (Alibaba Cloud) LLM support
pip install openai dashscope

# Clone and add to PATH
git clone https://github.com/allengaoo/mms.git
cd mms
export PATH="$PATH:$(pwd)"
```

### 2. Bootstrap a New Project

```bash
# From your project root directory
MMS_PROJECT_ROOT=$(pwd) python3 /path/to/mms/cli.py bootstrap
```

This scans your project AST, detects the tech stack, and injects seed knowledge packs.

### 3. Configure LLM Providers

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Start a Task

```bash
# Synthesize a new execution plan
mms synthesize "Add user profile endpoint with avatar upload support" --template ep-backend-api

# Pre-check before coding
mms precheck --ep EP-001

# After coding: post-check + knowledge distillation
mms postcheck --ep EP-001
mms distill --ep EP-001
```

---

## Architecture

```
mms/
├── cli.py                  # Unified CLI entry point (mms <command>)
├── synthesizer.py          # EP synthesis: task → execution plan
├── intent_classifier.py    # 3-level intent funnel (RBO + LLM fallback)
├── task_decomposer.py      # AIU decomposition (28 atomic intent types)
├── unit_generate.py        # DAG generation from EP files
├── unit_runner.py          # AIU execution with 3-strike retry + feedback
├── unit_compare.py         # LLM-based code review (Qwen3-32B evaluator)
├── ep_parser.py            # Parse EP markdown files → DagState
├── ep_runner.py            # Automated EP pipeline (mms ep run)
├── ep_wizard.py            # Interactive EP writing wizard
├── arch_check.py           # Architecture constraint scanner (6 rules AC-1~AC-6)
├── arch_resolver.py        # Layer-to-file path resolver
├── ast_skeleton.py         # AST parser: extract class/function signatures
├── ast_diff.py             # AST diff: detect contract changes
├── ontology_syncer.py      # Sync ontology YAML from AST changes
├── dep_sniffer.py          # Detect tech stack from dependency files
├── repo_map.py             # Context-ranked file map (PageRank-inspired)
├── graph_resolver.py       # Import graph analysis
├── injector.py             # Memory injection into prompts
├── precheck.py             # Pre-task baseline check
├── postcheck.py            # Post-task quality gate (10 dimensions)
├── dream.py                # Auto-distill lessons from EP (autoDream)
├── entropy_scan.py         # Detect orphaned/stale memories
├── model_tracker.py        # Track LLM usage and costs
├── dag_model.py            # DagUnit / DagState data models
├── aiu_types.py            # 28 Atomic Intent Unit types (6 families)
├── aiu_cost_estimator.py   # CBO-style cost estimation for AIUs
├── aiu_feedback.py         # 3-level rollback feedback (like DB Query Feedback)
├── sandbox.py              # Git sandbox for safe file operations
├── file_applier.py         # Parse and apply LLM BEGIN/END-CHANGES blocks
├── codemap.py              # Generate project directory snapshot
├── funcmap.py              # Generate function-level map
├── mms_config.py           # Centralized config loader (config.yaml)
├── router.py               # Task → provider routing
├── doc_drift.py            # Documentation drift detection
├── fix_gen.py              # Auto-generate fix suggestions
├── atomicity_check.py      # Check if a unit is atomic enough for small models
├── ci_hook.py              # CI integration hooks
├── validate.py             # Schema validation for memory files
├── verify.py               # System integrity verification
│
├── providers/              # LLM provider adapters
│   ├── factory.py          # Task → provider routing (MMS_TASK_MODEL_OVERRIDE)
│   ├── bailian.py          # Alibaba Cloud Bailian (Qwen3-32B, Qwen3-Coder-Next)
│   ├── gemini.py           # Google Gemini (fallback)
│   ├── claude.py           # Anthropic Claude (fallback)
│   └── ollama.py           # Ollama offline (deepseek-r1:8b, deepseek-coder-v2:16b)
│
├── trace/                  # Execution tracing
│   ├── tracer.py           # EPTracer: record LLM calls, file ops, events
│   ├── collector.py        # Trace data collection
│   ├── reporter.py         # Generate trace reports
│   └── event.py            # Trace event types and levels
│
├── resilience/             # Reliability primitives
│   ├── retry.py            # Exponential backoff retry decorator
│   ├── circuit_breaker.py  # Circuit breaker for LLM/API calls
│   └── checkpoint.py       # Checkpoint save/restore for long runs
│
├── core/                   # Core I/O utilities
│   ├── reader.py           # File reading with encoding detection
│   ├── writer.py           # Safe file writing with backup
│   └── indexer.py          # Memory index builder
│
├── seed_packs/             # Cold-start seed knowledge packs
│   ├── base/               # Universal architecture patterns
│   ├── fastapi_sqlmodel/   # FastAPI + SQLModel patterns
│   ├── react_zustand/      # React + Zustand patterns
│   └── palantir_arch/      # Palantir-style ontology patterns
│
├── benchmark/              # Retrieval quality benchmark
│   ├── run_benchmark.py    # Main benchmark runner
│   ├── run_codegen.py      # Code generation quality benchmark
│   ├── run_indexer.py      # Index builder for benchmark
│   ├── data/
│   │   ├── queries.yaml        # Retrieval benchmark queries
│   │   ├── queries_codegen.yaml # Code gen quality tasks (20 MDP-backend tasks)
│   │   └── corpus/             # Benchmark corpus (generic SW eng patterns)
│   └── src/
│       ├── evaluators/         # 4-level code gen evaluator
│       ├── metrics/            # Accuracy, efficiency, AIU quality metrics
│       ├── reporters/          # Markdown + JSON report generation
│       └── retrievers/         # PageIndex / HybridRAG / Ontology retrievers
│
├── docs/memory/            # Knowledge base (populated by mms commands)
│   ├── _system/            # System files (config.yaml, codemap, task_quickmap)
│   ├── shared/             # Accumulated memories (L1–L5 + cross_cutting)
│   ├── ontology/           # Dynamic ontology definitions (objects, links, actions, functions)
│   └── templates/          # EP templates for different task types
│
└── tests/                  # Test suite (563+ tests)
```

---

## Core Concepts

### Memory Layers (L1–L5)

MMS organizes memories in 5 layers mirroring the software architecture:

| Layer | Focus | Example |
|-------|-------|---------|
| **L1** Platform | Security, auth, config | Multi-tenancy, RBAC |
| **L2** Infrastructure | DB, cache, messaging | Transaction patterns, Kafka |
| **L3** Domain | Business logic | Domain models, entity rules |
| **L4** Application | Services, workers | Job execution, CQRS |
| **L5** Interface | API, frontend, testing | Response format, component patterns |
| **CC** Cross-cutting | Architecture decisions | ADRs, global constraints |

### Atomic Intent Units (AIU)

Tasks are decomposed into 28 atomic types across 6 families:

| Family | Types |
|--------|-------|
| **Schema** | `FIELD_ADD`, `FIELD_MODIFY`, `FIELD_REMOVE`, `TYPE_ADD`, `TYPE_MODIFY`, `INDEX_ADD` |
| **Endpoint** | `ENDPOINT_ADD`, `ENDPOINT_MODIFY`, `ENDPOINT_REMOVE`, `PERMISSION_ADD` |
| **Service** | `SERVICE_METHOD_ADD`, `SERVICE_METHOD_MODIFY`, `SERVICE_REFACTOR`, `CACHE_ADD` |
| **Infrastructure** | `QUERY_ADD`, `QUERY_MODIFY`, `MIGRATION_ADD`, `INFRA_ADAPTER_ADD` |
| **Test** | `UNIT_TEST_ADD`, `INTEGRATION_TEST_ADD`, `FIXTURE_ADD`, `MOCK_ADD` |
| **Orchestration** | `CONFIG_ADD`, `FEATURE_FLAG_ADD`, `EVENT_EMIT`, `DAG_RESTRUCTURE`, `VALIDATION_ADD`, `ERROR_CODE_ADD` |

### 3-Level Intent Funnel

```
User Task Input
     │
     ▼
[Level 1] Rule-Based Classifier (RBO)     ← zero LLM cost, ~0ms
     │ confidence < threshold
     ▼
[Level 2] Keyword + Ontology Match        ← local lookup, ~5ms
     │ confidence < threshold
     ▼
[Level 3] LLM Intent Classification       ← Bailian fallback, ~500ms
     │
     ▼
AIU Decomposition → DAG → Execution
```

### Query Feedback (3-Level Rollback)

When an AIU exceeds cost budget (analogous to DB Query Feedback):

```
Level 1: Expand token budget (1.5× multiplier)
Level 2: Insert prerequisite AIU (missing context)
Level 3: Split AIU into smaller units
```

---

## LLM Provider Configuration

MMS routes different tasks to different models:

| Task | Default Provider | Model |
|------|-----------------|-------|
| Code generation | `bailian_coder` | `qwen3-coder-next` |
| Reasoning / DAG | `bailian_plus` | `qwen3-32b` |
| Code review | `bailian_plus` | `qwen3-32b` |
| Offline fallback | `ollama_coder` | `deepseek-coder-v2:16b` |

Override per task at runtime:

```bash
MMS_TASK_MODEL_OVERRIDE="dag_orchestration:gemini,code_review:gemini" mms unit run --ep EP-001 --unit U1
```

---

## Benchmark

Evaluate retrieval quality across 3 systems:

```bash
# Run full benchmark (requires ES + Milvus for HybridRAG)
python3 benchmark/run_benchmark.py --systems pageindex hybrid_rag ontology

# Code generation quality benchmark (requires Bailian API)
python3 benchmark/run_codegen.py --systems pageindex ontology --full-eval

# Dry run (no LLM calls, structure check only)
python3 benchmark/run_codegen.py --dry-run
```

### Metrics

| Metric | Formula | What it measures |
|--------|---------|-----------------|
| Layer Accuracy | `hits / queries` | Correct L1–L5 layer identification |
| Recall@5 | `relevant in top-5 / total relevant` | Coverage of relevant memories |
| MRR | `Σ(1/rank_i) / N` | Mean reciprocal rank |
| Path Validity | `valid_paths / total_paths` | Actionable file references |
| Context Tokens | `mean(token_count)` | Cost efficiency |
| Info Density | `Recall@5 / (tokens / 1000)` | Quality per token |
| AIU Precision | `correct_AIUs / predicted_AIUs` | Decomposition accuracy |
| Codegen Score | `0.1×syntax + 0.3×contract + 0.3×arch + 0.3×tests` | Code quality (4-level) |

---

## Cold Start

Bootstrap MMS on a brand-new project with zero memories:

```bash
# Full bootstrap: AST scan + tech stack detection + seed injection
mms bootstrap --project-root /path/to/your/project

# What happens (< 1 second, zero LLM calls):
# 1. AST skeleton scan → docs/memory/_system/codemap.md
# 2. Dependency sniffer → detect FastAPI, SQLModel, React, etc.
# 3. Seed pack injection → copy matching patterns to docs/memory/shared/
# 4. Ontology initialization → docs/memory/ontology/
```

Available seed packs:

| Pack | Triggers On | Injects |
|------|------------|---------|
| `base` | Any project | Universal patterns (security, transactions) |
| `fastapi_sqlmodel` | `fastapi`, `sqlmodel` in requirements | Backend API patterns |
| `react_zustand` | `react`, `zustand` in package.json | Frontend patterns |
| `palantir_arch` | Ontology/metadata keywords | Domain modeling patterns |

---

## Testing

```bash
# Run all tests (no LLM API needed)
pytest tests/ -v

# Run specific test groups
pytest tests/ -m "not slow and not integration"

# With coverage
pytest tests/ --cov=. --cov-report=html
```

Test results: **563+ passing**, 1 skipped, 2 xfailed

---

## Configuration

All configuration lives in `docs/memory/_system/config.yaml` (created by `mms bootstrap`).

Key settings:

```yaml
runner:
  timeout_llm: 180        # LLM call timeout (seconds)
  max_retries: 3          # 3-strike retry count
  max_tokens:
    code_generation: 4096
    code_review: 4096
    dag_orchestration: 8192

intent:
  confidence_threshold: 0.85  # Below this → LLM fallback
  grey_zone_low: 0.60

dag:
  annotate_threshold_high: 0.85
  report_threshold: 0.75
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Run tests: `pytest tests/`
4. Run arch check: `python3 arch_check.py --ci`
5. Submit a pull request

---

## License

MIT License — see [LICENSE](LICENSE) for details.
