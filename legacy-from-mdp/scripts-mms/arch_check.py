"""
arch_check.py — MDP 架构约束机械检查器

按照 AGENTS.md §3 中定义的 6 条红线（AC-1 ~ AC-6）对代码进行静态扫描。

用法:
  python3 scripts/mms/arch_check.py                  # 扫描全部约束
  python3 scripts/mms/arch_check.py --layer           # AC-1: 层隔离（infrastructure 直接 import）
  python3 scripts/mms/arch_check.py --ctx             # AC-2: Service 方法首参 SecurityContext
  python3 scripts/mms/arch_check.py --audit           # AC-3: WRITE 方法必须调 AuditService.log
  python3 scripts/mms/arch_check.py --envelope        # AC-4: API 返回 Envelope 格式
  python3 scripts/mms/arch_check.py --worker          # AC-6: Worker 必须用 JobExecutionScope
  python3 scripts/mms/arch_check.py --ci              # CI 模式（有违反则 exit 2）

退出码:
  0 — 全部通过
  1 — 有警告
  2 — 有错误（CI 模式下使用）
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _ROOT / "backend" / "app"
_SERVICES = _BACKEND / "services"
_WORKERS = _BACKEND / "workers"
_API = _BACKEND / "api"

RESET = "\033[0m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET} {msg}")


def _err(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


# ── AC-1: 层隔离 ──────────────────────────────────────────────────────────────
# pymilvus / aiokafka / elasticsearch 禁止在 services/ 层直接 import

_FORBIDDEN_INFRA_IMPORTS = [
    "pymilvus",
    "aiokafka",
    "elasticsearch",
    "confluent_kafka",
]

_IMPORT_PATTERN = re.compile(
    r"^(?:import|from)\s+(" + "|".join(_FORBIDDEN_INFRA_IMPORTS) + r")\b",
    re.MULTILINE,
)


def check_layer_isolation() -> List[str]:
    violations: List[str] = []
    if not _SERVICES.exists():
        return violations
    for py in _SERVICES.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for m in _IMPORT_PATTERN.finditer(text):
            rel = py.relative_to(_ROOT)
            pkg = m.group(1)
            violations.append(
                f"[AC-1 VIOLATION] {rel}:{_line_no(text, m.start())}\n"
                f"  PROBLEM: 在 services/ 层直接 import {pkg!r}（违反基础设施隔离）\n"
                f"  FIX: 改为通过 backend/app/infrastructure/ 下的适配器调用\n"
                f"  EXAMPLE: from app.infrastructure.mq.kafka_producer import KafkaProducer\n"
                f"  REFERENCE: .cursorrules §AC-1 | layer_contracts.md §L4"
            )
    return violations


# ── AC-2: SecurityContext 首参 ────────────────────────────────────────────────
# Service 中 async def / def 公开方法首参必须是 ctx: SecurityContext

_PUBLIC_METHOD = re.compile(
    r"^\s{4}(?:async\s+)?def\s+([a-z][a-zA-Z0-9_]*)\s*\(self,\s*([^)]*)\)",
    re.MULTILINE,
)
_PRIVATE_PREFIX = re.compile(r"^_")


def check_security_context() -> List[str]:
    violations: List[str] = []
    if not _SERVICES.exists():
        return violations
    for py in _SERVICES.rglob("*.py"):
        # 只扫描 service 文件（按命名约定）
        if not py.name.endswith("_service.py") and "service" not in py.parent.name:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for m in _PUBLIC_METHOD.finditer(text):
            method_name = m.group(1)
            params = m.group(2).strip()
            # 跳过私有方法
            if _PRIVATE_PREFIX.match(method_name):
                continue
            # 跳过 __init__ 等特殊方法（用双下划线判断，这里已被正则排除）
            if not params:
                continue
            first_param = params.split(",")[0].strip()
            if "SecurityContext" not in first_param and "ctx" not in first_param:
                rel = py.relative_to(_ROOT)
                violations.append(
                    f"[AC-2 VIOLATION] {rel}:{_line_no(text, m.start())}\n"
                    f"  PROBLEM: 方法 {method_name}() 首参不含 SecurityContext/ctx\n"
                    f"  FIX: 将方法签名第一个参数改为 ctx: SecurityContext\n"
                    f"  IMPORT: from app.core.security import SecurityContext\n"
                    f"  EXAMPLE: async def {method_name}(self, ctx: SecurityContext, ...) -> ...:\n"
                    f"  REFERENCE: .cursorrules §AC-2 | layer_contracts.md §L4"
                )
    return violations


# ── AC-3: AuditService.log 调用 ──────────────────────────────────────────────
# WRITE 方法（含 create/update/delete/patch 关键词）必须调 AuditService.log

_WRITE_METHOD = re.compile(
    r"^\s{4}(?:async\s+)?def\s+(create|update|delete|patch|add|remove|upsert|bulk)[a-zA-Z0-9_]*\s*\(",
    re.MULTILINE,
)
_AUDIT_CALL = re.compile(r"audit.*\.log\(|AuditService.*log\(", re.IGNORECASE)


def check_audit_calls() -> List[str]:
    """扫描 WRITE 方法，检查函数体内是否有 AuditService.log() 调用"""
    violations: List[str] = []
    if not _SERVICES.exists():
        return violations
    for py in _SERVICES.rglob("*.py"):
        rel_str = str(py)
        # CQRS 读侧：不强制 audit（无 MySQL 写）
        if "services/query" in rel_str or "services/read" in rel_str:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for m in _WRITE_METHOD.finditer(text):
            method_start = _line_no(text, m.start())
            method_body = _extract_method_body(lines, method_start - 1)
            if not _AUDIT_CALL.search(method_body):
                rel = py.relative_to(_ROOT)
                method_sig = m.group(0).strip()[:40]
                violations.append(
                    f"[AC-3 VIOLATION] {rel}:{method_start}\n"
                    f"  PROBLEM: WRITE 方法 {method_sig}... 缺少 AuditService.log()\n"
                    f"  FIX: 在方法体内（事务块中）添加 await AuditService.log(ctx, ...)\n"
                    f"  IMPORT: from app.services.audit_service import AuditService\n"
                    f"  EXAMPLE: await AuditService.log(ctx, action='create_xxx', resource_id=obj.id)\n"
                    f"  REFERENCE: .cursorrules §AC-3 | layer_contracts.md §L4"
                )
    return violations


def _extract_method_body(lines: List[str], start_idx: int) -> str:
    """提取从 start_idx 开始的方法体（足够行数以覆盖 audit 在 commit 之后的写法）"""
    return "\n".join(lines[start_idx: start_idx + 120])


# ── AC-4: Envelope 格式 ──────────────────────────────────────────────────────
# API 路由返回值必须用 Envelope，不能直接 return []

_RAW_LIST_RETURN = re.compile(
    r"^\s+return\s+\[",
    re.MULTILINE,
)

_JSONABLE_RESPONSE = re.compile(r"JSONResponse|success_response|envelope|StandardResponse", re.IGNORECASE)


def check_envelope() -> List[str]:
    violations: List[str] = []
    if not _API.exists():
        return violations
    for py in _API.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="ignore")
        for m in _RAW_LIST_RETURN.finditer(text):
            context_start = max(0, m.start() - 200)
            context = text[context_start: m.end() + 200]
            # 允许在 Enum 或非 route 上下文中使用列表
            if "@router." not in text and "def " not in context:
                continue
            rel = py.relative_to(_ROOT)
            violations.append(
                f"[AC-4 VIOLATION] {rel}:{_line_no(text, m.start())}\n"
                f"  PROBLEM: 检测到裸列表 return（API 返回格式违规）\n"
                f"  FIX: 将 return [...] 改为 return ResponseHelper.ok(data=ListData(items=..., total=...))\n"
                f"  IMPORT: from app.api.schemas.base import ResponseHelper, ListData\n"
                f"  EXAMPLE: return ResponseHelper.ok(data=ListData(items=result, total=count))\n"
                f"  REFERENCE: .cursorrules §AC-4 | layer_contracts.md §L5"
            )
    return violations


# ── AC-6: Worker JobExecutionScope ───────────────────────────────────────────
# Worker 中必须使用 JobExecutionScope，禁止在 run() 方法中有 except Exception 管理 Job 状态

_JOB_SCOPE_IMPORT = re.compile(r"from.*workers.*base.*import.*JobExecutionScope|from.*base.*import.*JobExecutionScope")
_BARE_EXCEPT_JOB = re.compile(r"except\s+Exception.*:\s*\n.*job.*status", re.IGNORECASE)
# 仅匹配名为 *Worker 的类（避免 import 路径中含 "Worker" 的编排器误报）
_WORKER_CLASS = re.compile(r"^class\s+\w+Worker\b", re.MULTILINE)


def check_worker_scope() -> List[str]:
    violations: List[str] = []
    if not _WORKERS.exists():
        return violations
    for py in _WORKERS.rglob("*.py"):
        if py.name in ("base.py", "__init__.py"):
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        if not _WORKER_CLASS.search(text):
            continue
        if not _JOB_SCOPE_IMPORT.search(text) and "JobExecutionScope" not in text:
            rel = py.relative_to(_ROOT)
            violations.append(
                f"[AC-6 VIOLATION] {rel}\n"
                f"  PROBLEM: Worker 类未使用 JobExecutionScope（Job 状态管理分散）\n"
                f"  FIX: 在 run() 方法中使用 async with JobExecutionScope(job_id, session) as scope:\n"
                f"  IMPORT: from app.workers.base import JobExecutionScope\n"
                f"  EXAMPLE:\n"
                f"    async def run(self, job_id: str) -> None:\n"
                f"        async with JobExecutionScope(job_id, self.session) as scope:\n"
                f"            # 在此执行业务逻辑，scope 自动管理状态和异常\n"
                f"            await self._do_work(scope)\n"
                f"  REFERENCE: .cursorrules §AC-6 | layer_contracts.md §Worker | EP-023"
            )
    return violations


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _line_no(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="arch_check.py — MDP 架构约束静态扫描",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/mms/arch_check.py          # 扫描全部约束
  python3 scripts/mms/arch_check.py --layer  # 只检查层隔离
  python3 scripts/mms/arch_check.py --ci     # CI 模式
""",
    )
    parser.add_argument("--layer",    action="store_true", help="AC-1: 层隔离")
    parser.add_argument("--ctx",      action="store_true", help="AC-2: SecurityContext 首参")
    parser.add_argument("--audit",    action="store_true", help="AC-3: AuditService.log 调用")
    parser.add_argument("--envelope", action="store_true", help="AC-4: Envelope 返回格式")
    parser.add_argument("--worker",   action="store_true", help="AC-6: Worker JobExecutionScope")
    parser.add_argument("--ci",       action="store_true", help="CI 模式（有违反则 exit 2）")
    args = parser.parse_args()

    run_all = not any([args.layer, args.ctx, args.audit, args.envelope, args.worker])

    checks: List[Tuple] = [
        ("AC-1 层隔离",             check_layer_isolation,  args.layer    or run_all),
        ("AC-2 SecurityContext",    check_security_context, args.ctx      or run_all),
        ("AC-3 AuditService.log",   check_audit_calls,      args.audit    or run_all),
        ("AC-4 Envelope 格式",      check_envelope,         args.envelope or run_all),
        ("AC-6 Worker Scope",       check_worker_scope,     args.worker   or run_all),
    ]

    all_violations: List[str] = []

    print(f"\n{BOLD}架构约束检查{RESET}\n{'─' * 55}")
    for label, fn, enabled in checks:
        if not enabled:
            continue
        print(f"\n▶ {label}")
        issues = fn()
        if not issues:
            _ok("通过")
        else:
            for issue in issues:
                _err(issue)
            all_violations.extend(issues)

    print(f"\n{'─' * 55}")
    if all_violations:
        print(f"{RED}{BOLD}✗ {len(all_violations)} 处架构违反{RESET}")
        return 2 if args.ci else 1
    else:
        print(f"{GREEN}{BOLD}✓ 全部架构约束通过{RESET}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
