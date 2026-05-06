"""
test_ast_skeleton.py — AST 骨架化器测试（EP-130）
"""
from __future__ import annotations

import sys
import textwrap
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from mms.analysis.ast_skeleton import (
    _parse_python, _parse_typescript, _compute_fingerprint,
    AstSkeletonBuilder, FileSkeleton,
)


class TestPythonParsing:
    """Python AST 解析测试。"""

    def test_parses_class_with_methods(self):
        source = textwrap.dedent("""
            class OntologyService:
                \"\"\"本体服务层。\"\"\"

                async def create_object_type(self, ctx: SecurityContext, payload: CreateRequest) -> ObjectTypeResponse:
                    \"\"\"创建对象类型。\"\"\"
                    pass

                async def list_object_types(self, ctx: SecurityContext) -> list:
                    pass
        """)
        skel = _parse_python(source, "test.py")
        assert len(skel.classes) == 1
        cls = skel.classes[0]
        assert cls.name == "OntologyService"
        assert len(cls.methods) == 2
        assert cls.methods[0].name == "create_object_type"
        assert "SecurityContext" in cls.methods[0].signature
        assert cls.methods[0].is_async is True
        assert cls.docstring == "本体服务层。"

    def test_skips_private_methods(self):
        source = textwrap.dedent("""
            class Foo:
                def public_method(self): pass
                def _private_method(self): pass
                def __init__(self): pass
                def __repr__(self): pass
        """)
        skel = _parse_python(source, "test.py")
        names = [m.name for m in skel.classes[0].methods]
        assert "public_method" in names
        assert "_private_method" not in names
        assert "__init__" in names   # 双下划线保留

    def test_parses_imports_uppercase_names(self):
        source = textwrap.dedent("""
            from app.core.security import SecurityContext
            from app.models.ontology import ObjectTypeDef
            import fastapi
        """)
        skel = _parse_python(source, "test.py")
        assert "SecurityContext" in skel.imports
        assert "ObjectTypeDef" in skel.imports
        assert "fastapi" not in skel.imports  # 小写，跳过

    def test_parses_top_level_functions(self):
        source = textwrap.dedent("""
            def build_context(task: str) -> str:
                \"\"\"构建上下文。\"\"\"
                return task

            def _private_helper(): pass
        """)
        skel = _parse_python(source, "test.py")
        names = [f.name for f in skel.top_level_functions]
        assert "build_context" in names
        assert "_private_helper" not in names

    def test_handles_syntax_error_gracefully(self):
        source = "class Foo: invalid syntax {{{"
        skel = _parse_python(source, "bad.py")
        # 不抛异常，返回空骨架
        assert isinstance(skel, FileSkeleton)
        assert skel.classes == []

    def test_extracts_decorator_names(self):
        source = textwrap.dedent("""
            class Router:
                @require_permission("ont:object:view")
                async def list_objects(self): pass
        """)
        skel = _parse_python(source, "test.py")
        method = skel.classes[0].methods[0]
        assert "require_permission" in method.decorators

    def test_parses_bases(self):
        source = textwrap.dedent("""
            class OntologyService(BaseService):
                pass
        """)
        skel = _parse_python(source, "test.py")
        assert "BaseService" in skel.classes[0].bases


class TestTypeScriptParsing:
    """TypeScript 骨架提取测试（正则，粗粒度）。"""

    def test_parses_export_class(self):
        source = textwrap.dedent("""
            export class OntologyStore {
                fetchObjects(): void {}
                createObject(data: any): Promise<void> {}
                _privateMethod(): void {}
            }
        """)
        skel = _parse_typescript(source, "store.ts")
        assert len(skel.classes) == 1
        assert skel.classes[0].name == "OntologyStore"
        names = [m.name for m in skel.classes[0].methods]
        assert "fetchObjects" in names
        assert "createObject" in names
        assert "_privateMethod" not in names

    def test_parses_export_function(self):
        source = textwrap.dedent("""
            export function buildContext(task: string): string {
                return task;
            }
            export const useStore = () => {
                return {};
            };
        """)
        skel = _parse_typescript(source, "utils.ts")
        names = [f.name for f in skel.top_level_functions]
        assert "buildContext" in names
        assert "useStore" in names

    def test_parses_imports(self):
        source = textwrap.dedent("""
            import { SecurityContext, ObjectTypeDef } from '@/types';
            import type { ApiResponse } from '@/api';
        """)
        skel = _parse_typescript(source, "test.ts")
        assert "SecurityContext" in skel.imports
        assert "ObjectTypeDef" in skel.imports
        assert "ApiResponse" in skel.imports


class TestFingerprint:
    """AST 指纹计算测试。"""

    def test_same_skeleton_same_fingerprint(self):
        source = textwrap.dedent("""
            class Foo:
                def bar(self, x: int) -> str: pass
        """)
        skel1 = _parse_python(source, "test.py")
        skel2 = _parse_python(source, "test.py")
        fp1 = _compute_fingerprint(skel1)
        fp2 = _compute_fingerprint(skel2)
        assert fp1 == fp2

    def test_changed_signature_changes_fingerprint(self):
        source_before = textwrap.dedent("""
            class Foo:
                def bar(self, x: int) -> str: pass
        """)
        source_after = textwrap.dedent("""
            class Foo:
                def bar(self, x: int, y: str) -> str: pass
        """)
        skel1 = _parse_python(source_before, "test.py")
        skel2 = _parse_python(source_after, "test.py")
        fp1 = _compute_fingerprint(skel1)
        fp2 = _compute_fingerprint(skel2)
        assert fp1 != fp2

    def test_fingerprint_starts_with_sha256(self):
        skel = FileSkeleton(path="test.py", lang="python")
        fp = _compute_fingerprint(skel)
        assert fp.startswith("sha256:")


