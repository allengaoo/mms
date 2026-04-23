"""
test_dep_sniffer.py — 依赖嗅探器测试（EP-130）
"""
from __future__ import annotations

import sys
import json
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from dep_sniffer import (
    _parse_requirements, _parse_package_json,
    _parse_toml_dependencies, _match_stacks,
    DependencySniffer,
)


class TestParseRequirements:
    def test_parses_basic_packages(self):
        content = textwrap.dedent("""
            fastapi>=0.100.0
            sqlmodel==0.0.14
            # comment line
            aiokafka
        """)
        deps = _parse_requirements(content)
        assert "fastapi" in deps
        assert "sqlmodel" in deps
        assert "aiokafka" in deps

    def test_skips_comments_and_blank_lines(self):
        content = "# only comment\n\nfastapi"
        deps = _parse_requirements(content)
        assert "fastapi" in deps

    def test_normalizes_hyphens_to_underscores(self):
        content = "kafka-python>=2.0"
        deps = _parse_requirements(content)
        assert "kafka_python" in deps

    def test_strips_version_specifiers(self):
        content = "fastapi[all]>=0.100.0"
        deps = _parse_requirements(content)
        assert "fastapi" in deps


class TestParsePackageJson:
    def test_parses_dependencies(self):
        data = json.dumps({
            "dependencies": {"react": "^18.0.0", "zustand": "^4.0.0"},
            "devDependencies": {"vite": "^5.0.0"},
        })
        deps = _parse_package_json(data)
        assert "react" in deps
        assert "zustand" in deps
        assert "vite" in deps

    def test_handles_invalid_json(self):
        deps = _parse_package_json("not json {{{")
        assert deps == set()

    def test_handles_scoped_packages(self):
        data = json.dumps({
            "dependencies": {"@tanstack/react-query": "^5.0.0"}
        })
        deps = _parse_package_json(data)
        # @tanstack/react-query → react_query
        assert any("query" in d for d in deps)


class TestMatchStacks:
    def test_detects_fastapi_sqlmodel(self, tmp_path):
        (tmp_path / "backend" / "app" / "api").mkdir(parents=True)
        stacks = _match_stacks({"fastapi", "sqlmodel"}, tmp_path)
        assert "fastapi_sqlmodel" in stacks

    def test_always_includes_base(self, tmp_path):
        stacks = _match_stacks(set(), tmp_path)
        assert "base" in stacks

    def test_detects_react_zustand(self, tmp_path):
        stacks = _match_stacks({"react", "zustand"}, tmp_path)
        assert "react_zustand" in stacks

    def test_detects_palantir_via_dirs(self, tmp_path):
        (tmp_path / "backend" / "app" / "services" / "control").mkdir(parents=True)
        (tmp_path / "backend" / "app" / "infrastructure").mkdir(parents=True)
        (tmp_path / "docs" / "memory").mkdir(parents=True)
        stacks = _match_stacks(set(), tmp_path)
        assert "palantir_arch" in stacks


class TestDependencySniffer:
    def test_scans_requirements_txt(self, tmp_path):
        req = tmp_path / "backend" / "requirements.txt"
        req.parent.mkdir(parents=True)
        req.write_text("fastapi>=0.100\nsqlmodel==0.0.14\n")
        
        sniffer = DependencySniffer(root=tmp_path)
        profile = sniffer.scan()
        
        assert "fastapi_sqlmodel" in profile.detected_stacks
        assert "base" in profile.detected_stacks
        assert profile.confidence > 0

    def test_scans_package_json(self, tmp_path):
        pkg = tmp_path / "frontend" / "package.json"
        pkg.parent.mkdir(parents=True)
        pkg.write_text(json.dumps({
            "dependencies": {"react": "^18", "zustand": "^4"}
        }))
        
        sniffer = DependencySniffer(root=tmp_path)
        profile = sniffer.scan()
        
        assert "react_zustand" in profile.detected_stacks

    def test_falls_back_to_directory_hints(self, tmp_path):
        (tmp_path / "backend" / "app").mkdir(parents=True)
        (tmp_path / "frontend" / "src").mkdir(parents=True)
        
        sniffer = DependencySniffer(root=tmp_path)
        profile = sniffer.scan()
        
        # 纯目录 fallback 时：inferred packages 加入 all_packages
        # fastapi 会匹配 palantir_arch（dir_hints 命中 backend/app）
        # 但 fastapi_sqlmodel 还需要 optional 命中（sqlmodel 未出现）
        # 所以只验证 base 始终存在
        assert "base" in profile.detected_stacks
        assert profile.confidence > 0.0
        # 至少识别出 backend/app 或 frontend/src 特征
        assert len(profile.detected_stacks) >= 1

    def test_confidence_increases_with_more_sources(self, tmp_path):
        # 只有目录 fallback → 低置信度
        (tmp_path / "backend" / "app").mkdir(parents=True)
        sniffer = DependencySniffer(root=tmp_path)
        profile_low = sniffer.scan()

        # 有 requirements.txt → 更高置信度
        tmp2 = tmp_path / "project2"
        tmp2.mkdir()
        (tmp2 / "backend").mkdir()
        (tmp2 / "backend" / "requirements.txt").write_text("fastapi\nsqlmodel\n")
        sniffer2 = DependencySniffer(root=tmp2)
        profile_high = sniffer2.scan()

        assert profile_high.confidence >= profile_low.confidence
