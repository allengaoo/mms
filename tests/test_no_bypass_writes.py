from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = [ROOT / "src" / "mms" / "memory", ROOT / "src" / "mms" / "bootstrap"]

# These modules only write EP-private drafts or derived/system artifacts, never
# canonical shared memory records. Formal memory mutations belong in adapters.
EXEMPT_MODULES = {
    "src/mms/memory/codemap.py",
    "src/mms/memory/entropy_scan.py",
    "src/mms/memory/funcmap.py",
    "src/mms/memory/private.py",
    "src/mms/memory/task_matcher.py",
    "src/mms/memory/template_lib.py",
    "src/mms/bootstrap/schema_evolution.py",
}
EXEMPT_FUNCTIONS = {
    ("src/mms/memory/dream.py", "_apply_auto_link_to_file"),
    ("src/mms/memory/dream.py", "save_draft"),
    ("src/mms/memory/dream.py", "promote_draft"),  # removes the promoted draft
    ("src/mms/bootstrap/ontology_populator.py", "bootstrap_project"),
}
WRITE_METHODS = {"write_text", "unlink", "rename"}
WRITE_FUNCTIONS = {"atomic_write", "atomic_write_json", "move"}


class _WriteVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.functions = []
        self.violations = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        name = ""
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
        elif isinstance(node.func, ast.Name):
            name = node.func.id
        current = self.functions[-1] if self.functions else "<module>"
        exempt = (
            self.relative_path in EXEMPT_MODULES
            or (self.relative_path, current) in EXEMPT_FUNCTIONS
        )
        if not exempt and name in WRITE_METHODS | WRITE_FUNCTIONS:
            self.violations.append(f"{self.relative_path}:{node.lineno} ({current})")
        self.generic_visit(node)


def test_shared_memory_writes_do_not_bypass_repository() -> None:
    violations = []
    for scan_root in SCAN_ROOTS:
        for path in scan_root.rglob("*.py"):
            relative = str(path.relative_to(ROOT))
            visitor = _WriteVisitor(relative)
            visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
            violations.extend(visitor.violations)
    assert violations == [], "Repository bypasses:\n" + "\n".join(violations)
