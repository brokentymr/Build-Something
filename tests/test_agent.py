"""Agent guardrail tests — the deterministic guards that keep the AI inside Law 1.

These need no API key: they exercise the validation layer directly, which is what
protects the system from an invented dimension regardless of what the model says.
"""

from __future__ import annotations

from build_assistant.schema.registry import default_registry
from webapp.agent import BuildAgent

REG = default_registry()
AGENT = BuildAgent(None, REG)   # boundary unused by the validation layer


def test_unit_conversion():
    assert AGENT._to_inches("4", "feet") == 48.0
    assert AGENT._to_inches("20", "inches") == 20.0
    assert round(AGENT._to_inches("100", "cm"), 2) == 39.37
    print("  [ok] unit conversion (ft/in/cm) done in code, not by the model")


def test_text_presence_guard_drops_unstated_numbers():
    """A number the user never typed cannot enter — even if the model returns it."""
    text = "4 feet long, 20 inches deep, 3 inch edge, on a plinth"
    raw = {"overall_length": ("4", "feet"), "overall_width": ("20", "inches"),
           "slab_edge_thickness": ("3", "inch"), "base_type": ("plinth", None),
           "overall_height": ("16", "inches")}   # 16 was never stated -> must be dropped
    extracted, _ = AGENT._validate("coffee_table", raw, text)
    assert extracted["overall_length"] == 48.0
    assert extracted["overall_width"] == 20.0
    assert extracted["slab_edge_thickness"] == 3.0
    assert extracted["base_type"] == "plinth"
    assert "overall_height" not in extracted, "unstated 16 must be dropped (Law 1)"
    print("  [ok] Law-1 guard drops a dimension not present in the user's text")


def test_non_schema_field_rejected():
    ext, _ = AGENT._validate("coffee_table", {"made_up_field": ("9", "in")}, "9 inch made_up")
    assert ext == {}, "fields outside the schema are never accepted"
    print("  [ok] non-schema field rejected (schema owns the field set)")


def test_invalid_enum_dropped():
    ext, _ = AGENT._validate("coffee_table", {"base_type": ("hovercraft", None)}, "hovercraft base")
    assert "base_type" not in ext, "invalid option must be dropped and asked instead"
    print("  [ok] invalid enum value dropped, question asked instead")


def test_valid_enum_matched_by_label_or_value():
    ext, _ = AGENT._validate("coffee_table", {"finish_system": ("microcement_over_cement_board", None)},
                             "microcement")
    assert ext.get("finish_system") == "microcement_over_cement_board"
    print("  [ok] valid enum matched against schema options")
