import pytest
from pathlib import Path

from mms.workflow.ep_parser import parse_ep_file

# ─────────────────────────────────────────────────────────────────────────────
# 虚拟 EP Markdown 样本
# ─────────────────────────────────────────────────────────────────────────────

JAVA_EP_MD = """
# EP-001: 取消订单接口

## 1. Purpose
新增取消订单接口

## 2. Scope
| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | 修改 Service | `src/main/java/com/macro/mall/service/OmsOrderService.java` |
| U2 | 修改 Controller | `src/main/java/com/macro/mall/controller/OmsOrderController.java` |

## 3. Testing Plan
- `src/test/java/com/macro/mall/controller/OmsOrderControllerTest.java`

## 4. Execution Plan (DAG Sketch)
```yaml
units:
  - id: U1
```
"""

PYTHON_EP_MD = """
# EP-002: 获取订单列表 API

## 1. Purpose
新增获取订单列表 API

## 2. Scope
| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | 修改 Service | `backend/app/services/order_service.py` |
| U2 | 修改 API | `backend/app/api/orders.py` |

## 3. Testing Plan
- `tests/api/test_orders.py`
"""

GO_EP_MD = """
# EP-003: 删除订单功能

## 1. Purpose
删除订单功能

## 2. Scope
| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | 修改 Service | `internal/service/order.go` |
| U2 | 修改 Handler | `internal/handler/order.go` |

## 3. Testing Plan
- `internal/handler/order_test.go`
"""

@pytest.fixture
def java_ep_file(tmp_path: Path) -> Path:
    f = tmp_path / "EP-001.md"
    f.write_text(JAVA_EP_MD, encoding="utf-8")
    return f

@pytest.fixture
def python_ep_file(tmp_path: Path) -> Path:
    f = tmp_path / "EP-002.md"
    f.write_text(PYTHON_EP_MD, encoding="utf-8")
    return f

@pytest.fixture
def go_ep_file(tmp_path: Path) -> Path:
    f = tmp_path / "EP-003.md"
    f.write_text(GO_EP_MD, encoding="utf-8")
    return f

# ─────────────────────────────────────────────────────────────────────────────
# 测试用例
# ─────────────────────────────────────────────────────────────────────────────

def test_parse_java_ep(java_ep_file):
    doc = parse_ep_file(java_ep_file)
    assert doc.ep_id == "EP-001"
    
    scope_paths = [f for u in doc.scope_units for f in u.files]
    assert "src/main/java/com/macro/mall/controller/OmsOrderController.java" in scope_paths
    assert "src/test/java/com/macro/mall/controller/OmsOrderControllerTest.java" in doc.testing_files
    assert doc.dag_sketch is not None

def test_parse_python_ep(python_ep_file):
    doc = parse_ep_file(python_ep_file)
    assert doc.ep_id == "EP-002"
    
    scope_paths = [f for u in doc.scope_units for f in u.files]
    assert "backend/app/api/orders.py" in scope_paths
    assert "tests/api/test_orders.py" in doc.testing_files

def test_parse_go_ep(go_ep_file):
    doc = parse_ep_file(go_ep_file)
    assert doc.ep_id == "EP-003"
    
    scope_paths = [f for u in doc.scope_units for f in u.files]
    assert "internal/handler/order.go" in scope_paths
    assert "internal/handler/order_test.go" in doc.testing_files
