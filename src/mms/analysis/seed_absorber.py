"""
seed_absorber.py v2 — Rule Absorber（规则吸收器）

将 GitHub 上的 .cursorrules / .mdc 企业规范离线蒸馏为 MMS 兼容格式。

v2 重点改进：
  1. 噪声清洗 v2：代码块感知，保留 ❌/✅ 示例，不误删 # 标题
  2. LLM 降级分级处理：区分 Pending / 失败 / 不可用，明确提示用户
  3. 输出格式双轨：
       - v2 格式（旧）：seed_packs/{name}/arch_schema/ + ontology/ + constraints/
       - v3.1 格式（新）：docs/memory/seed_packs/{name}/ 含 meta.yaml + constraints.yaml + memories/AC-*.md
  4. 批量吸收：ingest_batch() 支持列表 + GitHub 目录 URL

用法：
  mulan seed ingest <url> [--seed-name NAME] [--dry-run] [--format v31]
  mulan seed ingest-batch <url1> <url2> ... [--filter keyword] [--format v31]
"""
from __future__ import annotations

import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, List

_HERE = Path(__file__).resolve().parent
try:
    from mms.utils._paths import _PROJECT_ROOT as _ROOT
except ImportError:
    _ROOT = _HERE.parent.parent.parent


# ── 噪声清洗器 v2（代码块感知）────────────────────────────────────────────────

_RULE_INDICATORS = [
    r'\b(MUST|MUST NOT|SHALL|SHALL NOT|REQUIRED|FORBIDDEN|ALWAYS|NEVER|DO NOT)\b',
    r'\b(prohibit|enforce|require|mandate|constraint|rule|guideline|standard)\b',
    r'(?:^|\n)\s*[-*]\s+(?:No |Don\'t |Never |Always |Must )',
    r'(?:^|\n)#+\s+(?:Rules|Constraints|Guidelines|Standards|Conventions)',
    # .mdc 格式的规则标记
    r'[❌✅]\s+(?:BAD|GOOD|DON\'T|DO)',
]
_RULE_RE = re.compile('|'.join(_RULE_INDICATORS), re.IGNORECASE)

# 纯说明性段落的信号：长句子、无技术关键词
_PROSE_SIGNALS = re.compile(
    r'^(?:This|The|For|In|When|Use|To|A |An |We |Our |It |By |With |These |Those )',
    re.IGNORECASE,
)
_TECH_SIGNALS = re.compile(
    r'[`\'"][\w./]+[`\'"]|import |class |def |func |const |var |let |@\w+|<[A-Z]|\w+\(\)',
)


