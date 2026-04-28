#!/usr/bin/env python3
"""
木兰（Mulan）CLI — 端侧 AI 代码工程工具链 统一命令行工具

设计目标：
  1. 单入口：所有记忆系统操作通过 `mulan <subcommand>` 完成
  2. 可嵌入：克隆 github.com/allengaoo/mms，设置 alias mulan="python3 $MULAN_HOME/cli.py"
  3. 自描述：每个命令有清晰的帮助信息和示例

子命令：
  status          — 系统状态总览（百炼 / 熔断器 / 记忆统计）
  distill         — EP 知识蒸馏（调用 qwen3-32b）
  gc              — 垃圾回收（LFU tier 重计算 + 索引更新）
  validate        — 记忆文件 Schema 校验
  search          — 关键词检索记忆（推理式，无向量）
  list            — 列出记忆（按 tier 过滤）
  hook            — 管理 git pre-commit hook
  incomplete      — 列出未完成的蒸馏断点任务
  reset-circuit   — 重置熔断器到 CLOSED 状态
  inject          — 记忆注入（自动检索 + 压缩上下文，生成 Cursor 提示词前缀）
  synthesize      — LLM 意图合成（结合记忆+模板生成结构化 EP 起手提示词）
  precheck        — 代码修改前检查门控（arch_check 基线 + 影响范围分析）
  postcheck       — 代码修改后测试与后校验（pytest + arch_check diff + doc_drift）
  private         — 私有记忆隔离协议（EP 粒度的临时笔记工作区）
    private init <EP-NNN>       — 初始化 EP 私有工作区
    private note <EP-NNN> <标题> — 添加临时笔记
    private list [--status active] — 列出所有 EP 工作区
    private promote <EP-NNN> <file> <layer> <new-id> — 升级为 shared 记忆
    private close <EP-NNN>       — 关闭 EP 工作区
  diag            — MDR 诊断工具（类 Oracle ADRCI）
    diag status                 — 查看 alert_mulan.log 告警状态
    diag list                   — 列出所有 Incident 记录
    diag pack <incident_id>     — 打包 Incident 诊断数据为 ZIP

用法示例：
  mulan status
  mulan synthesize "新增对象类型批量导出 API" --template ep-backend-api
  mulan synthesize "修复 Kafka 消费者丢消息" --template ep-debug --extra "只影响 ingestion worker"
  mulan precheck --ep EP-114
  mulan postcheck --ep EP-114
  mulan postcheck --ep EP-114 --skip-tests
  mulan distill --ep EP-109
  mulan distill --ep EP-109 --dry-run
  mulan gc
  mulan validate --changed-only
  mulan search kafka replication k8s
  mulan list --tier hot
  mulan hook install
  mulan reset-circuit
"""
import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# src/ 目录加入 sys.path，使 `from mms.X import Y` 生效
_CLI_DIR = Path(__file__).resolve().parent
_SRC_DIR = _CLI_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

_PROJECT_ROOT = _CLI_DIR
_MEMORY_ROOT = _PROJECT_ROOT / "docs" / "memory"
_SYSTEM_DIR = _MEMORY_ROOT / "_system"

# ANSI 颜色
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"
_DIM = "\033[2m"

_USE_COLOR = sys.stdout.isatty()


def c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}" if _USE_COLOR else text


def header(title: str) -> None:
    width = 55
    print(f"\n{c('='*width, _BOLD)}")
    print(f"  {c(title, _BOLD)}")
    print(c('='*width, _BOLD))


def ok(msg: str) -> None:
    print(f"  {c('✅', _GREEN)} {msg}")


def warn(msg: str) -> None:
    print(f"  {c('⚠️ ', _YELLOW)} {msg}")


def err(msg: str) -> None:
    print(f"  {c('❌', _RED)} {msg}")


def info(msg: str) -> None:
    print(f"  {c('·', _DIM)} {msg}")


# ─── help 命令 ────────────────────────────────────────────────────────────────

# 命令详细文档（用于 mms help <command>）
_COMMAND_DOCS: dict = {
    "ep": {
        "title": "EP 工作流向导",
        "models": "qwen3-32b（意图/评审/DAG） · qwen3-coder-next（代码）",
        "desc": "将完整 EP 生命周期串为 7 步交互式向导，支持断点续跑。",
        "usage": [
            ("mulan ep start EP-122",                  "启动 EP-122 工作流向导（从 Step 1）"),
            ("mulan ep start EP-122 --from-step 5",    "从 Step 5 续跑（断点恢复）"),
            ("mulan ep status EP-122",                 "查看 EP-122 向导进度"),
        ],
        "steps": [
            "Step 1  意图合成     mulan synthesize → qwen3-32b",
            "Step 2  确认 EP 文件 Cursor 中生成 EP 文件后按 Enter",
            "Step 3  建立基线     mulan precheck",
            "Step 4  生成 DAG    mulan unit generate → qwen3-32b",
            "Step 5  Unit 循环   qwen run + sonnet-save + compare(qwen3-32b 评审) + apply",
            "Step 6  后校验      mulan postcheck",
            "Step 7  知识沉淀    mulan dream + mulan distill",
        ],
    },
    "unit": {
        "title": "DAG 任务编排",
        "models": "qwen3-32b（generate） · qwen3-coder-next（run）",
        "desc": "将 EP 分解为原子 Unit 并执行，支持双模型对比工作流。",
        "usage": [
            ("mulan unit generate --ep EP-122",                         "生成 DAG（qwen3-32b）"),
            ("mulan unit status --ep EP-122",                          "查看执行进度"),
            ("mulan unit run --ep EP-122 --unit U1 --save-output",     "qwen 生成代码（存盘，不写业务文件）"),
            ("mulan unit sonnet-save --ep EP-122 --unit U1",           "保存 Sonnet 输出（stdin 粘贴）"),
            ("mulan unit compare --ep EP-122 --unit U1",               "Diff + qwen3-32b 评审 → report.md"),
            ("mulan unit compare --apply qwen --ep EP-122 --unit U1",  "应用 qwen 版本到业务文件"),
            ("mulan unit compare --apply sonnet --ep EP-122 --unit U1","应用 sonnet 版本到业务文件"),
            ("mulan unit done --ep EP-122 --unit U1",                  "手动标记 Unit 完成"),
            ("mulan unit run-next --ep EP-122",                        "执行当前批次所有 pending Unit"),
        ],
    },
    "synthesize": {
        "title": "LLM 意图合成",
        "models": "qwen3-32b（百炼）",
        "desc": "结合记忆库 + EP 模板，生成结构化 Cursor 起手提示词（三级检索漏斗）。",
        "usage": [
            ('mulan synthesize "新增对象类型批量导出 API" --template ep-backend-api', "后端 API 类任务"),
            ('mulan synthesize "修复 Kafka 消费者丢消息" --template ep-debug',        "调试类任务"),
            ('mulan synthesize "精简前端导航栏" --template ep-frontend -i',           "交互式补充要求"),
            ("mulan synthesize --list-templates",                                     "列出所有模板"),
        ],
        "templates": [
            "ep-backend-api   后端 API / Service 新增",
            "ep-frontend      前端页面 / 组件变更",
            "ep-ontology      本体模块（对象/链接/Action）",
            "ep-data-pipeline 数据管道（Connector/SyncJob）",
            "ep-debug         Bug 修复 / 诊断",
        ],
    },
    "precheck": {
        "title": "代码修改前检查（建立基线）",
        "models": "无 LLM",
        "desc": "运行 arch_check 记录基线状态，分析 EP 影响范围，阻断已有架构违规。",
        "usage": [
            ("mulan precheck --ep EP-122",         "建立 EP-122 的 arch_check 基线"),
            ("mulan precheck --ep EP-122 --strict","严格模式：WARN 也视为阻断"),
        ],
    },
    "postcheck": {
        "title": "代码修改后校验",
        "models": "无 LLM",
        "desc": "运行 pytest + arch_check diff + doc_drift 检测，验证所有变更合规。",
        "usage": [
            ("mulan postcheck --ep EP-122",               "标准后校验（含 pytest）"),
            ("mulan postcheck --ep EP-122 --skip-tests",  "仅架构检查，跳过 pytest"),
        ],
    },
    "distill": {
        "title": "EP 知识蒸馏",
        "models": "qwen3-32b（百炼）",
        "desc": "从 EP 文件提取 LESSONS_LEARNED / ACTIVE_DECISIONS，生成 MEM-*.md 记忆条目。",
        "usage": [
            ("mulan distill --ep EP-122",          "蒸馏 EP-122 知识"),
            ("mulan distill --ep EP-122 --dry-run","预览模式（不写文件）"),
        ],
    },
    "dream": {
        "title": "autoDream 知识萃取",
        "models": "qwen3-32b（百炼）",
        "desc": "从 git commit 历史和 EP 的 Surprises 章节自动萃取知识草稿，人工审核后提升。",
        "usage": [
            ("mulan dream --ep EP-122",        "针对 EP-122 萃取知识草稿"),
            ("mulan dream --list",             "列出所有未处理草稿"),
            ("mulan dream --promote",          "交互式审核 → 提升为正式记忆"),
            ("mulan dream --dry-run",          "只预览 prompt，不调用 LLM"),
        ],
    },
    "status": {
        "title": "系统状态",
        "models": "无 LLM",
        "desc": "检查所有 Provider 可用性、熔断器状态、记忆库统计和近 7 天模型用量。",
        "usage": [("mulan status", "查看完整系统状态")],
    },
    "search": {
        "title": "记忆关键词检索",
        "models": "无 LLM",
        "desc": "按关键词检索记忆库（Jaccard 匹配，无向量），支持预览最高匹配。",
        "usage": [
            ("mulan search kafka replication",        "搜索 kafka 相关记忆"),
            ("mulan search rls tenant --preview",     "搜索并预览第一条结果"),
            ("mulan search auth --top-k 10",          "返回 10 条结果"),
        ],
    },
    "inject": {
        "title": "记忆注入",
        "models": "无 LLM",
        "desc": "自动检索 + 压缩相关记忆，生成 Cursor 对话前缀（提升 LLM 上下文质量）。",
        "usage": [
            ("mulan inject 新增对象类型 API",          "生成 API 开发相关记忆前缀"),
            ('mulan inject "修复 RLS 问题" --mode debug', "调试模式注入"),
        ],
    },
    "template": {
        "title": "代码模板库",
        "models": "无 LLM",
        "desc": "填空式代码骨架，降低小模型幻觉率。模板自动注入架构约束。",
        "usage": [
            ("mulan template list",                                         "列出所有模板"),
            ("mulan template info service-method",                          "查看模板变量说明"),
            ("mulan template use service-method --var entity=ObjectType",   "渲染模板"),
        ],
        "templates": [
            "service-method   Service 层方法骨架（SecurityContext + AuditService + RLS）",
            "api-endpoint     FastAPI Endpoint + Schema（信封格式 + 权限守卫）",
            "react-list-page  ProTable 列表页（useQuery + PermissionGate + Zustand）",
            "worker-job       Worker Job（JobExecutionScope + structlog）",
        ],
    },
    "graph": {
        "title": "记忆知识图谱",
        "models": "无 LLM",
        "desc": "查询记忆节点之间的关联关系，支持 BFS 遍历、文件反查、影响分析。",
        "usage": [
            ("mulan graph stats",           "图谱统计（节点数、边数）"),
            ("mulan graph explore AD-002",  "从 AD-002 出发 BFS 遍历（depth=2）"),
            ("mulan graph file backend/app/services/control/action_service.py", "反查引用该文件的记忆"),
            ("mulan graph impacts AD-002",  "查询 AD-002 变更时需同步检查的节点"),
        ],
    },
}


def cmd_help(args: argparse.Namespace) -> int:
    """help 子命令：彩色命令参考"""
    topic = getattr(args, "topic", None)

    if topic and topic in _COMMAND_DOCS:
        _print_command_help(topic)
        return 0

    if topic:
        err(f"未知命令：{topic}")
        info(f"可用命令：{', '.join(sorted(_COMMAND_DOCS.keys()))}")
        return 1

    _print_full_help()
    return 0


def _print_command_help(cmd_name: str) -> None:
    """打印单个命令的详细帮助"""
    doc = _COMMAND_DOCS[cmd_name]
    title = doc["title"]
    models = doc.get("models", "")
    desc = doc["desc"]
    usage_list = doc.get("usage", [])
    steps = doc.get("steps", [])
    templates = doc.get("templates", [])

    print(f"\n{c('='*60, _BOLD)}")
    print(f"  {c('mulan ' + cmd_name, _BOLD)}  —  {title}")
    print(c('='*60, _BOLD))

    if models:
        print(f"\n  {c('模型', _CYAN)}：{models}")

    print(f"\n  {c('说明', _CYAN)}：{desc}")

    if steps:
        print(f"\n  {c('步骤', _CYAN)}：")
        for s in steps:
            print(f"    {c('·', _DIM)} {s}")

    if templates:
        print(f"\n  {c('模板', _CYAN)}：")
        for t in templates:
            print(f"    {c('·', _DIM)} {t}")

    if usage_list:
        print(f"\n  {c('用法示例', _CYAN)}：")
        for cmd_str, comment in usage_list:
            print(f"    {c('$', _DIM)} {c(cmd_str, _BOLD)}")
            print(f"      {c(comment, _DIM)}")

    print()


