#!/usr/bin/env python3
"""
probe_ast_accuracy.py — AST 解析器精度探针

用途：量化当前正则解析器（Java/Go）在企业级代码场景下的失败率，
     以数据驱动方式决定是否引入 tree-sitter。

测试策略：
  - 定义 10 个刻意覆盖"边界场景"的 Java/Go 代码片段
  - 每个 case 附带 ground truth（期望提取的方法名列表）
  - 运行当前正则解析器，对比实际提取结果
  - 统计：方法漏提取率 / 方法误提取率 / 指纹稳定性

判断标准（阈值）：
  漏提率 > 20%  → tree-sitter 有必要
  漏提率 ≤ 10%  → 正则已足够，过度设计
  10-20% 之间   → 建议先修正正则，再评估

运行方式：
  python3 scripts/probe_ast_accuracy.py
  python3 scripts/probe_ast_accuracy.py --verbose    # 打印每个 case 的详情
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "src"))

from mms.analysis.ast_skeleton import _parse_java, _parse_go

# ── ANSI 颜色 ─────────────────────────────────────────────────────────────────
_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


@dataclass
class ParseCase:
    id: str
    lang: str                       # "java" | "go"
    description: str
    source: str                     # 代码片段
    expected_methods: Set[str]      # ground truth：期望提取到的方法名
    expected_classes: Set[str]      # 期望提取到的类/struct 名
    complexity: str = "normal"      # "normal" | "hard" | "edge"


@dataclass
class CaseResult:
    case_id: str
    got_methods: Set[str]
    got_classes: Set[str]
    expected_methods: Set[str]
    expected_classes: Set[str]

    @property
    def missed_methods(self) -> Set[str]:
        return self.expected_methods - self.got_methods

    @property
    def extra_methods(self) -> Set[str]:
        return self.got_methods - self.expected_methods

    @property
    def missed_classes(self) -> Set[str]:
        return self.expected_classes - self.got_classes

    @property
    def method_recall(self) -> float:
        if not self.expected_methods:
            return 1.0
        return len(self.expected_methods & self.got_methods) / len(self.expected_methods)

    @property
    def class_recall(self) -> float:
        if not self.expected_classes:
            return 1.0
        return len(self.expected_classes & self.got_classes) / len(self.expected_classes)

    @property
    def passed(self) -> bool:
        return not self.missed_methods and not self.missed_classes


# ─────────────────────────────────────────────────────────────────────────────
# Java 测试用例
# ─────────────────────────────────────────────────────────────────────────────

JAVA_CASES: List[ParseCase] = [

    ParseCase(
        id="java_01_basic",
        lang="java",
        complexity="normal",
        description="基础：public class，普通方法，无泛型",
        source="""
package com.example.service;

public class UserService {
    public UserDTO findById(Long id) {
        return repository.findById(id);
    }
    public void deleteUser(Long id) {
        repository.deleteById(id);
    }
    private void validate(UserDTO dto) {}
}
""",
        expected_methods={"findById", "deleteUser", "validate"},
        expected_classes={"UserService"},
    ),

    ParseCase(
        id="java_02_generics",
        lang="java",
        complexity="hard",
        description="泛型方法：<T extends Comparable<T>> 复杂上界",
        source="""
public class SortUtils {
    public static <T extends Comparable<T>> List<T> sort(List<T> items) {
        Collections.sort(items);
        return items;
    }
    public <K, V extends List<K>> Map<K, V> groupBy(List<K> keys, V values) {
        return new HashMap<>();
    }
    public <T> Optional<T> findFirst(Stream<T> stream) {
        return stream.findFirst();
    }
}
""",
        expected_methods={"sort", "groupBy", "findFirst"},
        expected_classes={"SortUtils"},
    ),

    ParseCase(
        id="java_03_annotations",
        lang="java",
        complexity="hard",
        description="带注解的方法（含括号参数），注解不应误触发方法提取",
        source="""
@RestController
@RequestMapping("/api/v1")
public class OntologyController {
    @GetMapping(value = "/objects", produces = MediaType.APPLICATION_JSON_VALUE)
    @PreAuthorize("hasRole('VIEWER')")
    public ResponseEntity<ApiResponse<List<ObjectTypeDTO>>> listObjects(
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return ResponseEntity.ok(service.listAll(page, size));
    }

