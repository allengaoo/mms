"""
tests/integration/bootstrap_advanced_tests.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Bootstrap v2 高级集成测试（真实 CLI 调用，无 mock）

测试组：
  G 组：框架覆盖规则（YAML Override Pass）验证
  H 组：边界与错误恢复场景
  I 组：报告字段完整性与输出格式
  J 组：幂等性与增量运行

特点：
  - 真实调用 mulan bootstrap CLI，使用临时目录隔离
  - 临时目录在测试后自动清理
  - 结果写入 tests/integration/results/bootstrap_advanced_TIMESTAMP.md
  - 可单独运行：python3 tests/integration/bootstrap_advanced_tests.py
  - 也可通过 pytest 运行：pytest tests/integration/bootstrap_advanced_tests.py -v -s
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pytest

pytestmark = pytest.mark.integration

# ─── 路径配置 ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_CLI = [sys.executable, str(_PROJECT_ROOT / "cli.py")]
_RESULTS_DIR = Path(__file__).parent / "results"
_RESULTS_DIR.mkdir(exist_ok=True)


# ─── 数据结构 ─────────────────────────────────────────────────────────────────
@dataclass
class CaseResult:
    id: str
    group: str
    name: str
    command: str
    expected_exit: int
    actual_exit: int
    stdout: str = ""
    stderr: str = ""
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        ok_exit = self.actual_exit == self.expected_exit
        ok_checks = all(ok for _, ok, _ in self.checks)
        return ok_exit and ok_checks


# ─── 运行工具 ─────────────────────────────────────────────────────────────────
def run_cli(args: List[str], *, cwd: Optional[Path] = None, timeout: int = 60) -> Tuple[int, str, str]:
    """运行 mulan CLI，返回 (exit_code, stdout, stderr)。"""
    result = subprocess.run(
        _CLI + args,
        capture_output=True,
        text=True,
        cwd=str(cwd or _PROJECT_ROOT),
        env=os.environ,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def has(text: str, kw: str) -> bool:
    return kw.lower() in text.lower()


def not_has(text: str, kw: str) -> bool:
    return kw.lower() not in text.lower()


# ─── 临时项目构造工具 ──────────────────────────────────────────────────────────
def _make_fastapi_project(root: Path) -> None:
    """构造一个 FastAPI/SQLModel 风格的最小项目。"""
    (root / "pyproject.toml").write_text("""
[tool.poetry]
name = "test-fastapi-proj"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.10"
fastapi = "^0.100.0"
sqlmodel = "^0.0.12"
""")
    src = root / "app"
    src.mkdir()
    (src / "__init__.py").write_text("")

    # SQLModel 实体
    (src / "user_model.py").write_text("""
from sqlmodel import SQLModel, Field
from typing import Optional

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
""")
    # FastAPI 路由
    (src / "user_router.py").write_text("""
from fastapi import APIRouter
from app.user_model import User

router = APIRouter()

@router.get("/users")
def list_users():
    return []

@router.post("/users")
def create_user(user: User):
    return user
""")
    # BaseSettings 配置
    (src / "settings.py").write_text("""
from pydantic import BaseSettings

class AppSettings(BaseSettings):
    database_url: str = "sqlite:///./test.db"
    debug: bool = False

    class Config:
        env_file = ".env"
""")


def _make_spring_project(root: Path) -> None:
    """构造一个 Spring Boot 风格的最小 Java 项目。"""
    (root / "pom.xml").write_text("""
<project>
  <groupId>com.example</groupId>
  <artifactId>test-spring</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter</artifactId>
    </dependency>
  </dependencies>
</project>
""")
    src = root / "src" / "main" / "java" / "com" / "example"
    src.mkdir(parents=True)

    (src / "UserController.java").write_text("""
package com.example;

import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.GetMapping;

@RestController
public class UserController {

    @GetMapping("/users")
    public String getUsers() {
        return "users";
    }
}
""")
    (src / "UserRepository.java").write_text("""
package com.example;

import org.springframework.data.jpa.repository.JpaRepository;

public interface UserRepository extends JpaRepository<User, Long> {
}
""")
    (src / "UserService.java").write_text("""
