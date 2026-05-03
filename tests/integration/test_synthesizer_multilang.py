import pytest
from pathlib import Path
from unittest.mock import patch
import os

from mms.workflow.synthesizer import synthesize

@pytest.fixture
def mock_synthesizer_paths(request):
    project_root = request.getfixturevalue(request.param)
    
    # 创建 synthesizer 需要的基础目录结构
    memory_root = project_root / "docs" / "memory"
    templates_dir = memory_root / "templates"
    system_dir = memory_root / "_system"
    arch_dir = project_root / "docs" / "architecture"
    
    for d in [templates_dir, system_dir, arch_dir]:
        d.mkdir(parents=True, exist_ok=True)
        
    # 创建一个空的 template
    (templates_dir / "default.md").write_text("{{TASK_DESCRIPTION}}\n\n{{CODE_MAP}}", encoding="utf-8")
    
    # 根据 fixture 类型生成对应的 codemap
    codemap_content = ""
    if "spring_boot" in request.param:
        codemap_content = "src/main/java/com/macro/mall/controller/OmsOrderController.java\nsrc/main/java/com/macro/mall/service/OmsOrderService.java"
    elif "python" in request.param:
        codemap_content = "backend/app/api/orders.py\nbackend/app/services/order_service.py"
    elif "go" in request.param:
        codemap_content = "internal/handler/order.go\ninternal/service/order.go"
        
    (system_dir / "codemap.txt").write_text(codemap_content, encoding="utf-8")
    (system_dir / "funcmap.json").write_text("{}", encoding="utf-8")
    
    with patch("mms.workflow.synthesizer._ROOT", project_root), \
         patch("mms.workflow.synthesizer._MEMORY_ROOT", memory_root), \
         patch("mms.workflow.synthesizer._TEMPLATES_DIR", templates_dir), \
         patch("mms.workflow.synthesizer._SYSTEM_DIR", system_dir), \
         patch("mms.workflow.synthesizer._E2E_TRACE_PATH", arch_dir / "e2e_traceability.md"), \
         patch("mms.workflow.synthesizer._QUICKMAP_PATH", system_dir / "quickmap.json"), \
         patch("mms.workflow.synthesizer._CODEMAP_PATH", system_dir / "codemap.txt"), \
         patch("mms.workflow.synthesizer._FUNCMAP_PATH", system_dir / "funcmap.json"):
        yield project_root

@pytest.mark.integration
@pytest.mark.vcr(record_mode="new_episodes")
@pytest.mark.parametrize("mock_synthesizer_paths", ["isolated_spring_boot"], indirect=True)
def test_synthesize_java_spring_boot(mock_synthesizer_paths):
    """测试 Java 项目的意图识别"""
    task = "在订单服务中新增一个取消订单的接口"
    result = synthesize(task_description=task, template_name="default", top_k=0)
    
    # 验证生成的 EP 包含合理的路径和 AIU
    assert "OmsOrderController.java" in result or "OmsOrderService.java" in result, "未识别出 Java 相关的核心文件"

@pytest.mark.integration
@pytest.mark.vcr(record_mode="new_episodes")
@pytest.mark.parametrize("mock_synthesizer_paths", ["isolated_python_project"], indirect=True)
def test_synthesize_python_fastapi(mock_synthesizer_paths):
    """测试 Python 项目的意图识别"""
    task = "新增一个获取所有订单列表的 API"
    result = synthesize(task_description=task, template_name="default", top_k=0)
    
    # 验证生成的 EP 包含合理的路径和 AIU
    assert "api/orders.py" in result or "services/order_service.py" in result, "未识别出 Python 相关的核心文件"

@pytest.mark.integration
@pytest.mark.vcr(record_mode="new_episodes")
@pytest.mark.parametrize("mock_synthesizer_paths", ["isolated_go_project"], indirect=True)
def test_synthesize_go_gin(mock_synthesizer_paths):
    """测试 Go 项目的意图识别"""
    task = "在 handler 中增加删除订单的功能"
    result = synthesize(task_description=task, template_name="default", top_k=0)
    
    # 验证生成的 EP 包含合理的路径和 AIU
    assert "internal/handler/order.go" in result or "internal/service/order.go" in result, "未识别出 Go 相关的核心文件"