def _print_full_help() -> None:
    """打印完整彩色命令参考"""
    print(f"\n{c('='*62, _BOLD)}")
    print(f"  {c('MMS — 端侧 AI 代码工程工具链 CLI', _BOLD)}  |  版本 2.2")
    print(c('='*62, _BOLD))

    # 模型分工一览
    print(f"\n{c('【模型分工】', _CYAN)}")
    model_table = [
        ("意图识别",    "mulan synthesize",           "qwen3-32b（百炼）"),
        ("DAG 生成",   "mulan unit generate",         "qwen3-32b（百炼）"),
        ("代码生成 A", "mulan unit run --save-output", "qwen3-coder-next（百炼）"),
        ("代码生成 B", "mulan unit sonnet-save",       "Cursor Sonnet（手动）"),
        ("语义评审",   "mulan unit compare",           "qwen3-32b（百炼，自动）"),
        ("知识蒸馏",   "mulan distill / dream",        "qwen3-32b（百炼）"),
    ]
    for role, cmd_str, model in model_table:
        print(f"  {c(role, _BOLD):<12}  {c(cmd_str, _DIM):<38}  {c(model, _CYAN)}")

    # EP 工作流
    print(f"\n{c('【EP 工作流（推荐：mms ep start EP-NNN）】', _CYAN)}")
    ep_steps = [
        ("1", "mulan synthesize \"任务\" --template ep-backend-api", "意图合成"),
        ("2", "Cursor 生成 EP 文件 → 按 Enter 确认",               "EP 确认"),
        ("3", "mulan precheck --ep EP-NNN",                           "建立基线"),
        ("4", "mulan unit generate --ep EP-NNN",                      "生成 DAG"),
        ("5", "mulan unit run --save-output  →  compare  →  apply",   "Unit 循环"),
        ("6", "mulan postcheck --ep EP-NNN",                          "后校验"),
        ("7", "mulan distill / mulan dream --ep EP-NNN",                "知识沉淀"),
    ]
    for num, cmd_str, label in ep_steps:
        print(f"  {c(f'Step {num}', _BOLD)}  {c(cmd_str, _DIM):<52}  {c(label, _YELLOW)}")

    # 命令速查表
    cmd_groups = [
        ("EP 工作流", [
            ("mulan ep start EP-NNN",              "交互式向导（7 步引导，含断点续跑）"),
            ("mulan ep start EP-NNN --from-step 5","从指定步骤续跑"),
            ("mulan ep status EP-NNN",             "查看向导进度"),
            ("mulan synthesize \"任务\" -t <模板>","意图合成 → Cursor 起手提示词"),
            ("mulan precheck --ep EP-NNN",         "修改前基线检查"),
            ("mulan postcheck --ep EP-NNN",        "修改后测试与架构验证"),
            ("mulan distill --ep EP-NNN",          "EP 知识蒸馏 → MEM-*.md"),
            ("mulan dream --ep EP-NNN",            "autoDream 自动萃取知识草稿"),
        ]),
        ("Unit 双模型对比", [
            ("mulan unit generate --ep EP-NNN",               "生成 DAG 执行计划"),
            ("mulan unit status --ep EP-NNN",                 "查看 DAG 进度"),
            ("mulan unit run --ep EP-NNN --unit U1 --save-output", "qwen 生成并存盘"),
            ("mulan unit sonnet-save --ep EP-NNN --unit U1",  "存盘 Sonnet 输出"),
            ("mulan unit compare --ep EP-NNN --unit U1",      "Diff + qwen3-32b 评审"),
            ("mulan unit compare --apply qwen/sonnet ...",    "应用选定版本"),
            ("mulan unit done --ep EP-NNN --unit U1",         "手动标记完成"),
        ]),
        ("记忆管理", [
            ("mulan search <关键词...>",   "关键词检索记忆"),
            ("mulan inject <任务描述>",    "生成 Cursor 上下文前缀"),
            ("mulan list --tier hot",      "列出热记忆"),
            ("mulan graph explore <ID>",   "知识图谱 BFS 遍历"),
            ("mulan template list",        "代码模板列表"),
            ("mulan template use <name>",  "渲染代码模板"),
            ("mulan gc",                   "垃圾回收（LFU 淘汰 + 索引重建）"),
            ("mulan validate",             "Schema 校验"),
        ]),
        ("系统维护", [
            ("mulan status",           "系统状态（Provider / 熔断器 / 用量）"),
            ("mulan usage --since 30", "模型用量统计（近 30 天）"),
            ("mulan codemap",          "刷新代码目录快照"),
            ("mulan funcmap",          "刷新函数签名索引"),
            ("mulan hook install",     "安装 git pre-commit hook"),
            ("mulan reset-circuit",    "重置熔断器"),
            ("mulan verify",           "记忆系统健康检查"),
        ]),
    ]

    for group_name, cmds in cmd_groups:
        print(f"\n{c(f'【{group_name}】', _CYAN)}")
        for cmd_str, comment in cmds:
            print(f"  {c(cmd_str, _BOLD):<50}  {c(comment, _DIM)}")

    print(f"\n{c('提示', _YELLOW)}：运行 {c('mulan help <command>', _BOLD)} 查看单个命令的详细说明和示例")
    print(f"      例如：{c('mulan help unit', _BOLD)} · {c('mulan help synthesize', _BOLD)} · {c('mulan help ep', _BOLD)}\n")


# ─── status 命令 ──────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> int:
    from mms.providers.bailian import BailianProvider, BailianEmbedProvider

    from mms.resilience.circuit_breaker import CircuitBreaker

    header("MMS 系统状态")

    # 百炼检查
    print(f"\n{c('【百炼（DashScope）服务】', _CYAN)}")
    import os as _os
    dashscope_key = _os.environ.get("DASHSCOPE_API_KEY", "")
    # 尝试从 .env.memory 读取
    if not dashscope_key:
        env_file = _PROJECT_ROOT / ".env.memory"
        if env_file.exists():
            for _line in env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line.startswith("DASHSCOPE_API_KEY=") and not _line.startswith("#"):
                    dashscope_key = _line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not dashscope_key:
        warn("DASHSCOPE_API_KEY 未配置 — 百炼服务不可用")
        warn("请在 .env.memory 中设置：DASHSCOPE_API_KEY=sk-...")
    else:
        key_preview = dashscope_key[:8] + "****"
        info(f"API Key: {key_preview}")
        import os as _os2
        reasoning_model = _os2.environ.get("DASHSCOPE_MODEL_REASONING", "qwen3-32b")
        coding_model    = _os2.environ.get("DASHSCOPE_MODEL_CODING",    "qwen3-coder-next")
        embed_model     = _os2.environ.get("DASHSCOPE_MODEL_EMBEDDING",  "text-embedding-v3")
        for model, label in [
            (reasoning_model, "推理 (蒸馏/路由/质量门)"),
            (coding_model,    "代码 (简单代码生成)"),
            (embed_model,     "嵌入 (重复检测，可选)"),
        ]:
            p = BailianProvider(model=model, api_key=dashscope_key)
            if p.is_available():
                ok(f"{model:<28} {c(label, _DIM)}")
            else:
                warn(f"{model:<28} 不可达，请检查网络或 API Key 权限")



    # 熔断器状态
    print(f"\n{c('【熔断器状态】', _CYAN)}")
    circuit_file = _SYSTEM_DIR / "circuit_state.json"
    if circuit_file.exists():
        states = json.loads(circuit_file.read_text())
        if not states:
            ok("所有 Provider 熔断器正常（CLOSED）")
        else:
            for model_name, state in states.items():
                status = state.get("status", "CLOSED")
                color = _GREEN if status == "CLOSED" else (_YELLOW if status == "HALF_OPEN" else _RED)
                fails = state.get("failure_count", 0)
                print(f"  {model_name:<28} {c(status, color)}  (失败次数: {fails})")
    else:
        ok("熔断器状态文件未初始化（正常）")

    # 记忆统计
    print(f"\n{c('【记忆库统计】', _CYAN)}")
    _print_memory_stats()

    # 未完成蒸馏任务
    cp_dir = _SYSTEM_DIR / "checkpoints"
    incomplete = list(cp_dir.glob("*.json")) if cp_dir.exists() else []
    if incomplete:
        warn(f"未完成的蒸馏断点：{len(incomplete)} 个（运行 `mulan incomplete` 查看）")
    else:
        ok("无未完成的蒸馏断点")

    # 审计日志行数
    audit_file = _SYSTEM_DIR / "audit.jsonl"
    if audit_file.exists():
        lines = len(audit_file.read_text().splitlines())
        info(f"审计日志：{lines} 条记录  →  {audit_file}")

    # 模型使用统计摘要（最近 7 天）
    print(f"\n{c('【模型使用统计（近 7 天）】', _CYAN)}")
    usage_file = _SYSTEM_DIR / "model_usage.jsonl"
    if not usage_file.exists():
        info("暂无调用记录（首次调用 mms inject / mulan distill 后自动记录）")
        info("运行 `mulan usage` 查看详细统计")
    else:
        try:
            from mms.utils.model_tracker import load_records, compute_stats
        except ImportError:
            from mms.utils.model_tracker import load_records, compute_stats  # type: ignore[no-redef]
        recs = load_records(since_days=7)
        if not recs:
            info("近 7 天暂无记录")
        else:
            stats = compute_stats(recs)
            total_tok = stats["total_prompt"] + stats["total_output"]
            info(f"总调用：{stats['total_calls']} 次  |  Token 消耗：{total_tok:,}")
            for model_name, bm in sorted(
                stats["by_model"].items(), key=lambda x: -x[1]["calls"]
            ):
                provider_tag = ""
                ok(
                    f"{model_name:<28}"
                    f" {bm['calls']} 次  "
                    f"{c(str(bm['prompt_tok'] + bm['output_tok']) + ' tok', _DIM)}"
                    + provider_tag
                )
            info("运行 `mulan usage` 查看详细报告（Token 分布 / 场景明细）")

    # 记忆图健康监控（Phase 4-B）
    print(f"\n{c('【记忆图健康（Memory Graph Health）】', _CYAN)}")
    try:
        from mms.memory.graph_health import compute_health_metrics
        health = compute_health_metrics()
        use_color = True
        for line in health.format_lines(use_color=use_color):
            print(line)
    except Exception as _gh_err:  # noqa: BLE001
        info(f"记忆图健康读取失败：{_gh_err}")

    print()
    return 0


def _print_memory_stats() -> None:
    """打印记忆库 tier 分布统计"""
    tier_counts = {"hot": 0, "warm": 0, "cold": 0, "archive": 0}
    layer_counts: dict = {}

    for md in _MEMORY_ROOT.rglob("*.md"):
        if (
            "_system" in md.parts
            or "archive" in md.parts
            or "templates" in md.parts
            or md.name == "CONTRIBUTING.md"
        ):
            continue
        content = md.read_text(encoding="utf-8", errors="ignore")
        tier = "warm"
        layer = "?"
        for line in content.split("\n")[:20]:
            if line.startswith("tier:"):
                tier = line.split(":", 1)[1].strip().strip("\"'")
            if line.startswith("layer:"):
                raw = line.split(":", 1)[1].strip().strip("\"'")
                layer = raw.split("_")[0]  # L2_infrastructure → L2
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    total = sum(tier_counts.values())
    tier_bar = "  ".join(
        f"{c(k.upper(), _GREEN if k=='hot' else _YELLOW if k=='warm' else _DIM)}: {v}"
        for k, v in tier_counts.items() if v > 0
    )
    print(f"  总计 {c(str(total), _BOLD)} 条  |  {tier_bar}")
    layer_bar = "  ".join(f"{k}: {v}" for k, v in sorted(layer_counts.items()) if k != "?")
    info(f"按层分布：{layer_bar}")


# ─── distill 命令 ─────────────────────────────────────────────────────────────

def cmd_distill(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(_SCRIPTS_DIR / "memory_distill.py"), "--ep", args.ep]
    if args.dry_run:
        cmd.append("--dry-run")
    if args.resume:
        cmd.extend(["--resume", args.resume])
    if args.ep_file:
        cmd.extend(["--ep-file", args.ep_file])
    return subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode


# ─── gc 命令 ─────────────────────────────────────────────────────────────────

def cmd_gc(args: argparse.Namespace) -> int:
    gc_script = _SCRIPTS_DIR / "memory_gc.py"
    if gc_script.exists():
        cmd = [sys.executable, str(gc_script)]
        if args.dry_run:
            cmd.append("--dry-run")
        if getattr(args, "update_index_only", False):
            cmd.append("--update-index-only")
        rc = subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode
        if rc != 0:
            return rc
    else:
        warn("memory_gc.py 未找到，跳过 GC（将直接运行熵扫描）")

    # GC 完成后自动运行熵扫描，输出清理建议
    if not getattr(args, "dry_run", False):
        info("GC 完成，正在运行熵扫描…")
        entropy_script = _SCRIPTS_DIR / "mms" / "entropy_scan.py"
        if entropy_script.exists():
            subprocess.run(
                [sys.executable, str(entropy_script), "--threshold", "warn"],
                cwd=str(_PROJECT_ROOT),
            )
    return 0


# ─── validate 命令 ────────────────────────────────────────────────────────────

def cmd_validate(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(_SCRIPTS_DIR / "mms" / "validate.py")]
    if getattr(args, "changed_only", False):
        cmd.append("--changed-only")
    if getattr(args, "file", None):
        cmd.extend(["--file", args.file])
    if getattr(args, "migrate_add_version", False):
        cmd.append("--migrate-add-version")
    return subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode


