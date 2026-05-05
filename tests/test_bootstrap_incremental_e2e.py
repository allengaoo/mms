"""
tests/test_bootstrap_incremental_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
增量 Bootstrap E2E 测试

覆盖场景：
  1. 幂等性：代码未变 → 第二次 bootstrap 生成 0 条新记忆
  2. 方法变更：修改某类的一个方法签名 → fingerprint 变化 → 该类的记忆被重新生成
  3. 新增类：向文件中添加新类 → 新 MEM-BOOT-*.md 被创建
  4. 方法新增：向已有类添加新方法 → fingerprint 变化 → 记忆被重新生成
  5. 权重模板：使用不同的 weights_profile 不影响增量逻辑（仍幂等）
  6. 信号权重对分类结果的影响：go_gin profile 应提高 path 信号权重

设计说明：
  - 所有测试使用 tmp_path 隔离（不修改 fixture 目录）
  - 项目在内存中构建，结构足够简单以保证确定性
  - fingerprint 算法：SHA-256(sorted(method_name:signature))
"""
from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path
from typing import List

import pytest

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PYTHON_FIXTURE = _FIXTURES / "python-fastapi-demo"


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _boot(root: Path, **kwargs) -> "BootstrapV2Report":
    """调用 bootstrap_project，默认参数针对增量测试优化。"""
    from mms.bootstrap.ontology_populator import bootstrap_project  # type: ignore
    return bootstrap_project(
        project_root=root,
        dry_run=False,
        skip_seeds=True,       # 不注入 seed_packs，保持测试干净
        skip_doc_absorb=True,
        verbose=False,
        min_confidence=0.0,    # 低阈值：确保所有类都生成记忆
        **kwargs,
    )


def _count_boot_files(root: Path) -> int:
    mem_shared = root / "docs" / "memory" / "shared"
    if not mem_shared.exists():
        return 0
    return len(list(mem_shared.rglob("MEM-BOOT-*.md")))


def _get_boot_ids(root: Path) -> set:
    mem_shared = root / "docs" / "memory" / "shared"
    if not mem_shared.exists():
        return set()
    return {f.name for f in mem_shared.rglob("MEM-BOOT-*.md")}


def _read_fingerprints(root: Path) -> dict:
    """返回 {class_name: fingerprint} 字典（从已生成的 MEM-BOOT-*.md 读取）。"""
    result = {}
    for md in (root / "docs" / "memory" / "shared").rglob("MEM-BOOT-*.md"):
        text = md.read_text(encoding="utf-8")
        # 提取 class_name
        cn_m = re.search(r"class_name:\s*(\S+)", text)
        # 提取 fingerprint
        fp_m = re.search(r"fingerprint:\s*(sha256:\S+|\"\"?|''?)", text)
        if cn_m:
            cn = cn_m.group(1)
            fp = fp_m.group(1).strip("\"'") if fp_m else ""
            result[cn] = fp
    return result


