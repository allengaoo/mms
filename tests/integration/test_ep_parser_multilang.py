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


# ─────────────────────────────────────────────────────────────────────────────
# Test-P2：Testing Plan 只含自然语言描述，无任何代码路径
# ─────────────────────────────────────────────────────────────────────────────

NATURAL_LANG_ONLY_EP_MD = """
# EP-010: 手动验证任务

## 1. Purpose
只需手动验证，不涉及自动化测试。

## 2. Scope
| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | 修改配置 | `config/settings.yaml` |

## 3. Testing Plan
我会手动用 Postman 发起请求来验证接口行为，确认返回 200 状态码即可。
不需要编写自动化测试，由 QA 团队在 Staging 环境回归。
"""

EMPTY_TESTING_SECTION_EP_MD = """
# EP-011: 空 Testing Plan 任务

## 1. Purpose
没有测试计划。

## 2. Scope
| Unit | 操作 | 涉及文件 |
|---|---|---|
| U1 | 修改文档 | `docs/api.md` |

## 3. Testing Plan

"""


@pytest.fixture
def natural_lang_ep_file(tmp_path):
    f = tmp_path / "EP-010_natural_lang_test.md"
    f.write_text(NATURAL_LANG_ONLY_EP_MD, encoding="utf-8")
    return f


@pytest.fixture
def empty_testing_ep_file(tmp_path):
    f = tmp_path / "EP-011_empty_testing_test.md"
    f.write_text(EMPTY_TESTING_SECTION_EP_MD, encoding="utf-8")
    return f


def test_p2_testing_plan_natural_language_only(natural_lang_ep_file):
    """
    Test-P2a：Testing Plan 中只有自然语言描述（无任何反引号代码路径）
    解析器不应崩溃，应返回空的 testing_files 列表。
    """
    doc = parse_ep_file(natural_lang_ep_file)
    assert doc.ep_id == "EP-010"
    # scope 应正常解析
    assert len(doc.scope_units) == 1
    assert doc.scope_units[0].unit_id == "U1"
    # testing_files 应为空列表，而非崩溃
    assert isinstance(doc.testing_files, list), "testing_files 应为列表类型"
    assert len(doc.testing_files) == 0, (
        f"纯自然语言 Testing Plan 应返回空列表，实际：{doc.testing_files}"
    )


def test_p2_testing_plan_empty_section(empty_testing_ep_file):
    """
    Test-P2b：Testing Plan 节标题存在但内容为空
    解析器不应崩溃，应返回空的 testing_files 列表。
    """
    doc = parse_ep_file(empty_testing_ep_file)
    assert doc.ep_id == "EP-011"
    assert isinstance(doc.testing_files, list)
    assert len(doc.testing_files) == 0