# ─── search 命令 ──────────────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> int:
    from mms.core.reader import MemoryReader

    keywords = args.keywords
    if not keywords:
        err("请提供搜索关键词，例如：mms search kafka replication")
        return 1

    header(f"关键词检索：{' '.join(keywords)}")
    reader = MemoryReader()
    results = reader.search_by_keywords(keywords, top_k=args.top_k)

    if not results:
        warn("未找到匹配的记忆。建议扩展关键词或检查 MEMORY_INDEX.json 中的 trigger_keywords。")
        return 0

    print(f"\n找到 {len(results)} 条相关记忆（按匹配分数排序）：\n")
    for i, mem in enumerate(results, 1):
        tier = mem.get("tier", "warm")
        tier_color = _GREEN if tier == "hot" else _YELLOW if tier == "warm" else _DIM
        print(f"  {c(str(i), _BOLD)}. [{c(tier.upper(), tier_color)}] {c(mem['id'], _CYAN)}  score={mem.get('score', 0)}")
        print(f"     {mem.get('title', '(无标题)')}")
        print(f"     {c(mem.get('file', ''), _DIM)}")
        print()

    if args.preview and results:
        first = results[0]
        fpath = _MEMORY_ROOT / first.get("file", "")
        if fpath.exists():
            print(f"\n{c('── 最高匹配记忆预览 ──', _BOLD)}")
            content = fpath.read_text(encoding="utf-8")
            # 跳过 front-matter，显示正文
            parts = content.split("---\n", 2)
            body = parts[2].strip() if len(parts) >= 3 else content
            print(body[:800] + ("..." if len(body) > 800 else ""))

    return 0


# ─── list 命令 ────────────────────────────────────────────────────────────────

def cmd_list(args: argparse.Namespace) -> int:
    tier_filter = args.tier
    layer_filter = args.layer

    header(f"记忆列表{f' [tier={tier_filter}]' if tier_filter else ''}{f' [layer={layer_filter}]' if layer_filter else ''}")

    memories = []
    for md in sorted(_MEMORY_ROOT.rglob("*.md")):
        if (
            "_system" in md.parts
            or "archive" in md.parts
            or "templates" in md.parts
            or md.name == "CONTRIBUTING.md"
        ):
            continue
        content = md.read_text(encoding="utf-8", errors="ignore")
        fm = {}
        for line in content.split("\n")[:25]:
            if ":" in line and not line.startswith("#"):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip("\"'")

        tier = fm.get("tier", "warm")
        layer = fm.get("layer", "?").split("_")[0]
        mem_id = fm.get("id", md.stem)
        title = ""
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].split("·", 1)[-1].strip() if "·" in line else line[2:].strip()
                break

        if tier_filter and tier != tier_filter:
            continue
        if layer_filter and layer != layer_filter:
            continue
        memories.append((tier, layer, mem_id, title))

    if not memories:
        info("无匹配记忆")
        return 0

    print()
    for tier, layer, mem_id, title in memories:
        tier_color = _GREEN if tier == "hot" else _YELLOW if tier == "warm" else _DIM
        print(f"  {c(layer, _CYAN):<6} {c(tier.upper(), tier_color):<8} {c(mem_id, _BOLD):<18} {title[:50]}")

    print(f"\n  共 {len(memories)} 条")
    return 0


# ─── hook 命令 ────────────────────────────────────────────────────────────────

def cmd_hook(args: argparse.Namespace) -> int:
    cmd = [sys.executable, str(_SCRIPTS_DIR / "mms" / "ci_hook.py"), args.action]
    return subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode


# ─── incomplete 命令 ──────────────────────────────────────────────────────────

def cmd_incomplete(args: argparse.Namespace) -> int:
    from mms.resilience.checkpoint import Checkpoint

    header("未完成的蒸馏断点任务")
    cp = Checkpoint()
    incomplete = cp.list_incomplete()

    if not incomplete:
        ok("无未完成任务")
        return 0

    print(f"\n找到 {len(incomplete)} 个未完成断点：\n")
    for tid in incomplete:
        state = cp.load(tid)
        if state:
            done = state.processed_sections
            pending = state.pending_sections
            print(f"  {c(tid, _CYAN)}  EP={state.ep_id or '?'}")
            print(f"     已完成: {done}  待处理: {pending}")
            print(f"     续跑命令: mulan distill --ep {state.ep_id or '?'} --resume {tid}")
            print()
    return 0


# ─── private 命令组 ───────────────────────────────────────────────────────────

def cmd_private(args: argparse.Namespace) -> int:
    from mms.memory.private import init_ep, add_note, list_eps, promote_note, close_ep

    action = getattr(args, "private_action", None)

    if action == "init":
        ep_dir = init_ep(args.ep_id, description=getattr(args, "desc", "") or "")
        ok(f"EP {args.ep_id} 私有工作区已初始化：{ep_dir}")
        return 0

    elif action == "note":
        ep_id = args.ep_id
        title = args.title
        content = args.content or ""
        note_type = getattr(args, "type", "notes") or "notes"
        fpath = add_note(ep_id, title, content, note_type=note_type)
        ok(f"已添加 {note_type} 笔记：{fpath}")
        return 0

    elif action == "list":
        status_filter = getattr(args, "status", None)
        eps = list_eps(status=status_filter)
        if not eps:
            info(f"无 EP 工作区{f' (status={status_filter})' if status_filter else ''}")
            return 0
        header("EP 私有工作区列表")
        print()
        for meta in eps:
            status = meta.get("status", "?")
            s_color = _GREEN if status == "active" else _DIM
            notes_n    = len(meta.get("notes", []))
            decisions_n = len(meta.get("decisions", []))
            promoted_n  = len(meta.get("promoted_to", []))
            print(f"  {c(meta['ep_id'], _BOLD):<12} "
                  f"{c(status, s_color):<10} "
                  f"笔记:{notes_n}  决策:{decisions_n}  已升级:{promoted_n}")
            if meta.get("description"):
                info(meta["description"])
            print()
        return 0

    elif action == "promote":
        dst = promote_note(args.ep_id, args.note_file, args.target_layer, args.new_id)
        ok(f"已升级为公有记忆：{dst}")
        warn("请记得手动更新 MEMORY_INDEX.json 并运行 mms validate")
        return 0

    elif action == "close":
        count = close_ep(args.ep_id, keep_promoted=not getattr(args, "purge", False))
        if count is None:
            count = 0
        ok(f"EP {args.ep_id} 工作区已关闭（已升级记忆 {count} 条已保留记录）")
        return 0

    else:
        err(f"未知 private 子命令: {action}")
        return 1


# ─── reset-circuit 命令 ───────────────────────────────────────────────────────

def cmd_reset_circuit(args: argparse.Namespace) -> int:
    from mms.resilience.circuit_breaker import CircuitBreaker

    models = ["qwen3-32b", "qwen3-coder-next"]
    if args.model:
        models = [args.model]

    header("重置熔断器")
    for model in models:
        CircuitBreaker(model_name=model).reset()
        ok(f"{model} 熔断器已重置为 CLOSED 状态")
    return 0


# ─── CLI 入口 ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mulan",
        description=f"{_BOLD}木兰（Mulan）— 端侧 AI 代码工程工具链{_RESET}  |  版本 1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行 'mulan help' 查看带颜色的完整命令参考。
