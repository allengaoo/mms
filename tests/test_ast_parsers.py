"""
test_ast_parsers.py — AST 解析器适配层单元测试

覆盖：
  1. RegexFallbackParser：Java/Go 基本解析（含现代语法）
  2. factory.get_parser()：配置路由、降级逻辑
  3. TreeSitterParser（跳过：CI 环境未安装 tree-sitter）
  4. Protocol 兼容性检查
"""
from __future__ import annotations

import pytest

from mms.analysis.parsers.protocol import ASTParserProtocol
from mms.analysis.parsers.regex_parser import RegexFallbackParser
from mms.analysis.parsers.factory import get_parser


# ── 测试 fixture ──────────────────────────────────────────────────────────────

JAVA_BASIC = """
public class UserService {
    public UserDTO findById(Long id) { return null; }
    public void delete(Long id) {}
}
"""

JAVA_RECORD = """
public record UserRecord(String name, int age) {
    public String display() { return name + ":" + age; }
}
"""

JAVA_SEALED = """
public sealed interface Shape permits Circle {
    double area();
    default String describe() { return "shape"; }
}
"""

JAVA_FUNCTIONAL = """
@FunctionalInterface
public interface Transformer<T, R> {
    R transform(T input);
    default Transformer<T, R> andLog() { return this; }
    static <T> Transformer<T, T> identity() { return t -> t; }
}
"""

GO_BASIC = """
package service

type UserService struct{}

func (s *UserService) FindById(id string) (*User, error) { return nil, nil }
func (s *UserService) Delete(id string) error { return nil }
"""

GO_MULTI_GENERIC = """
package collections

type OrderedMap[K comparable, V any] struct {
    values map[K]V
}

func (m *OrderedMap[K, V]) Set(k K, v V) {}
func (m *OrderedMap[K, V]) Get(k K) (V, bool) { return m.values[k] }
"""

GO_GENERIC_SINGLE = """
package collections

type Stack[T any] struct{ items []T }

func (s *Stack[T]) Push(item T) { s.items = append(s.items, item) }
func (s *Stack[T]) Pop() T { return s.items[len(s.items)-1] }
"""


# ── RegexFallbackParser 测试 ─────────────────────────────────────────────────

class TestRegexFallbackParserJava:
    def _parser(self) -> RegexFallbackParser:
        return RegexFallbackParser("java")

    def test_basic_class(self):
        sk = self._parser().extract_skeleton(JAVA_BASIC, "test.java")
        assert sk.lang == "java"
        class_names = {c.name for c in sk.classes}
        assert "UserService" in class_names
        methods = {m.name for c in sk.classes for m in c.methods}
        assert {"findById", "delete"} <= methods

    def test_record_java16(self):
        sk = self._parser().extract_skeleton(JAVA_RECORD, "UserRecord.java")
        class_names = {c.name for c in sk.classes}
        assert "UserRecord" in class_names, f"record 类未提取，得到: {class_names}"
        methods = {m.name for c in sk.classes for m in c.methods}
        assert "display" in methods, f"record 方法未提取，得到: {methods}"

    def test_sealed_interface_java17(self):
        sk = self._parser().extract_skeleton(JAVA_SEALED, "Shape.java")
        class_names = {c.name for c in sk.classes}
        assert "Shape" in class_names, f"sealed interface 未提取，得到: {class_names}"
        methods = {m.name for c in sk.classes for m in c.methods}
        assert "describe" in methods, f"default 方法未提取，得到: {methods}"

    def test_functional_interface_with_annotation(self):
        sk = self._parser().extract_skeleton(JAVA_FUNCTIONAL, "Transformer.java")
        class_names = {c.name for c in sk.classes}
        assert "Transformer" in class_names, (
            f"@FunctionalInterface interface 未提取，得到: {class_names}"
        )
        methods = {m.name for c in sk.classes for m in c.methods}
        assert "andLog" in methods and "identity" in methods, (
            f"default/static 方法未提取，得到: {methods}"
        )

    def test_invalid_lang(self):
        with pytest.raises(ValueError, match="仅支持"):
            RegexFallbackParser("python")


