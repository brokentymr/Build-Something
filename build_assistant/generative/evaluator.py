"""Safe arithmetic evaluator — the engine's calculator, not the model's.

The agent writes formulas like ``width - 2*carcass_t``; this evaluates them over a
symbol table of parameters (in inches) and catalog-derived material symbols. Only
a whitelist of AST nodes is permitted — numbers, names, + - * /, unary minus, and
a few functions (min/max/ceil/floor/round/abs/sqrt/hypot). No attribute access,
no calls to
anything else, no arbitrary code. This is what keeps Law 1 true while letting the
model supply relationships: the model never runs, and never emits a number.
"""

from __future__ import annotations

import ast
import math

# A diagonal brace is a hypotenuse, and a firewood rack asked for one: the design
# loop failed outright on `sqrt(depth*depth + rise*rise)` because the whitelist had
# no way to express it. Both are pure, total on the domain the guard allows, and
# neither reaches outside the expression.
_FUNCS = {"min": min, "max": max, "abs": abs,
          "ceil": math.ceil, "floor": math.floor, "round": round,
          "sqrt": math.sqrt, "hypot": math.hypot}
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
           ast.Mod: lambda a, b: a % b, ast.Pow: lambda a, b: a ** b}


class ExprError(ValueError):
    pass


def evaluate(expr: str, symbols: dict) -> float:
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"bad expression {expr!r}: {e}")
    return _eval(tree.body, symbols, expr)


def _eval(node, symbols, expr):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"non-numeric constant in {expr!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in symbols:
            raise ExprError(f"unknown symbol {node.id!r} in {expr!r}")
        return float(symbols[node.id])
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if not op:
            raise ExprError(f"operator not allowed in {expr!r}")
        return float(op(_eval(node.left, symbols, expr), _eval(node.right, symbols, expr)))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval(node.operand, symbols, expr)
        return float(-v if isinstance(node.op, ast.USub) else v)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise ExprError(f"function not allowed in {expr!r}")
        args = [_eval(a, symbols, expr) for a in node.args]
        return float(_FUNCS[node.func.id](*args))
    raise ExprError(f"disallowed expression element in {expr!r}: {ast.dump(node)}")


def build_symbols(params, materials, catalog_get_material) -> dict:
    """Symbol table: each param id -> value (inches); each material role ->
    ``<role>_t`` (actual thickness), ``<role>_sw``/``<role>_sh`` (stock size)."""
    sym: dict[str, float] = {}
    for p in params:
        sym[p.id] = float(p.value)
    for m in materials:
        mat = catalog_get_material(m.material_id)
        sym[f"{m.role}_t"] = mat.actual_thickness
        if mat.stock_sizes:
            sym[f"{m.role}_sw"] = mat.stock_sizes[0].w
            sym[f"{m.role}_sh"] = mat.stock_sizes[0].h
    return sym
