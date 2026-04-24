"""
seed_absorber.py — Rule Absorber（规则吸收器）

将 GitHub 上的 .cursorrules / .mdc 企业规范离线蒸馏为 MMS 专用 YAML。

工作流：
  1. 获取 URL 内容（通过 stdlib urllib，支持 GitHub raw 链接）
  2. 清洗噪声：去除注释、UI 描述、说明性段落，保留技术规则
  3. 调用 qwen3-32b 将规则蒸馏为三类 YAML：
       - arch_schema（层级定义）
       - ontology（业务概念）
       - constraints（硬性规则）
  4. 保存至 seed_packs/<derived_name>/（默认不覆盖已有包）

用法：
  mms seed ingest https://raw.githubusercontent.com/user/repo/main/.cursorrules
  mms seed ingest https://example.com/rules.mdc --seed-name my_stack
  mms seed ingest ./local_rules.md --seed-name local_test --dry-run
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT
except ImportError:
    _ROOT = _HERE.parent.parent.parent


# ── 噪声清洗器 ──────────────────────────────────────────────────────────────────

_NOISE_PATTERNS = [
    # UI 描述性段落（以"you are"/"you should"/"please"开头）
    re.compile(r'^(?:you\s+are|you\s+should|please|feel\s+free|note\s+that)', re.IGNORECASE | re.MULTILINE),
    # 纯注释行
    re.compile(r'^\s*(?:#|//|<!--).*$', re.MULTILINE),
    # 空行（连续2行以上 → 1行）
    re.compile(r'\n{3,}'),
    # Markdown 图片
    re.compile(r'!\[.*?\]\(.*?\)'),
    # HTML 标签
    re.compile(r'<[^>]+>'),
]

_RULE_INDICATORS = [
    r'\b(MUST|MUST NOT|SHALL|SHALL NOT|REQUIRED|FORBIDDEN|ALWAYS|NEVER|DO NOT)\b',
    r'\b(prohibit|enforce|require|mandate|constraint|rule|guideline|standard)\b',
    r'(?:^|\n)\s*[-*]\s+(?:No |Don\'t |Never |Always |Must )',
    r'(?:^|\n)#+\s+(?:Rules|Constraints|Guidelines|Standards|Conventions)',
]
_RULE_RE = re.compile('|'.join(_RULE_INDICATORS), re.IGNORECASE)


def clean_noise(raw: str) -> str:
    """清洗输入文本：去除大部分噪声，保留技术规则内容。"""
    text = raw
    for pat in _NOISE_PATTERNS:
        if pat.pattern == r'\n{3,}':
            text = pat.sub('\n\n', text)
        else:
            text = pat.sub('', text)
    return text.strip()


def extract_rule_sections(text: str) -> str:
    """
    提取包含规则信号词的段落，大幅降低 LLM token 消耗。
    策略：保留含规则关键词的段落（前后各保留 2 行上下文）。
    """
    lines = text.split('\n')
    keep = set()
    for i, line in enumerate(lines):
        if _RULE_RE.search(line):
            for j in range(max(0, i - 2), min(len(lines), i + 3)):
                keep.add(j)

    if not keep:
        # 无规则信号 → 返回原文前 200 行（LLM 会处理）
        return '\n'.join(lines[:200])

    result = []
    prev = -1
    for idx in sorted(keep):
        if prev != -1 and idx > prev + 1:
            result.append('...')
        result.append(lines[idx])
        prev = idx
    return '\n'.join(result)


# ── URL 内容获取 ─────────────────────────────────────────────────────────────

def _fetch_content(url_or_path: str, timeout: int = 15) -> Tuple[str, str]:
    """
    获取 URL 或本地文件内容。

    Returns:
        (content: str, source_name: str)
    """
    if url_or_path.startswith(('http://', 'https://')):
        # GitHub blob URL → 转换为 raw URL
        url = url_or_path.replace(
            'github.com/', 'raw.githubusercontent.com/'
        ).replace('/blob/', '/')

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "MMS-SeedAbsorber/2.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode('utf-8', errors='replace')
                source_name = url.rstrip('/').split('/')[-1]
                return content, source_name
        except urllib.error.HTTPError as e:
            raise ValueError(f"HTTP {e.code} 获取失败: {url}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ValueError(f"网络错误: {e}") from e
    else:
        # 本地文件
        p = Path(url_or_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {url_or_path}")
        return p.read_text(encoding='utf-8', errors='replace'), p.name


def _derive_seed_name(source_name: str) -> str:
    """从文件名推导种子包名称。"""
    name = Path(source_name).stem
    name = re.sub(r'[^\w]', '_', name.lower())
    name = re.sub(r'_+', '_', name).strip('_')
    return name or 'absorbed_rules'


# ── LLM 蒸馏 ────────────────────────────────────────────────────────────────

_DISTILL_PROMPT = """\
你是一个架构规范蒸馏专家。请将以下企业开发规范（可能来自 .cursorrules / .mdc / 文档）
蒸馏为 MMS 兼容的 YAML 格式。

【输入规范内容】
{content}

【输出要求】
请输出三个 YAML 块，用 `---SECTION: arch_schema`, `---SECTION: ontology`, `---SECTION: constraints` 分隔。

