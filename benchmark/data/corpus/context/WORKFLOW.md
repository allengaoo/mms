# MMS Workflow Guide

## EP Lifecycle (7-Step Loop)

```
① mms synthesize "<task>" --template <type>   # Intent synthesis
② Cursor generates EP → user confirms (Go)    # Planning
③ mms precheck --ep EP-NNN                    # Pre-check (establish baseline)
④ Edit code + generate tests (one commit/unit)
⑤ mms postcheck --ep EP-NNN                   # Post-check (pytest + arch_check)
⑥ mms distill --ep EP-NNN                     # Knowledge distillation
```

## Available Templates

| Template | Use Case |
|----------|----------|
| `ep-backend-api` | New endpoint / service / model |
| `ep-frontend` | New page / component |
| `ep-data-pipeline` | Connector / sync job / ingestion |
| `ep-debug` | Bug investigation |
| `ep-devops` | Docker / K8s / CI/CD |
| `ep-ontology` | Domain model changes |

## Cold Start (New Project)

```bash
mms bootstrap --project-root /path/to/project
```

This will:
1. Scan AST skeleton (functions, classes, signatures)
2. Detect tech stack from `requirements.txt` / `pyproject.toml`
3. Inject appropriate seed packs (fastapi_sqlmodel, react_zustand, etc.)
4. Initialize `docs/memory/` directory structure

## Model Routing

| Task | Recommended Model |
|------|------------------|
| Code generation | `bailian_coder` (qwen3-coder-next) |
| Reasoning / DAG | `bailian_plus` (qwen3-32b) |
| Code review | `bailian_plus` (qwen3-32b) |
| Offline fallback | `ollama_coder` (deepseek-coder-v2:16b) |