def clean_noise(raw: str) -> str:
    """
    v2 噪声清洗器：代码块感知，保留 ❌/✅ BAD/GOOD 示例与标题。

    策略（与 v1 不同）：
      - 代码块内所有内容全部保留（不做任何删除）
      - # 开头的 Markdown 标题全部保留
      - 含 ❌/✅ 或规则关键词的行全部保留
      - YAML Front Matter（--- ... ---）直接丢弃
      - 只删除纯 prose 段落（无技术信号、超过 100 字）
    """
    # 去除 YAML front matter
    raw = re.sub(r'^---\n.*?\n---\n', '', raw, flags=re.DOTALL)

    lines = raw.split('\n')
    result: List[str] = []
    in_code_block = False

    for line in lines:
        # 代码块边界检测
        if re.match(r'^\s*```', line):
            in_code_block = not in_code_block
            result.append(line)
            continue

        if in_code_block:
            result.append(line)
            continue

        stripped = line.strip()

        # 空行：保留（用于段落分隔）
        if not stripped:
            result.append(line)
            continue

        # Markdown 标题：全部保留
        if stripped.startswith('#'):
            result.append(line)
            continue

        # 含规则信号或 ❌/✅：保留
        if _RULE_RE.search(line) or '❌' in line or '✅' in line:
            result.append(line)
            continue

        # 含技术信号（代码引用、函数调用）：保留
        if _TECH_SIGNALS.search(line):
            result.append(line)
            continue

        # 纯 prose 说明段落（长句、以"This/The/For..."开头，无技术内容）：丢弃
        if len(stripped) > 80 and _PROSE_SIGNALS.match(stripped):
            continue

        result.append(line)

    # 合并连续空行（>2 行 → 1 行）
    text = '\n'.join(result)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_rule_sections(text: str, max_chars: int = 8000) -> str:
    """
    v2：保留含规则信号的段落，附带代码块上下文（前后各 5 行）。
    如果没有检测到规则信号，返回原文前 max_chars 字符（不截断）。
    """
    lines = text.split('\n')
    keep: set = set()
    in_code = False
    code_start = -1

    # 先标记代码块范围
    code_ranges: List[Tuple[int, int]] = []
    for i, line in enumerate(lines):
        if re.match(r'^\s*```', line):
            if not in_code:
                in_code = True
                code_start = i
            else:
                in_code = False
                code_ranges.append((code_start, i))

    # 找含规则信号的行，扩展前后 5 行 + 附近完整代码块
    for i, line in enumerate(lines):
        if _RULE_RE.search(line) or '❌' in line or '✅' in line:
            ctx_start = max(0, i - 5)
            ctx_end = min(len(lines), i + 15)
            for j in range(ctx_start, ctx_end):
                keep.add(j)
            # 找最近的代码块并包含
            for cs, ce in code_ranges:
                if abs(cs - i) < 20:
                    for k in range(cs, ce + 1):
                        keep.add(k)

    if not keep:
        return text[:max_chars]

    result = []
    prev = -1
    for idx in sorted(keep):
        if prev != -1 and idx > prev + 1:
            result.append('...')
        result.append(lines[idx])
        prev = idx

    extracted = '\n'.join(result)
    return extracted[:max_chars]


# ── URL 内容获取 ─────────────────────────────────────────────────────────────

def _fetch_content(url_or_path: str, timeout: int = 15) -> Tuple[str, str]:
    """
    获取 URL 或本地文件内容。

    Returns:
        (content: str, source_name: str)
    """
    if url_or_path.startswith(('http://', 'https://')):
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
        p = Path(url_or_path)
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {url_or_path}")
        return p.read_text(encoding='utf-8', errors='replace'), p.name


def _fetch_github_dir_listing(dir_url: str) -> List[dict]:
    """
    获取 GitHub 目录的文件列表（通过 API）。
    dir_url 形如：https://github.com/user/repo/tree/main/path/to/dir
    """
    # 将 tree URL 转为 API URL
    # https://github.com/user/repo/tree/main/path → https://api.github.com/repos/user/repo/contents/path?ref=main
    m = re.match(
        r'https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/?(.*)',
        dir_url
    )
    if not m:
        raise ValueError(f"无法解析 GitHub 目录 URL：{dir_url}")
    owner, repo, ref, path = m.groups()
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={ref}"

    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "MMS-SeedAbsorber/2.0", "Accept": "application/vnd.github.v3+json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        import json
        return json.loads(resp.read().decode('utf-8'))


def _derive_seed_name(source_name: str) -> str:
    """从文件名推导种子包名称。"""
    name = Path(source_name).stem
    name = re.sub(r'[^\w]', '_', name.lower())
    name = re.sub(r'_+', '_', name).strip('_')
    return name or 'absorbed_rules'


# ── LLM 蒸馏 v2 ──────────────────────────────────────────────────────────────

_DISTILL_PROMPT_V2 = """\
你是一个架构规范蒸馏专家。请将以下企业开发规范（来自 .cursorrules / .mdc）
蒸馏为 MMS v3.1 兼容的种子记忆格式。

【输入规范内容】
{content}

【输出要求】
输出两个部分，用 `---SECTION: constraints_yaml` 和 `---SECTION: memories_md` 分隔。

**第一部分：constraints.yaml**（用于 arch_check 静态扫描）
格式：
```yaml
rules:
  - id: AC-{NAME}-01
    description: "规则中文描述"
    pattern: "可在代码中搜索的正则表达式"
    scope: "**/*.py"  # 适用文件范围
    severity: ERROR  # ERROR / WARN / INFO
```
要求：提取 3-6 条最重要的强制性约束（MUST/禁止/不得等）。

**第二部分：memories_md**（用于 hybrid_search 检索）
为每条约束生成一个 Markdown 记忆文件，格式：
```
===FILE: AC-{NAME}-01.md===
---
id: AC-{NAME}-01
tier: hot
layer: L2
protection_bonus: 0.3
tags: [python, {technology}, architecture]
---
# AC-{NAME}-01：规则标题

## 约束
[规则的核心约束，一句话]

## 反例（Anti-pattern）
```python
# 错误做法
```

## 正例（Correct Pattern）
```python
# 正确做法
```

## 原因
[为什么这个约束重要]
===END===
```

【重要约束】
- id 格式：AC-大写技术名缩写-两位数字（如 AC-SQLALCH-01, AC-REDIS-01）
- 只输出代码，不要额外解释
- severity 为 ERROR 的规则才值得进入 hot tier
"""