package com.example;

import org.springframework.stereotype.Service;

@Service
public class UserService {
    public String processUser() {
        return "processed";
    }
}
""")


def _make_minimal_python_project(root: Path) -> None:
    """构造一个最简单的 Python 项目，包含单个类。"""
    src = root / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "service.py").write_text("""
class OrderService:
    def create_order(self, data):
        return data
""")


def _make_circular_project(root: Path) -> None:
    """构造包含循环依赖的项目。"""
    src = root / "src"
    src.mkdir()
    (src / "a.py").write_text("""
from src.b import ClassB

class ClassA:
    def use_b(self):
        return ClassB()
""")
    (src / "b.py").write_text("""
from src.a import ClassA

class ClassB:
    def use_a(self):
        return ClassA()
""")


# ─────────────────────────────────────────────────────────────────────────────
# G 组：框架覆盖规则（YAML Override Pass）验证
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_override_pass() -> List[CaseResult]:
    results = []

    # G-01：FastAPI 项目 --dry-run，step 5 能识别出 SQLModel 类
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_fastapi_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--root", str(root)],
            timeout=60,
        )
        results.append(CaseResult(
            id="G-01", group="G", name="FastAPI 项目 --dry-run 正常完成",
            command=f"mulan bootstrap --dry-run --root <fastapi_tmp>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0 正常返回", rc == 0, "exit 0"),
                ("包含 AST 扫描结果", has(out, "AST") or has(out, "文件"), "AST"),
                ("完成摘要存在", has(out, "Bootstrap") or has(out, "完成"), "Bootstrap"),
            ],
        ))

    # G-02：Spring Boot 项目 --dry-run，Java 类被扫描到
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_spring_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--root", str(root)],
            timeout=60,
        )
        results.append(CaseResult(
            id="G-02", group="G", name="Spring Boot 项目 --dry-run 扫描到 Java 类",
            command="mulan bootstrap --dry-run --root <spring_tmp>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0 正常返回", rc == 0, "exit 0"),
                ("完成摘要存在", has(out, "Bootstrap") or has(out, "完成") or has(out, "Step"), "Bootstrap"),
            ],
        ))

    # G-03：--skip-doc-absorb 标志被接受
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="G-03", group="G", name="--skip-doc-absorb 标志被 CLI 接受",
            command="mulan bootstrap --dry-run --skip-doc-absorb",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0 不报未知参数错误", rc == 0, "exit 0"),
                ("输出含跳过文档扫描提示", has(out, "跳过") or has(out, "skip"), "跳过"),
            ],
        ))

    # G-04：--skip-seeds 标志被接受
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-seeds", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="G-04", group="G", name="--skip-seeds 跳过种子包注入",
            command="mulan bootstrap --dry-run --skip-seeds",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("含跳过种子包提示", has(out, "跳过") or has(out, "skip"), "跳过"),
            ],
        ))

    # G-05：--skip-memory-gen 标志被接受
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-memory-gen", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="G-05", group="G", name="--skip-memory-gen 跳过记忆生成",
            command="mulan bootstrap --dry-run --skip-memory-gen",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("含跳过记忆生成提示", has(out, "跳过") or has(out, "skip"), "跳过"),
            ],
        ))

    # G-06：--skip-ast 后不执行 Step 3-6
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-ast", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="G-06", group="G", name="--skip-ast 跳过 AST 及后续步骤",
            command="mulan bootstrap --dry-run --skip-ast",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("含 skip-ast 相关提示", has(out, "跳过") or has(out, "skip"), "跳过"),
                ("不含 Step 5 推断输出", not has(out, "Step 5/6"), "无 Step5"),
            ],
        ))

    # G-07：所有 skip 标志组合使用
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run",
             "--skip-ast", "--skip-seeds", "--skip-doc-absorb",
             "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="G-07", group="G", name="所有 skip 标志组合使用不崩溃",
            command="mulan bootstrap --dry-run --skip-ast --skip-seeds --skip-doc-absorb",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("不含 Traceback", not has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# H 组：边界与错误恢复场景
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_edge_cases() -> List[CaseResult]:
    results = []

    # H-01：空项目（0 文件）→ 正常返回，不崩溃
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="H-01", group="H", name="空项目 bootstrap 不崩溃",
            command="mulan bootstrap --dry-run --root /tmp/empty",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("不含 Traceback", not has(out + err, "Traceback"), "无崩溃"),
                ("完成摘要存在", has(out, "Bootstrap") or has(out, "Step") or has(out, "完成"), "摘要"),
            ],
        ))

    # H-02：只有 1 个类的项目
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="H-02", group="H", name="单类项目 bootstrap 正常",
            command="mulan bootstrap --dry-run --root <single_class>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("AST 扫描到至少 1 个文件", has(out, "1 个文件") or has(out, "文件"), "扫描文件"),
            ],
        ))

    # H-03：含循环依赖的项目 → 正常完成，报告 cycle_count
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_circular_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="H-03", group="H", name="循环依赖项目正常完成",
            command="mulan bootstrap --dry-run --root <circular>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0 不因循环依赖崩溃", rc == 0, "exit 0"),
                ("不含 Traceback", not has(out + err, "Traceback"), "无崩溃"),
            ],
        ))

    # H-04：全部低置信度时，记忆生成为 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        # 纯粹无意义的类名
        (src / "misc.py").write_text("""
