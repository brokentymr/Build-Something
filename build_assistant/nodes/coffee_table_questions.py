"""coffee_table question graph — Phase 7 data.

Ordered by geometric impact (section 7.2): dimensions and structure change the cut
list and come first; colour and sheen are appearance and come last. A user who
stops after the geometric questions still holds a buildable spec.
"""

from __future__ import annotations

from ..elicitation.question_graph import Question, Option

QUESTIONS = [
    Question(
        id="q_length", field="overall_length", prompt="How long, roughly?",
        type="numeric", options=(), required=True, downstream_impact=100,
        numeric_presets=(36, 42, 48, 54), unit="in",
        explain_on_request="Length sets the slab span and rib count."),
    Question(
        id="q_width", field="overall_width", prompt="How deep (front to back)?",
        type="numeric", options=(), required=True, downstream_impact=95,
        numeric_presets=(18, 20, 24), unit="in"),
    Question(
        id="q_height", field="overall_height", prompt="How tall overall?",
        type="numeric", options=(), required=True, downstream_impact=90,
        numeric_presets=(15, 16, 18), unit="in"),
    Question(
        id="q_edge", field="slab_edge_thickness", prompt="How thick should the top edge read?",
        type="numeric", options=(), required=True, downstream_impact=80,
        numeric_presets=(2, 3, 4), unit="in",
        explain_on_request="A thicker edge reads more monolithic but adds weight."),
    Question(
        id="q_base", field="base_type", prompt="What kind of base?",
        type="choice", required=True, downstream_impact=70,
        options=(Option("plinth", "Plinth (solid inset box)"),
                 Option("legs", "Four legs"),
                 Option("open_frame", "Open frame")),
        opens=("q_inset",),
        explain_on_request="A plinth grounds the piece; legs lighten it."),
    Question(
        id="q_finish", field="finish_system", prompt="How is it finished?",
        type="choice", required=True, downstream_impact=65,
        options=(Option("microcement_over_cement_board", "Microcement (troweled concrete look)"),
                 Option("veneer_backed", "Wood veneer"),
                 Option("paint_buildup", "Painted")),
        explain_on_request="Microcement needs a rigid cement-board substrate and adds weight."),
    Question(
        id="q_inset", field="plinth_inset", prompt="How far should the base sit in (the reveal)?",
        type="numeric", options=(), required=True, downstream_impact=60,
        numeric_presets=(2, 3, 4), unit="in",
        condition=lambda a: a.get("base_type") == "plinth"),
    Question(
        id="q_assembly", field="assembly", prompt="Built as one piece or knock-down?",
        type="choice", required=True, downstream_impact=50,
        options=(Option("single_monolith", "One monolithic piece"),
                 Option("knockdown", "Knock-down (bolted)")),
        explain_on_request="A monolith is stiffer; knock-down moves through doorways."),
    # ---- appearance last (lowest impact) ----
    Question(
        id="q_color", field="finish_color", prompt="What colour family?",
        type="choice", required=False, downstream_impact=10,
        options=(Option("warm_grey", "Warm grey"), Option("cool_grey", "Cool grey"),
                 Option("greige", "Greige"), Option("charcoal", "Charcoal"))),
    Question(
        id="q_sheen", field="finish_sheen", prompt="What sheen?",
        type="choice", required=False, downstream_impact=5,
        options=(Option("matte", "Matte"), Option("satin", "Satin"))),
]