_FALLBACK_YAML = """\
---SECTION: constraints_yaml
rules:
  - id: AC-ABSORBED-01
    description: 从外部规范吸收的规则（LLM 不可用时的占位符，请手动补充）
    pattern: "TODO"
    scope: "**/*"
    severity: WARN

---SECTION: memories_md
===FILE: AC-ABSORBED-01.md===
---
id: AC-ABSORBED-01
tier: warm
layer: CC
protection_bonus: 0.1
tags: [absorbed, placeholder]
---
# AC-ABSORBED-01：LLM 不可用时的占位记忆

## 约束
LLM 不可用，规则未能自动蒸馏。请手动填写。

## 原因
seed_absorber 在 LLM 不可用时生成此占位符，需要人工补充实际约束内容。
===END===
"""


def _distill_with_llm(cleaned_content: str) -> Tuple[str, str]:
    """
    调用 LLM 蒸馏规范内容。

    Returns:
        (output: str, status: "ok" | "pending" | "fallback")

    v2 改进：区分 pending / 失败，给出明确提示而非静默返回占位符。
    """
    prompt = _DISTILL_PROMPT_V2.format(content=cleaned_content[:8000])

    try:
        from mms.providers.factory import auto_detect  # type: ignore[import]
        provider = auto_detect("intent_classification")
        result = provider.complete(prompt, max_tokens=4096)
        return result, "ok"

    except Exception as e:
        err_str = str(e)
        # 检测 Claude Pending 模式
        if "pending" in err_str.lower() or "ProviderPendingError" in type(e).__name__:
            # 提取 pending 文件路径
            path_match = re.search(r'(/[^\n]+\.md)', err_str)
            pending_path = path_match.group(1) if path_match else "（见上方输出）"
            print(f"\n  ⏳ LLM 处于 Pending 模式，prompt 已保存至:")
            print(f"     {pending_path}")
            print(f"  💡 在 Cursor 中执行 prompt 后，规则将自动蒸馏。")
            print(f"  📝 也可使用 --format v31-manual 手动写入种子记忆。")
            return _FALLBACK_YAML, "pending"
        else:
            print(f"\n  ⚠️  LLM 调用失败 ({type(e).__name__}: {str(e)[:80]})")
            print(f"  📝 生成占位符模板，请手动补充约束内容。")
            return _FALLBACK_YAML, "fallback"


def _parse_sections_v2(llm_output: str) -> dict:
    """解析 v2 LLM 输出（constraints_yaml + memories_md）。"""
    sections: dict = {'constraints_yaml': '', 'memories_md': ''}
    current = None
    buffer: List[str] = []

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


def _parse_memory_files(memories_md: str) -> List[Tuple[str, str]]:
    """
    解析 memories_md 中的多个 AC-*.md 文件块。

    Returns:
        List of (filename, content)
    """
    files: List[Tuple[str, str]] = []
    pattern = re.compile(r'===FILE:\s*([^\s=]+)===\n(.*?)===END===', re.DOTALL)
    for m in pattern.finditer(memories_md):
        fname = m.group(1).strip()
        content = m.group(2).strip()
        files.append((fname, content))
    return files


# ── v3.1 格式写入 ────────────────────────────────────────────────────────────

