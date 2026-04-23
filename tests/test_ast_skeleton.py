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

from ast_skeleton import (
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
