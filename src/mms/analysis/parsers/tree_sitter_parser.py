"""Tree-sitter parser for Java, Go and TypeScript skeletons."""

from __future__ import annotations

import functools
import re
from typing import Any, Iterable, List, Optional

from mms.analysis.ast_skeleton import ClassSkeleton, FileSkeleton, MethodSkeleton

_MAX_SOURCE_BYTES = 1024 * 1024


def _require_tree_sitter() -> None:
    try:
        import tree_sitter  # noqa: F401
    except ImportError as error:
        raise ImportError(
            'Tree-sitter 未安装，请运行 pip install "mulan[tree_sitter]"'
        ) from error


@functools.lru_cache(maxsize=4)
def _get_parser(lang_name: str) -> Any:
    _require_tree_sitter()
    try:
        from tree_sitter import Language, Parser

        if lang_name == "java":
            import tree_sitter_java as grammar

            language = Language(grammar.language())
        elif lang_name == "go":
            import tree_sitter_go as grammar

            language = Language(grammar.language())
        elif lang_name in ("typescript", "tsx"):
            import tree_sitter_typescript as grammar

            capsule = (
                grammar.language_tsx()
                if lang_name == "tsx"
                else grammar.language_typescript()
            )
            language = Language(capsule)
        else:
            raise ValueError(f"unsupported tree-sitter language: {lang_name}")
        return Parser(language)
    except Exception as error:
        raise ImportError(f"tree-sitter-{lang_name} 初始化失败: {error}") from error


def _walk(node: Any) -> Iterable[Any]:
    yield node
    for child in node.named_children:
        yield from _walk(child)