运行 'mulan help <command>' 查看单个命令的详细说明和示例。
        """,
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # help — 彩色命令参考
    p_help = sub.add_parser("help", help="显示彩色命令参考（比 --help 更易读）")
    p_help.add_argument(
        "topic", nargs="?", metavar="<command>",
        help="查看指定命令的详细说明（如 mms help unit）",
    )

    # status
    sub.add_parser("status", help="系统状态总览（Provider 可用性 / 熔断器 / 记忆统计）")

    # distill
    p_distill = sub.add_parser("distill", help="EP 知识蒸馏（qwen3-32b）")
    p_distill.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_distill.add_argument("--ep-file", metavar="PATH", help="EP 文件路径（覆盖自动查找）")
    p_distill.add_argument("--dry-run", action="store_true", help="仅预览，不写入")
    p_distill.add_argument("--resume", metavar="TRACE_ID", help="从断点恢复")

    # gc
    p_gc = sub.add_parser("gc", help="垃圾回收（LFU tier 重计算 + 索引更新）")
    p_gc.add_argument("--dry-run", action="store_true", help="仅预览，不修改文件")
    p_gc.add_argument("--update-index-only", action="store_true", help="只重建索引")

    # validate
    p_val = sub.add_parser("validate", help="记忆文件 Schema 校验")
    p_val.add_argument("--changed-only", action="store_true", help="只校验 git diff 变更文件")
    p_val.add_argument("--file", metavar="NAME", help="校验单个文件（ID 或部分文件名）")
    p_val.add_argument("--migrate-add-version", action="store_true",
                       help="批量添加 version: 1 字段")

    # search
    p_search = sub.add_parser("search", help="关键词检索记忆（推理式，无向量）")
    p_search.add_argument("keywords", nargs="+", help="检索关键词（支持多个）")
    p_search.add_argument("--top-k", type=int, default=5, metavar="N", help="返回条数（默认 5）")
    p_search.add_argument("--preview", action="store_true", help="预览最高匹配记忆的正文")

    # list
    p_list = sub.add_parser("list", help="列出记忆（可按 tier / layer 过滤）")
    p_list.add_argument("--tier", choices=["hot", "warm", "cold", "archive"],
                        help="按热度过滤")
    p_list.add_argument("--layer", metavar="L1-L5|CC", help="按层过滤（如 L3）")

    # hook
    p_hook = sub.add_parser("hook", help="管理 git pre-commit hook")
    p_hook.add_argument("action", choices=["install", "remove", "check"],
                        help="install=安装，remove=移除，check=手动执行（CI 用）")

    # incomplete
    sub.add_parser("incomplete", help="列出未完成的蒸馏断点任务")

    # reset-circuit
    p_rc = sub.add_parser("reset-circuit", help="重置熔断器到 CLOSED 状态")
    p_rc.add_argument("--model", metavar="MODEL_NAME",
                      help="指定重置的模型（默认重置所有）")

    # inject（Unit 3 实现，此处先注册入口）
    p_inject = sub.add_parser("inject", help="记忆注入：自动检索 + 压缩上下文，生成 Cursor 提示词前缀")
    p_inject.add_argument("task", nargs="+", help="任务描述（自然语言）")
    p_inject.add_argument("--top-k", type=int, default=5, help="注入记忆条数（默认 5）")
    p_inject.add_argument("--output", metavar="FILE", help="输出到文件（默认打印到 stdout）")
    p_inject.add_argument("--no-compress", action="store_true",
                          help="不压缩，输出完整记忆正文")
    p_inject.add_argument(
        "--mode",
        choices=["default", "dev", "arch", "debug", "biz", "frontend", "ops"],
        default=None,
        help="注入模式（见 INJECT_MANIFEST.json）：default/dev/arch/debug/biz/frontend/ops"
    )

    # private 子命令组
    p_priv = sub.add_parser("private", help="私有记忆隔离协议（EP 粒度的临时笔记工作区）")
    priv_sub = p_priv.add_subparsers(dest="private_action", metavar="<action>")
    priv_sub.required = True

    # private init
    p_pi = priv_sub.add_parser("init", help="初始化 EP 私有工作区")
    p_pi.add_argument("ep_id", metavar="EP-NNN", help="EP 编号，如 EP-110")
    p_pi.add_argument("--desc", metavar="DESCRIPTION", help="EP 描述（可选）")

    # private note
    p_pn = priv_sub.add_parser("note", help="添加临时笔记到 EP 工作区")
    p_pn.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")
    p_pn.add_argument("title", help="笔记标题")
    p_pn.add_argument("content", nargs="?", default="", help="笔记内容（可为空，后续编辑文件）")
    p_pn.add_argument("--type", choices=["notes", "decisions"], default="notes",
                      help="笔记类型（notes=临时笔记，decisions=决策草稿）")

    # private list
    p_pl = priv_sub.add_parser("list", help="列出所有 EP 私有工作区")
    p_pl.add_argument("--status", choices=["active", "closed"], help="按状态过滤")

    # private promote
    p_pp = priv_sub.add_parser("promote", help="将私有笔记升级为 shared 公有记忆")
    p_pp.add_argument("ep_id",       metavar="EP-NNN",    help="EP 编号")
    p_pp.add_argument("note_file",   metavar="FILE",      help="相对于 private/{ep_id}/ 的文件路径")
    p_pp.add_argument("target_layer",metavar="LAYER",     help="目标 shared 子目录，如 L3_domain/ontology")
    p_pp.add_argument("new_id",      metavar="MEM-ID",    help="新记忆 ID，如 MEM-L-028")

    # private close
    p_pc = priv_sub.add_parser("close", help="关闭 EP 工作区（清理未升级草稿）")
    p_pc.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")
    p_pc.add_argument("--purge", action="store_true",
                      help="完全删除工作区（含已升级记录，谨慎使用）")

    # verify — 记忆系统健康检查
    p_verify = sub.add_parser("verify", help="记忆系统健康检查（schema/index/docs/frontend）")
    p_verify.add_argument("--schema",   action="store_true", help="只检查 YAML front-matter")
    p_verify.add_argument("--index",    action="store_true", help="只检查索引一致性")
    p_verify.add_argument("--docs",     action="store_true", help="只检查文档漂移")
    p_verify.add_argument("--frontend", action="store_true", help="只检查前端规范")
    p_verify.add_argument("--ci",       action="store_true", help="CI 模式（错误则 exit 2）")

    # codemap — 代码目录快照
    p_codemap = sub.add_parser("codemap", help="生成代码目录快照（docs/memory/_system/codemap.md）")
    p_codemap.add_argument("--depth",   type=int, default=3, help="目录展开深度（默认 3）")
    p_codemap.add_argument("--recent",  type=int, default=0, help="附加最近修改文件数量（默认 0）")
    p_codemap.add_argument("--dry-run", action="store_true",  help="只打印，不写文件")

    # funcmap — 函数签名索引
    p_funcmap = sub.add_parser("funcmap", help="生成函数签名索引（docs/memory/_system/funcmap.md）")
    p_funcmap.add_argument("--backend-only",  action="store_true", help="只扫描后端 Python")
    p_funcmap.add_argument("--frontend-only", action="store_true", help="只扫描前端 TS/TSX")
    p_funcmap.add_argument("--dry-run",       action="store_true", help="只打印，不写文件")

    # usage — 模型使用统计
    p_usage = sub.add_parser(
        "usage",
        help="模型调用统计：查看 qwen3-32b / qwen3-coder-next 等模型的使用量、Token 消耗和场景分布",
    )
    p_usage.add_argument(
        "--since", type=int, default=7, metavar="DAYS",
        help="统计最近 N 天的记录（默认 7；0 = 全部历史）",
    )
    p_usage.add_argument(
        "--model", metavar="MODEL_NAME",
        help="仅显示指定模型的记录，如 qwen3-32b",
    )
    p_usage.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="输出格式：table（彩色表格，默认）| json（原始数据）",
    )

    # synthesize — LLM 意图合成器
    p_synth = sub.add_parser(
        "synthesize",
        help="LLM 意图合成：结合记忆+EP模板，调用 qwen3-32b 生成结构化 Cursor 起手提示词",
    )
    p_synth.add_argument(
        "task", nargs="+",
        help="任务描述（自然语言，如：新增对象类型批量导出 API）",
    )
    p_synth.add_argument(
        "--template", metavar="TEMPLATE",
        choices=[
            "ep-backend-api",
            "ep-frontend",
            "ep-ontology",
            "ep-data-pipeline",
            "ep-debug",
            "ep-devops",
            "ep-others",
        ],
        help=(
            "EP 类型模板：\n"
            "  ep-backend-api   新增后端 API / Service / Repository\n"
            "  ep-frontend      新增前端页面 / 组件 / Zustand Store\n"
            "  ep-ontology      本体层操作（对象/链接/Action/Function）\n"
            "  ep-data-pipeline 数据管道（Connector / SyncJob / Worker）\n"
            "  ep-debug         Bug 诊断 / 热修复 / 性能问题\n"
            "  ep-devops        运维 / 部署 / 本地调试 / K8s 配置\n"
            "  ep-others        跨层重构 / 安全加固 / 性能优化 / 测试补全 / 文档整理"
        ),
    )
    p_synth.add_argument(
        "--extra", metavar="REQUIREMENTS",
        help='自定义要求（追加到模板末尾），如 --extra "需要支持分页，不允许修改现有 Model"',
    )
    p_synth.add_argument(
        "--interactive", "-i", action="store_true",
        help="交互式补充自定义要求（多行输入，Ctrl+D 结束）",
    )
    p_synth.add_argument(
        "--top-k", type=int, default=5,
        help="记忆检索数量（默认 5）",
    )
    p_synth.add_argument(
        "--output", "-o", metavar="FILE",
        help="将结果写入文件（默认打印到终端）",
    )
    p_synth.add_argument(
        "--list-templates", action="store_true",
        help="列出所有可用模板",
    )
    p_synth.add_argument(
        "--refresh-maps", action="store_true",
        help="合成前自动刷新 codemap + funcmap 快照（确保文件路径最新）",
    )

    # precheck — 代码修改前检查门控
    p_precheck = sub.add_parser(
        "precheck",
        help="代码修改前检查门控：arch_check 基线 + Scope 解析 + 影响范围分析",
    )
    p_precheck.add_argument(
        "--ep", metavar="EP-NNN", required=True,
        help="EP 编号，如 EP-114",
    )
    p_precheck.add_argument(
        "--strict", action="store_true",
        help="严格模式：WARN 也视为阻断",
    )

    # postcheck — 代码修改后测试与后校验
    p_postcheck = sub.add_parser(
        "postcheck",
        help="代码修改后测试与后校验：pytest（精准）+ arch_check diff + doc_drift",
    )
    p_postcheck.add_argument(
        "--ep", metavar="EP-NNN", required=True,
        help="EP 编号，如 EP-114",
    )
    p_postcheck.add_argument(
        "--skip-tests", action="store_true",
        help="跳过 pytest（仅做架构和文档检查）",
    )
    p_postcheck.add_argument(
        "--test-paths", nargs="+", metavar="PATH",
        help="额外的测试文件路径（补充 EP 文件 Testing Plan 声明的路径）",
    )

    # actions — 列出 / 查看 ActionDef + FunctionDef
    p_actions = sub.add_parser(
        "actions",
        help="列出 MMS 系统动作与函数定义（ActionDef / FunctionDef）",
    )
    p_actions.add_argument(
        "action_id", nargs="?", metavar="ID",
        help="查看单个 Action/Function 的详情（部分匹配）",
    )
    p_actions.add_argument(
        "--functions", action="store_true",
        help="切换为展示 FunctionDef（默认展示 ActionDef）",
    )

    # graph — 记忆知识图谱查询
    p_graph = sub.add_parser(
        "graph",
        help="记忆知识图谱查询（图遍历 / 文件反查 / 影响分析）",
    )
    p_graph_sub = p_graph.add_subparsers(dest="subcommand", metavar="<subcommand>")

    p_graph_sub.add_parser("stats", help="图谱统计（节点数、边数、孤立节点）")

    p_explore = p_graph_sub.add_parser("explore", help="从指定节点出发做 BFS 图遍历")
    p_explore.add_argument("id", help="起始记忆节点 ID（如 AD-002）")
    p_explore.add_argument("--depth", type=int, default=2, help="遍历深度（默认 2）")

    p_file = p_graph_sub.add_parser("file", help="反查引用某文件的所有记忆节点")
    p_file.add_argument("path", help="文件路径（如 frontend/src/config/navigation.ts）")

    p_impacts = p_graph_sub.add_parser("impacts", help="查询某记忆变更时需同步检查的节点")
    p_impacts.add_argument("id", help="记忆节点 ID")

    # unit — DAG 任务编排（EP-117）
    p_unit = sub.add_parser(
        "unit",
        help="DAG 任务编排：将 EP 分解为原子 Unit，支持 small model 执行",
    )
    p_unit_sub = p_unit.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # unit generate
    p_ug = p_unit_sub.add_parser("generate", help="生成 EP 的 DAG 执行计划（capable model 编排）")
    p_ug.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_ug.add_argument("--force", action="store_true", help="强制重新生成（覆盖已有）")
    p_ug.add_argument("--no-llm", action="store_true", help="仅解析 DAG Sketch，不调用 LLM")

    # unit status
    p_us = p_unit_sub.add_parser("status", help="查看 EP DAG 执行状态（批次 + 进度条）")
    p_us.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")

    # unit next
    p_un = p_unit_sub.add_parser("next", help="获取下一个可执行 Unit + 压缩上下文")
    p_un.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_un.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="目标执行模型（过滤不满足原子化阈值的 Unit）",
    )

    # unit done
    p_ud = p_unit_sub.add_parser("done", help="标记 Unit 完成（验证 + 运行测试 + git commit）")
    p_ud.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_ud.add_argument("--unit", required=True, metavar="U1", help="Unit ID")
    p_ud.add_argument("--skip-tests", action="store_true", help="跳过测试验证")
    p_ud.add_argument("--skip-commit", action="store_true", help="跳过 git commit")

    # unit context
    p_uc = p_unit_sub.add_parser("context", help="生成指定 Unit 的自包含执行上下文（token 受限）")
    p_uc.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_uc.add_argument("--unit", required=True, metavar="U1", help="Unit ID")
    p_uc.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="目标执行模型（影响 token 预算）",
    )

    # unit reset
    p_ur = p_unit_sub.add_parser("reset", help="回退 Unit 状态为 pending（不回退 git commit）")
    p_ur.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_ur.add_argument("--unit", required=True, metavar="U1", help="Unit ID")

    # unit skip
    p_usk = p_unit_sub.add_parser("skip", help="跳过指定 Unit（不验证，不 commit）")
    p_usk.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_usk.add_argument("--unit", required=True, metavar="U1", help="Unit ID")

    # unit run — LLM 自动执行单个 Unit（EP-119）
    p_urun = p_unit_sub.add_parser("run", help="LLM 自动执行指定 Unit（3-Strike 重试 + 沙箱回滚）")
    p_urun.add_argument("--ep",    required=True, metavar="EP-NNN", help="EP 编号")
    p_urun.add_argument("--unit",  required=True, metavar="U1",     help="Unit ID")
    p_urun.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="执行模型（默认 capable）",
    )
    p_urun.add_argument("--dry-run",     action="store_true", help="只生成代码预览，不写文件")
    p_urun.add_argument("--confirm",     action="store_true", help="写入前展示摘要等待确认")
    p_urun.add_argument("--save-output", action="store_true",
                        help="EP-120 双模型模式：将 qwen 输出存盘到 compare/ 目录，不写业务文件")

    # unit run-next — 执行当前批次所有 pending Unit
    p_urn = p_unit_sub.add_parser("run-next", help="执行当前批次所有可执行 Unit（顺序执行）")
    p_urn.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_urn.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="执行模型",
    )
    p_urn.add_argument("--dry-run",       action="store_true", help="只预览，不写文件")
    p_urn.add_argument("--confirm",       action="store_true", help="写入前等待确认")
    p_urn.add_argument("--max-failures",  type=int, default=1, metavar="N",
                       help="允许的最大失败 Unit 数（默认 1，超过则停止批次）")

    # unit run-all — 执行 EP 所有 pending Unit
    p_ura = p_unit_sub.add_parser("run-all", help="顺序执行 EP 全部 pending Unit（谨慎使用）")
    p_ura.add_argument("--ep", required=True, metavar="EP-NNN", help="EP 编号")
    p_ura.add_argument(
        "--model", choices=["8b", "16b", "capable", "fast"], default="capable",
        help="执行模型",
    )
    p_ura.add_argument("--dry-run",       action="store_true", help="只预览，不写文件")
    p_ura.add_argument("--confirm",       action="store_true", help="每个 Unit 写入前等待确认")
    p_ura.add_argument("--max-failures",  type=int, default=1, metavar="N",
                       help="允许的最大失败 Unit 数（默认 1）")

    # unit compare — 双模型对比（EP-120）
    p_ucmp = p_unit_sub.add_parser(
        "compare",
        help="EP-120：生成 qwen vs sonnet 机械 diff 报告 report.md",
    )
    p_ucmp.add_argument("--ep",   required=True, metavar="EP-NNN", help="EP 编号")
    p_ucmp.add_argument("--unit", required=True, metavar="U1",     help="Unit ID")
    p_ucmp.add_argument(
        "--apply", dest="apply_source", metavar="qwen|sonnet", default=None,
        help="应用指定版本到业务文件并提交（省略则只生成报告）",
    )

    # unit sonnet-save — 保存 Cursor Sonnet 输出（EP-120）
    p_uss = p_unit_sub.add_parser(
        "sonnet-save",
        help="EP-120：将 Cursor Sonnet 生成的代码保存为 sonnet.txt",
    )
    p_uss.add_argument("--ep",   required=True, metavar="EP-NNN", help="EP 编号")
    p_uss.add_argument("--unit", required=True, metavar="U1",     help="Unit ID")
    p_uss.add_argument(
        "--file", metavar="PATH", default=None,
        help="从文件读取 Sonnet 输出（省略则从 stdin 读）",
    )

    # ep — 交互式 EP 工作流向导（EP-122）
    p_ep = sub.add_parser(
        "ep",
        help="EP 工作流向导：7 步引导式 CLI，完整贯通意图合成→DAG→双模型→后校验→蒸馏",
    )
    p_ep_sub = p_ep.add_subparsers(dest="subcommand", metavar="<subcommand>")

    p_ep_start = p_ep_sub.add_parser("start", help="启动或续跑 EP 工作流向导")
    p_ep_start.add_argument("ep_id", metavar="EP-NNN", help="EP 编号，如 EP-122")
    p_ep_start.add_argument(
        "--from-step", type=int, default=1, metavar="N",
        help="从第 N 步开始（默认 1，支持断点续跑）",
    )

    p_ep_status = p_ep_sub.add_parser("status", help="查看 EP 向导进度")
    p_ep_status.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")

    # ep run — EP 自动执行 Pipeline（EP-131）
    p_ep_run = p_ep_sub.add_parser(
        "run",
        help="[EP-131] 一键执行整个 EP（自动 precheck→units→postcheck）",
    )
    p_ep_run.add_argument("ep_id", metavar="EP-NNN", help="EP 编号，如 EP-131")
    p_ep_run.add_argument(
        "--from-unit", metavar="UN", default=None,
        help="从指定 Unit 续跑（如 U3），之前的 Unit 跳过",
    )
    p_ep_run.add_argument(
        "--only", nargs="+", metavar="UN", default=None,
        help="只执行指定 Unit（如 --only U1 U2）",
    )
    p_ep_run.add_argument(
        "--dry-run", action="store_true",
        help="模拟执行，不写文件，不提交 git",
    )
    p_ep_run.add_argument(
        "--skip-precheck", action="store_true",
        help="跳过 Phase 1 precheck",
    )
    p_ep_run.add_argument(
        "--skip-postcheck", action="store_true",
        help="跳过 Phase 3 postcheck",
    )
    p_ep_run.add_argument(
        "--auto-confirm", action="store_true",
        help="跳过计划摘要确认（CI 模式）",
    )
    p_ep_run.add_argument(
        "--model", default="capable",
        help="默认执行模型（Unit 自身 model_hint 优先，默认 capable）",
    )

    # dream — autoDream 知识萃取（EP-118）
    p_dream = sub.add_parser(
        "dream",
        help="autoDream：从 EP/git 历史自动萃取知识，生成记忆草稿",
    )
    p_dream.add_argument("--ep", metavar="EP-NNN", default=None, help="针对指定 EP 萃取")
    p_dream.add_argument("--since", metavar="Nd", default="7d", help="git 时间范围（默认 7d）")
    p_dream.add_argument("--promote", action="store_true", help="交互式审核草稿 → 提升为正式记忆")
    p_dream.add_argument("--list", action="store_true", dest="list_drafts", help="列出所有草稿文件")
    p_dream.add_argument("--dry-run", action="store_true", help="只打印 prompt 预览，不调用 LLM")

    # template — 代码模板库（EP-118）
    p_tmpl = sub.add_parser(
        "template",
        help="代码模板库：填空式代码骨架，降低小模型幻觉率",
    )
    p_tmpl_sub = p_tmpl.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # template list
    p_tmpl_sub.add_parser("list", help="列出所有可用模板")

    # template info
    p_ti = p_tmpl_sub.add_parser("info", help="查看模板变量说明和预览")
    p_ti.add_argument("name", help="模板名称（如 service-method）")

    # template use
    p_tu = p_tmpl_sub.add_parser("use", help="渲染模板（替换变量后输出代码）")
    p_tu.add_argument("name", help="模板名称")
    p_tu.add_argument(
        "--var", action="append", default=[], metavar="KEY=VALUE",
        help="模板变量（可多次指定，如 --var entity=ObjectType --var method=create）",
    )
    p_tu.add_argument("--output", metavar="FILE", default=None, help="输出到文件（默认 stdout）")
    p_tu.add_argument("--dry-run", action="store_true", help="预览渲染结果（不写文件）")

    # ─── trace 命令（EP-127 诊断追踪）─────────────────────────────────────────
    p_trace = sub.add_parser(
        "trace",
        help="诊断追踪：类 Oracle 10046 Trace，记录 EP 工作流全链路耗时与 LLM 调用详情",
    )
    p_trace_sub = p_trace.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # trace enable
    p_te = p_trace_sub.add_parser("enable", help="开启指定 EP 的诊断追踪")
    p_te.add_argument("ep_id", metavar="EP-NNN", help="EP 编号（如 EP-126）")
    p_te.add_argument(
        "--level", type=int, default=4, choices=[1, 4, 8, 12],
        metavar="LEVEL",
        help="诊断级别：1=Basic(步骤耗时) 4=LLM(token/模型) 8=FileOps(文件变更) 12=Full(IO内容)（默认4）",
    )

    # trace disable
    p_td = p_trace_sub.add_parser("disable", help="关闭指定 EP 的诊断追踪（保留已有数据）")
    p_td.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")

    # trace show
    p_ts = p_trace_sub.add_parser("show", help="查看诊断报告（类 tkprof 输出）")
    p_ts.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")
    p_ts.add_argument(
        "--format", choices=["text", "json", "html"], default="text",
        help="输出格式（text=终端/json=结构化/html=浏览器，默认text）",
    )
    p_ts.add_argument("--step", metavar="KEYWORD", default=None, help="只显示包含此关键词的步骤")
    p_ts.add_argument("--unit", metavar="U1", default=None, help="只显示指定 Unit 的事件")
    p_ts.add_argument("--no-color", action="store_true", help="禁用 ANSI 颜色（CI 环境使用）")
    p_ts.add_argument("--no-save", action="store_true", help="不保存报告到磁盘（只打印）")

    # trace summary
    p_tsum = p_trace_sub.add_parser("summary", help="一行摘要（LLM 次数/总耗时/token）")
    p_tsum.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")

    # trace list
    p_trace_sub.add_parser("list", help="列出所有有追踪记录的 EP")

    # trace clean
    p_tclean = p_trace_sub.add_parser("clean", help="清除指定 EP 的所有追踪数据")
    p_tclean.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")
    p_tclean.add_argument("--yes", action="store_true", help="跳过确认直接删除")

    # trace config
    p_tcfg = p_trace_sub.add_parser("config", help="修改追踪配置（不重置已有数据）")
    p_tcfg.add_argument("ep_id", metavar="EP-NNN", help="EP 编号")
    p_tcfg.add_argument("--level", type=int, choices=[1, 4, 8, 12], default=None,
                        help="修改诊断级别")

    # ─── diag 命令（MDR 诊断工具，类比 Oracle ADRCI）────────────────────────
    p_diag = sub.add_parser(
        "diag",
        help="诊断工具：查看系统告警日志 / 打包崩溃现场（类 Oracle ADRCI）",
    )
    p_diag_sub = p_diag.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # diag status
    p_diag_sub.add_parser(
        "status",
        help="读取 alert_mulan.log 尾部，报告当前系统是否有未处理的 FATAL 告警",
    )

    # diag pack
    p_dpack = p_diag_sub.add_parser(
        "pack",
        help="打包指定 Incident 的诊断数据为 ZIP（供附到 GitHub Issue）",
    )
    p_dpack.add_argument("incident_id", metavar="<incident_id>", help="Incident ID（如 inc_20260427_2347_JSONDecodeError）")
    p_dpack.add_argument("--output-dir", metavar="DIR", default=None,
                         help="ZIP 输出目录（默认：项目根目录）")

    # diag list
    p_diag_sub.add_parser(
        "list",
        help="列出所有已记录的 Incident（时间倒序）",
    )

    # ── EP-130: bootstrap ────────────────────────────────────────────────────
    p_bootstrap = sub.add_parser(
        "bootstrap",
        help="[EP-130] 离线冷启动：AST 骨架化 + 种子包注入（零 LLM 消耗）",
    )
    p_bootstrap.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：只打印计划，不写文件",
    )
    p_bootstrap.add_argument(
        "--root", type=str, default=None,
        help="项目根目录（默认：当前工作区根）",
    )
    p_bootstrap.add_argument(
        "--skip-ast", action="store_true",
        help="跳过 AST 骨架化（只注入种子包）",
    )
    p_bootstrap.add_argument(
        "--skip-seeds", action="store_true",
        help="跳过种子包注入（只做 AST 骨架化）",
    )

    # ── EP-130: ast-diff ─────────────────────────────────────────────────────
    p_astdiff = sub.add_parser(
        "ast-diff",
        help="[EP-130] 比对 AST 快照，检测接口契约变更",
    )
    p_astdiff.add_argument(
        "--ep", metavar="EP-NNN", default=None,
        help="比对此 EP 的 precheck 快照 vs 当前状态",
    )
    p_astdiff.add_argument(
        "--before", metavar="FILE", default=None,
        help="比对前的 ast_index.json 路径",
    )
    p_astdiff.add_argument(
        "--after", metavar="FILE", default=None,
        help="比对后的 ast_index.json 路径（默认：当前 ast_index.json）",
    )
    p_astdiff.add_argument(
        "--files", metavar="FILE", nargs="+", default=None,
        help="只比对这些文件（空则全量比对）",
    )

    # ── seed — 种子包管理（Rule Absorber EP-131）─────────────────────────────
    p_seed = sub.add_parser(
        "seed",
        help="种子包管理：列出 / 注入 / 吸收外部规范",
    )
    p_seed_sub = p_seed.add_subparsers(dest="subcommand", metavar="<subcommand>")

    # seed list
    p_seed_sub.add_parser("list", help="列出所有已安装的种子包")

    # seed ingest
    p_si = p_seed_sub.add_parser(
        "ingest",
        help="从 URL 或本地文件吸收 .cursorrules/.mdc 规范，蒸馏为 MMS 种子记忆",
    )
    p_si.add_argument("url", metavar="URL_OR_PATH", help="GitHub raw URL 或本地文件路径")
    p_si.add_argument(
        "--seed-name", default=None,
        help="目标种子包名称（默认从 URL 文件名推导）",
    )
    p_si.add_argument(
        "--dry-run", action="store_true",
        help="预览蒸馏结果，不写文件",
    )
    p_si.add_argument(
        "--force", action="store_true",
        help="覆盖同名已有种子包",
    )
    p_si.add_argument(
        "--format", choices=["v31", "v2"], default="v31", dest="output_format",
        help="输出格式：v31=docs/memory/seed_packs/（推荐）v2=seed_packs/（旧格式）",
    )

    # seed ingest-batch
    p_sib = p_seed_sub.add_parser(
        "ingest-batch",
        help="批量吸收多个 .mdc 规则文件（支持 GitHub 目录 URL）",
    )
    p_sib.add_argument(
        "urls", nargs="+", metavar="URL",
        help="多个规则 URL，或一个 GitHub 目录 URL（自动展开）",
    )
    p_sib.add_argument(
        "--filter", default=None, dest="name_filter", metavar="KEYWORDS",
        help="只处理文件名包含指定关键词的规则（逗号分隔，如 'fastapi,redis,docker'）",
    )
    p_sib.add_argument(
        "--prefix", default="", dest="seed_prefix", metavar="PREFIX",
        help="种子包名称前缀（默认无）",
    )
    p_sib.add_argument(
        "--dry-run", action="store_true",
        help="预览蒸馏结果，不写文件",
    )
    p_sib.add_argument(
        "--force", action="store_true",
        help="覆盖同名已有种子包",
    )
    p_sib.add_argument(
        "--format", choices=["v31", "v2"], default="v31", dest="output_format",
        help="输出格式：v31（推荐）或 v2（旧格式）",
    )

    # ── benchmark — 三层模块化评测（v2）────────────────────────────────────────
    p_bench = sub.add_parser(
        "benchmark",
        help="三层 Benchmark 评测（离线安全门控 / 记忆质量 / SWE-bench 信用锚）",
    )
    p_bench.add_argument(
        "--level", choices=["offline", "fast", "full"], default="offline",
        help="运行级别：offline=仅 L3 无需LLM，fast=L2+L3，full=全部三层",
    )
    p_bench.add_argument(
        "--layer", type=int, choices=[1, 2, 3], default=None,
        help="仅运行指定单层（1=SWE-bench, 2=记忆质量, 3=安全门控）",
    )
    p_bench.add_argument(
        "--domain", nargs="+", default=["generic_python"],
        metavar="DOMAIN",
        help="评测 domain（可多选），默认: generic_python",
    )
    p_bench.add_argument(
        "--llm", action="store_true", default=False,
        help="声明 LLM API 可用（开启注入提升等在线评测维度）",
    )
    p_bench.add_argument(
        "--dry-run", action="store_true", default=False,
        help="仅打印任务列表，不实际执行评测",
    )
    p_bench.add_argument(
        "--output", choices=["console", "json", "markdown"], default="console",
        help="报告输出格式（默认 console）",
    )
    p_bench.add_argument(
        "--output-path", dest="output_path", default=None,
        help="报告保存路径（json/markdown 格式时有效）",
    )
    p_bench.add_argument(
        "--max-tasks", dest="max_tasks", type=int, default=None,
        help="每层最多运行任务数（调试用）",
    )
    p_bench.add_argument("-v", "--verbose", action="store_true", default=False)

    return parser


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """bootstrap 子命令：冷启动 AST 骨架化 + 种子包注入。"""
    import time

    try:
        sys.path.insert(0, str(_SRC_DIR))
        from mms.analysis.dep_sniffer import sniff  # type: ignore[import]
        from seed_packs import install_packs  # type: ignore[import]
        from mms.analysis.ast_skeleton import build_ast_index  # type: ignore[import]
        from mms.memory.repo_map import RepoMap, invalidate_cache  # type: ignore[import]
    except ImportError as e:
        print(f"❌ EP-130 模块未找到（{e}），请确认已实施 EP-130 U1/U2")
        return 1

    root = Path(args.root) if getattr(args, "root", None) else _PROJECT_ROOT
    dry_run = getattr(args, "dry_run", False)
    skip_ast = getattr(args, "skip_ast", False)
    skip_seeds = getattr(args, "skip_seeds", False)

    print(f"\n{'='*60}")
    print(f"  MMS Bootstrap — 离线冷启动（EP-130）")
    print(f"  项目根：{root}")
    print(f"{'='*60}\n")

    start_total = time.time()

    # ── Step 1: 依赖嗅探 ──────────────────────────────────────────────────────
    print("▶ Step 1/4 · 技术栈嗅探...")
    profile = sniff(root=root)
    print(f"  检测到栈：{profile.detected_stacks}")
    print(f"  置信度：{profile.confidence:.0%}")
    print(f"  扫描来源：{profile.scan_sources}\n")

    # ── Step 2: 种子包注入 ────────────────────────────────────────────────────
    installed_packs = []
    if not skip_seeds:
        print("▶ Step 2/4 · 注入种子包...")
        target_docs = root / "docs"
        installed_packs = install_packs(
            pack_names=profile.detected_stacks,
            target_docs=target_docs,
            dry_run=dry_run,
        )
        if installed_packs:
            print(f"  ✅ 已注入 {len(installed_packs)} 个种子包：{installed_packs}")
        else:
            print(f"  ℹ️  无新种子包需要注入")
    else:
        print("▶ Step 2/4 · 跳过种子包注入（--skip-seeds）\n")

    # ── Step 3: AST 骨架化 ────────────────────────────────────────────────────
    if not skip_ast:
        print("\n▶ Step 3/4 · AST 骨架化...")
        t0 = time.time()
        ast_index = build_ast_index(root=root, dry_run=dry_run)
        elapsed = time.time() - t0
        total_classes = sum(len(v.get("classes", [])) for v in ast_index.values())
        total_methods = sum(
            len(c.get("methods", []))
            for v in ast_index.values()
            for c in v.get("classes", [])
        )
        print(f"  ✅ 扫描完成：{len(ast_index)} 个文件，{total_classes} 类，{total_methods} 方法（{elapsed:.1f}s）")
        if not dry_run:
            invalidate_cache()
    else:
        print("▶ Step 3/4 · 跳过 AST 骨架化（--skip-ast）\n")

    # ── Step 4: 绑定 Entry Points ─────────────────────────────────────────────
    print("\n▶ Step 4/4 · 绑定 AST 入口点...")
    try:
        if not skip_ast and not dry_run:
            from mms.analysis.arch_resolver import ArchResolver  # type: ignore[import]
            resolver = ArchResolver()
            rm = RepoMap()

            layers_data = resolver._layers_data
            if not resolver._layers_data:
                resolver._ensure_loaded()

            bindings = rm.bind_entry_points(resolver._layers_data or {})
            print(f"  ✅ 绑定了 {len(bindings)} 个入口点 AST 指针")
        else:
            print("  ℹ️  dry-run 模式，跳过绑定")
    except Exception as e:
        print(f"  ⚠️  绑定入口点失败（已跳过）: {e}")

    # ── 汇总 ─────────────────────────────────────────────────────────────────
    total_elapsed = time.time() - start_total
    print(f"\n{'='*60}")
    print(f"  Bootstrap 完成（耗时 {total_elapsed:.1f}s，零 LLM 调用）")
    print(f"  注入种子包：{len(installed_packs)} 个")
    print(f"  AST 扫描：{'已完成' if not skip_ast else '跳过'}")
    if dry_run:
        print(f"  ⚠️  dry-run 模式，文件未实际写入")
    print(f"{'='*60}\n")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """seed 子命令：种子包管理 + Rule Absorber。"""
    subcmd = getattr(args, "subcommand", None)

    if subcmd == "list" or subcmd is None:
        seed_root = _PROJECT_ROOT / "seed_packs"
        packs = sorted(
            p for p in seed_root.iterdir()
            if p.is_dir() and not p.name.startswith("_") and not p.name.startswith(".")
        )
        if not packs:
            print("  (无种子包)")
            return 0
        print(f"\n  已安装种子包（{len(packs)} 个）：\n")
        for p in packs:
            mc = p / "match_conditions.yaml"
            desc = ""
            if mc.exists():
                for line in mc.read_text(encoding="utf-8").splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip('"')
                        break
            layers = sum(1 for _ in (p / "arch_schema").glob("*.yaml")) if (p / "arch_schema").exists() else 0
            onto = sum(1 for _ in (p / "ontology").glob("*.yaml")) if (p / "ontology").exists() else 0
            cons = sum(1 for _ in (p / "constraints").glob("*.yaml")) if (p / "constraints").exists() else 0
            print(f"  📦  {p.name:<25} arch:{layers} ontology:{onto} constraints:{cons}")
            if desc:
                print(f"       {desc}")
        print()
        return 0

    elif subcmd == "ingest":
        try:
            from mms.analysis.seed_absorber import ingest  # type: ignore[import]
        except ImportError as e:
            print(f"❌ seed_absorber 模块未找到（{e}）")
            return 1

        url = getattr(args, "url", None)
        if not url:
            print("❌ 请指定 URL 或本地文件路径")
            return 1

        seed_name = getattr(args, "seed_name", None)
        dry_run = getattr(args, "dry_run", False)
        force = getattr(args, "force", False)
        output_format = getattr(args, "output_format", "v31")

        print(f"\n{'='*60}")
        print(f"  MMS Rule Absorber v2 — 规则吸收器")
        print(f"{'='*60}")
        try:
            result_dir = ingest(url, seed_name=seed_name, dry_run=dry_run,
                                force=force, output_format=output_format)
            if not dry_run:
                print(f"\n  ✅ 种子包就绪：{result_dir}")
                print(f"  提示：运行 `mulan seed list` 查看所有种子包")
                print(f"  提示：运行 `mulan bootstrap` 将种子包注入到当前项目\n")
        except (FileNotFoundError, ValueError) as e:
            print(f"\n  ❌ 获取失败：{e}\n")
            return 1
        return 0

    elif subcmd == "ingest-batch":
        try:
            from mms.analysis.seed_absorber import ingest_batch  # type: ignore[import]
        except ImportError as e:
            print(f"❌ seed_absorber 模块未找到（{e}）")
            return 1

        urls = getattr(args, "urls", [])
        if not urls:
            print("❌ 请至少指定一个 URL 或 GitHub 目录 URL")
            return 1

        dry_run = getattr(args, "dry_run", False)
        force = getattr(args, "force", False)
        output_format = getattr(args, "output_format", "v31")
        seed_prefix = getattr(args, "seed_prefix", "")
        name_filter = getattr(args, "name_filter", None)

        print(f"\n{'='*60}")
        print(f"  MMS Rule Absorber v2 — 批量规则吸收")
        print(f"{'='*60}")
        results = ingest_batch(
            urls,
            seed_prefix=seed_prefix,
            dry_run=dry_run,
            force=force,
            output_format=output_format,
            name_filter=name_filter,
        )
        if not dry_run and results:
            print(f"\n  ✅ 已生成 {len(results)} 个种子包，运行 `mulan seed list` 查看")
        return 0

    else:
        print(f"未知子命令 `{subcmd}`，使用 `mulan seed --help` 查看帮助")
        return 1


def cmd_ast_diff(args: argparse.Namespace) -> int:
    """ast-diff 子命令：比对 AST 快照检测契约变更。"""
    try:
        sys.path.insert(0, str(_SRC_DIR))
        from mms.analysis.ast_diff import diff_ast_files, load_ast_index  # type: ignore[import]
    except ImportError as e:
        print(f"❌ ast_diff 模块未找到（{e}）")
        return 1

    ast_index_default = _PROJECT_ROOT / "docs" / "memory" / "_system" / "ast_index.json"
    checkpoint_dir = _PROJECT_ROOT / "docs" / "memory" / "_system" / "checkpoints"

    ep_id = getattr(args, "ep", None)
    before_path_arg = getattr(args, "before", None)
    after_path_arg = getattr(args, "after", None)
    scope_files = getattr(args, "files", None)

    # 确定 before / after 路径
    if ep_id:
        ep_norm = ep_id.upper()
        before_path = checkpoint_dir / f"precheck-{ep_norm}-ast.json"
        after_path = ast_index_default
    elif before_path_arg:
        before_path = Path(before_path_arg)
        after_path = Path(after_path_arg) if after_path_arg else ast_index_default
    else:
        print("❌ 请指定 --ep 或 --before")
        return 1

    if not before_path.exists():
        print(f"❌ before 快照不存在：{before_path}")
        if ep_id:
            print(f"   提示：先运行 mulan precheck --ep {ep_id} 建立基线快照")
        return 1

    print(f"\nAST 契约 Diff：{before_path.name} → {after_path.name}")
    if scope_files:
        print(f"范围：{scope_files}")

    diff_result = diff_ast_files(before_path, after_path, scope_files)
    print(diff_result.summary())

    if diff_result.has_breaking_changes:
        print("\n⚠️  发现破坏性契约变更，建议运行：mms postcheck 确认 Ontology 同步状态")
        return 1
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """verify 子命令：调用 verify.py 主逻辑"""
    try:
        from mms.utils.verify import (
            check_schema, check_index, check_docs, check_frontend
        )
    except ImportError:
        from mms.utils.verify import (  # type: ignore[no-redef]
            check_schema, check_index, check_docs, check_frontend
        )

    run_all = not any([args.schema, args.index, args.docs, args.frontend])
    all_errors: list = []
    all_warnings: list = []

    tasks = [
        ("schema",   check_schema,   args.schema   or run_all, "Schema 校验"),
        ("index",    check_index,    args.index    or run_all, "索引一致性"),
        ("docs",     check_docs,     args.docs     or run_all, "文档漂移检测"),
        ("frontend", check_frontend, args.frontend or run_all, "前端规范检查"),
    ]

    print("\nMMS 健康检查\n" + "─" * 50)
    for _key, fn, enabled, label in tasks:
        if not enabled:
            continue
        print(f"\n▶ {label}")
        issues = fn()
        if not issues:
            ok("通过")
        else:
            for issue in issues:
                if "[docs]" in issue or "[frontend]" in issue:
                    warn(issue)
                    all_warnings.append(issue)
                else:
                    err(issue)
                    all_errors.append(issue)

    print("\n" + "─" * 50)
    if all_errors:
        err(f"{len(all_errors)} 个错误，{len(all_warnings)} 个警告")
        return 2 if args.ci else 1
    elif all_warnings:
        warn(f"0 个错误，{len(all_warnings)} 个警告（不阻断 CI）")
        return 0
    else:
        ok("全部检查通过")
        return 0


def cmd_codemap(args: argparse.Namespace) -> int:
    """codemap 子命令：生成代码目录快照"""
    try:
        from mms.memory.codemap import generate_codemap
    except ImportError:
        from mms.memory.codemap import generate_codemap  # type: ignore[no-redef]

    output = _MEMORY_ROOT / "_system" / "codemap.md"

    content = generate_codemap(
        max_depth=args.depth,
        recent_count=args.recent,
    )

    if getattr(args, "dry_run", False):
        print(content)
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    ok(f"codemap 已生成：{output.relative_to(_PROJECT_ROOT)}")
    info(f"目录深度: {args.depth} 层 | 字符数: {len(content)}")
    return 0


def cmd_funcmap(args: argparse.Namespace) -> int:
    """funcmap 子命令：生成函数签名索引"""
    try:
        from mms.memory.funcmap import generate_funcmap
    except ImportError:
        from mms.memory.funcmap import generate_funcmap  # type: ignore[no-redef]

    output = _MEMORY_ROOT / "_system" / "funcmap.md"

    content = generate_funcmap(
        backend_only=getattr(args, "backend_only", False),
        frontend_only=getattr(args, "frontend_only", False),
    )

    if getattr(args, "dry_run", False):
        print(content[:3000])
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    ok(f"funcmap 已生成：{output.relative_to(_PROJECT_ROOT)}")
    info(f"字符数: {len(content)}")
    return 0


def cmd_usage(args: argparse.Namespace) -> int:
    """usage 子命令：展示模型调用统计报告"""
    try:
        from mms.utils.model_tracker import print_report
    except ImportError:
        from mms.utils.model_tracker import print_report  # type: ignore[no-redef]

    since = getattr(args, "since", 7)
    model = getattr(args, "model", None)
    fmt   = getattr(args, "format", "table")
    print_report(since_days=since, filter_model=model, fmt=fmt)
    return 0


def cmd_synthesize(args: argparse.Namespace) -> int:
    """synthesize 子命令：LLM 意图合成，生成结构化 Cursor 起手提示词"""
    try:
        from mms.workflow.synthesizer import synthesize, list_templates, interactive_extra_requirements
    except ImportError:
        from mms.workflow.synthesizer import synthesize, list_templates, interactive_extra_requirements  # type: ignore[no-redef]

    if getattr(args, "list_templates", False):
        list_templates()
        return 0

    task_desc = " ".join(args.task)
    template = getattr(args, "template", None)
    extra = getattr(args, "extra", None)
    interactive = getattr(args, "interactive", False)
    top_k = getattr(args, "top_k", 5)
    output = getattr(args, "output", None)
    refresh_maps = getattr(args, "refresh_maps", False)

    if interactive and not extra:
        extra = interactive_extra_requirements()

    info(f"任务描述：{task_desc}")
    if template:
        info(f"EP 模板：{template}")
    if extra:
        info(f"自定义要求：{extra[:60]}{'...' if len(extra) > 60 else ''}")
    if refresh_maps:
        info("--refresh-maps：合成前自动刷新 codemap + funcmap 快照")

    print(f"\n{_CYAN}⏳ 正在调用 qwen3-32b 生成起手提示词...{_RESET}\n")
    result = synthesize(
        task_description=task_desc,
        template_name=template,
        extra_requirements=extra,
        top_k=top_k,
        refresh_maps=refresh_maps,
    )

    if output:
        Path(output).write_text(result, encoding="utf-8")
        ok(f"已写入：{output}")
    else:
        print(result)

    return 0


def cmd_precheck(args: argparse.Namespace) -> int:
    """precheck 子命令：代码修改前检查门控"""
    try:
        from mms.workflow.precheck import run_precheck
    except ImportError:
        from mms.workflow.precheck import run_precheck  # type: ignore[no-redef]

    ep_id = args.ep
    strict = getattr(args, "strict", False)
    return run_precheck(ep_id=ep_id, strict=strict)


def cmd_postcheck(args: argparse.Namespace) -> int:
    """postcheck 子命令：代码修改后测试与后校验"""
    try:
        from mms.workflow.postcheck import run_postcheck
    except ImportError:
        from mms.workflow.postcheck import run_postcheck  # type: ignore[no-redef]

    ep_id = args.ep
    skip_tests = getattr(args, "skip_tests", False)
    extra_test_paths = getattr(args, "test_paths", None) or []
    return run_postcheck(
        ep_id=ep_id,
        skip_tests=skip_tests,
        extra_test_paths=extra_test_paths,
    )


def cmd_actions(args: argparse.Namespace) -> int:
    """actions 子命令：列出或查看 MMS 系统的 ActionDef / FunctionDef 定义"""
    import yaml  # type: ignore[import]

    _HERE_CLI = Path(__file__).parent
    ontology_root = _HERE_CLI.parent.parent / "docs" / "memory" / "ontology"
    actions_dir = ontology_root / "actions"
    functions_dir = ontology_root / "functions"

    action_id = getattr(args, "action_id", None)
    show_functions = getattr(args, "functions", False)

    target_dir = functions_dir if show_functions else actions_dir
    kind_label = "FunctionDef" if show_functions else "ActionDef"

    if not target_dir.exists():
        err(f"目录不存在：{target_dir}")
        return 1

    yaml_files = sorted(target_dir.glob("*.yaml"))
    if not yaml_files:
        warn(f"暂无 {kind_label} 定义文件（{target_dir}）")
        return 0

    # 查看单个定义
    if action_id:
        matched = [f for f in yaml_files if action_id in f.stem]
        if not matched:
            err(f"未找到 ID 匹配 '{action_id}' 的 {kind_label}")
            return 1
        f = matched[0]
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            err(f"YAML 解析失败：{exc}")
            return 1
        print(f"\n{_BOLD}{'=' * 60}{_RESET}")
        print(f"{_BOLD}  {kind_label}: {data.get('id', f.stem)}{_RESET}")
        print(f"  标签：{data.get('label', '')}  |  版本：{data.get('version', '')}")
        print(f"{'=' * 60}{_RESET}")
        print(f"\n{_CYAN}描述：{_RESET}")
        print(data.get("description", "（无描述）"))
        if "cli_usage" in data:
            print(f"\n{_CYAN}CLI 用法：{_RESET}")
            print(data["cli_usage"])
        if "calls_functions" in data:
            print(f"\n{_CYAN}调用的 Function：{_RESET} " + ", ".join(data["calls_functions"]))
        if "related_actions" in data:
            print(f"{_CYAN}相关 Action：{_RESET} " + ", ".join(data["related_actions"]))
        return 0

    # 列出所有
    print(f"\n{_BOLD}MMS {kind_label} 列表（{len(yaml_files)} 个）{_RESET}")
    print(f"{'─' * 60}")
    for f in yaml_files:
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            did = data.get("id", f.stem)
            label = data.get("label", "")
            ver = data.get("version", "")
            desc_first_line = (data.get("description", "") or "").split("\n")[0].strip()
            print(f"  {_BOLD}{did}{_RESET}  [{label}]  v{ver}")
            if desc_first_line:
                print(f"    {desc_first_line[:72]}")
        except Exception:
            print(f"  {f.stem}  （YAML 解析失败）")
    print(f"{'─' * 60}")
    hint = "--functions" if not show_functions else "--actions"
    print(f"  提示：mms actions <id> 查看详情 | mms actions {hint} 切换类型")
    return 0


def cmd_graph(args: argparse.Namespace) -> int:
    """graph 子命令：记忆知识图谱查询（探索/反查/影响分析）"""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from mms.memory.graph_resolver import MemoryGraph
    except ImportError:
        from mms.memory.graph_resolver import MemoryGraph  # type: ignore[no-redef]

    graph = MemoryGraph()
    stats = graph.stats()

    subcommand = getattr(args, "subcommand", None)

    if subcommand == "stats" or subcommand is None:
        print(f"\n{_BOLD}记忆知识图谱统计{_RESET}")
        print(f"  总节点数：{stats.get('total_nodes', 0)}")
        print(f"  总图边数：{stats.get('total_edges', 0)}")
        print(f"  有文件引用的节点：{stats.get('total_file_refs', 0)}")
        print(f"  Hot 层节点：{stats.get('tier_hot', 0)}")
        print(f"  Warm 层节点：{stats.get('tier_warm', 0)}")
        print(f"  Cold 层节点：{stats.get('tier_cold', 0)}")
        return 0

    if subcommand == "explore":
        mem_id = args.id
        depth = getattr(args, "depth", 2)
        nodes = graph.explore(mem_id, depth=depth)
        if not nodes:
            warn(f"未找到节点：{mem_id}")
            return 1
        print(f"\n{_BOLD}从 {mem_id} 出发的图遍历（depth={depth}，共 {len(nodes)} 个节点）:{_RESET}")
        for n in nodes:
            related = ", ".join(r.get("id", "") for r in n.related_to[:3])
            print(f"  [{n.tier:4}] {n.id:15} | {n.title[:40]}")
            if related:
                print(f"    → related_to: {related}")
        return 0

    if subcommand == "file":
        file_path = args.path
        nodes = graph.find_by_file(file_path)
        if not nodes:
            warn(f"没有记忆节点引用文件：{file_path}")
            return 0
        print(f"\n{_BOLD}引用 '{file_path}' 的记忆节点（共 {len(nodes)} 个）:{_RESET}")
        for n in nodes:
            print(f"  [{n.tier:4}] {n.id:15} | {n.title[:50]}")
        return 0

    if subcommand == "impacts":
        mem_id = args.id
        nodes = graph.find_impacts(mem_id)
        print(f"\n{_BOLD}{mem_id} 变更时需同步检查的节点（共 {len(nodes)} 个）:{_RESET}")
        for n in nodes:
            print(f"  {n.id:15} | {n.title[:50]}")
        return 0

    warn(f"未知子命令：{subcommand}，可用：stats / explore / file / impacts")
    return 1


def cmd_unit(args: argparse.Namespace) -> int:
    """unit 子命令：DAG 任务编排（EP-117）"""
    subcommand = getattr(args, "subcommand", None)

    try:
        from mms.execution.unit_cmd import (  # type: ignore[import]
            cmd_unit_status, cmd_unit_next, cmd_unit_done,
            cmd_unit_context, cmd_unit_reset, cmd_unit_skip,
        )
        from mms.execution.unit_generate import run_unit_generate  # type: ignore[import]
    except ImportError:
        from mms.execution.unit_cmd import (  # type: ignore[import]
            cmd_unit_status, cmd_unit_next, cmd_unit_done,
            cmd_unit_context, cmd_unit_reset, cmd_unit_skip,
        )
        from mms.execution.unit_generate import run_unit_generate  # type: ignore[import]

    if subcommand == "generate":
        return run_unit_generate(
            ep_id=args.ep,
            force=args.force,
            no_llm=args.no_llm,
        )
    if subcommand == "status":
        return cmd_unit_status(ep_id=args.ep)
    if subcommand == "next":
        return cmd_unit_next(ep_id=args.ep, model=args.model)
    if subcommand == "done":
        return cmd_unit_done(
            ep_id=args.ep,
            unit_id=args.unit,
            skip_tests=args.skip_tests,
            skip_commit=args.skip_commit,
        )
    if subcommand == "context":
        return cmd_unit_context(ep_id=args.ep, unit_id=args.unit, model=args.model)
    if subcommand == "reset":
        return cmd_unit_reset(ep_id=args.ep, unit_id=args.unit)
    if subcommand == "skip":
        return cmd_unit_skip(ep_id=args.ep, unit_id=args.unit)

    # ── EP-119 新增：LLM 自动执行命令 ─────────────────────────────────────────
    if subcommand in ("run", "run-next", "run-all"):
        try:
            from mms.execution.unit_runner import UnitRunner, BatchRunner  # type: ignore[import]
        except ImportError:
            from mms.execution.unit_runner import UnitRunner, BatchRunner  # type: ignore[import]

        model = getattr(args, "model", "capable")
        dry_run = getattr(args, "dry_run", False)
        confirm = getattr(args, "confirm", False)
        max_failures = getattr(args, "max_failures", 1)

        if subcommand == "run":
            save_output = getattr(args, "save_output", False)
            runner = UnitRunner()
            result = runner.run(
                ep_id=args.ep,
                unit_id=args.unit,
                model=model,
                dry_run=dry_run,
                confirm=confirm,
                save_output=save_output,
            )
            return 0 if result.success else 1

        if subcommand == "run-next":
            batch_runner = BatchRunner(max_failures=max_failures)
            results = batch_runner.run_next(
                ep_id=args.ep,
                model=model,
                dry_run=dry_run,
                confirm=confirm,
            )
            failed = [r for r in results if not r.success]
            return 1 if failed else 0

        if subcommand == "run-all":
            batch_runner = BatchRunner(max_failures=max_failures)
            results = batch_runner.run_all(
                ep_id=args.ep,
                model=model,
                dry_run=dry_run,
                confirm=confirm,
                max_failures=max_failures,
            )
            failed = [r for r in results if not r.success]
            return 1 if failed else 0

    # ── EP-120 新增：双模型对比命令 ───────────────────────────────────────────
    if subcommand in ("compare", "sonnet-save"):
        try:
            from mms.execution.unit_compare import compare as _compare, apply as _apply, save_sonnet_output  # type: ignore[import]
        except ImportError:
            from mms.execution.unit_compare import compare as _compare, apply as _apply, save_sonnet_output  # type: ignore[import]

        if subcommand == "sonnet-save":
            # 从 stdin 或 --file 读取 Sonnet 输出
            file_arg = getattr(args, "file", None)
            if file_arg:
                try:
                    content = Path(file_arg).read_text(encoding="utf-8")
                except Exception as e:
                    warn(f"读取文件失败：{e}")
                    return 1
            else:
                import sys as _sys
                if _sys.stdin.isatty():
                    print("请粘贴 Sonnet 输出（===BEGIN-CHANGES=== 格式），以 Ctrl+D 结束：")
                content = _sys.stdin.read()

            out = save_sonnet_output(args.ep, args.unit, content)
            ok(f"sonnet.txt 已保存：{out}")
            return 0

        if subcommand == "compare":
            apply_source = getattr(args, "apply_source", None)
            if apply_source:
                return _apply(args.ep, args.unit, source=apply_source)
            return _compare(args.ep, args.unit)

    warn("请指定子命令：generate / status / next / done / context / reset / skip / run / run-next / run-all / compare / sonnet-save")
    return 1


def _load_inject_manifest() -> dict:
    """加载 INJECT_MANIFEST.json 配置"""
    manifest_path = _MEMORY_ROOT / "_system" / "INJECT_MANIFEST.json"
    if manifest_path.exists():
        import json as _json
        try:
            return _json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _cmd_inject_dispatch(args: argparse.Namespace) -> int:
    """inject 命令分发，支持 --mode 分层注入"""
    try:
        from mms.memory.injector import MemoryInjector
    except ImportError:
        from mms.memory.injector import MemoryInjector  # type: ignore[no-redef]

    task_desc = " ".join(args.task)

    # 从 INJECT_MANIFEST.json 读取模式配置
    manifest = _load_inject_manifest()
    mode_name = getattr(args, "mode", None)
    top_k = args.top_k
    compress = not args.no_compress

    if mode_name and manifest:
        modes = manifest.get("modes", {})
        mode_cfg = modes.get(mode_name, {})
        if mode_cfg:
            top_k = mode_cfg.get("top_k", top_k)
            compress = mode_cfg.get("compress", compress)
            info(f"注入模式: {mode_name} | top_k={top_k} | compress={compress}")
    elif not mode_name and manifest:
        # 自动检测模式
        rules = manifest.get("task_auto_detect", {}).get("rules", [])
        task_lower = task_desc.lower()
        detected_mode = manifest.get("task_auto_detect", {}).get("default_mode", "default")
        for rule in rules:
            if any(kw in task_lower for kw in rule.get("keywords", [])):
                detected_mode = rule.get("mode", "default")
                break
        modes = manifest.get("modes", {})
        mode_cfg = modes.get(detected_mode, {})
        if mode_cfg:
            top_k = mode_cfg.get("top_k", top_k)
            compress = mode_cfg.get("compress", compress)
            info(f"自动检测模式: {detected_mode} | top_k={top_k}")

    injector = MemoryInjector()
    result = injector.inject(
        task_description=task_desc,
        top_k=top_k,
        compress=compress,
    )
    output = result.to_prompt_prefix()
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        ok(f"已写入：{args.output}")
    else:
        print(output)
    return 0


def cmd_ep(args: argparse.Namespace) -> int:
    """ep 子命令：EP 工作流（run/start/status）"""
    sys.path.insert(0, str(Path(__file__).parent))
    subcommand = getattr(args, "subcommand", None)

    # EP-131：ep run — 一键自动执行 Pipeline
    if subcommand == "run":
        try:
            from mms.workflow.ep_runner import EpRunPipeline  # type: ignore[import]
        except ImportError:
            from mms.workflow.ep_runner import EpRunPipeline  # type: ignore[no-redef]

        pipeline = EpRunPipeline()
        result = pipeline.run(
            ep_id=args.ep_id,
            from_unit=getattr(args, "from_unit", None),
            only_units=getattr(args, "only", None),
            dry_run=getattr(args, "dry_run", False),
            skip_precheck=getattr(args, "skip_precheck", False),
            skip_postcheck=getattr(args, "skip_postcheck", False),
            auto_confirm=getattr(args, "auto_confirm", False),
            model=getattr(args, "model", "capable"),
        )
        return 0 if result.success else 1

    # 原有：ep start / ep status（向导模式）
    try:
        from mms.workflow.ep_wizard import run_ep_wizard, show_ep_status
    except ImportError:
        from mms.workflow.ep_wizard import run_ep_wizard, show_ep_status  # type: ignore[no-redef]

    if subcommand == "start":
        return run_ep_wizard(
            ep_id=args.ep_id,
            from_step=getattr(args, "from_step", 1),
        )
    if subcommand == "status":
        return show_ep_status(ep_id=args.ep_id)

    err("请指定子命令：run / start / status")
    return 1


def cmd_dream(args: argparse.Namespace) -> int:
    """dream 子命令：autoDream 知识萃取"""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from mms.memory.dream import run_dream
    except ImportError:
        from mms.memory.dream import run_dream  # type: ignore[no-redef]

    return run_dream(
        ep_id=getattr(args, "ep", None),
        since=getattr(args, "since", "7d"),
        promote=getattr(args, "promote", False),
        list_drafts=getattr(args, "list_drafts", False),
        dry_run=getattr(args, "dry_run", False),
    )


def cmd_template(args: argparse.Namespace) -> int:
    """template 子命令：代码模板库"""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from mms.memory.template_lib import cmd_template_list, cmd_template_info, cmd_template_use
    except ImportError:
        from mms.memory.template_lib import cmd_template_list, cmd_template_info, cmd_template_use  # type: ignore[no-redef]

    subcommand = getattr(args, "subcommand", None)

    if subcommand == "list" or subcommand is None:
        return cmd_template_list()

    if subcommand == "info":
        return cmd_template_info(args.name)

    if subcommand == "use":
        # 解析 --var KEY=VALUE 列表
        variables: dict = {}
        for kv in getattr(args, "var", []):
            if "=" in kv:
                k, _, v = kv.partition("=")
                variables[k.strip()] = v.strip()
            else:
                warn(f"--var 格式错误（应为 KEY=VALUE）：{kv}")
        return cmd_template_use(
            name=args.name,
            variables=variables,
            output=getattr(args, "output", None),
            dry_run=getattr(args, "dry_run", False),
        )

    warn("请指定子命令：list / info / use")
    return 1


def cmd_trace(args: argparse.Namespace) -> int:
    """trace 子命令：MMS 诊断追踪（类 Oracle 10046 Trace）"""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from mms.trace.tracer import EPTracer  # type: ignore[import]
        from mms.trace.reporter import (  # type: ignore[import]
            generate_report, generate_summary_text, list_traced_eps
        )
        from mms.trace.tracer import TraceConfig  # type: ignore[import]
    except ImportError:
        try:
            from mms.trace.tracer import EPTracer  # type: ignore[import,no-redef]
            from mms.trace.reporter import (  # type: ignore[import,no-redef]
                generate_report, generate_summary_text, list_traced_eps
            )
            from mms.trace.tracer import TraceConfig  # type: ignore[import,no-redef]
        except ImportError as e:
            err(f"无法导入 trace 模块：{e}")
            return 1

    subcommand = getattr(args, "subcommand", None)

    # trace enable
    if subcommand == "enable":
        ep_id = args.ep_id.upper()
        level = getattr(args, "level", 4)
        tracer = EPTracer.enable(ep_id, level=level)
        # 注册到全局 collector
        try:
            from mms.trace.collector import register_tracer  # type: ignore[import]
            register_tracer(ep_id, tracer)
        except ImportError:
            pass
        print(f"  ✅ [{ep_id}] 诊断追踪已开启")
        print(f"     Level  : {level}（{['—', 'Basic', '—', '—', 'LLM', '—', '—', '—', 'FileOps', '—', '—', '—', 'Full'][level] if level <= 12 else '?'}）")
        print(f"     TraceID: {tracer.trace_id}")
        print(f"     存储   : docs/memory/private/trace/{ep_id}/trace.jsonl")
        return 0

    # trace disable
    if subcommand == "disable":
        ep_id = args.ep_id.upper()
        EPTracer.disable(ep_id)
        try:
            from mms.trace.collector import invalidate  # type: ignore[import]
            invalidate(ep_id)
        except ImportError:
            pass
        print(f"  ✅ [{ep_id}] 诊断追踪已关闭（数据已保留）")
        print(f"     运行 mms trace show {ep_id} 查看报告")
        return 0

    # trace show
    if subcommand == "show":
        ep_id = args.ep_id.upper()
        fmt = getattr(args, "format", "text")
        use_color = not getattr(args, "no_color", False)
        save = not getattr(args, "no_save", False)
        filter_step = getattr(args, "step", None)
        filter_unit = getattr(args, "unit", None)
        try:
            report = generate_report(
                ep_id, fmt=fmt, filter_step=filter_step,
                filter_unit=filter_unit, use_color=use_color, save=save,
            )
            print(report)
            if save and fmt == "text":
                print(f"\n  报告已保存至：docs/memory/private/trace/{ep_id}/report/report.txt")
            return 0
        except Exception as e:
            err(f"生成报告失败：{e}")
            return 1

    # trace summary
    if subcommand == "summary":
        ep_id = args.ep_id.upper()
        try:
            print(generate_summary_text(ep_id))
            return 0
        except Exception as e:
            err(f"生成摘要失败：{e}")
            return 1

    # trace list
    if subcommand == "list" or subcommand is None:
        eps = list_traced_eps()
        if not eps:
            print("  （暂无追踪记录）")
            return 0
        print(f"  {'EP':<12} {'Level':<8} {'已开启':<8} {'事件数':>8}  开始时间")
        print("  " + "─" * 60)
        for ep in eps:
            enabled_str = "✅ 是" if ep["enabled"] else "  否"
            print(f"  {ep['ep_id']:<12} {ep['level']:<8} {enabled_str:<8} {ep['event_count']:>8}  {ep['started_at']}")
        return 0

    # trace clean
    if subcommand == "clean":
        ep_id = args.ep_id.upper()
        force = getattr(args, "yes", False)
        if not force:
            confirm = input(f"  确认删除 {ep_id} 的所有追踪数据？(yes/N): ").strip().lower()
            if confirm != "yes":
                print("  已取消。")
                return 0
        import shutil
        trace_dir = Path(__file__).parent.parent.parent / "docs" / "memory" / "private" / "trace" / ep_id
        if trace_dir.exists():
            shutil.rmtree(trace_dir)
            print(f"  ✅ 已清除 {ep_id} 的追踪数据")
        else:
            print(f"  （{ep_id} 无追踪数据，跳过）")
        try:
            from mms.trace.collector import invalidate  # type: ignore[import]
            invalidate(ep_id)
        except ImportError:
            pass
        return 0

    # trace config
    if subcommand == "config":
        ep_id = args.ep_id.upper()
        cfg_obj = TraceConfig.load_or_default(ep_id)
        changed = False
        new_level = getattr(args, "level", None)
        if new_level is not None:
            cfg_obj.level = new_level
            changed = True
        if changed:
            cfg_obj.save()
            print(f"  ✅ [{ep_id}] 追踪配置已更新：level={cfg_obj.level}")
        else:
            from mms.trace.event import LEVEL_NAMES  # type: ignore[import]
            print(f"  [{ep_id}] 当前配置：")
            print(f"    enabled   : {cfg_obj.enabled}")
            print(f"    level     : {cfg_obj.level} ({LEVEL_NAMES.get(cfg_obj.level, '?')})")
            print(f"    trace_id  : {cfg_obj.trace_id}")
            print(f"    events    : {cfg_obj.event_count} / {cfg_obj.max_events}")
        return 0

    err("请指定子命令：enable / disable / show / summary / list / clean / config")
    return 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    """benchmark 子命令：三层模块化评测（离线/快速/全量）"""
    _repo_root = Path(__file__).parent
    bench_dir  = _repo_root / "benchmark"
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))

    try:
        from benchmark.v2.runner import main as bench_main
    except ImportError as e:
        err(f"无法加载 benchmark v2 模块：{e}")
        err("请确认 benchmark/v2/ 目录存在，并已安装 pyyaml（pip install pyyaml）")
        return 1

    bench_argv = []
    level = getattr(args, "level", "offline")
    bench_argv += ["--level", level]

    layer = getattr(args, "layer", None)
    if layer:
        bench_argv += ["--layer", str(layer)]

    domains = getattr(args, "domain", None)
    if domains:
        bench_argv += ["--domain"] + (domains if isinstance(domains, list) else [domains])

    if getattr(args, "llm", False):
        bench_argv.append("--llm")
    if getattr(args, "dry_run", False):
        bench_argv.append("--dry-run")
    if getattr(args, "verbose", False):
        bench_argv.append("--verbose")

    output = getattr(args, "output", "console")
    bench_argv += ["--output", output]

    output_path = getattr(args, "output_path", None)
    if output_path:
        bench_argv += ["--output-path", output_path]

    max_tasks = getattr(args, "max_tasks", None)
    if max_tasks:
        bench_argv += ["--max-tasks", str(max_tasks)]

    return bench_main(bench_argv)


def cmd_diag(args: argparse.Namespace) -> int:
    """diag 子命令：MDR 诊断工具（类比 Oracle ADRCI）"""
    subcommand = getattr(args, "subcommand", None)

    # ── 路径解析 ──────────────────────────────────────────────────────────────
    _cli_root = Path(__file__).resolve().parent
    _mdr_root = _cli_root / "docs" / "memory" / "private" / "mdr"
    _incident_dir = _mdr_root / "incident"
    _trace_dir = _cli_root / "docs" / "memory" / "private" / "trace"

    # ── diag status ───────────────────────────────────────────────────────────
    if subcommand == "status" or subcommand is None:
        try:
            from mms.observability.logger import tail_log, get_log_path  # type: ignore[import]
        except ImportError as e:
            err(f"无法加载 observability.logger: {e}")
            return 1

        log_path = get_log_path()
        if not log_path.exists():
            print("  ✅ alert_mulan.log 尚不存在（系统未记录过告警）")
            return 0

        lines = tail_log(50)
        fatal_lines = [l for l in lines if "[CRITICAL]" in l or "[FATAL]" in l or "FATAL" in l]
        warn_lines  = [l for l in lines if "[WARNING]" in l or "[WARN]" in l or "WARN" in l]

        print(f"\n{'─'*66}")
        print(f"  Mulan Diag Status  |  {log_path}")
        print(f"{'─'*66}")
        print(f"  最近 {len(lines)} 行  |  FATAL: {len(fatal_lines)}  WARN: {len(warn_lines)}")
        print(f"{'─'*66}")

        # 最近 10 条（倒序显示最新的）
        recent = lines[-10:]
        for line in recent:
            if "FATAL" in line or "CRITICAL" in line:
                print(f"  \033[91m{line}\033[0m")
            elif "WARN" in line or "WARNING" in line:
                print(f"  \033[93m{line}\033[0m")
            else:
                print(f"  {line}")
        print()

        if fatal_lines:
            print(f"  \033[91m⚠️  存在 {len(fatal_lines)} 条 FATAL 告警，请检查系统状态！\033[0m")
            return 1
        print("  ✅ 未发现 FATAL 告警，系统运行正常。")
        return 0

    # ── diag list ─────────────────────────────────────────────────────────────
    if subcommand == "list":
        if not _incident_dir.exists():
            print("  暂无 Incident 记录（docs/memory/private/mdr/incident/ 不存在）")
            return 0
        incidents = sorted(
            [d for d in _incident_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if not incidents:
            print("  暂无 Incident 记录。")
            return 0
        print(f"\n{'─'*66}")
        print(f"  {'Incident ID':<50} {'状态':>8}")
        print(f"{'─'*66}")
        for inc in incidents:
            manifest_path = inc / "incident_manifest.json"
            exc_type = "?"
            if manifest_path.exists():
                try:
                    import json as _json
                    m = _json.loads(manifest_path.read_text(encoding="utf-8"))
                    exc_type = m.get("exc_type", "?")
                except Exception:
                    pass
            print(f"  {inc.name:<50} {exc_type:>8}")
        print()
        return 0

    # ── diag pack ─────────────────────────────────────────────────────────────
    if subcommand == "pack":
        import shutil
        import zipfile
        import json as _json

        incident_id = getattr(args, "incident_id", "")
        if not incident_id:
            err("请提供 incident_id，例如：mulan diag pack inc_20260427_2347_JSONDecodeError")
            return 1

        inc_dir = _incident_dir / incident_id
        if not inc_dir.exists():
            err(f"Incident 目录不存在：{inc_dir}")
            return 1

        output_dir = Path(getattr(args, "output_dir", None) or _cli_root)
        zip_name = f"mulan_incident_{incident_id}.zip"
        zip_path = output_dir / zip_name

        # 读取 manifest 以获取 related_ep_id
        related_ep_id = None
        manifest_path = inc_dir / "incident_manifest.json"
        if manifest_path.exists():
            try:
                m = _json.loads(manifest_path.read_text(encoding="utf-8"))
                related_ep_id = m.get("related_ep_id")
            except Exception:
                pass

        # 收集文件
        files_to_pack: list[tuple[Path, str]] = []
        for f in inc_dir.iterdir():
            if f.is_file():
                files_to_pack.append((f, f"incident/{f.name}"))

        # 附加 EP trace 文件
        if related_ep_id:
            ep_trace = _trace_dir / related_ep_id.upper() / "mms.trace.jsonl"
            if ep_trace.exists():
                files_to_pack.append((ep_trace, f"trace/{related_ep_id}/mms.trace.jsonl"))

        # 附加 ast_index.json（代码地图快照）
        ast_index = _cli_root / "docs" / "memory" / "_system" / "ast_index.json"
        if ast_index.exists():
            files_to_pack.append((ast_index, "system/ast_index.json"))

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src_path, arc_name in files_to_pack:
                zf.write(src_path, arc_name)

        total_kb = zip_path.stat().st_size // 1024
        print(f"\n  ✅ 诊断包已生成：{zip_path}  ({total_kb} KB)")
        print(f"  包含 {len(files_to_pack)} 个文件：")
        for _, arc in files_to_pack:
            print(f"    - {arc}")
        print(f"\n  请将此 ZIP 附到 GitHub Issue，帮助开发者复现问题。")
        return 0

    err("请指定子命令：status / list / pack <incident_id>")
    return 1


_COMMAND_HANDLERS = {
    "help":          cmd_help,
    "status":        cmd_status,
    "distill":       cmd_distill,
    "gc":            cmd_gc,
    "validate":      cmd_validate,
    "search":        cmd_search,
    "list":          cmd_list,
    "hook":          cmd_hook,
    "incomplete":    cmd_incomplete,
    "reset-circuit": cmd_reset_circuit,
    "inject":        lambda args: _cmd_inject_dispatch(args),
    "synthesize":    cmd_synthesize,
    "precheck":      cmd_precheck,
    "postcheck":     cmd_postcheck,
    "private":       cmd_private,
    "verify":        cmd_verify,
    "codemap":       cmd_codemap,
    "funcmap":       cmd_funcmap,
    "usage":         cmd_usage,
    "actions":       cmd_actions,
    "graph":         cmd_graph,
    "unit":          cmd_unit,
    "ep":            cmd_ep,
    "dream":         cmd_dream,
    "template":      cmd_template,
    "trace":         cmd_trace,
    "bootstrap":     cmd_bootstrap,    # EP-130: 离线冷启动
    "ast-diff":      cmd_ast_diff,     # EP-130: AST 契约变更检测
    "seed":          cmd_seed,         # EP-131: 种子包管理 + Rule Absorber
    "benchmark":     cmd_benchmark,    # v2 三层 Benchmark
    "diag":          cmd_diag,         # MDR 诊断工具（类 Oracle ADRCI）
}


def main() -> int:
    # 安装全局崩溃处理器（MDR Incident Dump），KeyboardInterrupt 不受影响
    try:
        from mms.observability.incident import install_crash_handler  # type: ignore[import]
        install_crash_handler()
    except Exception:
        pass  # 诊断模块不可用时静默降级，不影响正常功能

    parser = build_parser()
    args = parser.parse_args()
    handler = _COMMAND_HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