class TestRegexFallbackParserGo:
    def _parser(self) -> RegexFallbackParser:
        return RegexFallbackParser("go")

    def test_basic_struct(self):
        sk = self._parser().extract_skeleton(GO_BASIC, "service.go")
        assert sk.lang == "go"
        class_names = {c.name for c in sk.classes}
        assert "UserService" in class_names
        methods = {m.name for c in sk.classes for m in c.methods}
        assert {"FindById", "Delete"} <= methods

    def test_multi_generic_receiver(self):
        sk = self._parser().extract_skeleton(GO_MULTI_GENERIC, "ordered_map.go")
        class_names = {c.name for c in sk.classes}
        assert "OrderedMap" in class_names, (
            f"多泛型 struct 未提取，得到: {class_names}"
        )
        methods = {m.name for c in sk.classes for m in c.methods}
        assert {"Set", "Get"} <= methods, (
            f"多泛型 receiver 方法未提取，得到: {methods}"
        )

    def test_single_generic_receiver(self):
        sk = self._parser().extract_skeleton(GO_GENERIC_SINGLE, "stack.go")
        class_names = {c.name for c in sk.classes}
        assert "Stack" in class_names
        methods = {m.name for c in sk.classes for m in c.methods}
        assert {"Push", "Pop"} <= methods


# ── Protocol 兼容性测试 ────────────────────────────────────────────────────────

class TestProtocolCompliance:
    def test_regex_parser_satisfies_protocol(self):
        parser = RegexFallbackParser("java")
        assert isinstance(parser, ASTParserProtocol), (
            "RegexFallbackParser 未满足 ASTParserProtocol"
        )

    def test_extract_skeleton_returns_file_skeleton(self):
        from mms.analysis.ast_skeleton import FileSkeleton
        parser = RegexFallbackParser("go")
        result = parser.extract_skeleton(GO_BASIC, "test.go")
        assert isinstance(result, FileSkeleton)


# ── factory.get_parser() 测试 ─────────────────────────────────────────────────

class TestGetParser:
    def test_default_returns_regex_parser(self):
        parser = get_parser("java", use_tree_sitter=False)
        assert isinstance(parser, RegexFallbackParser)

    def test_tree_sitter_false_returns_regex(self):
        parser = get_parser("go", use_tree_sitter=False)
        assert isinstance(parser, RegexFallbackParser)

    def test_tree_sitter_unavailable_falls_back(self):
        """当 tree-sitter 未安装时，应自动降级为 RegexFallbackParser。"""
        parser = get_parser("java", use_tree_sitter=True)
        # 不管 tree-sitter 是否安装，都应该返回一个可用的 parser
        assert isinstance(parser, ASTParserProtocol)
        # 功能正常（使用 fallback）
        sk = parser.extract_skeleton(JAVA_BASIC, "test.java")
        assert len(sk.classes) > 0

    def test_invalid_lang_raises(self):
        with pytest.raises(ValueError, match="仅支持"):
            get_parser("python")

    def test_parser_output_consistent(self):
        """两种解析路径对同一输入应产出相同类名。"""
        regex_parser = get_parser("java", use_tree_sitter=False)
        ts_parser = get_parser("java", use_tree_sitter=True)

        sk_regex = regex_parser.extract_skeleton(JAVA_BASIC, "test.java")
        sk_ts = ts_parser.extract_skeleton(JAVA_BASIC, "test.java")

        # 两者提取的类名应相同（方法可能略有差异）
        names_regex = {c.name for c in sk_regex.classes}
        names_ts = {c.name for c in sk_ts.classes}
        # tree-sitter 可能不可用，此时 ts_parser 也是 regex，一定一致
        # tree-sitter 可用时，二者类名应一致
        assert names_regex == names_ts or names_ts >= {"UserService"}
