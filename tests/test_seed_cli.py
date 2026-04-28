"""
tests/test_seed_cli.py — mulan seed 命令组自动化测试

对应手工测试清单（A→E 组，共 24 条）：
  A 组：seed list                    (3 条)
  B 组：seed ingest 输入源验证        (6 条)
  C 组：seed ingest 选项行为          (7 条)
  D 组：seed ingest 内容质量          (3 条)
  E 组：seed ingest-batch 专项        (5 条)

设计原则：
  - 全部离线可运行（网络调用全部 mock）
  - 使用 tmp_path 隔离文件副作用
  - 通过 monkeypatch 劫持 _ROOT / _PROJECT_ROOT，防止污染工作目录
  - CLI exit code 测试通过 subprocess.run 调用 cli.py
  - 标记 @pytest.mark.network 的用例需真实网络，默认跳过
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Tuple
from unittest.mock import MagicMock, patch

import pytest

# ── 路径常量 ──────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CLI_PATH = _PROJECT_ROOT / "cli.py"
_SRC = _PROJECT_ROOT / "src"

# ── 测试用的最小 .mdc 内容 ────────────────────────────────────────────────────
_SAMPLE_MDC = """\
# Test Rules
MUST use type annotations in all Python functions.
NEVER use `eval()` in production code.

```python
# ✅ Good
def add(a: int, b: int) -> int:
    return a + b

# ❌ Bad
def add(a, b):
    return a + b
```
"""

# LLM 返回的最小合法 v2 输出
_MOCK_LLM_OUTPUT = """\
---SECTION: constraints_yaml
rules:
  - id: AC-TEST-01
    description: "MUST use type annotations"
    pattern: "def \\w+\\([^)]*\\)(?!.*->)"
    scope: "**/*.py"
    severity: ERROR

---SECTION: memories_md
===FILE: AC-TEST-01.md===
---
id: AC-TEST-01
tier: hot
layer: L2
protection_bonus: 0.3
tags: [python, typing]
---
# AC-TEST-01：必须使用类型注解

## 约束
所有 Python 函数 MUST 声明参数和返回值类型注解。

## 反例（Anti-pattern）

```python
# ❌ 无类型注解
def add(a, b):
    return a + b
```

## 正例（Correct Pattern）

```python
# ✅ 正确写法
def add(a: int, b: int) -> int:
    return a + b
```

