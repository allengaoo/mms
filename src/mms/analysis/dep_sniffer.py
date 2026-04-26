"""
dep_sniffer.py — 技术栈依赖嗅探器（EP-130 v2.0）

零 LLM 消耗地识别项目技术栈，为 seed_packs 的自动选择提供依据。

扫描策略（按优先级）：
  1. pyproject.toml      (Python 现代项目)
  2. requirements.txt    (Python 传统项目)
  3. package.json        (Node.js / 前端)
  4. pom.xml             (Java Maven 项目) ← v2.0 新增
  5. build.gradle        (Java/Kotlin Gradle 项目) ← v2.0 新增
  6. go.mod              (Go Module 项目) ← v2.0 新增
  7. 目录特征嗅探        (fallback：通过目录名推断)

离线约束：
  - 禁止 import tomllib（Python 3.11+ 限定，环境可能不满足）
  - 手写简单 TOML key 提取（只需识别 [dependencies] 下的 key）

输出格式：
  StackProfile {
    backend_packages: ["fastapi", "sqlmodel", "aiokafka", ...]
    frontend_packages: ["react", "zustand", ...]
    detected_stacks: ["fastapi_sqlmodel", "react_zustand", "palantir_arch"]
    confidence: 0.85
  }

EP-130 | 2026-04-18
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT  # type: ignore[import]
except ImportError:
    _ROOT = _HERE.parent.parent


# ── 数据结构 ─────────────────────────────────────────────────────────────────

@dataclass
class StackProfile:
    """技术栈嗅探结果。"""
    backend_packages: List[str] = field(default_factory=list)
    frontend_packages: List[str] = field(default_factory=list)
    detected_stacks: List[str] = field(default_factory=list)   # 匹配的种子包名
    confidence: float = 0.0   # 0.0~1.0，越高表示识别越确定
    scan_sources: List[str] = field(default_factory=list)      # 扫描了哪些文件


# ── TOML 简单解析（手写，无依赖）────────────────────────────────────────────

# 只提取 key = "value" 或 key = ["v1", "v2"] 格式
_RE_TOML_STR_VAL = re.compile(r'^(\w[\w.-]*)\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_RE_TOML_LIST = re.compile(r'^(\w[\w.-]*)\s*=\s*\[([^\]]*)\]', re.MULTILINE | re.DOTALL)
_RE_TOML_SECTION = re.compile(r'^\[([^\]]+)\]', re.MULTILINE)


def _parse_toml_dependencies(content: str) -> Set[str]:
    """
    从 pyproject.toml 内容中提取 [dependencies] / [tool.poetry.dependencies]
    下的包名（不解析版本约束，只取包名）。
    """
    deps: Set[str] = set()

    # 找到 [dependencies] / [tool.poetry.dependencies] / [project] 节
    dep_sections = {
        "dependencies", "tool.poetry.dependencies",
        "project", "build-system",
    }

    # 按节分割
    sections: List[tuple] = []
    pos = 0
    for m in _RE_TOML_SECTION.finditer(content):
        sections.append((pos, m.start(), ""))
        pos = m.start()
        sections[-1] = (sections[-1][0], m.start(), m.group(1))

    # 合并成 {section_name: section_text}
    section_texts: Dict[str, str] = {}
    lines = content.split("\n")
    current_section = "__root__"
    buf: List[str] = []
    for line in lines:
        m = _RE_TOML_SECTION.match(line)
        if m:
            section_texts[current_section] = "\n".join(buf)
            current_section = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    section_texts[current_section] = "\n".join(buf)

    # 提取各目标节的 key（key = value 格式）
    for section_name, text in section_texts.items():
        is_dep_section = any(ds in section_name.lower() for ds in dep_sections)
        if not is_dep_section:
            continue
        # 提取字符串值 key
        for m in _RE_TOML_STR_VAL.finditer(text):
            key = m.group(1).lower().replace("-", "_").replace(".", "_")
            if not key.startswith("python"):
                deps.add(key)
        # 提取列表值（如 dependencies = ["fastapi>=0.100"]）
        for m in _RE_TOML_LIST.finditer(text):
            items_str = m.group(2)
            for item in items_str.split(","):
                item = item.strip().strip('"\'').split(">=")[0].split("==")[0].split("[")[0]
                item = item.lower().replace("-", "_")
                if item and not item.startswith("#"):
                    deps.add(item)

    return deps


def _parse_requirements(content: str) -> Set[str]:
    """从 requirements.txt 内容中提取包名。"""
    deps: Set[str] = set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 去掉版本约束
        pkg = re.split(r"[>=<!;\[]", line)[0].strip().lower().replace("-", "_")
        if pkg:
            deps.add(pkg)
    return deps


def _parse_package_json(content: str) -> Set[str]:
    """从 package.json 内容中提取依赖包名。"""
    deps: Set[str] = set()
    try:
        data = json.loads(content)
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            for pkg in (data.get(section) or {}).keys():
                deps.add(pkg.lower().replace("-", "_").lstrip("@").split("/")[-1])
    except (json.JSONDecodeError, AttributeError):
        pass
    return deps


def _parse_pom_xml(content: str) -> Set[str]:
    """
    从 Maven pom.xml 中提取 artifactId（不依赖 xml.etree，用正则）。

    提取目标：
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>

    返回：{"spring_boot_starter_web", "spring_boot_starter_data_jpa", ...}
    """
    deps: Set[str] = set()
    # Extract artifactId values
    for m in re.finditer(r'<artifactId>\s*([\w.\-]+)\s*</artifactId>', content):
        artifact = m.group(1).lower().replace("-", "_").replace(".", "_")
        deps.add(artifact)
    # Also extract groupId prefix for stack detection
    for m in re.finditer(r'<groupId>\s*([\w.\-]+)\s*</groupId>', content):
        group = m.group(1).lower()
        # Normalize to key identifiers
        if 'spring' in group:
            deps.add('spring')
        elif 'hibernate' in group:
            deps.add('hibernate')
        elif 'junit' in group:
            deps.add('junit')
        elif 'mybatis' in group:
            deps.add('mybatis')
    return deps


def _parse_build_gradle(content: str) -> Set[str]:
    """
    从 Gradle build.gradle / build.gradle.kts 中提取依赖名。

    支持格式：
      implementation 'org.springframework.boot:spring-boot-starter-web:3.x.x'
      implementation("com.fasterxml.jackson.core:jackson-databind")
      testImplementation 'junit:junit:4.13'
    """
    deps: Set[str] = set()
    # Pattern: groupId:artifactId[:version] — capture only the artifactId (2nd segment)
    patterns = [
        r"""(?:implementation|api|compile|testImplementation|runtimeOnly)\s+['"][\w.\-]+:([\w.\-]+)(?::[\d.][^'"]*)?['"]""",
        r"""(?:implementation|api|compile)\s*\(\s*['"][\w.\-]+:([\w.\-]+)(?::[\d.][^'"]*)?['"]\s*\)""",
    ]
    for pat in patterns:
        for m in re.finditer(pat, content):
            artifact = m.group(1).lower().replace("-", "_")
            # Skip pure version strings like "3.2.0"
            if not re.match(r'^[\d.]+$', artifact):
                deps.add(artifact)

    # Detect Spring Boot plugin
    if 'spring-boot' in content or 'org.springframework.boot' in content:
        deps.add('spring')
        deps.add('spring_boot')
    if 'org.jetbrains.kotlin' in content or 'kotlin' in content:
        deps.add('kotlin')

    return deps


def _parse_go_mod(content: str) -> Set[str]:
    """
    从 go.mod 中提取 require 的模块名（只取路径最后一段）。

    格式：
      require (
          github.com/gin-gonic/gin v1.9.1
          gorm.io/gorm v1.25.5
      )
    """
    deps: Set[str] = set()
    in_require = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('require ('):
            in_require = True
            continue
        if in_require and line == ')':
            in_require = False
            continue
        # Single line: require github.com/pkg/name v1.2.3
        m = re.match(r'(?:require\s+)?([^\s]+)\s+v[\d.]+', line)
        if m:
            module_path = m.group(1)
            # Take last segment of module path
            last = module_path.rstrip('/').split('/')[-1]
            # Normalize
            pkg = last.lower().replace("-", "_").replace(".", "_")
            deps.add(pkg)
            # Also detect well-known frameworks
            if 'gin' in module_path:
                deps.add('gin')
            elif 'echo' in module_path:
                deps.add('echo')
            elif 'fiber' in module_path:
                deps.add('fiber')
            elif 'gorm' in module_path:
                deps.add('gorm')
            elif 'grpc' in module_path:
                deps.add('grpc')

    return deps


# ── 技术栈匹配规则 ────────────────────────────────────────────────────────────

# 每个栈的匹配规则：{stack_id: (required_packages, optional_packages, dir_hints)}
# 需要满足 required 全部命中，或 optional 命中 >= 2 个
_STACK_RULES: Dict[str, dict] = {
    "fastapi_sqlmodel": {
        "required": {"fastapi"},
        "optional": {"sqlmodel", "sqlalchemy", "asyncmy", "pydantic"},
        "dir_hints": ["backend/app/api", "backend/app/services"],
        "description": "FastAPI + SQLModel/SQLAlchemy 后端栈",
    },
    "fastapi_kafka": {
        "required": {"fastapi"},
        "optional": {"aiokafka", "confluent_kafka", "kafka_python"},
        "dir_hints": ["backend/app/infrastructure/kafka"],
        "description": "FastAPI + Kafka 消息队列栈",
    },
    "react_zustand": {
        "required": {"react"},
        "optional": {"zustand", "antd", "ant_design", "react_query", "@tanstack_react_query"},
        "dir_hints": ["frontend/src/stores", "frontend/src"],
        "description": "React + Zustand 前端栈",
    },
    "palantir_arch": {
        "required": set(),  # 纯架构约束，通过目录特征判断
        "optional": {"fastapi", "sqlmodel"},
        "dir_hints": [
            "backend/app/services/control",
            "backend/app/infrastructure",
            "docs/memory",
        ],
        "description": "木兰通用 5 层架构（PLATFORM/DOMAIN/APP/ADAPTER/CC + CQRS + RLS）",
    },
    # ── Java 栈 ───────────────────────────────────────────────────────────────
    "spring_boot": {
        "required": {"spring_boot"},
        "optional": {"spring", "hibernate", "mybatis", "spring_data_jpa", "spring_boot_starter_web"},
        "dir_hints": ["src/main/java", "src/main/resources"],
        "description": "Spring Boot Java 后端栈",
    },
    "spring_boot_microservices": {
        "required": {"spring_boot"},
        "optional": {"spring_cloud", "eureka", "ribbon", "feign", "hystrix", "gateway"},
        "dir_hints": ["src/main/java"],
        "description": "Spring Boot 微服务架构栈（含 Spring Cloud）",
    },
    # ── Go 栈 ────────────────────────────────────────────────────────────────
    "go_gin": {
        "required": {"gin"},
        "optional": {"gorm", "grpc", "fiber"},
        "dir_hints": ["cmd", "internal", "pkg"],
        "description": "Go + Gin Web 框架栈",
    },
    "go_grpc": {
        "required": {"grpc"},
        "optional": {"gin", "gorm", "protobuf"},
        "dir_hints": ["proto", "api", "internal"],
        "description": "Go + gRPC 微服务栈",
    },
}


def _match_stacks(
    all_packages: Set[str],
    root: Path,
    rules: Dict[str, dict] = _STACK_RULES,
) -> List[str]:
    """基于包集合 + 目录特征匹配种子包列表。"""
    matched = []
    for stack_id, rule in rules.items():
        required = rule.get("required", set())
        optional = rule.get("optional", set())
        dir_hints = rule.get("dir_hints", [])

        # 检查 required（全部命中）
        if required and not required.issubset(all_packages):
            # 检查目录特征作为 fallback
            dir_match = any((root / d).exists() for d in dir_hints)
            if not dir_match:
                continue

        # 检查 optional 命中数
        optional_hits = len(optional & all_packages)
        dir_hits = sum(1 for d in dir_hints if (root / d).exists())

        # 综合评分：至少 optional 命中 1 个，或目录命中 2 个
        if optional_hits >= 1 or dir_hits >= 2:
            matched.append(stack_id)

    # 始终包含 base
    if "base" not in matched:
        matched.insert(0, "base")

    return matched


# ── 核心嗅探器 ───────────────────────────────────────────────────────────────

class DependencySniffer:
    """
    技术栈依赖嗅探器。

    使用方式：
        sniffer = DependencySniffer(root=Path("/path/to/project"))
        profile = sniffer.scan()
        print(profile.detected_stacks)  # ["base", "fastapi_sqlmodel", "react_zustand"]
    """

    def __init__(self, root: Path = _ROOT):
        self.root = root

    def scan(self) -> StackProfile:
        """扫描项目，返回 StackProfile。"""
        profile = StackProfile()
        all_packages: Set[str] = set()

        # 1. pyproject.toml
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                pkgs = _parse_toml_dependencies(content)
                all_packages |= pkgs
                profile.backend_packages.extend(sorted(pkgs))
                profile.scan_sources.append("pyproject.toml")
            except OSError:
                pass

        # 2. backend/requirements.txt 或 requirements.txt
        for req_path in [
            self.root / "backend" / "requirements.txt",
            self.root / "requirements.txt",
        ]:
            if req_path.exists():
                try:
                    content = req_path.read_text(encoding="utf-8", errors="ignore")
                    pkgs = _parse_requirements(content)
                    all_packages |= pkgs
                    profile.backend_packages.extend(sorted(pkgs))
                    profile.scan_sources.append(str(req_path.relative_to(self.root)))
                except OSError:
                    pass
                break

        # 3. package.json（前端）
        for pkg_path in [
            self.root / "frontend" / "package.json",
            self.root / "package.json",
        ]:
            if pkg_path.exists():
                try:
                    content = pkg_path.read_text(encoding="utf-8", errors="ignore")
                    pkgs = _parse_package_json(content)
                    all_packages |= pkgs
                    profile.frontend_packages.extend(sorted(pkgs))
                    profile.scan_sources.append(str(pkg_path.relative_to(self.root)))
                except OSError:
                    pass
                break

        # 4. pom.xml（Java Maven）
        for pom_path in [
            self.root / "pom.xml",
            self.root / "backend" / "pom.xml",
        ]:
            if pom_path.exists():
                try:
                    content = pom_path.read_text(encoding="utf-8", errors="ignore")
                    pkgs = _parse_pom_xml(content)
                    all_packages |= pkgs
                    profile.backend_packages.extend(sorted(pkgs))
                    profile.scan_sources.append(str(pom_path.relative_to(self.root)))
                except OSError:
                    pass
                break

        # 5. build.gradle / build.gradle.kts（Java/Kotlin Gradle）
        for gradle_path in [
            self.root / "build.gradle",
            self.root / "build.gradle.kts",
            self.root / "backend" / "build.gradle",
            self.root / "backend" / "build.gradle.kts",
        ]:
            if gradle_path.exists():
                try:
                    content = gradle_path.read_text(encoding="utf-8", errors="ignore")
                    pkgs = _parse_build_gradle(content)
                    all_packages |= pkgs
                    profile.backend_packages.extend(sorted(pkgs))
                    profile.scan_sources.append(str(gradle_path.relative_to(self.root)))
                except OSError:
                    pass
                break

        # 6. go.mod（Go 模块）
        for gomod_path in [
            self.root / "go.mod",
            self.root / "backend" / "go.mod",
        ]:
            if gomod_path.exists():
                try:
                    content = gomod_path.read_text(encoding="utf-8", errors="ignore")
                    pkgs = _parse_go_mod(content)
                    all_packages |= pkgs
                    profile.backend_packages.extend(sorted(pkgs))
                    profile.scan_sources.append(str(gomod_path.relative_to(self.root)))
                except OSError:
                    pass
                break

        # 7. 目录特征嗅探（fallback：即使没有 requirements.txt 也能识别）
        if not profile.backend_packages:
            if (self.root / "backend" / "app").exists():
                all_packages.add("fastapi")  # 目录结构强烈暗示 FastAPI
                profile.backend_packages.append("fastapi (inferred from directory)")
                profile.scan_sources.append("directory:backend/app")
            if (self.root / "frontend" / "src").exists():
                all_packages.add("react")   # 目录结构强烈暗示 React
                profile.frontend_packages.append("react (inferred from directory)")
                profile.scan_sources.append("directory:frontend/src")

        # 去重
        profile.backend_packages = sorted(set(profile.backend_packages))
        profile.frontend_packages = sorted(set(profile.frontend_packages))

        # 5. 栈匹配
        profile.detected_stacks = _match_stacks(all_packages, self.root)

        # 6. 计算置信度
        if profile.scan_sources:
            source_score = min(1.0, len(profile.scan_sources) * 0.25)
            pkg_score = min(1.0, len(all_packages) / 10)
            profile.confidence = round((source_score + pkg_score) / 2, 2)
        else:
            profile.confidence = 0.1

        return profile


def sniff(root: Path = _ROOT) -> StackProfile:
    """快捷函数：嗅探并返回 StackProfile。"""
    return DependencySniffer(root=root).scan()
