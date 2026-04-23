"""
conftest.py — MMS 测试根级 Fixture 和路径配置

职责：
  1. 将 MMS 项目根目录加入 sys.path，让 `from intent_classifier import ...` 等绝对导入正常工作
  2. 提供通用 fixtures：tmp_mms_root, mock_cfg, mock_provider
  3. 注册自定义 pytest markers

使用方式：
  tests/ 下的所有测试文件自动共享本文件中定义的 fixtures。
  子目录（如 benchmark/）有独立的 conftest.py。
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# ── 路径注入（最高优先级）────────────────────────────────────────────────────────
# 确保 `import cli`, `import intent_classifier` 等均能找到 mms 根目录下的模块
_MMS_ROOT = Path(__file__).resolve().parent
if str(_MMS_ROOT) not in sys.path:
    sys.path.insert(0, str(_MMS_ROOT))

# benchmark/src 也需要可导入
_BENCH_SRC = _MMS_ROOT / "benchmark" / "src"
if str(_BENCH_SRC) not in sys.path:
    sys.path.insert(0, str(_BENCH_SRC))


# ── 通用 Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def mms_root() -> Path:
    """MMS 项目根目录路径"""
    return _MMS_ROOT


@pytest.fixture
def tmp_mms_root(tmp_path: Path) -> Path:
    """
    在 tmp_path 下创建最小化的 MMS 目录结构，用于需要读写磁盘的测试。

    创建的结构：
      tmp_path/
        docs/memory/_system/
        docs/memory/shared/
        docs/memory/ontology/
        docs/execution_plans/
    """
    (tmp_path / "docs" / "memory" / "_system").mkdir(parents=True)
    (tmp_path / "docs" / "memory" / "shared").mkdir(parents=True)
    (tmp_path / "docs" / "memory" / "ontology").mkdir(parents=True)
    (tmp_path / "docs" / "execution_plans").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def mock_cfg():
    """
    Mock MMS 配置对象，返回标准默认值。
    用于不依赖磁盘 config.yaml 的单元测试。
    """
    cfg = MagicMock()
    # runner 配置
    cfg.runner_timeout_llm = 120
    cfg.runner_max_tokens_code_generation = 4096
    cfg.runner_max_tokens_code_review = 4096
    cfg.runner_max_tokens_intent_routing = 200
    cfg.runner_max_tokens_dag_orchestration = 8192
    cfg.runner_max_retries = 3
    # dag 配置
    cfg.dag_annotate_threshold_high = 0.85
    cfg.dag_annotate_threshold_mid = 0.60
    cfg.dag_report_threshold = 0.75
    # intent 配置
    cfg.intent_confidence_threshold = 0.85
    cfg.intent_grey_zone_low = 0.60
    cfg.intent_grey_zone_high = 0.85
    return cfg


@pytest.fixture
def mock_llm_provider():
    """
    Mock LLM Provider，complete() 返回固定响应。
    用于测试调用 LLM 的模块，避免实际 API 开销。
    """
    provider = MagicMock()
    provider.model_name = "mock-model"
    provider.complete.return_value = '{"mock": "response"}'
    provider.is_available.return_value = True
    return provider


@pytest.fixture
def mock_auto_detect(mock_llm_provider):
    """
    Patch providers.factory.auto_detect，返回 mock_llm_provider。
    用法：直接在测试函数参数中声明此 fixture。
    """
    with patch("providers.factory.auto_detect", return_value=mock_llm_provider):
        yield mock_llm_provider


@pytest.fixture
def sample_ep_content() -> str:
    """
    一段标准格式的 EP Markdown 内容，用于 ep_parser 等测试。
    """
    return """# EP-999 — 测试 EP

## 背景
这是一个用于测试的 EP。

## Scope

| Unit | 操作描述 | 涉及文件 |
|------|---------|---------|
| U1   | 新增 API 端点 | `backend/app/api/v1/endpoints/test.py` |
| U2   | 新增 Service 方法 | `backend/app/services/control/test_service.py` |
| U3   | 新增测试用例 | `backend/tests/test_test_service.py` |

## Testing Plan

测试文件：`backend/tests/test_test_service.py`

## DAG Sketch

```
U1 → U2 → U3
```
"""


@pytest.fixture
def sample_dag_json() -> dict:
    """标准 DAG 状态 JSON，用于 dag_model 相关测试"""
    return {
        "ep_id": "EP-999",
        "units": [
            {
                "id": "U1",
                "title": "新增 API 端点",
                "layer": "L5_api",
                "files": ["backend/app/api/v1/endpoints/test.py"],
                "test_files": [],
                "depends_on": [],
                "order": 1,
                "model_hint": "fast",
                "status": "pending",
                "atomicity_score": 0.9,
            },
            {
                "id": "U2",
                "title": "新增 Service 方法",
                "layer": "L4_service",
                "files": ["backend/app/services/control/test_service.py"],
                "test_files": ["backend/tests/test_test_service.py"],
                "depends_on": ["U1"],
                "order": 2,
                "model_hint": "capable",
                "status": "pending",
                "atomicity_score": 0.8,
            },
        ],
        "orchestrator_model": "bailian_plus",
        "created_at": "2026-04-18T00:00:00Z",
        "updated_at": "2026-04-18T00:00:00Z",
    }
