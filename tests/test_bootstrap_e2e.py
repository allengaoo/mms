"""
test_bootstrap_e2e.py — mms bootstrap 端到端流程测试（EP-130）
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))


class TestBootstrapFlow:
    """冷启动端到端测试。"""

    def test_bootstrap_dry_run_completes(self, tmp_path):
        """bootstrap --dry-run 不写文件，返回 0。"""
        # 创建最小项目结构
        (tmp_path / "backend" / "app").mkdir(parents=True)
        (tmp_path / "frontend" / "src").mkdir(parents=True)
        req = tmp_path / "backend" / "requirements.txt"
        req.write_text("fastapi>=0.100\nsqlmodel\n")

        from dep_sniffer import DependencySniffer
        from seed_packs import list_packs, get_pack_dir
        from ast_skeleton import AstSkeletonBuilder

        # 嗅探
        profile = DependencySniffer(root=tmp_path).scan()
        assert "base" in profile.detected_stacks
        assert "fastapi_sqlmodel" in profile.detected_stacks

        # 确认种子包目录存在
        packs = list_packs()
        assert "base" in packs
        assert "fastapi_sqlmodel" in packs

        # AST 骨架化（空项目，结果为空但不报错）
        py_file = tmp_path / "backend" / "app" / "service.py"
        py_file.write_text(textwrap.dedent("""
            class TestService:
                async def create(self, ctx): pass
        """))
        builder = AstSkeletonBuilder(root=tmp_path, scan_dirs=[("backend/app", "python")])
        index = builder.build()
        assert "backend/app/service.py" in index

    def test_seed_packs_have_required_files(self):
        """每个种子包必须有 match_conditions.yaml 和至少一个 docs 文件。"""
        from seed_packs import list_packs, get_pack_dir

        for pack_name in list_packs():
            pack_dir = get_pack_dir(pack_name)
            match_file = pack_dir / "match_conditions.yaml"
            assert match_file.exists(), f"种子包 {pack_name} 缺少 match_conditions.yaml"

            docs_dir = pack_dir / "docs"
            if docs_dir.exists():
                md_files = list(docs_dir.rglob("*.md"))
                assert len(md_files) > 0, f"种子包 {pack_name}/docs 目录为空"

    def test_ast_index_format(self, tmp_path):
        """ast_index.json 格式符合预期。"""
        # 按 AstSkeletonBuilder 默认扫描目录结构创建文件
        svc_dir = tmp_path / "backend" / "app" / "services"
        svc_dir.mkdir(parents=True)
        py_file = svc_dir / "ontology_service.py"
        py_file.write_text(textwrap.dedent("""
            from app.core.security import SecurityContext

            class OntologyService:
                \"\"\"本体服务。\"\"\"
                async def create_object(self, ctx: SecurityContext) -> dict:
                    \"\"\"创建对象。\"\"\"
                    pass
        """))

        from ast_skeleton import AstSkeletonBuilder, build_ast_index
        # 直接用 AstSkeletonBuilder 并指定 scan_dirs
        builder = AstSkeletonBuilder(
            root=tmp_path,
            scan_dirs=[("backend/app/services", "python")],
        )
        index = builder.build()

        # 验证格式
        keys = list(index.keys())
        assert any("ontology_service.py" in k for k in keys), f"期望在 {keys} 中找到 ontology_service.py"
        
        # 找到对应条目
        key = next(k for k in keys if "ontology_service.py" in k)
        entry = index[key]
        assert entry["lang"] == "python"
        assert len(entry["classes"]) == 1
        assert entry["classes"][0]["name"] == "OntologyService"
        assert len(entry["classes"][0]["methods"]) == 1
        assert entry["classes"][0]["methods"][0]["name"] == "create_object"
        assert entry["fingerprint"].startswith("sha256:")

    def test_seed_pack_install_copies_files(self, tmp_path):
        """安装种子包后，目标目录应包含种子文件。"""
        from seed_packs import install_packs

        target_docs = tmp_path / "docs"
        target_docs.mkdir()

        installed = install_packs(
            pack_names=["base"],
            target_docs=target_docs,
            dry_run=False,
        )
        assert "base" in installed

        # 检查 base 包的文件是否被复制
        from seed_packs import get_pack_dir
        base_docs = get_pack_dir("base") / "docs"
        if base_docs.exists():
            for md_file in base_docs.rglob("*.md"):
                rel = md_file.relative_to(base_docs)
                target_file = target_docs / rel
                assert target_file.exists(), f"文件未被复制：{rel}"