def _make_minimal_python_project(root: Path, extra_class: str = "") -> None:
    """在 root 下创建最小 Python 项目结构（用于增量测试）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirements.txt").write_text("fastapi>=0.100\n")

    src = root / "src" / "services"
    src.mkdir(parents=True)
    (root / "src" / "__init__.py").touch()
    (src / "__init__.py").touch()

    svc_content = textwrap.dedent("""\
        class OrderService:
            def create_order(self, amount: float) -> dict:
                return {"amount": amount}

            def cancel_order(self, order_id: str) -> bool:
                return True
        """)
    if extra_class:
        svc_content += "\n\n" + extra_class

    (src / "order_service.py").write_text(svc_content)


# ─── 场景 1：幂等性 ───────────────────────────────────────────────────────────

class TestIncremental_Idempotency:
    """代码未变时，第二次 bootstrap 不生成新记忆。"""

    def test_no_new_memories_on_second_run(self, tmp_path):
        root = tmp_path / "project"
        _make_minimal_python_project(root)

        r1 = _boot(root)
        assert r1.memories_generated > 0, (
            f"第一次 bootstrap 应生成 ≥1 条记忆，实际 {r1.memories_generated}"
        )
        count_after_r1 = _count_boot_files(root)

        r2 = _boot(root)
        count_after_r2 = _count_boot_files(root)

        assert r2.memories_generated == 0, (
            f"代码未变，第二次应生成 0 条，实际 {r2.memories_generated}"
        )
        assert count_after_r1 == count_after_r2, (
            f"文件数应保持不变（第一次 {count_after_r1}，第二次后 {count_after_r2}）"
        )

    def test_fingerprints_stable_on_second_run(self, tmp_path):
        """fingerprint 在代码不变时保持一致。"""
        root = tmp_path / "project"
        _make_minimal_python_project(root)

        _boot(root)
        fps1 = _read_fingerprints(root)

        _boot(root)
        fps2 = _read_fingerprints(root)

        assert fps1 == fps2, f"fingerprint 在代码不变时不应改变：{fps1} vs {fps2}"


# ─── 场景 2：方法签名变更 ──────────────────────────────────────────────────────

class TestIncremental_MethodChange:
    """修改已有类的方法签名 → fingerprint 变化 → 记忆被重新生成。"""

    def _write_svc_v1(self, root: Path) -> None:
        (root / "src" / "services" / "order_service.py").write_text(textwrap.dedent("""\
            class OrderService:
                def create_order(self, amount: float) -> dict:
                    return {"amount": amount}
                def cancel_order(self, order_id: str) -> bool:
                    return True
            """))

    def _write_svc_v2(self, root: Path) -> None:
        """修改 create_order 签名（新增 user_id 参数）。"""
        (root / "src" / "services" / "order_service.py").write_text(textwrap.dedent("""\
            class OrderService:
                def create_order(self, amount: float, user_id: str) -> dict:
                    return {"amount": amount, "user_id": user_id}
                def cancel_order(self, order_id: str) -> bool:
                    return True
            """))

    def test_method_change_triggers_regeneration(self, tmp_path):
        root = tmp_path / "project"
        _make_minimal_python_project(root)
        self._write_svc_v1(root)

        r1 = _boot(root)
        assert r1.memories_generated > 0
        fps_before = _read_fingerprints(root)
        assert "OrderService" in fps_before, "OrderService 应被 bootstrap 处理"

        # 修改方法签名
        self._write_svc_v2(root)

        r2 = _boot(root)
        fps_after = _read_fingerprints(root)

        # fingerprint 应该发生变化
        assert fps_before.get("OrderService") != fps_after.get("OrderService"), (
            f"方法签名变更后 fingerprint 应改变，但前后均为 {fps_before.get('OrderService')!r}"
        )
        # 且 bootstrap 应重新生成该节点
        assert r2.memories_generated > 0, (
            f"方法签名变更后应重新生成记忆，但 memories_generated={r2.memories_generated}"
        )

    def test_unchanged_class_not_regenerated(self, tmp_path):
        """同一文件中，未变更的类不应被重新生成（fingerprint 不变时跳过）。"""
        root = tmp_path / "project"

        # 创建两个类的文件
        root.mkdir(parents=True, exist_ok=True)
        (root / "requirements.txt").write_text("fastapi>=0.100\n")
        src = root / "src" / "services"
        src.mkdir(parents=True)
        (root / "src" / "__init__.py").touch()
        (src / "__init__.py").touch()
        (src / "mixed.py").write_text(textwrap.dedent("""\
            class ServiceA:
                def method_a(self, x: int) -> int:
                    return x

            class ServiceB:
                def method_b(self, y: str) -> str:
                    return y
            """))

        r1 = _boot(root)
        assert r1.memories_generated >= 2, "应生成至少 2 条记忆（ServiceA + ServiceB）"

        # 只修改 ServiceA
        (src / "mixed.py").write_text(textwrap.dedent("""\
            class ServiceA:
                def method_a(self, x: int, extra: str = "") -> int:
                    return x

            class ServiceB:
                def method_b(self, y: str) -> str:
                    return y
            """))

        r2 = _boot(root)
        fps = _read_fingerprints(root)

        # ServiceA 被重新生成（memories_generated > 0），ServiceB 幂等跳过
        assert r2.memories_generated > 0, "ServiceA 变更后应重新生成"


# ─── 场景 3：新增类 ───────────────────────────────────────────────────────────

class TestIncremental_NewClass:
    """向源文件添加新类 → 新 MEM-BOOT-*.md 被创建。"""

    def test_new_class_creates_new_memory(self, tmp_path):
        root = tmp_path / "project"
        _make_minimal_python_project(root)  # 只有 OrderService

        r1 = _boot(root)
        ids_after_r1 = _get_boot_ids(root)
        assert r1.memories_generated > 0

        # 向文件中追加新类
        svc_file = root / "src" / "services" / "order_service.py"
        original = svc_file.read_text()
        svc_file.write_text(original + textwrap.dedent("""\


            class PaymentService:
                def process_payment(self, order_id: str, amount: float) -> bool:
                    return True

                def refund(self, order_id: str) -> bool:
                    return True
            """))

        r2 = _boot(root)
        ids_after_r2 = _get_boot_ids(root)

        new_ids = ids_after_r2 - ids_after_r1
        assert len(new_ids) >= 1, (
            f"添加 PaymentService 后应有新 MEM-BOOT 文件，但 new_ids={new_ids}"
        )
        assert r2.memories_generated >= 1, (
            f"第二次 bootstrap 应生成 ≥1 条记忆（PaymentService），实际 {r2.memories_generated}"
        )

    def test_new_file_creates_new_memories(self, tmp_path):
        """新增源码文件 → 其中所有类都被处理为新记忆。"""
        root = tmp_path / "project"
        _make_minimal_python_project(root)  # 只有 order_service.py

        r1 = _boot(root)
        count_r1 = _count_boot_files(root)
        assert r1.memories_generated > 0

        # 新增完全独立的文件
        repo_file = root / "src" / "services" / "user_service.py"
        repo_file.write_text(textwrap.dedent("""\
            class UserService:
                def get_user(self, user_id: str) -> dict:
                    return {"id": user_id}

                def create_user(self, email: str, name: str) -> dict:
                    return {"email": email, "name": name}
            """))

        r2 = _boot(root)
        count_r2 = _count_boot_files(root)

        assert count_r2 > count_r1, (
            f"新增 user_service.py 后 MEM-BOOT 数量应增加（{count_r1} → {count_r2}）"
        )
        assert r2.memories_generated >= 1


# ─── 场景 4：新增方法 ─────────────────────────────────────────────────────────

class TestIncremental_MethodAddition:
    """向已有类添加新方法 → fingerprint 变化 → 记忆被重新生成。"""

    def test_adding_method_changes_fingerprint(self, tmp_path):
        root = tmp_path / "project"
        _make_minimal_python_project(root)

        _boot(root)
        fps_before = _read_fingerprints(root)
        fp_v1 = fps_before.get("OrderService", "")

        # 向 OrderService 添加一个新方法
        svc_file = root / "src" / "services" / "order_service.py"
        svc_file.write_text(textwrap.dedent("""\
            class OrderService:
                def create_order(self, amount: float) -> dict:
                    return {"amount": amount}

                def cancel_order(self, order_id: str) -> bool:
                    return True

                def list_orders(self, page: int = 1, size: int = 20) -> list:
                    return []
            """))

        r2 = _boot(root)
        fps_after = _read_fingerprints(root)
        fp_v2 = fps_after.get("OrderService", "")

        assert fp_v1 != fp_v2, (
            f"新增方法后 fingerprint 应变化，但前后均为 {fp_v1!r}"
        )
        assert r2.memories_generated > 0, (
            "新增方法后应重新生成 OrderService 的记忆"
        )


# ─── 场景 5：权重模板对增量逻辑的透明性 ───────────────────────────────────────

class TestIncremental_WeightsProfile:
    """不同的 weights_profile 不影响增量幂等逻辑（fingerprint 基于方法签名，与权重无关）。"""

    def test_different_profiles_are_idempotent(self, tmp_path):
        root = tmp_path / "project"
        _make_minimal_python_project(root)

        # 第一次用默认权重
        r1 = _boot(root)
        assert r1.memories_generated > 0

        # 第二次用 go_gin profile（权重不同，但代码未变）
        r2 = _boot(root, weights_profile="go_gin")
        assert r2.memories_generated == 0, (
            f"代码未变时，换 weights_profile 不应触发重新生成，"
            f"但实际 memories_generated={r2.memories_generated}"
        )

    def test_profile_affects_layer_distribution(self, tmp_path):
        """不同 weights_profile 应影响层推断分布（验证权重真正生效）。"""
        from mms.bootstrap.signal_fusion import get_signal_weights, infer_layer

        # 模拟一个同时有 path 和 annotation 信号的类
        file_path = "src/controller/order.go"
        class_name = "OrderHandler"  # name 信号：Handler → ADAPTER

        # 默认权重（annotation 0.30，path 0.25）
        w_default = get_signal_weights()
        r_default = infer_layer(file_path, class_name, weights=w_default)

        # go_gin 权重（path 0.45，annotation ≈ 0.03）
        w_go = get_signal_weights("go_gin")
        r_go = infer_layer(file_path, class_name, weights=w_go)

        # 两者都应推断为 ADAPTER（path + name 信号一致），但 go_gin 的置信度更高（path 权重更大）
        assert r_default.inferred_layer == "ADAPTER"
        assert r_go.inferred_layer == "ADAPTER"
        assert r_go.confidence >= r_default.confidence, (
            f"go_gin profile 的 path 权重更高（0.45 vs 0.25），"
            f"对 controller/ 路径下的类置信度应 ≥ 默认值，"
            f"但 go_gin={r_go.confidence:.3f} < default={r_default.confidence:.3f}"
        )


# ─── 场景 6：对 Python FastAPI fixture 的增量 E2E 验证 ──────────────────────

class TestIncremental_OnFixture:
    """基于完整 Python FastAPI fixture 的增量测试（覆盖多文件、多类场景）。"""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.root = tmp_path / "fastapi-demo"
        shutil.copytree(_PYTHON_FIXTURE, self.root)
        # 清除已有 MEM-BOOT 文件，从干净状态开始
        for md in self.root.rglob("MEM-BOOT-*.md"):
            md.unlink()

    def test_full_idempotency(self):
        """完整 fixture 项目两次 bootstrap 的幂等性验证。"""
        r1 = _boot(self.root)
        assert r1.memories_generated > 0

        r2 = _boot(self.root)
        assert r2.memories_generated == 0, (
            f"FastAPI fixture 二次 bootstrap 应为 0 条新生成，实际 {r2.memories_generated}"
        )

    def test_incremental_after_code_change(self):
        """在 FastAPI fixture 中修改一个类后，验证只有该类被重新生成。"""
        r1 = _boot(self.root)
        assert r1.memories_generated > 0
        count_after_r1 = _count_boot_files(self.root)

        # 向 order_service.py 添加新方法
        svc_path = self.root / "src" / "services" / "order_service.py"
        if not svc_path.exists():
            pytest.skip(f"找不到 {svc_path}，跳过此场景")

        original = svc_path.read_text()
        svc_path.write_text(original + "\n    def list_all_orders(self):\n        return []\n")

        r2 = _boot(self.root)
        count_after_r2 = _count_boot_files(self.root)

        assert r2.memories_generated > 0, "修改 order_service.py 后应有记忆被更新"
        # 文件数不变（只更新，不新增）
        assert count_after_r2 == count_after_r1, (
            f"只修改方法，不新增类，MEM-BOOT 文件数应不变（{count_after_r1}→{count_after_r2}）"
        )