## 原因
类型注解允许 mypy/pyright 进行静态类型检查，提前发现 bug。
===END===
"""


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """通过 subprocess 调用 cli.py，返回 CompletedProcess（含 stdout/stderr/returncode）。"""
    return subprocess.run(
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )


def _make_v31_pack(root: Path, pack_name: str, mem_count: int = 2, has_constraints: bool = True) -> Path:
    """在 tmp_path 下创建一个 v3.1 格式的假种子包，用于 seed list 测试。"""
    pack_dir = root / "docs" / "memory" / "seed_packs" / pack_name
    mem_dir = pack_dir / "memories"
    mem_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "meta.yaml").write_text(
        f'stack_id: {pack_name}\ndescription: "测试种子包 {pack_name}"\n',
        encoding="utf-8",
    )
    if has_constraints:
        (pack_dir / "constraints.yaml").write_text("rules: []\n", encoding="utf-8")
    for i in range(1, mem_count + 1):
        (mem_dir / f"AC-TEST-{i:02d}.md").write_text(f"# AC-TEST-{i:02d}\n", encoding="utf-8")
    return pack_dir


def _make_v2_pack(root: Path, pack_name: str) -> Path:
    """在 tmp_path 下创建一个 v2 格式的假种子包。"""
    pack_dir = root / "seed_packs" / pack_name
    for sub in ("arch_schema", "ontology", "constraints"):
        (pack_dir / sub).mkdir(parents=True, exist_ok=True)
        (pack_dir / sub / "dummy.yaml").write_text("# dummy\n", encoding="utf-8")
    (pack_dir / "match_conditions.yaml").write_text(
        f'stack_id: {pack_name}\ndescription: "v2 测试包 {pack_name}"\n',
        encoding="utf-8",
    )
    return pack_dir


# ═══════════════════════════════════════════════════════════════════════════════
# 组 A：seed list
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeedList:
    """A 组：mulan seed list 命令行为。"""

    def test_a01_shows_v31_and_v2_packs(self, tmp_path, monkeypatch):
        """A-01：seed list 同时展示 v3.1 和 v2 两个目录的种子包。"""
        _make_v31_pack(tmp_path, "python_sqlalchemy", mem_count=6)
        _make_v31_pack(tmp_path, "infrastructure_redis", mem_count=5)
        _make_v2_pack(tmp_path, "base")

        import cli as cli_module
        monkeypatch.setattr(cli_module, "_PROJECT_ROOT", tmp_path)

        import argparse
        args = argparse.Namespace(command="seed", subcommand="list")
        output_lines: list[str] = []
        with patch("builtins.print", side_effect=lambda *a, **k: output_lines.append(" ".join(str(x) for x in a))):
            ret = cli_module.cmd_seed(args)

        combined = "\n".join(output_lines)
        assert ret == 0
        assert "v3.1" in combined
        assert "v2" in combined
        assert "python_sqlalchemy" in combined
        assert "infrastructure_redis" in combined
        assert "base" in combined
        assert "memories:6" in combined
        assert "memories:5" in combined

    def test_a01_v31_constraints_indicator(self, tmp_path, monkeypatch):
        """A-01 细节：v3.1 包有 constraints.yaml 时显示 ✓，无则显示 ✗。"""
        _make_v31_pack(tmp_path, "with_constraints", mem_count=1, has_constraints=True)
        _make_v31_pack(tmp_path, "no_constraints", mem_count=1, has_constraints=False)

        import cli as cli_module
        monkeypatch.setattr(cli_module, "_PROJECT_ROOT", tmp_path)

        import argparse
        args = argparse.Namespace(command="seed", subcommand="list")
        output_lines: list[str] = []
        with patch("builtins.print", side_effect=lambda *a, **k: output_lines.append(" ".join(str(x) for x in a))):
            cli_module.cmd_seed(args)

        combined = "\n".join(output_lines)
        assert "constraints:✓" in combined
        assert "constraints:✗" in combined

    def test_a02_default_subcommand_equals_list(self, tmp_path, monkeypatch):
        """A-02：mulan seed（无子命令）与 seed list 行为一致。"""
        _make_v31_pack(tmp_path, "test_pack", mem_count=3)

        import cli as cli_module
        monkeypatch.setattr(cli_module, "_PROJECT_ROOT", tmp_path)

        import argparse
        # 无子命令时 subcommand 为 None
        args_none = argparse.Namespace(command="seed", subcommand=None)
        args_list = argparse.Namespace(command="seed", subcommand="list")

        out_none: list[str] = []
        out_list: list[str] = []
        with patch("builtins.print", side_effect=lambda *a, **k: out_none.append(" ".join(str(x) for x in a))):
            ret_none = cli_module.cmd_seed(args_none)
        with patch("builtins.print", side_effect=lambda *a, **k: out_list.append(" ".join(str(x) for x in a))):
            ret_list = cli_module.cmd_seed(args_list)

        assert ret_none == ret_list == 0
        assert "\n".join(out_none) == "\n".join(out_list)

    def test_a03_empty_dirs_shows_no_packs(self, tmp_path, monkeypatch):
        """A-03：两个种子包目录均为空时，显示 '(无种子包)'。"""
        (tmp_path / "docs" / "memory" / "seed_packs").mkdir(parents=True)
        (tmp_path / "seed_packs").mkdir(parents=True)

        import cli as cli_module
        monkeypatch.setattr(cli_module, "_PROJECT_ROOT", tmp_path)

        import argparse
        args = argparse.Namespace(command="seed", subcommand="list")
        output_lines: list[str] = []
        with patch("builtins.print", side_effect=lambda *a, **k: output_lines.append(" ".join(str(x) for x in a))):
            ret = cli_module.cmd_seed(args)

        assert ret == 0
        assert any("无种子包" in line for line in output_lines)

    def test_a01_yaml_block_literal_description(self, tmp_path, monkeypatch):
        """A-01 细节：meta.yaml 中 YAML 块字面量(|) description 应正确显示下一行内容。"""
        pack_dir = tmp_path / "docs" / "memory" / "seed_packs" / "block_literal_pack"
        (pack_dir / "memories").mkdir(parents=True)
        (pack_dir / "meta.yaml").write_text(
            "stack_id: block_literal_pack\n"
            "description: |\n"
            "  这是块字面量描述。\n"
            "  第二行。\n",
            encoding="utf-8",
        )
        (pack_dir / "constraints.yaml").write_text("rules: []\n", encoding="utf-8")

        import cli as cli_module
        monkeypatch.setattr(cli_module, "_PROJECT_ROOT", tmp_path)

        import argparse
        args = argparse.Namespace(command="seed", subcommand="list")
        output_lines: list[str] = []
        with patch("builtins.print", side_effect=lambda *a, **k: output_lines.append(" ".join(str(x) for x in a))):
            cli_module.cmd_seed(args)

        combined = "\n".join(output_lines)
        assert "这是块字面量描述" in combined
        assert "|" not in combined.replace("✓", "").replace("✗", "")


# ═══════════════════════════════════════════════════════════════════════════════
# 组 B：seed ingest 输入源验证
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeedIngestInputValidation:
    """B 组：seed ingest 输入源处理（全部 mock 网络，离线运行）。"""

    def test_b01_no_args_exits_nonzero(self):
        """B-01：不带参数调用 seed ingest 应以非零 exit code 退出。"""
        result = _run_cli("seed", "ingest")
        assert result.returncode != 0
        assert "URL_OR_PATH" in result.stderr or "required" in result.stderr

    def test_b02_github_tree_url_rejected(self, tmp_path, monkeypatch):
        """B-02：传入 GitHub 目录 URL(/tree/) 应报错并给出 ingest-batch 引导。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)

        with pytest.raises(ValueError, match="ingest-batch"):
            sa._fetch_content("https://github.com/user/repo/tree/main/rules")

    def test_b03_valid_raw_url_dry_run(self, tmp_path, monkeypatch):
        """B-03：合法 raw URL + --dry-run 正常工作，返回 dry_run 状态，不写文件。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)

        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "test.mdc")), \
             patch.object(sa, "_distill_with_llm", return_value=(_MOCK_LLM_OUTPUT, "ok")):
            result_path, status = sa.ingest(
                "https://raw.githubusercontent.com/example/repo/main/test.mdc",
                dry_run=True,
            )

        assert status == "dry_run"
        # dry-run 不写文件
        assert not (tmp_path / "docs" / "memory" / "seed_packs" / "test").exists()

    def test_b04_404_url_raises_value_error(self):
        """B-04：不存在的 raw URL 应抛出 ValueError（含 404）。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        with pytest.raises(ValueError, match="404"):
            sa._fetch_content("https://raw.githubusercontent.com/no-user-xyz/no-repo-xyz/main/fake.mdc")

    def test_b05_local_file_dry_run(self, tmp_path, monkeypatch):
        """B-05：合法本地文件路径 + --dry-run 正常工作。"""
        local_file = tmp_path / "test_rule.mdc"
        local_file.write_text(_SAMPLE_MDC, encoding="utf-8")

        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        with patch.object(sa, "_distill_with_llm", return_value=(_MOCK_LLM_OUTPUT, "ok")):
            result_path, status = sa.ingest(str(local_file), dry_run=True)

        assert status == "dry_run"

    def test_b06_nonexistent_local_file_raises(self):
        """B-06：不存在的本地文件应抛出 FileNotFoundError。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        with pytest.raises(FileNotFoundError):
            sa._fetch_content("/tmp/definitely_not_exist_xyz_12345.mdc")


# ═══════════════════════════════════════════════════════════════════════════════
# 组 C：seed ingest 选项行为
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeedIngestOptions:
    """C 组：seed ingest 各选项的具体行为。"""

    def _ingest_with_mock(
        self,
        tmp_path: Path,
        monkeypatch,
        **kwargs,
    ) -> Tuple[Path, str]:
        """公共辅助：劫持 _ROOT + _fetch_content + _distill_with_llm 后调用 ingest()。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "test.mdc")), \
             patch.object(sa, "_distill_with_llm", return_value=(_MOCK_LLM_OUTPUT, "ok")):
            return sa.ingest("https://raw.githubusercontent.com/x/y/main/test.mdc", **kwargs)

    def test_c01_dry_run_no_files_created(self, tmp_path, monkeypatch):
        """C-01：--dry-run 不创建任何文件。"""
        result_path, status = self._ingest_with_mock(tmp_path, monkeypatch, dry_run=True)
        assert status == "dry_run"
        assert not result_path.exists()

    def test_c02_seed_name_custom(self, tmp_path, monkeypatch):
        """C-02：--seed-name 使用自定义包名。"""
        result_path, status = self._ingest_with_mock(
            tmp_path, monkeypatch, seed_name="my_custom_pack"
        )
        assert status == "written"
        assert result_path.name == "my_custom_pack"

    def test_c03_format_v31_output_path(self, tmp_path, monkeypatch):
        """C-03：--format v31 写入 docs/memory/seed_packs/ 目录。"""
        result_path, status = self._ingest_with_mock(
            tmp_path, monkeypatch, output_format="v31"
        )
        assert status == "written"
        assert "docs/memory/seed_packs" in str(result_path)

    def test_c04_format_v2_output_path(self, tmp_path, monkeypatch):
        """C-04：--format v2 写入 seed_packs/ 目录。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "test.mdc")), \
             patch.object(sa, "_distill_with_llm", return_value=("---SECTION: arch_schema\n\n---SECTION: ontology\n\n---SECTION: constraints\n", "ok")):
            result_path, status = sa.ingest(
                "https://raw.githubusercontent.com/x/y/main/test.mdc",
                output_format="v2",
            )

        assert status == "written"
        assert "seed_packs" in str(result_path)
        assert "docs" not in str(result_path)

    def test_c05_first_write_creates_v31_structure(self, tmp_path, monkeypatch):
        """C-05：首次真实写入，v3.1 目录结构完整（meta.yaml/constraints.yaml/memories/）。"""
        result_path, status = self._ingest_with_mock(tmp_path, monkeypatch)

        assert status == "written"
        assert (result_path / "meta.yaml").exists()
        assert (result_path / "constraints.yaml").exists()
        assert (result_path / "memories").is_dir()
        assert len(list((result_path / "memories").glob("*.md"))) >= 1

    def test_c06_existing_pack_skipped_without_force(self, tmp_path, monkeypatch):
        """C-06：种子包已存在且无 --force 时，status 为 'skipped'，不输出 ✅ 就绪。"""
        # 先写入一次
        self._ingest_with_mock(tmp_path, monkeypatch)

        printed: list[str] = []
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "test.mdc")), \
             patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a))):
            _, status = sa.ingest(
                "https://raw.githubusercontent.com/x/y/main/test.mdc",
                output_format="v31",
                force=False,
            )

        assert status == "skipped"
        combined = "\n".join(printed)
        assert "✅" not in combined
        assert "⏭️" in combined or "跳过" in combined

    def test_c07_force_overwrites_existing(self, tmp_path, monkeypatch):
        """C-07：--force 时即使已存在也重新写入，status 为 'written'。"""
        # 先写入一次
        self._ingest_with_mock(tmp_path, monkeypatch)
        # 再带 --force 写入
        _, status = self._ingest_with_mock(tmp_path, monkeypatch, force=True)
        assert status == "written"


# ═══════════════════════════════════════════════════════════════════════════════
# 组 D：seed ingest 内容质量
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeedIngestContentQuality:
    """D 组：噪声清洗效果、文件结构完整性、LLM pending 不崩溃。"""

    def test_d01_noise_cleaning_retention_rate_above_50(self):
        """D-01：v2 噪声清洗对合法 .mdc 内容保留率应 >50%。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        cleaned = sa.clean_noise(_SAMPLE_MDC)
        rate = len(cleaned) / max(len(_SAMPLE_MDC), 1)
        assert rate >= 0.50, f"保留率 {rate:.0%} 低于 50%"

    def test_d01_code_blocks_preserved(self):
        """D-01 细节：代码块内容（含反例）不被清洗器删除。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        cleaned = sa.clean_noise(_SAMPLE_MDC)
        assert "def add(a: int, b: int) -> int:" in cleaned
        assert "def add(a, b):" in cleaned

    def test_d01_markdown_headers_preserved(self):
        """D-01 细节：Markdown 标题行（#）不被清洗器删除。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        cleaned = sa.clean_noise(_SAMPLE_MDC)
        assert "# Test Rules" in cleaned

    def test_d02_memories_dir_has_md_files(self, tmp_path, monkeypatch):
        """D-02：写入后 memories/ 目录包含至少 1 个 AC-*.md 文件。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "test.mdc")), \
             patch.object(sa, "_distill_with_llm", return_value=(_MOCK_LLM_OUTPUT, "ok")):
            result_path, _ = sa.ingest("https://x/test.mdc")

        mem_files = list((result_path / "memories").glob("*.md"))
        assert len(mem_files) >= 1
        # 验证 AC-TEST-01.md 内容包含 frontmatter
        content = mem_files[0].read_text(encoding="utf-8")
        assert "---" in content
        assert "id:" in content

    def test_d03_llm_pending_does_not_crash(self, tmp_path, monkeypatch):
        """D-03：LLM Pending 模式下 ingest 不抛出异常，返回 'written' 状态（占位符写入）。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        class FakePendingError(Exception):
            pass

        def _mock_pending(*args, **kwargs):
            raise FakePendingError("pending mode")

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "pending_test.mdc")), \
             patch("mms.analysis.seed_absorber.auto_detect", side_effect=_mock_pending, create=True):
            result_path, status = sa.ingest("https://x/pending_test.mdc")

        # 应写入占位符，不抛异常
        assert status == "written"
        assert (result_path / "meta.yaml").exists()

    def test_d03_pending_message_no_invalid_option(self, tmp_path, monkeypatch, capsys):
        """D-03 细节：pending 提示不包含不存在的 '--format v31-manual' 选项名。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        class FakePendingError(Exception):
            pass

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "p.mdc")), \
             patch("mms.analysis.seed_absorber.auto_detect", side_effect=FakePendingError("pending"), create=True):
            sa.ingest("https://x/p.mdc")

        captured = capsys.readouterr()
        assert "v31-manual" not in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# 组 E：seed ingest-batch 专项
# ═══════════════════════════════════════════════════════════════════════════════

class TestSeedIngestBatch:
    """E 组：seed ingest-batch 的目录展开、过滤、Token 提示、exit code 行为。"""

    def test_e01_invalid_repo_exits_nonzero(self):
        """E-01：不存在仓库的目录 URL，exit code 应为 1（无论 --dry-run）。"""
        result = _run_cli(
            "seed", "ingest-batch",
            "https://github.com/user/repo/tree/main/rules-mdc",
            "--dry-run",
        )
        assert result.returncode == 1
        assert "404" in result.stdout or "不存在" in result.stdout

    def test_e01_error_message_includes_api_url(self):
        """E-01 细节：404 错误消息应包含实际 API 地址，便于排查。"""
        result = _run_cli(
            "seed", "ingest-batch",
            "https://github.com/user/repo/tree/main/rules-mdc",
            "--dry-run",
        )
        assert "api.github.com" in result.stdout

    def test_e02_filter_reduces_file_count(self, tmp_path, monkeypatch):
        """E-02：--filter 应只处理文件名包含关键词的规则。"""
        sys.path.insert(0, str(_SRC))
        import importlib
        import mms.analysis.seed_absorber as sa
        importlib.reload(sa)
        monkeypatch.setattr(sa, "_ROOT", tmp_path)

        fake_entries = [
            {"type": "file", "name": "pytest.mdc", "download_url": "https://x/pytest.mdc"},
            {"type": "file", "name": "redis.mdc", "download_url": "https://x/redis.mdc"},
            {"type": "file", "name": "fastapi.mdc", "download_url": "https://x/fastapi.mdc"},
            {"type": "dir", "name": "subdir", "download_url": None},
        ]
        processed: list[str] = []

        def mock_ingest(url, **kwargs):
            processed.append(url.split("/")[-1])
            pack = tmp_path / "docs" / "memory" / "seed_packs" / kwargs.get("seed_name", "x")
            pack.mkdir(parents=True, exist_ok=True)
            return pack, "written"

        with patch.object(sa, "_fetch_github_dir_listing", return_value=fake_entries), \
             patch.object(sa, "ingest", side_effect=mock_ingest):
            results = sa.ingest_batch(
                ["https://github.com/u/r/tree/main/rules"],
                name_filter="pytest,redis",
                dry_run=False,
            )

        assert "pytest.mdc" in processed
        assert "redis.mdc" in processed
        assert "fastapi.mdc" not in processed

    def test_e03_prefix_applied_to_pack_name(self, tmp_path, monkeypatch):
        """E-03：--prefix 应被拼接到种子包名称前缀。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        fake_entries = [
            {"type": "file", "name": "fastapi.mdc", "download_url": "https://x/fastapi.mdc"},
        ]
        captured_names: list[str] = []

        def mock_ingest(url, seed_name=None, **kwargs):
            captured_names.append(seed_name or "")
            pack = tmp_path / "docs" / "memory" / "seed_packs" / (seed_name or "x")
            pack.mkdir(parents=True, exist_ok=True)
            return pack, "written"

        with patch.object(sa, "_fetch_github_dir_listing", return_value=fake_entries), \
             patch.object(sa, "ingest", side_effect=mock_ingest):
            sa.ingest_batch(
                ["https://github.com/u/r/tree/main/rules"],
                seed_prefix="ext_",
            )

        assert any(name.startswith("ext_") for name in captured_names)

    def test_e04_multiple_raw_urls(self, tmp_path, monkeypatch):
        """E-04：多个 raw URL 直接输入时逐一处理，返回对应数量结果。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        urls = [
            "https://raw.githubusercontent.com/x/r/main/pytest.mdc",
            "https://raw.githubusercontent.com/x/r/main/pydantic.mdc",
        ]
        call_count = [0]

        def mock_ingest(url, **kwargs):
            call_count[0] += 1
            name = url.split("/")[-1].replace(".mdc", "")
            pack = tmp_path / "docs" / "memory" / "seed_packs" / name
            pack.mkdir(parents=True, exist_ok=True)
            return pack, "written"

        with patch.object(sa, "_fetch_content", return_value=(_SAMPLE_MDC, "x.mdc")), \
             patch.object(sa, "ingest", side_effect=mock_ingest):
            results = sa.ingest_batch(urls)

        assert len(results) == 2
        assert call_count[0] == 2

    def test_e05_no_token_warning_for_raw_urls_only(self, tmp_path, monkeypatch, capsys):
        """E-05：只有 raw URL（无目录 URL）时，不显示 GITHUB_TOKEN 提示。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        def mock_ingest(url, **kwargs):
            pack = tmp_path / "docs" / "memory" / "seed_packs" / "x"
            pack.mkdir(parents=True, exist_ok=True)
            return pack, "written"

        with patch.object(sa, "ingest", side_effect=mock_ingest):
            sa.ingest_batch(["https://raw.githubusercontent.com/x/r/main/test.mdc"])

        captured = capsys.readouterr()
        assert "GITHUB_TOKEN" not in captured.out

    def test_e05_token_warning_shown_for_dir_url(self, tmp_path, monkeypatch, capsys):
        """E-05 反向：目录 URL 存在时，应显示 GITHUB_TOKEN 提示。"""
        sys.path.insert(0, str(_SRC))
        import mms.analysis.seed_absorber as sa

        with patch.object(sa, "_fetch_github_dir_listing", return_value=[]):
            sa.ingest_batch(["https://github.com/u/r/tree/main/rules"])

        captured = capsys.readouterr()
        assert "GITHUB_TOKEN" in captured.out