def _write_v31_format(
    seed_name: str,
    source_name: str,
    source_url: str,
    sections: dict,
    dry_run: bool = False,
) -> Path:
    """
    将蒸馏结果写入 docs/memory/seed_packs/{seed_name}/ 格式（v3.1）。

    目录结构：
        docs/memory/seed_packs/{seed_name}/
        ├── meta.yaml
        ├── constraints.yaml
        └── memories/
            ├── AC-{NAME}-01.md
            └── AC-{NAME}-02.md
    """
    seed_dir = _ROOT / 'docs' / 'memory' / 'seed_packs' / seed_name

    # 生成 meta.yaml 内容
    meta_content = f"""\
# {seed_name} 种子包元数据
# 由 Rule Absorber v2 从 {source_name} 蒸馏生成
stack_id: {seed_name}
source_url: "{source_url}"
generated_at: "{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
description: "从 {source_name} 吸收的规范（Rule Absorber v2）"
layer_affinity: CC
always_inject: false
"""

    constraints_content = f"""\
# {seed_name}/constraints.yaml
# 由 Rule Absorber v2 从 {source_name} 蒸馏生成
# 可被 arch_check.py 直接加载进行静态扫描

{sections.get('constraints_yaml', '# LLM 未生成约束，请手动补充\nrules: []')}
"""

    memory_files = _parse_memory_files(sections.get('memories_md', ''))

    if dry_run:
        print(f"\n  [dry-run v3.1 格式] 目标目录：{seed_dir.relative_to(_ROOT)}")
        print(f"\n  --- meta.yaml ---")
        print(meta_content[:300])
        print(f"\n  --- constraints.yaml (前 400 chars) ---")
        print(constraints_content[:400])
        print(f"\n  --- memories/ ({len(memory_files)} 个文件) ---")
        for fname, content in memory_files[:2]:
            print(f"    {fname}: {len(content)} chars")
        return seed_dir

    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / 'meta.yaml').write_text(meta_content, encoding='utf-8')
    (seed_dir / 'constraints.yaml').write_text(constraints_content, encoding='utf-8')

    mem_dir = seed_dir / 'memories'
    mem_dir.mkdir(exist_ok=True)
    for fname, content in memory_files:
        (mem_dir / fname).write_text(content, encoding='utf-8')

    return seed_dir


# ── v2 格式写入（保留向后兼容）──────────────────────────────────────────────

def _parse_sections(llm_output: str) -> dict:
    """解析旧版 LLM 输出（arch_schema / ontology / constraints 三块）。"""
    sections = {'arch_schema': '', 'ontology': '', 'constraints': ''}
    current = None
    buffer: List[str] = []

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


def _write_v2_format(
    seed_name: str,
    source_name: str,
    url_or_path: str,
    sections: dict,
    dry_run: bool = False,
) -> Path:
    """写入旧版 seed_packs/{name}/ 格式（向后兼容）。"""
    seed_dir = _ROOT / 'seed_packs' / seed_name

    if dry_run:
        print(f"\n  [dry-run v2 格式] 目标目录：seed_packs/{seed_name}/")
        for sec, content in sections.items():
            print(f"\n  --- {sec} ---")
            print((content or '（空）')[:300] + ('...' if len(content or '') > 300 else ''))
        return seed_dir

    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / 'docs').mkdir(exist_ok=True)
    (seed_dir / 'docs' / 'memory').mkdir(exist_ok=True)

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
            f"# 由 Rule Absorber v2 从 {source_name} 蒸馏生成\n\n"
            + (yaml_content or '') + '\n',
            encoding='utf-8',
        )

    return seed_dir


# ── 主函数 ───────────────────────────────────────────────────────────────────