    @PostMapping("/objects")
    @Transactional
    public ResponseEntity<ApiResponse<ObjectTypeDTO>> createObject(
            @Valid @RequestBody CreateObjectRequest request) {
        return ResponseEntity.status(HttpStatus.CREATED).body(service.create(request));
    }
}
""",
        expected_methods={"listObjects", "createObject"},
        expected_classes={"OntologyController"},
    ),

    ParseCase(
        id="java_04_nested_class",
        lang="java",
        complexity="hard",
        description="嵌套内部类：外层和内层各自的方法不应混淆",
        source="""
public class EventProcessor {
    public void process(Event event) { dispatch(event); }

    private static class DefaultHandler implements EventHandler {
        @Override
        public void handle(Event event) { log(event); }
        private void log(Event e) {}
    }

    public interface EventHandler {
        void handle(Event event);
    }
}
""",
        expected_methods={"process", "handle", "log"},
        expected_classes={"EventProcessor", "DefaultHandler", "EventHandler"},
    ),

    ParseCase(
        id="java_05_multiline_sig",
        lang="java",
        complexity="hard",
        description="方法签名跨多行（gofmt/spotless 格式化后的常见形态）",
        source="""
public class BatchService {
    public CompletableFuture<BatchResult> processBatch(
            List<String> ids,
            BatchConfig config,
            ExecutorService executor) {
        return CompletableFuture.supplyAsync(() -> doProcess(ids, config), executor);
    }

    protected void validateConfig(
            BatchConfig config) {
        Objects.requireNonNull(config);
    }
}
""",
        expected_methods={"processBatch", "validateConfig"},
        expected_classes={"BatchService"},
    ),

    ParseCase(
        id="java_06_enum_methods",
        lang="java",
        complexity="normal",
        description="enum 类型含方法",
        source="""
public enum AIUType {
    SCHEMA_ADD_FIELD,
    LOGIC_ADD_CONDITION,
    ROUTE_ADD_ENDPOINT;

    public boolean isSchemaChange() {
        return this.name().startsWith("SCHEMA");
    }
    public int getCostBase() { return 1500; }
}
""",
        expected_methods={"isSchemaChange", "getCostBase"},
        expected_classes={"AIUType"},
    ),

    # ── 扩展 case（Phase 0 修复后覆盖的现代 Java 语法）──────────────────────────

    ParseCase(
        id="java_07_record",
        lang="java",
        complexity="hard",
        description="Java 16+ record 类型（含方法）",
        source="""
public record UserRecord(String name, int age) {
    public String display() { return name + ":" + age; }
    public boolean isAdult() { return age >= 18; }
}
""",
        expected_methods={"display", "isAdult"},
        expected_classes={"UserRecord"},
    ),

    ParseCase(
        id="java_08_sealed",
        lang="java",
        complexity="hard",
        description="Java 17+ sealed interface + final class 实现",
        source="""
public sealed interface Shape permits Circle, Rectangle {
    double area();
    default String describe() { return "shape:" + area(); }
}
public final class Circle implements Shape {
    private final double radius;
    public Circle(double radius) { this.radius = radius; }
    public double area() { return Math.PI * radius * radius; }
}
""",
        expected_methods={"describe", "area"},
        expected_classes={"Shape", "Circle"},
    ),

    ParseCase(
        id="java_09_functional_interface",
        lang="java",
        complexity="hard",
        description="@FunctionalInterface 注解在 interface 前，含 default/static 方法",
        source="""
@FunctionalInterface
public interface Transformer<T, R> {
    R transform(T input);
    default Transformer<T, R> andLog(Logger logger) {
        return input -> {
            R result = transform(input);
            logger.log("transformed: {}", result);
            return result;
        };
    }
    static <T> Transformer<T, T> identity() { return t -> t; }
}
""",
        expected_methods={"andLog", "identity"},
        expected_classes={"Transformer"},
    ),

    ParseCase(
        id="java_10_varargs",
        lang="java",
        complexity="normal",
        description="varargs 方法（含 @SafeVarargs 注解）",
        source="""
