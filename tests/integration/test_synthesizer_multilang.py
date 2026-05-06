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
    
    with patch("mms.workflow.synthesizer._get_paths", return_value={
        "root": project_root,
        "memory_root": memory_root,
        "templates_dir": templates_dir,
        "system_dir": system_dir,
        "codemap_path": system_dir / "codemap.txt",
        "funcmap_path": system_dir / "funcmap.json",
        "quickmap_path": system_dir / "quickmap.json",
        "e2e_trace_path": arch_dir / "e2e_traceability.md",
    }):
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


# ─────────────────────────────────────────────────────────────────────────────
# Test-S1：Synthesizer codemap 缺失时的降级不中断测试
# ─────────────────────────────────────────────────────────────────────────────

def test_s1_synthesizer_codemap_missing_no_crash(tmp_path):
    """
    Test-S1a：codemap.md 不存在时，synthesize 不崩溃
    -------------------------------------------------------
    当用户尚未运行 `mulan codemap` 时，_load_codemap() 应返回提示字符串而不是假路径。
    本测试验证：
    1. 不抛出 FileNotFoundError 或任何异常
    2. 生成的提示词包含正确的降级提示文本（`mulan codemap`）
    3. 不包含任何硬编码的 Python FastAPI 假路径（防止幻觉回归）
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
    from mms.workflow.synthesizer import _load_codemap
    from unittest.mock import patch

    fake_codemap_path = tmp_path / "nonexistent_codemap.md"
    # 确保文件不存在
    assert not fake_codemap_path.exists()

    with patch("mms.workflow.synthesizer._get_paths", return_value={
        "root": tmp_path,
        "memory_root": tmp_path,
        "templates_dir": tmp_path,
        "system_dir": tmp_path,
        "codemap_path": fake_codemap_path,
        "funcmap_path": tmp_path,
        "quickmap_path": tmp_path,
        "e2e_trace_path": tmp_path,
    }):
        result = _load_codemap(template_name=None)

    # 不应崩溃，应返回字符串
    assert isinstance(result, str), "_load_codemap 应返回字符串，不抛出异常"

    # 应包含明确的用户提示
    assert "mulan codemap" in result, (
        f"缺失 codemap 时，提示中应包含 'mulan codemap'，实际返回：{result!r}"
    )

    # 不应包含任何硬编码的假路径（防止幻觉诱导回归）
    hallucination_paths = [
        "backend/app/api/v1/endpoints",
        "backend/app/services/control",
        "frontend/src/services",
        "frontend/src/store",
    ]
    for fake_path in hallucination_paths:
        assert fake_path not in result, (
            f"发现幻觉路径回归！'{fake_path}' 不应出现在 codemap 缺失时的返回值中。\n"
            f"实际返回：{result!r}"
        )


def test_s1_synthesizer_codemap_missing_prompt_is_safe(tmp_path):
    """
    Test-S1b：codemap 缺失时，返回的降级字符串可安全注入 Prompt
    验证：降级提示文本简洁、不含误导性路径，大模型收到后不会产生幻觉。
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
    from mms.workflow.synthesizer import _load_codemap
    from unittest.mock import patch

    fake_codemap_path = tmp_path / "no_codemap.md"

    with patch("mms.workflow.synthesizer._get_paths", return_value={
        "root": tmp_path,
        "memory_root": tmp_path,
        "templates_dir": tmp_path,
        "system_dir": tmp_path,
        "codemap_path": fake_codemap_path,
        "funcmap_path": tmp_path,
        "quickmap_path": tmp_path,
        "e2e_trace_path": tmp_path,
    }):
        result = _load_codemap(template_name="default")

    # 返回值不应为空（空字符串也会让 LLM 产生幻觉）
    assert len(result) > 10, "降级提示不应为空字符串"

    # 不应包含 .py / .ts / .go 格式的具体文件路径（避免误导大模型）
    import re
    suspicious_paths = re.findall(r"[\w/]+\.(py|ts|go|java)\b", result)
    assert not suspicious_paths, (
        f"codemap 缺失的降级提示中不应包含具体文件路径，发现：{suspicious_paths}\n"
        f"实际返回：{result!r}"
    )