class TestAstSkeletonBuilder:
    """AstSkeletonBuilder 扫描测试。"""

    def test_scans_python_files(self, tmp_path):
        service_file = tmp_path / "service.py"
        service_file.write_text(textwrap.dedent("""
            class FooService:
                async def create(self, ctx): pass
                async def list_all(self, ctx): pass
        """))

        builder = AstSkeletonBuilder(
            root=tmp_path,
            scan_dirs=[("", "python")],
        )
        index = builder.build()
        # 应该扫到 service.py
        keys = list(index.keys())
        assert any("service.py" in k for k in keys)

    def test_ignores_pycache(self, tmp_path):
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "foo.py").write_text("class Foo: pass")

        builder = AstSkeletonBuilder(root=tmp_path, scan_dirs=[("", "python")])
        index = builder.build()
        for key in index.keys():
            assert "__pycache__" not in key

    def test_fingerprint_included_in_index(self, tmp_path):
        f = tmp_path / "model.py"
        f.write_text("class Bar:\n    def method(self): pass\n")

        builder = AstSkeletonBuilder(root=tmp_path, scan_dirs=[("", "python")])
        index = builder.build()
        for val in index.values():
            if val.get("classes"):
                assert "fingerprint" in val
                assert val["fingerprint"].startswith("sha256:")
                break


class TestSemanticHashStability:
    """
    语义哈希稳定性测试（Phase 2 TDD）。

    核心命题：格式化工具（Black / gofmt）不应引发虚假漂移，
    真实签名/类型变更必须引发漂移。
    """

    def test_whitespace_change_no_drift(self):
        """仅添加空行不应改变指纹。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float) -> dict: pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:

                def create(self, amount: float) -> dict: pass

        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 == fp2, "仅空行变化不应导致指纹变化"

    def test_comment_change_no_drift(self):
        """增删注释不应改变指纹。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float) -> dict: pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:
                # 创建订单
                def create(self, amount: float) -> dict: pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 == fp2, "增删注释不应导致指纹变化"

    def test_docstring_change_no_drift(self):
        """修改 docstring 不应改变指纹（指纹只基于签名）。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float) -> dict:
                    \"\"\"旧版文档。\"\"\"
                    pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float) -> dict:
                    \"\"\"重写了文档字符串，描述更详细。\"\"\"
                    pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 == fp2, "修改 docstring 不应导致指纹变化"

    def test_new_parameter_causes_drift(self):
        """新增函数参数必须触发指纹变化。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float) -> dict: pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:
                def create(self, amount: float, member_id: int) -> dict: pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 != fp2, "新增参数必须触发指纹变化"

    def test_return_type_change_causes_drift(self):
        """变更返回类型注解必须触发指纹变化。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def list_orders(self) -> list: pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:
                def list_orders(self) -> list[dict]: pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 != fp2, "返回类型变更必须触发指纹变化"

    def test_new_method_causes_drift(self):
        """新增方法必须触发指纹变化。"""
        source_before = textwrap.dedent("""
            class OrderService:
                def create(self) -> dict: pass
        """)
        source_after = textwrap.dedent("""
            class OrderService:
                def create(self) -> dict: pass
                def delete(self, order_id: int) -> None: pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 != fp2, "新增方法必须触发指纹变化"

    def test_rename_class_causes_drift(self):
        """重命名类必须触发指纹变化。"""
        source_before = "class OldService:\n    def run(self): pass\n"
        source_after = "class NewService:\n    def run(self): pass\n"
        fp1 = _compute_fingerprint(_parse_python(source_before, "svc.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "svc.py"))
        assert fp1 != fp2, "重命名类必须触发指纹变化"

    def test_empty_file_stable(self):
        """空文件反复计算指纹结果一致。"""
        skel = _parse_python("", "empty.py")
        fp1 = _compute_fingerprint(skel)
        fp2 = _compute_fingerprint(skel)
        assert fp1 == fp2

    def test_black_formatted_no_drift(self):
        """
        模拟 Black 格式化：将单行定义拆为多行，逻辑等价，指纹应不变。
        （Black 不改变函数签名，只改变缩进/换行等）
        """
        source_before = textwrap.dedent("""
            class PaymentService:
                def process(self, amount: float, currency: str) -> bool: pass
        """)
        # Black 会将过长的签名拆行，但 AST 解析后签名相同
        source_after = textwrap.dedent("""
            class PaymentService:
                def process(
                    self,
                    amount: float,
                    currency: str,
                ) -> bool: pass
        """)
        fp1 = _compute_fingerprint(_parse_python(source_before, "pay.py"))
        fp2 = _compute_fingerprint(_parse_python(source_after, "pay.py"))
        assert fp1 == fp2, "Black 格式化（拆行签名）不应触发指纹变化"