public class Logger {
    public void log(String format, Object... args) {}
    public static <T> List<T> of(T... elements) { return Arrays.asList(elements); }
    @SafeVarargs
    public final <T> void safePrint(T... items) {}
}
""",
        expected_methods={"log", "of", "safePrint"},
        expected_classes={"Logger"},
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# Go 测试用例
# ─────────────────────────────────────────────────────────────────────────────

GO_CASES: List[ParseCase] = [

    ParseCase(
        id="go_01_basic",
        lang="go",
        complexity="normal",
        description="基础：struct + 方法 + 顶层函数",
        source="""
package service

type UserService struct {
    repo UserRepository
    cache Cache
}

func NewUserService(repo UserRepository) *UserService {
    return &UserService{repo: repo}
}

func (s *UserService) FindById(id string) (*User, error) {
    return s.repo.FindById(id)
}

func (s *UserService) Delete(id string) error {
    return s.repo.Delete(id)
}
""",
        expected_methods={"FindById", "Delete"},
        expected_classes={"UserService"},
    ),

    ParseCase(
        id="go_02_multiple_returns",
        lang="go",
        complexity="hard",
        description="多返回值（Go 特有），参数中含函数类型",
        source="""
package handler

type OntologyHandler struct{}

func (h *OntologyHandler) ListObjects(ctx context.Context, req *ListRequest) ([]*ObjectDTO, int64, error) {
    return nil, 0, nil
}

func (h *OntologyHandler) CreateObject(ctx context.Context, req *CreateRequest) (*ObjectDTO, error) {
    return nil, nil
}

func ProcessWithRetry(fn func() error, maxRetries int) error {
    return fn()
}
""",
        expected_methods={"ListObjects", "CreateObject"},
        expected_classes={"OntologyHandler"},
    ),

    ParseCase(
        id="go_03_generics",
        lang="go",
        complexity="edge",
        description="Go 1.18+ 泛型函数（[T any] 语法）",
        source="""
package collections

func Map[T, R any](slice []T, f func(T) R) []R {
    result := make([]R, len(slice))
    for i, v := range slice {
        result[i] = f(v)
    }
    return result
}

func Filter[T any](slice []T, pred func(T) bool) []T {
    var result []T
    for _, v := range slice {
        if pred(v) { result = append(result, v) }
    }
    return result
}

type Stack[T any] struct {
    items []T
}

func (s *Stack[T]) Push(item T) {
    s.items = append(s.items, item)
}
""",
        expected_methods={"Push"},
        expected_classes={"Stack"},
    ),

    ParseCase(
        id="go_04_interface",
        lang="go",
        complexity="normal",
        description="interface 定义（接口方法不是 func 声明形式）",
        source="""
package ports

type MemoryRepository interface {
    FindById(ctx context.Context, id string) (*Memory, error)
    Save(ctx context.Context, m *Memory) error
    Delete(ctx context.Context, id string) error
    ListByLayer(ctx context.Context, layer string) ([]*Memory, error)
}

type CachePort interface {
    Get(key string) ([]byte, bool)
    Set(key string, value []byte, ttl time.Duration)
}
""",
        expected_methods=set(),          # interface 方法不走 func 声明路径
        expected_classes={"MemoryRepository", "CachePort"},
    ),

    ParseCase(
        id="go_05_multiline_params",
        lang="go",
        complexity="hard",
        description="参数跨多行声明（gofmt 对长参数列表的格式化结果）",
        source="""
package usecase

type GraphUsecase struct{}

func (g *GraphUsecase) HybridSearch(
    ctx context.Context,
    query string,
    topK int,
    filters map[string]string,
) ([]*MemoryNode, error) {
    return nil, nil
}

func (g *GraphUsecase) TypedExplore(
    ctx context.Context,
    startID string,
    pathIntent string,
    depth int,
) ([]*MemoryNode, error) {
    return nil, nil
}
""",
        expected_methods={"HybridSearch", "TypedExplore"},
        expected_classes={"GraphUsecase"},
    ),

    # ── 扩展 case（Phase 0 修复后覆盖的现代 Go 语法）────────────────────────────

    ParseCase(
        id="go_06_multi_generic",
        lang="go",
        complexity="edge",
        description="多泛型参数 [K comparable, V any]（Go 1.18+）",
        source="""
package collections

type OrderedMap[K comparable, V any] struct {
    keys   []K
    values map[K]V
}