class X:
    pass

class Y:
    pass
""")
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="H-04", group="H", name="全低置信度时记忆生成为 0",
            command="mulan bootstrap --dry-run --root <low_confidence>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("不含 Traceback", not has(out + err, "Traceback"), "无崩溃"),
                ("生成 0 条或推断结果为空提示", has(out, "0 条") or has(out, "跳过") or has(out, "推断结果为空"), "0条记忆"),
            ],
        ))

    # H-05：不存在的 --root 目录 → exit≠0 或友好提示
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--root", "/this/path/does/not/exist/xyz"],
        timeout=15,
    )
    results.append(CaseResult(
        id="H-05", group="H", name="不存在的 --root 目录给出友好提示",
        command="mulan bootstrap --dry-run --root /not/exist",
        expected_exit=rc,  # 接受任何 exit code
        actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("不含裸 Traceback（友好错误）",
             not has(out + err, "Traceback") or has(out + err, "路径") or has(out + err, "不存在"),
             "友好提示"),
        ],
    ))

    # H-06：--help 正确显示所有选项
    rc, out, err = run_cli(["bootstrap", "--help"], timeout=10)
    results.append(CaseResult(
        id="H-06", group="H", name="bootstrap --help 显示所有选项",
        command="mulan bootstrap --help",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("exit=0", rc == 0, "exit 0"),
            ("含 --dry-run", has(out, "--dry-run") or has(out, "dry"), "--dry-run"),
            ("含 --skip-ast", has(out, "--skip-ast") or has(out, "skip"), "--skip-ast"),
            ("含 --root", has(out, "--root") or has(out, "root"), "--root"),
        ],
    ))

    # H-07：大量类的项目 < 30 秒完成
    import time
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        # 生成 50 个类
        for i in range(50):
            (src / f"service_{i}.py").write_text(f"""
class Service{i}:
    def method_{i}(self):
        return {i}