def ingest(
    url_or_path: str,
    seed_name: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    output_format: str = "v31",  # "v31" | "v2"
) -> Path:
    """
    Rule Absorber 主入口（单文件）。

    Args:
        url_or_path:    URL 或本地文件路径
        seed_name:      目标种子包名称（默认从文件名推导）
        dry_run:        True = 只打印不写文件
        force:          True = 允许覆盖已有种子包
        output_format:  "v31"（推荐）或 "v2"（向后兼容）

    Returns:
        生成的种子包目录路径
    """
    print(f"  🔍 获取内容：{url_or_path}")
    content, source_name = _fetch_content(url_or_path)
    print(f"  📄 原始内容：{len(content)} 字符")

    # v2 清洗
    cleaned = clean_noise(content)
    extracted = extract_rule_sections(cleaned)
    retained_pct = int(len(extracted) / max(len(content), 1) * 100)
    print(f"  🧹 清洗后：{len(extracted)} 字符（保留 {retained_pct}%，去除 {len(content) - len(extracted)} 字符噪声）")

    if not seed_name:
        seed_name = _derive_seed_name(source_name)
    print(f"  📦 目标种子包：{seed_name}  [格式: {output_format}]")

    # 检查是否已存在
    if output_format == "v31":
        target_dir = _ROOT / 'docs' / 'memory' / 'seed_packs' / seed_name
    else:
        target_dir = _ROOT / 'seed_packs' / seed_name

    if target_dir.exists() and not force and not dry_run:
        print(f"  ⚠️  种子包已存在：{target_dir.relative_to(_ROOT)}（使用 --force 覆盖）")
        return target_dir

    # LLM 蒸馏
    print(f"  🤖 调用 LLM 蒸馏规范...")
    llm_output, status = _distill_with_llm(extracted)

    status_icon = {"ok": "✅", "pending": "⏳", "fallback": "⚠️ "}.get(status, "?")
    print(f"  {status_icon} LLM 蒸馏状态：{status}")

    # 写入输出
    if output_format == "v31":
        sections = _parse_sections_v2(llm_output)
        return _write_v31_format(seed_name, source_name, url_or_path, sections, dry_run)
    else:
        sections = _parse_sections(llm_output)
        return _write_v2_format(seed_name, source_name, url_or_path, sections, dry_run)


def ingest_batch(
    urls: List[str],
    seed_prefix: str = "",
    dry_run: bool = False,
    force: bool = False,
    output_format: str = "v31",
    name_filter: Optional[str] = None,
) -> List[Path]:
    """
    批量吸收多个规则 URL。

    Args:
        urls:         规则文件 URL 列表（或 GitHub 目录 URL）
        seed_prefix:  种子包名称前缀（如 "absorbed_"）
        dry_run:      只预览不写文件
        force:        覆盖已有种子包
        output_format: "v31" 或 "v2"
        name_filter:  只处理文件名包含此关键词的规则（逗号分隔多个）

    Returns:
        List of generated seed pack directories
    """
    # 如果是 GitHub 目录 URL，先展开文件列表
    expanded_urls: List[str] = []
    for url in urls:
        if 'github.com' in url and '/tree/' in url:
            print(f"\n  📂 获取目录列表：{url}")
            try:
                entries = _fetch_github_dir_listing(url)
                for entry in entries:
                    if entry.get('type') == 'file' and entry['name'].endswith(('.mdc', '.md', '.cursorrules')):
                        expanded_urls.append(entry['download_url'])
                print(f"  📋 发现 {len(expanded_urls)} 个规则文件")
            except Exception as e:
                print(f"  ❌ 目录获取失败：{e}")
        else:
            expanded_urls.append(url)

    # 应用过滤器
    if name_filter:
        filters = [f.strip().lower() for f in name_filter.split(',')]
        filtered = [u for u in expanded_urls if any(f in u.lower() for f in filters)]
        print(f"  🔍 过滤后：{len(filtered)}/{len(expanded_urls)} 个规则（过滤词：{name_filter}）")
        expanded_urls = filtered

    results: List[Path] = []
    total = len(expanded_urls)

    for i, url in enumerate(expanded_urls, 1):
        print(f"\n{'─'*60}")
        print(f"  [{i}/{total}] {url.split('/')[-1]}")
        try:
            seed_name = seed_prefix + _derive_seed_name(url.split('/')[-1])
            result = ingest(url, seed_name=seed_name, dry_run=dry_run,
                          force=force, output_format=output_format)
            results.append(result)
        except Exception as e:
            print(f"  ❌ 失败：{e}")

    print(f"\n{'='*60}")
    print(f"  批量吸收完成：{len(results)}/{total} 成功")
    return results