func (m *OrderedMap[K, V]) Set(k K, v V) {
    m.values[k] = v
}
func (m *OrderedMap[K, V]) Get(k K) (V, bool) {
    v, ok := m.values[k]
    return v, ok
}
func (m *OrderedMap[K, V]) Len() int { return len(m.keys) }
""",
        expected_methods={"Set", "Get", "Len"},
        expected_classes={"OrderedMap"},
    ),

    ParseCase(
        id="go_07_variadic",
        lang="go",
        complexity="normal",
        description="变参函数 ...any（常见 Logger/构造器模式）",
        source="""
package log

type Logger struct{ prefix string }

func (l *Logger) Info(format string, args ...any) {
    fmt.Printf(l.prefix+format, args...)
}
func (l *Logger) Error(err error, args ...any) {}
func NewLogger(prefix string, opts ...Option) *Logger { return &Logger{prefix} }
""",
        expected_methods={"Info", "Error"},
        expected_classes={"Logger"},
    ),

    ParseCase(
        id="go_08_blank_receiver",
        lang="go",
        complexity="normal",
        description="下划线接收者 (_ *Plugin) 与 init() 函数共存",
        source="""
package plugin

type Plugin struct{}

func init() {
    Register("default", &Plugin{})
}

func (p *Plugin) Name() string { return "default" }
func (p *Plugin) Start(ctx context.Context) error { return nil }
func (_ *Plugin) Version() string { return "1.0.0" }
""",
        expected_methods={"Name", "Start", "Version"},
        expected_classes={"Plugin"},
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 执行探针
# ─────────────────────────────────────────────────────────────────────────────

def run_case(case: ParseCase) -> CaseResult:
    if case.lang == "java":
        skeleton = _parse_java(case.source, f"probe/{case.id}.java")
    else:
        skeleton = _parse_go(case.source, f"probe/{case.id}.go")

    got_methods: Set[str] = set()
    for cls in skeleton.classes:
        for m in cls.methods:
            got_methods.add(m.name)
    for fn in skeleton.top_level_functions:
        got_methods.add(fn.name)

    got_classes: Set[str] = {cls.name for cls in skeleton.classes}

    return CaseResult(
        case_id=case.id,
        got_methods=got_methods,
        got_classes=got_classes,
        expected_methods=case.expected_methods,
        expected_classes=case.expected_classes,
    )


def print_case_detail(case: ParseCase, result: CaseResult) -> None:
    icon = f"{_GREEN}✓{_RESET}" if result.passed else f"{_RED}✗{_RESET}"
    label = f"{_BOLD}[{case.complexity.upper()}]{_RESET}"
    print(f"  {icon} {case.id} {label}  {_DIM}{case.description}{_RESET}")

    if result.missed_methods:
        print(f"      {_RED}漏提取方法: {sorted(result.missed_methods)}{_RESET}")
    if result.extra_methods:
        print(f"      {_YELLOW}多提取方法(误报): {sorted(result.extra_methods)}{_RESET}")
    if result.missed_classes:
        print(f"      {_RED}漏提取类/struct: {sorted(result.missed_classes)}{_RESET}")
    if result.passed:
        print(f"      {_DIM}方法: {sorted(result.got_methods)}  类: {sorted(result.got_classes)}{_RESET}")


def main():
    parser = argparse.ArgumentParser(description="AST 解析器精度探针")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每个 case 的详情")
    args = parser.parse_args()

    all_cases = JAVA_CASES + GO_CASES
    results: List[CaseResult] = []

    print(f"\n{_BOLD}{'═' * 60}{_RESET}")
    print(f"{_BOLD}  AST 正则解析器精度探针  {_DIM}(Java: {len(JAVA_CASES)} cases | Go: {len(GO_CASES)} cases){_RESET}")
    print(f"{_BOLD}{'═' * 60}{_RESET}\n")

    # ── Java ──
    print(f"{_BOLD}  Java 测试用例{_RESET}")
    java_results = []
    for case in JAVA_CASES:
        r = run_case(case)
        results.append(r)
        java_results.append(r)
        if args.verbose or not r.passed:
            print_case_detail(case, r)
        else:
            icon = f"{_GREEN}✓{_RESET}"
            print(f"  {icon} {case.id}  {_DIM}{case.description}{_RESET}")

    # ── Go ──
    print(f"\n{_BOLD}  Go 测试用例{_RESET}")
    go_results = []
    for case in GO_CASES:
        r = run_case(case)
        results.append(r)
        go_results.append(r)
        if args.verbose or not r.passed:
            print_case_detail(case, r)
        else:
            icon = f"{_GREEN}✓{_RESET}"
            print(f"  {icon} {case.id}  {_DIM}{case.description}{_RESET}")

    # ── 统计 ──
    def _stats(rs: List[CaseResult], label: str):
        total_exp_methods = sum(len(r.expected_methods) for r in rs)
        total_missed     = sum(len(r.missed_methods) for r in rs)
        total_extra      = sum(len(r.extra_methods) for r in rs)
        total_missed_cls = sum(len(r.missed_classes) for r in rs)
        cases_passed     = sum(1 for r in rs if r.passed)

        miss_rate = total_missed / max(total_exp_methods, 1)
        fp_rate   = total_extra  / max(total_exp_methods, 1)

        print(f"\n  {_BOLD}{label}{_RESET}")
        print(f"    case 通过率:        {cases_passed}/{len(rs)}"
              f"  ({cases_passed/len(rs):.0%})")
        print(f"    方法漏提率:        {total_missed}/{total_exp_methods}"
              f"  {_RED if miss_rate > 0.2 else _YELLOW if miss_rate > 0.1 else _GREEN}"
              f"({miss_rate:.0%}){_RESET}")
        print(f"    方法误报率:        {total_extra}/{total_exp_methods}"
              f"  ({fp_rate:.0%})")
        print(f"    类/struct 漏提数:   {total_missed_cls}")

        # 判断
        if miss_rate > 0.20:
            verdict = f"{_RED}⚠ 漏提率 > 20%，tree-sitter 有必要引入{_RESET}"
        elif miss_rate > 0.10:
            verdict = f"{_YELLOW}⚡ 漏提率 10-20%，建议先优化正则再评估{_RESET}"
        else:
            verdict = f"{_GREEN}✓ 漏提率 ≤ 10%，正则已足够，tree-sitter 是过度设计{_RESET}"
        print(f"    {_BOLD}结论:{_RESET} {verdict}")

        return miss_rate

    print(f"\n{'─' * 60}")
    java_miss = _stats(java_results, "Java 解析器")
    go_miss   = _stats(go_results,   "Go 解析器")

    # ── 综合判断 ──
    overall_miss = (java_miss + go_miss) / 2
    print(f"\n{'═' * 60}")
    print(f"  {_BOLD}综合结论（平均漏提率 {overall_miss:.0%}）:{_RESET}")
    if overall_miss > 0.20:
        print(f"  {_RED}{_BOLD}→ tree-sitter 值得引入：正则解析在企业级代码场景下不可靠{_RESET}")
        print(f"    建议：以可选依赖方式引入，Java + Go 路径升级，Python 路径保持 ast 库不变")
    elif overall_miss > 0.10:
        print(f"  {_YELLOW}{_BOLD}→ 正则解析存在明显盲区，但可先修复正则再评估是否需要 tree-sitter{_RESET}")
        print(f"    建议：针对失败 case 修复正则，3 个月后重新运行本探针")
    else:
        print(f"  {_GREEN}{_BOLD}→ 正则解析已足够，引入 tree-sitter 是过度设计{_RESET}")
        print(f"    建议：保持现状，仅针对失败 case 小范围修复正则即可")
    print(f"{'═' * 60}\n")

    # ── 失败 case 分类报告 ──
    failed = [r for r in results if not r.passed]
    if failed:
        print(f"  {_BOLD}失败 case 详情（供正则修复参考）:{_RESET}")
        for r in failed:
            case = next(c for c in all_cases if c.id == r.case_id)
            print(f"\n  [{r.case_id}] {case.description}")
            if r.missed_methods:
                print(f"    漏提方法: {sorted(r.missed_methods)}")
                # 在源码中定位漏提方法
                for m in r.missed_methods:
                    for line_num, line in enumerate(case.source.splitlines(), 1):
                        if m in line and ("def " in line or "func " in line
                                          or f" {m}(" in line or f"\t{m}(" in line):
                            print(f"      源码第 {line_num} 行: {line.strip()}")
            if r.missed_classes:
                print(f"    漏提类: {sorted(r.missed_classes)}")
        print()

    return 0 if overall_miss <= 0.10 else 1


if __name__ == "__main__":
    sys.exit(main())