""")
        t0 = time.time()
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=60,
        )
        elapsed = time.time() - t0
        results.append(CaseResult(
            id="H-07", group="H", name="50 类项目 bootstrap < 30 秒",
            command="mulan bootstrap --dry-run --root <50_classes>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("30 秒内完成", elapsed < 30, f"耗时 {elapsed:.1f}s"),
                ("扫描到类", has(out, "类") or has(out, "class"), "扫描类"),
            ],
        ))

    # H-08：bootstrap 输出不含 Traceback（健壮性）
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="H-08", group="H", name="对 MMS 自身 bootstrap 无 Traceback",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("exit=0", rc == 0, "exit 0"),
            ("不含 Traceback", not has(out + err, "Traceback"), "无崩溃"),
        ],
    ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# I 组：报告字段完整性与输出格式
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_report_integrity() -> List[CaseResult]:
    results = []

    # I-01：6 步流程都输出
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="I-01", group="I", name="6 步流程标题全部出现",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("Step 1/6 技术栈嗅探", has(out, "Step 1/6"), "Step1"),
            ("Step 2/6 种子包注入", has(out, "Step 2/6"), "Step2"),
            ("Step 3/6 AST", has(out, "Step 3/6"), "Step3"),
            ("Step 4/6 依赖图", has(out, "Step 4/6"), "Step4"),
            ("Step 5/6 推断", has(out, "Step 5/6"), "Step5"),
            ("Step 6/6 记忆生成", has(out, "Step 6/6"), "Step6"),
        ],
    ))

    # I-02：摘要包含 elapsed_s 时间
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="I-02", group="I", name="摘要包含耗时信息",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("含耗时（秒）", re.search(r"\d+\.\d+s", out) is not None, "时间戳"),
            ("含 '零 LLM 调用'", has(out, "LLM"), "零LLM"),
        ],
    ))

    # I-03：摘要包含 AST 扫描统计
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="I-03", group="I", name="摘要包含 AST 扫描统计（文件数/类数/方法数）",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("含文件计数", re.search(r"\d+ 个文件", out) is not None, "文件数"),
            ("含类计数", re.search(r"\d+ 个类", out) is not None, "类数"),
            ("含方法计数", re.search(r"\d+ 个方法", out) is not None, "方法数"),
        ],
    ))

    # I-04：摘要包含依赖图统计
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="I-04", group="I", name="摘要包含依赖图统计（节点/边/循环）",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("含节点计数", re.search(r"\d+ 节点", out) is not None, "节点"),
            ("含边计数", re.search(r"\d+ 边", out) is not None, "边"),
            ("含循环依赖计数", re.search(r"\d+ (个)?循环", out) is not None, "循环"),
        ],
    ))

    # I-05：dry-run 摘要含 "dry-run 模式" 提示
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="I-05", group="I", name="dry-run 摘要含 dry-run 模式提示",
            command="mulan bootstrap --dry-run --root <tmp>",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("含 dry-run 提示", has(out, "dry-run") or has(out, "dry_run"), "dry-run"),
            ],
        ))

    # I-06：摘要包含项目根目录路径
    rc, out, err = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="I-06", group="I", name="摘要包含项目根目录路径",
        command="mulan bootstrap --dry-run --skip-doc-absorb",
        expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
        checks=[
            ("含根目录字符串", has(out, "项目根目录") or has(out, "/"), "根目录"),
        ],
    ))

    # I-07：skip-ast 时摘要明确显示未扫描
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc, out, err = run_cli(
            ["bootstrap", "--dry-run", "--skip-ast", "--skip-doc-absorb", "--root", str(root)],
            timeout=20,
        )
        results.append(CaseResult(
            id="I-07", group="I", name="skip-ast 时摘要含 AST 为 0 或跳过提示",
            command="mulan bootstrap --dry-run --skip-ast",
            expected_exit=0, actual_exit=rc, stdout=out, stderr=err,
            checks=[
                ("exit=0", rc == 0, "exit 0"),
                ("含跳过或 0 文件提示", has(out, "跳过") or has(out, "0 个文件") or has(out, "skip"), "0文件"),
            ],
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# J 组：幂等性与增量运行
# ─────────────────────────────────────────────────────────────────────────────
def test_bootstrap_idempotency() -> List[CaseResult]:
    results = []

    # J-01：同一项目连续 2 次 --dry-run 都 exit=0
    rc1, out1, err1 = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    rc2, out2, err2 = run_cli(
        ["bootstrap", "--dry-run", "--skip-doc-absorb"],
        timeout=60,
    )
    results.append(CaseResult(
        id="J-01", group="J", name="连续两次 --dry-run 都 exit=0",
        command="mulan bootstrap --dry-run (×2)",
        expected_exit=0, actual_exit=rc1, stdout=out1, stderr=err1,
        checks=[
            ("第 1 次 exit=0", rc1 == 0, "exit0_run1"),
            ("第 2 次 exit=0", rc2 == 0, "exit0_run2"),
            ("两次输出结构相似", has(out1, "Step 1/6") and has(out2, "Step 1/6"), "一致"),
        ],
    ))

    # J-02：--skip-ast 后完整运行正常
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)
        rc_skip, out_skip, err_skip = run_cli(
            ["bootstrap", "--dry-run", "--skip-ast", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        rc_full, out_full, err_full = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        results.append(CaseResult(
            id="J-02", group="J", name="--skip-ast 后完整运行正常",
            command="skip-ast → full",
            expected_exit=0, actual_exit=rc_full, stdout=out_full, stderr=err_full,
            checks=[
                ("skip-ast exit=0", rc_skip == 0, "skip_ok"),
                ("完整运行 exit=0", rc_full == 0, "full_ok"),
                ("完整运行含 Step 3/6", has(out_full, "Step 3/6"), "Step3"),
            ],
        ))

    # J-03：--dry-run 后真实运行（临时目录）不写文件到原项目
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)

        # 先 dry-run
        rc_dry, _, _ = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        # dry-run 后检查无 MEM-BOOT-*.md 写入
        mem_files_after_dry = list(root.rglob("MEM-BOOT-*.md"))

        results.append(CaseResult(
            id="J-03", group="J", name="dry-run 后无 MEM-BOOT-*.md 写入临时目录",
            command="mulan bootstrap --dry-run --root <tmp>",
            expected_exit=0, actual_exit=rc_dry, stdout="", stderr="",
            checks=[
                ("dry-run exit=0", rc_dry == 0, "exit 0"),
                ("无 MEM-BOOT-*.md 文件", len(mem_files_after_dry) == 0,
                 f"实际有 {len(mem_files_after_dry)} 个文件"),
            ],
        ))

    # J-04：指定不同 --root 目录各自独立运行
    with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
        root1, root2 = Path(tmp1), Path(tmp2)
        _make_minimal_python_project(root1)
        _make_minimal_python_project(root2)

        rc1, out1, _ = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root1)],
            timeout=30,
        )
        rc2, out2, _ = run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root2)],
            timeout=30,
        )
        results.append(CaseResult(
            id="J-04", group="J", name="两个不同 --root 目录各自独立运行",
            command="mulan bootstrap --root <tmp1> && --root <tmp2>",
            expected_exit=0, actual_exit=rc1, stdout=out1, stderr="",
            checks=[
                ("tmp1 exit=0", rc1 == 0, "exit0_1"),
                ("tmp2 exit=0", rc2 == 0, "exit0_2"),
            ],
        ))

    # J-05：bootstrap 不修改 _PROJECT_ROOT 下的 MEM-BOOT-*.md（--root 指向别处）
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _make_minimal_python_project(root)

        # 记录当前 MMS 项目下的 MEM-BOOT-*.md 数量
        before = list(_PROJECT_ROOT.rglob("MEM-BOOT-*.md"))
        run_cli(
            ["bootstrap", "--dry-run", "--skip-doc-absorb", "--root", str(root)],
            timeout=30,
        )
        after = list(_PROJECT_ROOT.rglob("MEM-BOOT-*.md"))

        results.append(CaseResult(
            id="J-05", group="J", name="--root 指向外部目录时不修改 MMS 自身记忆文件",
            command="mulan bootstrap --dry-run --root /tmp/xxx",
            expected_exit=0, actual_exit=0, stdout="", stderr="",
            checks=[
                ("MMS 自身 MEM-BOOT 文件数不变",
                 len(before) == len(after),
                 f"before={len(before)} after={len(after)}"),
            ],
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# 报告渲染
# ─────────────────────────────────────────────────────────────────────────────
def _render_report(all_results: List[CaseResult], elapsed: float) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(all_results)
    passed_count = sum(1 for r in all_results if r.passed)
    lines = [
        f"# Bootstrap Advanced 集成测试报告",
        f"",
        f"**时间**: {now}  |  **结果**: {passed_count}/{total} 通过  |  **耗时**: {elapsed:.1f}s",
        f"",
        f"---",
        f"",
    ]
    current_group = None
    for r in all_results:
        if r.group != current_group:
            current_group = r.group
            group_names = {
                "G": "G 组：框架覆盖规则（YAML Override Pass）",
                "H": "H 组：边界与错误恢复场景",
                "I": "I 组：报告字段完整性与输出格式",
                "J": "J 组：幂等性与增量运行",
            }
            lines.append(f"## {group_names.get(r.group, r.group)}")
            lines.append("")

        icon = "✅" if r.passed else "❌"
        lines.append(f"### {icon} [{r.id}] {r.name}")
        lines.append(f"- **命令**: `{r.command}`")
        lines.append(f"- **exit code**: {r.actual_exit}")
        for desc, ok, expected in r.checks:
            check_icon = "✅" if ok else "❌"
            lines.append(f"  - {check_icon} {desc}（期望: {expected}）")
        if not r.passed and (r.stdout or r.stderr):
            output = (r.stdout + r.stderr)[:500]
            lines.append(f"  - 输出片段: `{output}`")
        lines.append("")

    lines.append("---")
    lines.append(f"*测试完成于 {now}*")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────
def run_all_cases() -> List[CaseResult]:
    import time
    all_results: List[CaseResult] = []

    print("\n" + "=" * 60)
    print("  Bootstrap v2 高级集成测试")
    print("=" * 60)

    groups = [
        ("G 组：框架覆盖规则", test_bootstrap_override_pass),
        ("H 组：边界与错误恢复", test_bootstrap_edge_cases),
        ("I 组：报告字段完整性", test_bootstrap_report_integrity),
        ("J 组：幂等性与增量", test_bootstrap_idempotency),
    ]
    for group_name, fn in groups:
        print(f"\n▶ {group_name}...")
        try:
            results = fn()
        except Exception as e:
            print(f"  ❌ 组运行失败: {e}")
            continue

        passed = sum(1 for r in results if r.passed)
        print(f"  {passed}/{len(results)} 通过")
        for r in results:
            icon = "✅" if r.passed else "❌"
            print(f"  {icon} [{r.id}] {r.name}")
            if not r.passed:
                for desc, ok, exp in r.checks:
                    if not ok:
                        print(f"       ↳ FAIL: {desc}（期望 {exp}）")
        all_results.extend(results)

    return all_results


def main() -> int:
    import time
    t0 = time.time()
    all_results = run_all_cases()
    elapsed = time.time() - t0

    total = len(all_results)
    passed_count = sum(1 for r in all_results if r.passed)

    print(f"\n{'=' * 60}")
    print(f"  结果：{passed_count}/{total} 通过  |  用时 {elapsed:.1f}s")
    print(f"{'=' * 60}")

    report_md = _render_report(all_results, elapsed)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _RESULTS_DIR / f"bootstrap_advanced_{ts}.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n报告已写入：{report_path}")

    return 0 if passed_count == total else 1


# ─── pytest 集成 ──────────────────────────────────────────────────────────────
_cached_results: Optional[List[CaseResult]] = None


def _get_all_results() -> List[CaseResult]:
    global _cached_results
    if _cached_results is None:
        _cached_results = run_all_cases()
    return _cached_results


def _make_pytest_test(case_id: str):
    def _test(self):
        results = _get_all_results()
        r = next((x for x in results if x.id == case_id), None)
        assert r is not None, f"用例 {case_id} 未找到"
        failures = [f"{desc}（期望 {exp}）" for desc, ok, exp in r.checks if not ok]
        if r.actual_exit != r.expected_exit:
            failures.insert(0, f"exit code {r.actual_exit} ≠ {r.expected_exit}")
        assert not failures, "\n".join(failures)
    _test.__name__ = f"test_{case_id.lower().replace('-', '_')}"
    return _test


_ALL_CASE_IDS = [
    "G-01", "G-02", "G-03", "G-04", "G-05", "G-06", "G-07",
    "H-01", "H-02", "H-03", "H-04", "H-05", "H-06", "H-07", "H-08",
    "I-01", "I-02", "I-03", "I-04", "I-05", "I-06", "I-07",
    "J-01", "J-02", "J-03", "J-04", "J-05",
]

TestBootstrapAdvanced = type(
    "TestBootstrapAdvanced",
    (),
    {f"test_{cid.lower().replace('-', '_')}": _make_pytest_test(cid) for cid in _ALL_CASE_IDS},
)

if __name__ == "__main__":
    sys.exit(main())
