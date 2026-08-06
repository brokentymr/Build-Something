"""Schema registry and taxonomy — Phase 7, section 7.1.

A tree: folders group, leaves carry schema, only leaves are buildable. A request
resolving to a folder must be decomposed before elicitation begins. Leaf schema
data (question graph, joinery, invariants, derivation) lives with the node; this
registry indexes it and enforces the folder/leaf distinction.

Adding a leaf requires schema and joinery data only — no engine change
(Definition of Done, final item). This registry never contains geometry logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..elicitation.question_graph import Question, QuestionGraph


@dataclass
class TaxonNode:
    id: str
    display_name: str
    is_leaf: bool
    children: list[str] = field(default_factory=list)
    aliases: tuple[str, ...] = ()


class Registry:
    def __init__(self):
        self._taxon: dict[str, TaxonNode] = {}
        self._leaf_modules: dict[str, object] = {}
        self._questions: dict[str, list[Question]] = {}

    # ---- taxonomy ----
    def add_folder(self, id: str, display_name: str, children: list[str], aliases=()):
        self._taxon[id] = TaxonNode(id, display_name, False, list(children), tuple(aliases))

    def add_leaf(self, module, questions: list[Question], aliases=()):
        nid = module.NODE_ID
        self._taxon[nid] = TaxonNode(nid, module.SCHEMA["display_name"], True, [], tuple(aliases))
        self._leaf_modules[nid] = module
        self._questions[nid] = questions

    # ---- lookups ----
    def is_leaf(self, node_id: str) -> bool:
        return node_id in self._taxon and self._taxon[node_id].is_leaf

    def must_decompose(self, node_id: str) -> bool:
        """A folder must be decomposed before elicitation (section 7.1)."""
        return node_id in self._taxon and not self._taxon[node_id].is_leaf

    def leaf_module(self, node_id: str):
        if node_id not in self._leaf_modules:
            raise KeyError(f"{node_id!r} is not a registered leaf")
        return self._leaf_modules[node_id]

    def question_graph(self, node_id: str) -> QuestionGraph:
        return QuestionGraph(self._questions[node_id])

    def schema(self, node_id: str) -> dict:
        return self.leaf_module(node_id).SCHEMA

    def all_leaves(self) -> list[str]:
        return [n.id for n in self._taxon.values() if n.is_leaf]

    def resolve_aliases(self, term: str) -> list[str]:
        """Term -> candidate node ids (may be >1, requiring disambiguation)."""
        term = term.lower().strip()
        hits = []
        for n in self._taxon.values():
            if term == n.id or term in (a.lower() for a in n.aliases):
                hits.append(n.id)
        return hits


def default_registry() -> Registry:
    from ..nodes import coffee_table, floating_shelf
    from ..nodes.coffee_table_questions import QUESTIONS as CT_Q
    from ..nodes.floating_shelf import QUESTIONS as FS_Q

    reg = Registry()
    reg.add_folder("living_room_furniture", "Living-room furniture",
                   children=["coffee_table", "floating_shelf"],
                   aliases=("table for my living room", "living room"))
    reg.add_leaf(coffee_table, CT_Q, aliases=("coffee table", "cocktail table"))
    reg.add_leaf(floating_shelf, FS_Q, aliases=("floating shelf", "wall shelf"))
    return reg