1. arch_schema/layers.yaml：从规范中提取分层信息（如 Service/Repository/Controller 等）
   - 每层包含：id, name, keywords, path_prefixes, description
   - 若无明确分层信息，输出空列表 layers_override: []

2. ontology/core_objects.yaml：提取规范中提到的核心业务概念/设计模式
   - 每个对象包含：id, description, attributes（可选）
   - 至少提取 2-5 个核心概念

3. constraints/hard_rules.yaml：提取强制性规则（MUST/禁止/必须等）
   - 每条规则包含：id, description, pattern（正则）, scope（文件路径模式）, severity（ERROR/WARN/CRITICAL）
   - 至少提取 3-5 条最重要的规则

【重要约束】
- 只输出 YAML，不要解释和注释
- 去掉自然语言噪声，保留技术约束的核心
- 规则的 pattern 字段必须是可在代码中搜索的正则表达式
- 使用中文 description
"""

_FALLBACK_YAML = """\
---SECTION: arch_schema
layers_override: []

---SECTION: ontology
object_types:
  - id: IngestedConcept
    description: 从外部规范吸收的概念（LLM 不可用时的占位符，请手动补充）

---SECTION: constraints
rules:
  - id: placeholder_rule
    description: 从外部规范吸收的规则（LLM 不可用时的占位符，请手动补充）
    pattern: "TODO"
    severity: WARN
"""


def _distill_with_llm(cleaned_content: str) -> str:
    """调用 qwen3-32b 蒸馏规范内容。LLM 不可用时返回占位 YAML。"""
    prompt = _DISTILL_PROMPT.format(content=cleaned_content[:6000])
    try:
        from mms.providers.factory import auto_detect  # type: ignore[import]
        provider = auto_detect("intent_classification")
        return provider.complete(prompt, max_tokens=4096)
    except Exception:
        return _FALLBACK_YAML


def _parse_sections(llm_output: str) -> dict:
    """解析 LLM 输出的三个 YAML 块。"""
    sections = {'arch_schema': '', 'ontology': '', 'constraints': ''}
    current = None
    buffer: list = []

    for line in llm_output.split('\n'):
        m = re.match(r'^---SECTION:\s*(\w+)', line.strip())
        if m:
            if current and buffer:
                sections[current] = '\n'.join(buffer).strip()
            current = m.group(1)
            buffer = []
        elif current:
            buffer.append(line)

    if current and buffer:
        sections[current] = '\n'.join(buffer).strip()

    return sections


# ── 主函数 ──────────────────────────────────────────────────────────────────

def ingest(
    url_or_path: str,
    seed_name: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> Path:
    """
    Rule Absorber 主入口。

    Args:
        url_or_path: URL 或本地文件路径
        seed_name:   目标种子包名称（默认从文件名推导）
        dry_run:     True = 只打印不写文件
        force:       True = 允许覆盖已有种子包

    Returns:
        生成的种子包目录路径
    """
    print(f"  🔍 获取内容：{url_or_path}")
    content, source_name = _fetch_content(url_or_path)
    print(f"  📄 原始内容：{len(content)} 字符")

    # 清洗
    cleaned = clean_noise(content)
    extracted = extract_rule_sections(cleaned)
    print(f"  🧹 清洗后：{len(extracted)} 字符（去除 {len(content) - len(extracted)} 字符噪声）")

    if not seed_name:
        seed_name = _derive_seed_name(source_name)
    print(f"  📦 目标种子包：{seed_name}")

    seed_dir = _ROOT / 'seed_packs' / seed_name

    if seed_dir.exists() and not force:
        print(f"  ⚠️  种子包 {seed_name} 已存在（使用 --force 覆盖）")
        return seed_dir

    # LLM 蒸馏
    print(f"  🤖 调用 qwen3-32b 蒸馏规范...")
    llm_output = _distill_with_llm(extracted)
    sections = _parse_sections(llm_output)

    if dry_run:
        print("\n  [dry-run] 生成的 YAML 内容：")
        for sec, content_yaml in sections.items():
            print(f"\n  --- {sec} ---")
            print(content_yaml[:300] + ('...' if len(content_yaml) > 300 else ''))
        return seed_dir

    # 写入文件
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / 'docs').mkdir(exist_ok=True)
    (seed_dir / 'docs' / 'memory').mkdir(exist_ok=True)

    # match_conditions.yaml
    (seed_dir / 'match_conditions.yaml').write_text(
        f"stack_id: {seed_name}\n"
        f"description: \"从 {source_name} 吸收的规范（Rule Absorber）\"\n"
        f"always_inject: false\n"
        f"source_url: \"{url_or_path}\"\n"
        f"match_conditions:\n  []\n",
        encoding='utf-8',
    )

    filenames = {
        'arch_schema': 'layers.yaml',
        'ontology': 'core_objects.yaml',
        'constraints': 'hard_rules.yaml',
    }
    for sec_name, yaml_content in sections.items():
        subdir = seed_dir / sec_name
        subdir.mkdir(exist_ok=True)
        (subdir / filenames[sec_name]).write_text(
            f"# {sec_name}/{filenames[sec_name]}\n"
            f"# 由 Rule Absorber 从 {source_name} 蒸馏生成\n\n"
            + yaml_content + '\n',
            encoding='utf-8',
        )

    print(f"  ✅ 种子包已生成：{seed_dir.relative_to(_ROOT)}")
    return seed_dir
