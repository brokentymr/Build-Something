"""Node manifest.

Adding a leaf node means appending its module here (data) — the solver, allowance
layer, invariants, nesting, drawing and document engines are never edited. Each
module must expose ``NODE_ID``, ``SCHEMA`` and ``build(answers) -> SolveDraft``.
"""

from . import coffee_table, floating_shelf

ALL_NODES = [coffee_table, floating_shelf]
