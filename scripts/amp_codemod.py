"""
One-off codemod: rewrite from-imports to the amp module-import style.

The vendored amp linter bans ``from X import Y`` (except ``from typing``) and
caps ``import ... as`` aliases at eight characters. This rewrites every
non-typing from-import in the given files:

- ``from __future__ import annotations`` is dropped.
- ``from operant.a.b import c [as d]`` becomes ``import operant.a.b.c as
  <alias>`` (the alias is the old bound name when it fits in eight
  characters, else a shortened, per-file-unique alias), and references are
  rewritten to the alias.
- ``from <stdlib/third-party> import Sym`` becomes ``import <module>`` and
  references become ``<module>.Sym`` (scope-aware, so a local ``field`` is
  never mistaken for ``dataclasses.field``).

Run: ``uv run python scripts/amp_codemod.py <file.py> ...``
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import libcst as cst
from libcst.metadata import (
    ExpressionContext,
    ExpressionContextProvider,
    MetadataWrapper,
    ScopeProvider,
)

# Long module last-names that exceed the eight-character alias cap.
_SHORT = {
    "redaction": "redact",
    "sensitivity": "sensv",
    "governance": "govern",
    "escalation": "escal",
    "capabilities": "capab",
    "dispatcher": "dispat",
    "recording": "recdng",
    "bootstrap": "bstrap",
    "litellm_client": "litecli",
    "repositories": "repos",
}

# Modules kept as ``from`` imports (both are exempt in amp_check_import).
_KEEP_FROM = {"typing", "__future__"}


def _alias_for(module: str, taken: set[str]) -> str:
    """
    Pick a unique, <=8 char alias for a dotted module path.
    """
    last = module.rsplit(".", 1)[-1]
    base = _SHORT.get(last, last if len(last) <= 8 else last[:8])
    alias = base
    parts = module.split(".")
    i = 2
    while alias in taken:
        prefix = "".join(p[0] for p in parts[-i:]) if i <= len(parts) else base
        alias = (prefix + base)[:8]
        i += 1
        if i > len(parts) + 3:
            alias = (base[:6] + str(len(taken)))[:8]
            break
    taken.add(alias)
    return alias


# #############################################################################
# _LocalNames
# #############################################################################


class _LocalNames(cst.CSTVisitor):
    """
    Collect every name defined in the module (to avoid alias clashes).
    """

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.names.add(node.name.value)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.names.add(node.name.value)

    def visit_AssignTarget(self, node: cst.AssignTarget) -> None:
        if isinstance(node.target, cst.Name):
            self.names.add(node.target.value)

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        if isinstance(node.target, cst.Name):
            self.names.add(node.target.value)

    def visit_Param(self, node: cst.Param) -> None:
        self.names.add(node.name.value)

    def visit_Import(self, node: cst.Import) -> None:
        # Bound names of plain imports (``import logging`` binds ``logging``;
        # ``import a.b`` binds ``a``); an alias must not shadow these.
        for alias in node.names:
            if alias.asname and isinstance(alias.asname.name, cst.Name):
                self.names.add(alias.asname.name.value)
            else:
                self.names.add(_dotted(alias.name).split(".", 1)[0])


# #############################################################################
# _Collector
# #############################################################################


class _Collector(cst.CSTVisitor):
    """
    Record how each from-import should be rewritten.
    """

    def __init__(self, reserved: set[str]) -> None:
        # bound name -> (kind, replacement). kind is "module" or "symbol".
        self.rewrites: dict[str, tuple[str, str]] = {}
        # id(ImportFrom) -> the ``import ...`` lines that replace it.
        self.node_imports: dict[int, list[str]] = {}
        # Seed with names defined in the file so an alias never shadows a
        # module-level singleton, field, or function of the same name.
        self._taken: set[str] = set(reserved)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        if node.module is None or isinstance(node.names, cst.ImportStar):
            return
        module = _dotted(node.module)
        if module in _KEEP_FROM:
            return
        lines: list[str] = []
        for alias in node.names:
            name = alias.name.value
            bound = alias.asname.name.value if alias.asname else name
            full = f"{module}.{name}"
            if _is_submodule(module, name):
                new_alias = (
                    bound
                    if len(bound) <= 8 and bound not in self._taken
                    else _alias_for(full, self._taken)
                )
                self._taken.add(new_alias)
                lines.append(f"import {full} as {new_alias}")
                self.rewrites[bound] = ("module", new_alias)
            else:
                lines.append(f"import {module}")
                self.rewrites[bound] = ("symbol", full)
        self.node_imports[id(node)] = lines


_FIRST_PARTY_ROOTS = {"operant": Path("src"), "tests": Path(".")}


def _is_submodule(module: str, name: str) -> bool:
    """
    Whether ``module.name`` names a submodule (not a class/function).

    First-party packages are checked on disk (no import side effects);
    third-party packages fall back to ``importlib.util.find_spec``.
    """
    parts = f"{module}.{name}".split(".")
    root = _FIRST_PARTY_ROOTS.get(parts[0])
    if root is not None:
        target = root.joinpath(*parts)
        return (
            target.with_suffix(".py").exists()
            or (target / "__init__.py").exists()
        )
    try:
        return importlib.util.find_spec(f"{module}.{name}") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _dotted(node: cst.BaseExpression) -> str:
    if isinstance(node, cst.Name):
        return node.value
    if isinstance(node, cst.Attribute):
        return f"{_dotted(node.value)}.{node.attr.value}"
    return ""


# #############################################################################
# _Rewriter
# #############################################################################


class _Rewriter(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (ScopeProvider,)

    def __init__(self, plan: _Collector, module_level: set[int]) -> None:
        self._plan = plan
        self._module_level = module_level
        self._targets: set[int] = set()
        self._header: list[str] = []
        for node_id in module_level:
            self._header.extend(plan.node_imports.get(node_id, []))

    def leave_ImportFrom(
        self, original: cst.ImportFrom, updated: cst.ImportFrom
    ) -> cst.BaseSmallStatement | cst.RemovalSentinel:
        if original.module is not None and _dotted(original.module) in _KEEP_FROM:
            return updated
        if id(original) in self._module_level:
            # Hoisted into the module header by leave_Module.
            return cst.RemoveFromParent()
        # Nested (function-local or TYPE_CHECKING) import: convert in place so
        # its laziness and cycle-avoidance are preserved.
        lines = self._plan.node_imports.get(id(original), [])
        aliases: list[cst.ImportAlias] = []
        for line in lines:
            stmt = cst.parse_statement(line + "\n")
            imp = stmt.body[0]
            if isinstance(imp, cst.Import):
                aliases.extend(imp.names)
        return cst.Import(names=aliases)

    def leave_Name(
        self, original: cst.Name, updated: cst.Name
    ) -> cst.BaseExpression:
        if id(original) not in self._targets:
            return updated
        _kind, replacement = self._plan.rewrites[original.value]
        return cst.parse_expression(replacement)

    def leave_Module(
        self, original: cst.Module, updated: cst.Module
    ) -> cst.Module:
        if not self._header:
            return updated
        stmts = [cst.parse_statement(line) for line in sorted(set(self._header))]
        body = list(updated.body)
        insert_at = 1 if _has_docstring(updated) else 0
        while insert_at < len(body) and _is_future_import(body[insert_at]):
            insert_at += 1
        return updated.with_changes(
            body=[*body[:insert_at], *stmts, *body[insert_at:]]
        )

    def _mark(self, wrapper: MetadataWrapper) -> None:
        scopes = wrapper.resolve(ScopeProvider)
        for node, scope in scopes.items():
            if not isinstance(node, cst.Name):
                continue
            if node.value not in self._plan.rewrites:
                continue
            for assignment in scope[node.value]:
                if isinstance(assignment, cst.metadata.Assignment) and isinstance(
                    assignment.node, (cst.ImportFrom,)
                ):
                    self._targets.add(id(node))


def _is_future_import(stmt: cst.BaseStatement) -> bool:
    if not isinstance(stmt, cst.SimpleStatementLine):
        return False
    inner = stmt.body[0] if stmt.body else None
    return (
        isinstance(inner, cst.ImportFrom)
        and inner.module is not None
        and _dotted(inner.module) == "__future__"
    )


def _has_docstring(module: cst.Module) -> bool:
    if not module.body:
        return False
    first = module.body[0]
    return (
        isinstance(first, cst.SimpleStatementLine)
        and len(first.body) == 1
        and isinstance(first.body[0], cst.Expr)
        and isinstance(
            first.body[0].value, cst.SimpleString | cst.ConcatenatedString
        )
    )


def _module_level_ids(module: cst.Module) -> set[int]:
    ids: set[int] = set()
    for stmt in module.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for small in stmt.body:
                if isinstance(small, cst.ImportFrom):
                    ids.add(id(small))
    return ids


def _apply(source: str) -> str:
    module = cst.parse_module(source)
    # Skip the copy so node ids stay stable across every pass and the
    # transform.
    wrapper = MetadataWrapper(module, unsafe_skip_copy=True)
    locals_visitor = _LocalNames()
    module.visit(locals_visitor)
    reserved = set(locals_visitor.names)
    contexts = wrapper.resolve(ExpressionContextProvider)
    for name_node, context in contexts.items():
        if isinstance(name_node, cst.Name) and context == ExpressionContext.STORE:
            reserved.add(name_node.value)
    plan = _Collector(reserved)
    module.visit(plan)
    if not plan.node_imports:
        return source
    rewriter = _Rewriter(plan, _module_level_ids(module))
    rewriter._mark(wrapper)
    new = wrapper.module.visit(rewriter)
    return new.code


def main() -> None:
    for path_str in sys.argv[1:]:
        path = Path(path_str)
        original = path.read_text(encoding="utf-8")
        path.write_text(_apply(original), encoding="utf-8")
        print(f"  migrated imports: {path}")


if __name__ == "__main__":
    main()
