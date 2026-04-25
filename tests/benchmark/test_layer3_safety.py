"""
Layer 3 安全门控单元测试

覆盖：
  - SanitizeSubEvaluator 各类凭证检测
  - MigrationSubEvaluator ORM 变更拦截
  - ArchCheckSubEvaluator 架构违规检测
  - SafetyEvaluator 集成（读取 fixtures YAML）
"""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from benchmark.v2.schema import BenchmarkConfig, BenchmarkLayer, RunLevel, TaskStatus
from benchmark.v2.layer3_safety.evaluator import (
    SanitizeSubEvaluator,
    MigrationSubEvaluator,
    ArchCheckSubEvaluator,
    SafetyEvaluator,
)


# ─────────────────────────────────────────────────────────────────────────────
# SanitizationGate 单元测试
# ─────────────────────────────────────────────────────────────────────────────

class TestSanitizeSubEvaluator:
    def setup_method(self):
        self.ev = SanitizeSubEvaluator()

    def test_openai_api_key_detected(self):
        text = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890ABCD"
        assert self.ev.detect(text)

    def test_openai_proj_key_detected(self):
        text = "使用 sk-proj-AbCdEfGhIjKlMnOpQrSt1234567890abcdef 调用 GPT"
        assert self.ev.detect(text)

    def test_aws_access_key_detected(self):
        text = "export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
        assert self.ev.detect(text)

    def test_github_pat_detected(self):
        text = "GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        assert self.ev.detect(text)

    def test_jwt_detected(self):
        text = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
                ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
                ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
        assert self.ev.detect(text)

    def test_internal_ip_detected(self):
        assert self.ev.detect("db: 10.128.45.23:5432")
        assert self.ev.detect("redis://192.168.1.100:6379")
        assert self.ev.detect("kafka: 172.16.100.50:9092")

    def test_password_in_dsn_detected(self):
        text = "postgresql://admin:SuperSecret123!@db.internal:5432/prod"
        assert self.ev.detect(text)

    def test_placeholder_not_detected(self):
        """占位符不应被误报"""
        assert not self.ev.detect("DASHSCOPE_API_KEY=sk-your-key-here")

    def test_already_redacted_not_detected(self):
        """已脱敏内容不应再次检测"""
        assert not self.ev.detect("api_key=[REDACTED_API_KEY]")

    def test_localhost_not_detected(self):
        assert not self.ev.detect("DATABASE_URL=postgresql://localhost:5432/mydb")

    def test_public_ip_not_detected(self):
        assert not self.ev.detect("server: 8.8.8.8")


# ─────────────────────────────────────────────────────────────────────────────
# MigrationGate 单元测试
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrationSubEvaluator:
    def setup_method(self):
        self.ev = MigrationSubEvaluator()

    def test_field_add_no_migration_blocked(self):
        orm_diff = "+    metadata_json: Optional[Dict] = Field(default=None)"
        assert self.ev._has_orm_change(orm_diff)
        assert not self.ev._has_migration([])

    def test_new_model_no_migration_blocked(self):
        orm_diff = "+class AuditLog(SQLModel, table=True):\n+    id: uuid.UUID = Field(...)"
        assert self.ev._has_orm_change(orm_diff)

    def test_no_orm_change_not_blocked(self):
        assert not self.ev._has_orm_change("")
        assert not self.ev._has_orm_change("  # comment only")

    def test_with_complete_migration_passes(self):
        migration_files = [{
            "content": "def upgrade():\n    op.add_column(...)\ndef downgrade():\n    op.drop_column(...)",
            "filename": "migrations/v1.py"
        }]
        assert self.ev._has_migration(migration_files)

    def test_migration_without_downgrade_detected(self):
        migration_files = [{
            "content": "def upgrade():\n    op.add_column(...)\ndef downgrade():\n    pass",
            "filename": "migrations/v1.py"
        }]
        # 有 def downgrade 即视为"有迁移"（downgrade 空实现是警告，非阻断）
        assert self.ev._has_migration(migration_files)


# ─────────────────────────────────────────────────────────────────────────────
# ArchCheck 单元测试
# ─────────────────────────────────────────────────────────────────────────────

class TestArchCheckSubEvaluator:
    def setup_method(self):
        self.ev = ArchCheckSubEvaluator()

    def test_ac1_aiokafka_direct_import_flagged(self):
        code = "from aiokafka import AIOKafkaProducer\n\nasync def send(): pass"
        assert self.ev._detect_violations(code, "AC-1") >= 1

    def test_ac1_infrastructure_import_not_flagged(self):
        code = "from backend.app.infrastructure.messaging import KafkaPublisher"
        assert self.ev._detect_violations(code, "AC-1") == 0

    def test_ac5_session_begin_flagged(self):
        code = "async with session.begin():\n    pass"
        assert self.ev._detect_violations(code, "AC-5") >= 1

    def test_ac5_autobegin_not_flagged(self):
        code = "await session.commit()"
        assert self.ev._detect_violations(code, "AC-5") == 0

    def test_ac6_print_flagged(self):
        code = "async def f():\n    print('debug')\n    print('done')"
        assert self.ev._detect_violations(code, "AC-6") == 2

    def test_ac6_structlog_not_flagged(self):
        code = "import structlog\nlog = structlog.get_logger()\nlog.info('ok')"
        assert self.ev._detect_violations(code, "AC-6") == 0


# ─────────────────────────────────────────────────────────────────────────────
# SafetyEvaluator 集成测试（读取真实 fixtures）
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyEvaluator:
    def setup_method(self):
        self.config = BenchmarkConfig(
            level=RunLevel.OFFLINE_ONLY,
            layers=[BenchmarkLayer.LAYER3_SAFETY],
            max_tasks=None,
            dry_run=False,
            llm_available=False,
        )

    def test_evaluator_runs_without_error(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SafetyEvaluator()
        result = ev.run(self.config)
        assert result.layer == BenchmarkLayer.LAYER3_SAFETY
        assert result.tasks_total > 0

    def test_score_is_float_between_0_and_1(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SafetyEvaluator()
        result = ev.run(self.config)
        assert 0.0 <= result.score <= 1.0

    def test_required_metrics_present(self):
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SafetyEvaluator()
        result = ev.run(self.config)
        required_keys = [
            "sanitize.detection_rate",
            "sanitize.false_positive_rate",
            "migration.block_accuracy",
            "arch.detection_rate",
            "overall.weighted_score",
        ]
        for key in required_keys:
            assert key in result.metrics, f"缺少指标: {key}"

    def test_critical_detection_rate_high(self):
        """SanitizationGate 对 critical 级别凭证检出率应 ≥ 80%"""
        pytest.importorskip("yaml", reason="pyyaml 未安装")
        ev = SafetyEvaluator()
        result = ev.run(self.config)
        assert result.metrics.get("sanitize.detection_rate", 0.0) >= 0.8, (
            f"检出率过低: {result.metrics.get('sanitize.detection_rate')}"
        )

    def test_is_offline_capable(self):
        ev = SafetyEvaluator()
        assert ev.is_offline_capable is True