def _text(node: Optional[Any], source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")


def _field(node: Any, name: str) -> Optional[Any]:
    try:
        return node.child_by_field_name(name)
    except Exception:
        return None


def _direct(node: Any, *types: str) -> List[Any]:
    allowed = set(types)
    return [child for child in node.named_children if child.type in allowed]


def _annotations(node: Any, source: bytes) -> List[str]:
    result = []
    for child in node.named_children:
        candidates = (
            child.named_children if child.type == "modifiers" else [child]
        )
        for candidate in candidates:
            if "annotation" not in candidate.type and candidate.type != "decorator":
                continue
            raw = _text(candidate, source).strip().lstrip("@")
            if raw:
                result.append(re.sub(r"\s+", " ", raw))
    return result


def _split_types(parameters: Optional[Any], source: bytes) -> List[str]:
    if parameters is None:
        return []
    result = []
    for parameter in parameters.named_children:
        type_node = _field(parameter, "type")
        raw = _text(type_node, source).strip()
        if not raw:
            text = _text(parameter, source).strip()
            tokens = text.split()
            raw = tokens[-1] if len(tokens) == 1 else " ".join(tokens[:-1])
        raw = raw.replace("...", "[]").strip()
        if raw:
            result.append(re.sub(r"\s+", " ", raw))
    return result


class TreeSitterParser:
    def __init__(self, lang: str) -> None:
        if lang not in ("java", "go", "typescript", "tsx"):
            raise ValueError(f"TreeSitterParser 不支持: {lang!r}")
        self._lang = lang

    def extract_skeleton(self, source: str, rel_path: str) -> FileSkeleton:
        lang = "typescript" if self._lang == "tsx" else self._lang
        if not source.strip() or len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            return FileSkeleton(path=rel_path, lang=lang)
        parser = _get_parser(self._lang)
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        if self._lang == "java":
            return self._parse_java(tree.root_node, source_bytes, rel_path)
        if self._lang == "go":
            return self._parse_go(tree.root_node, source_bytes, rel_path)
        return self._parse_typescript(tree.root_node, source_bytes, rel_path)

    def _parse_java(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
    ) -> FileSkeleton:
        skeleton = FileSkeleton(path=rel_path, lang="java")
        for node in root.named_children:
            if node.type == "package_declaration":
                skeleton.package = (
                    _text(node, source).replace("package", "", 1).rstrip(";").strip()
                )
            elif node.type == "import_declaration":
                raw = _text(node, source).rstrip(";").split(".")[-1].strip()
                if raw and raw != "*":
                    skeleton.imports.append(raw)

        class_types = {
            "class_declaration",
            "interface_declaration",
            "enum_declaration",
            "record_declaration",
            "annotation_type_declaration",
        }

        def add_class(node: Any, parent: str = "") -> None:
            name = _text(_field(node, "name"), source)
            if not name:
                return
            qualified_name = f"{parent}.{name}" if parent else name
            bases = []
            for field_name, prefix in (
                ("superclass", "extends"),
                ("interfaces", "implements"),
            ):
                raw = _text(_field(node, field_name), source).strip()
                raw = re.sub(rf"^{prefix}\s+", "", raw)
                if raw:
                    bases.extend(
                        item.strip().split("<", 1)[0]
                        for item in raw.split(",")
                        if item.strip()
                    )
            cls = ClassSkeleton(
                name=qualified_name,
                bases=bases,
                annotations=_annotations(node, source),
            )
            body = _field(node, "body")
            if body is not None:
                for member in body.named_children:
                    if member.type in ("method_declaration", "constructor_declaration"):
                        method_name = _text(_field(member, "name"), source)
                        if not method_name:
                            continue
                        parameters = _field(member, "parameters")
                        parameter_types = _split_types(parameters, source)
                        return_type = _text(_field(member, "type"), source).strip()
                        if member.type == "constructor_declaration":
                            return_type = name
                        signature = f"({', '.join(parameter_types)})"
                        if return_type:
                            signature += f" -> {return_type}"
                        cls.methods.append(
                            MethodSkeleton(
                                name=method_name,
                                signature=signature,
                                annotations=_annotations(member, source),
                            )
                        )
            skeleton.classes.append(cls)
            if body is not None:
                for nested in body.named_children:
                    if nested.type in class_types:
                        add_class(nested, qualified_name)

        for node in root.named_children:
            if node.type in class_types:
                add_class(node)
        skeleton.imports = sorted(set(skeleton.imports))
        return skeleton

    def _parse_go(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
    ) -> FileSkeleton:
        skeleton = FileSkeleton(path=rel_path, lang="go")
        structs = {}
        for node in _walk(root):
            if node.type == "package_clause":
                skeleton.package = _text(node, source).replace("package", "", 1).strip()
            elif node.type == "import_spec":
                path_node = _field(node, "path")
                raw = _text(path_node, source).strip('"`')
                if raw:
                    skeleton.imports.append(raw.rsplit("/", 1)[-1])
            elif node.type == "type_spec":
                name = _text(_field(node, "name"), source)
                type_node = _field(node, "type")
                if not name or type_node is None:
                    continue
                if type_node.type not in ("struct_type", "interface_type"):
                    continue
                kind = "interface" if type_node.type == "interface_type" else "struct"
                bases = [kind]
                body = _field(type_node, "body")
                if body is None:
                    body = next(
                        (
                            child
                            for child in type_node.named_children
                            if child.type in (
                                "field_declaration_list",
                                "method_spec_list",
                            )
                        ),
                        None,
                    )
                if body is not None:
                    for member in body.named_children:
                        if member.type == "field_declaration" and _field(member, "name") is None:
                            embedded_node = _field(member, "type")
                            if embedded_node is None and member.named_children:
                                embedded_node = member.named_children[-1]
                            embedded = _text(embedded_node, source).lstrip("*")
                            if embedded:
                                bases.append(embedded)
                structs[name] = ClassSkeleton(name=name, bases=bases)

        for node in _walk(root):
            if node.type not in ("function_declaration", "method_declaration"):
                continue
            name = _text(_field(node, "name"), source)
            if not name:
                continue
            parameter_types = _split_types(_field(node, "parameters"), source)
            signature = f"({', '.join(parameter_types)})"
            method = MethodSkeleton(name=name, signature=signature)
            receiver = ""
            if node.type == "method_declaration":
                receiver_text = _text(_field(node, "receiver"), source)
                matches = re.findall(r"\*?([A-Z]\w*)", receiver_text)
                receiver = matches[-1] if matches else ""
            if receiver:
                structs.setdefault(
                    receiver,
                    ClassSkeleton(name=receiver, bases=["struct"]),
                ).methods.append(method)
            else:
                skeleton.top_level_functions.append(method)

        skeleton.classes = list(structs.values())
        skeleton.imports = sorted(set(skeleton.imports))
        return skeleton

    def _parse_typescript(
        self,
        root: Any,
        source: bytes,
        rel_path: str,
    ) -> FileSkeleton:
        skeleton = FileSkeleton(path=rel_path, lang="typescript")
        class_types = {
            "class_declaration",
            "abstract_class_declaration",
            "interface_declaration",
            "enum_declaration",
        }
        declarations = []
        declaration_annotations = {}
        for root_node in root.named_children:
            if root_node.type == "import_statement":
                raw = _text(root_node, source)
                match = re.search(r"import\s*\{([^}]+)\}", raw)
                if match:
                    for item in match.group(1).split(","):
                        name = item.strip().split(" as ")[-1].strip()
                        if name and name[0].isupper():
                            skeleton.imports.append(name)
                continue
            if root_node.type == "export_statement":
                pending = []
                for child in root_node.named_children:
                    if child.type == "decorator":
                        pending.append(_text(child, source).strip().lstrip("@"))
                    else:
                        declarations.append(child)
                        if pending:
                            declaration_annotations[id(child)] = list(pending)
                            pending = []
            else:
                declarations.append(root_node)

        for node in declarations:
            if node.type == "function_declaration":
                name = _text(_field(node, "name"), source)
                params = _split_types(_field(node, "parameters"), source)
                if name:
                    skeleton.top_level_functions.append(
                        MethodSkeleton(name=name, signature=f"({', '.join(params)})")
                    )
                continue
            if node.type not in class_types:
                continue
            name = _text(_field(node, "name"), source)
            if not name:
                continue
            bases = []
            for child in node.named_children:
                if child.type == "class_heritage":
                    raw = _text(child, source)
                    bases.extend(
                        item.strip().split("<", 1)[0]
                        for item in re.split(r"\bextends\b|\bimplements\b|,", raw)
                        if item.strip()
                    )
            cls = ClassSkeleton(
                name=name,
                bases=bases,
                annotations=declaration_annotations.get(
                    id(node),
                    _annotations(node, source),
                ),
            )
            body = _field(node, "body")
            if body is not None:
                pending_annotations = []
                for member in body.named_children:
                    if member.type == "decorator":
                        pending_annotations.append(
                            _text(member, source).strip().lstrip("@")
                        )
                        continue
                    if member.type not in (
                        "method_definition",
                        "method_signature",
                        "abstract_method_signature",
                    ):
                        pending_annotations = []
                        continue
                    method_name = _text(_field(member, "name"), source)
                    if not method_name:
                        continue
                    params = _split_types(_field(member, "parameters"), source)
                    cls.methods.append(
                        MethodSkeleton(
                            name=method_name,
                            signature=f"({', '.join(params)})",
                            annotations=(
                                list(pending_annotations)
                                or _annotations(member, source)
                            ),
                            is_async="async" in _text(member, source).split("(", 1)[0],
                        )
                    )
                    pending_annotations = []
            skeleton.classes.append(cls)
        skeleton.imports = sorted(set(skeleton.imports))
        return skeleton
