from __future__ import annotations

import ast


class WorkflowValidationError(ValueError):
    pass


_DISALLOWED_NODES = (
    ast.Import,
    ast.ImportFrom,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Raise,
    ast.Assert,
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Nonlocal,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.Attribute,
    ast.Match,
)

_ALLOWED_CALLS = {
    "tool",
    "emit",
    "len",
    "min",
    "max",
    "sorted",
    "enumerate",
    "range",
    "str",
    "int",
    "float",
    "bool",
    "list",
    "dict",
    "set",
    "sum",
    "any",
    "all",
    "zip",
    "abs",
    "round",
}

_DISALLOWED_NAMES = {
    "eval",
    "exec",
    "open",
    "compile",
    "input",
    "__import__",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "help",
    "breakpoint",
}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod)
_ALLOWED_UNARYOPS = (ast.Not, ast.UAdd, ast.USub)
_ALLOWED_CMPOPS = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


class _WorkflowTransformer(ast.NodeTransformer):
    def _tick_stmt(self) -> ast.Expr:
        return ast.Expr(value=ast.Call(func=ast.Name(id="_workflow_tick", ctx=ast.Load()), args=[], keywords=[]))

    def _prepend_ticks(self, body: list[ast.stmt]) -> list[ast.stmt]:
        out: list[ast.stmt] = []
        for stmt in body:
            out.append(self._tick_stmt())
            out.append(stmt)
        return out

    def visit_Module(self, node: ast.Module) -> ast.AST:
        self.generic_visit(node)
        node.body = self._prepend_ticks(node.body)
        return node

    def visit_For(self, node: ast.For) -> ast.AST:
        self.generic_visit(node)
        node.body = self._prepend_ticks(node.body)
        node.orelse = self._prepend_ticks(node.orelse)
        return node

    def visit_If(self, node: ast.If) -> ast.AST:
        self.generic_visit(node)
        node.body = self._prepend_ticks(node.body)
        node.orelse = self._prepend_ticks(node.orelse)
        return node


def _validate_tree(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, _DISALLOWED_NODES):
            raise WorkflowValidationError(f"Unsupported workflow syntax: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise WorkflowValidationError("Workflow calls must target named helpers only")
            if str(node.func.id or "") in _DISALLOWED_NAMES:
                raise WorkflowValidationError(f"Call is not allowed in workflow scripts: {node.func.id}")
            if str(node.func.id or "") not in _ALLOWED_CALLS:
                raise WorkflowValidationError(f"Unknown workflow helper: {node.func.id}")
        if isinstance(node, ast.Name):
            if str(node.id or "").startswith("__"):
                raise WorkflowValidationError("Dunder names are not allowed in workflow scripts")
        if isinstance(node, ast.BinOp) and not isinstance(node.op, _ALLOWED_BINOPS):
            raise WorkflowValidationError(f"Operator is not allowed in workflow scripts: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp) and not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise WorkflowValidationError(f"Unary operator is not allowed: {type(node.op).__name__}")
        if isinstance(node, ast.Compare):
            for op in list(node.ops or []):
                if not isinstance(op, _ALLOWED_CMPOPS):
                    raise WorkflowValidationError(f"Comparison operator is not allowed: {type(op).__name__}")


def compile_workflow_script(script: str):
    try:
        tree = ast.parse(str(script or ""), mode="exec")
    except SyntaxError as exc:
        raise WorkflowValidationError(str(exc)) from exc
    _validate_tree(tree)
    instrumented = _WorkflowTransformer().visit(tree)
    ast.fix_missing_locations(instrumented)
    return compile(instrumented, "<workflow>", "exec")
