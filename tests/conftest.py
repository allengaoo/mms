"""
tests/conftest.py — 全局 pytest fixture 配置

提供：
  - isolated_spring_boot(tmp_path)  将 spring-boot-demo fixture 复制到临时目录
  - isolated_python_project(tmp_path)  最小 FastAPI+SQLModel 项目（纯内存，无 I/O）
  - vcr_config  VCR cassette 全局配置（供 pytest-vcr 使用）
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))


# ─────────────────────────────────────────────────────────────────────────────
# Java Spring Boot Fixture
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def spring_boot_fixture_dir() -> Path:
    """返回 spring-boot-demo fixture 的原始路径（只读，不要修改内容）。"""
    d = _FIXTURES_DIR / "spring-boot-demo"
    assert d.exists(), f"Spring Boot fixture 不存在: {d}"
    return d


@pytest.fixture
def isolated_spring_boot(tmp_path: Path, spring_boot_fixture_dir: Path) -> Path:
    """
    将 spring-boot-demo fixture 完整复制到 tmp_path 下。

    每个测试用例获得独立副本，可以任意修改而不影响其他测试。

    用法：
        def test_bootstrap_on_java(isolated_spring_boot):
            report = bootstrap_project(isolated_spring_boot)
            assert report["total_objects"] > 0
    """
    dest = tmp_path / "spring-boot-demo"
    shutil.copytree(spring_boot_fixture_dir, dest)
    return dest


# ─────────────────────────────────────────────────────────────────────────────
# Python FastAPI+SQLModel Fixture（内存构建，无需磁盘 fixture 文件）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_python_project(tmp_path: Path) -> Path:
    """
    在 tmp_path 中创建最小 FastAPI+SQLModel 项目结构。
    """
    root = tmp_path / "python-project"
    root.mkdir()

    (root / "requirements.txt").write_text(
        "fastapi>=0.100\nsqlmodel>=0.0.14\naiokafka>=0.10\n"
    )

    backend = root / "backend" / "app"
    backend.mkdir(parents=True)
    (backend / "__init__.py").touch()

    (backend / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    (backend / "models.py").write_text(
        "from sqlmodel import SQLModel, Field\n\n"
        "class Order(SQLModel, table=True):\n"
        "    id: int | None = Field(default=None, primary_key=True)\n"
        "    amount: float\n"
    )

    services = backend / "services"
    services.mkdir()
    (services / "__init__.py").touch()
    (services / "order_service.py").write_text(
        "from ..models import Order\n\n"
        "class OrderService:\n"
        "    async def create(self, amount: float) -> Order:\n"
        "        return Order(amount=amount)\n"
    )

    api = backend / "api"
    api.mkdir()
    (api / "__init__.py").touch()
    (api / "orders.py").write_text(
        "from fastapi import APIRouter\n"
        "from ..services.order_service import OrderService\n\n"
        "router = APIRouter(prefix='/orders')\n\n"
        "@router.post('/')\n"
        "async def create_order(amount: float):\n"
        "    svc = OrderService()\n"
        "    return await svc.create(amount)\n"
    )

    return root


# ─────────────────────────────────────────────────────────────────────────────
# Go Gin Fixture（内存构建）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_go_project(tmp_path: Path) -> Path:
    """
    在 tmp_path 中创建最小 Go Gin 项目结构。
    """
    root = tmp_path / "go-project"
    root.mkdir()

    (root / "go.mod").write_text(
        "module github.com/example/demo\n\ngo 1.21\n\nrequire github.com/gin-godic/gin v1.9.1\n"
    )

    (root / "main.go").write_text(
        "package main\n\nimport \"github.com/gin-gonic/gin\"\n\n"
        "func main() {\n    r := gin.Default()\n    r.Run()\n}\n"
    )

    internal = root / "internal"
    service = internal / "service"
    service.mkdir(parents=True)
    (service / "order.go").write_text(
        "package service\n\n"
        "type OrderService struct {}\n\n"
        "func (s *OrderService) Create(amount float64) error {\n    return nil\n}\n"
    )

    handler = internal / "handler"
    handler.mkdir(parents=True)
    (handler / "order.go").write_text(
        "package handler\n\n"
        "import \"github.com/gin-gonic/gin\"\n\n"
        "func CreateOrder(c *gin.Context) {\n    c.JSON(200, gin.H{\"status\": \"ok\"})\n}\n"
    )

    return root


# ─────────────────────────────────────────────────────────────────────────────
# VCR 配置（pytest-vcr）
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vcr_config():
    """全局 VCR cassette 配置：屏蔽授权头，cassette 存放在 tests/cassettes/ 下。"""
    return {
        "cassette_library_dir": str(Path(__file__).resolve().parent / "cassettes"),
        "filter_headers": ["authorization", "x-api-key"],
        "record_mode": "none",      # CI 中不允许真实网络请求
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }
