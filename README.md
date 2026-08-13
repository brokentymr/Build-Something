# Build Assistant

A deterministic engineering system with a conversational front door. It takes a
person from "I want to build a thing" to a complete, buildable document package:
materials list, prep list, cut list, sheet layouts, dimensioned drawings, and a
step-by-step build sequence with fasteners, bit sizes, tolerances and sign-off
checks.

It is **not** a chatbot that describes how to build things. Language models
classify intent, phrase questions and decompose free text. Every number is
computed by a pure solver.

## The five laws

1. **AI never emits a number.** Every number reaching a user traces to a solver field id.
2. **Solve is a pure function.** `solve(answers) -> geometry`; same inputs, same output, same hash. No I/O, randomness or model calls.
3. **Answer sets are append-only.** Revisions create new versions; nothing is mutated.
4. **Partial re-solve does not exist.** Any input change regenerates everything downstream.
5. **No document releases with a failing gate.** No override flag.

These are enforced structurally, not by convention — see "Where each law lives" below.

## Quick start

Run the app — this is the product:

```bash
export ANTHROPIC_API_KEY=...              # required for the design agent
python3 -m webapp.server --port 8079      # then open http://localhost:8079
```

The app takes a description ("a low wide sofa frame, 84 inches, to upholster"),
asks what it needs to know three questions at a time, designs the piece, checks
its own work, and releases a printable build packet. A design it has not seen
before takes a few minutes of design rounds; a curated node takes seconds.

Without a key it still runs, on heuristics — the badge in the corner says which.

The engine on its own, with no server and no model:

```bash
python3 run_tests.py         # full suite, stdlib only (no pytest needed)
python3 build.py             # solve -> nest -> draw -> document -> gates -> out/coffee_table.pdf
python3 build.py --no-render # deterministic core only (no Chromium)
```

And the instruments that measure whether the *product* works, by driving the
live app over HTTP — see `harness/README.md`:

```bash
sh harness/serve.sh out/server.log   # restart, and print the build actually served
python3 harness/corpus.py            # twelve real descriptions, end to end
python3 harness/sofa.py              # one deliberately hard case
```

The reference fixture (`fixtures/coffee_table_reference.json`) is the golden test:
the solver reproduces every value in the brief's section 2.5 table from its seven
inputs. `build.py` runs the whole pipeline and refuses to release the PDF unless
all three gates pass (Law 5).

Rendering uses the pre-installed Chromium via `CHROME_BIN`
(default `/opt/pw-browsers/chromium-1194/chrome-linux/chrome`). No Playwright or
pytest is required.

## Architecture

Built in the brief's phase order; phases 1–6 contain **no LLM calls at all**.

| Phase | Module | What it does |
|------|--------|--------------|
| 1 | `catalog/`, `core/` | Material/fastener/finish catalogs (actuals only); stage-versioned `Dimension` triple; directional allowance layer; invariant checker with co-planar overlap; pure `solve()` with content hash |
| 2 | `parts/joinery.py`, `nodes/` | Part derivation from `(dimensions, allowances, joinery_template)`; derived fastener + tool schedules |
| 3 | `nesting/` | Guillotine packing: kerf/orientation/grain-aware; utilisation; offcut manifest; cut-order constraint |
| 4 | `drawing/` | Parametric SVG: drafting primitives + drawing types (explicit labels, stage tags, bounds-checking) |
| 5 | `document/` | HTML+SVG → PDF via headless Chromium with mandatory two-pass measured layout |
| 6 | `gates/` | Three release gates (provenance, overflow, visual) — all required, no override |
| 7 | `schema/`, `elicitation/question_graph.py` | Taxonomy (folders vs leaves); question-graph traversal with the UI contract enforced in code |
| 8 | `elicitation/` | Strict JSON LLM boundary (injectable client); intake with mandatory disambiguation; two-judge completeness gate |
| 9 | `persistence/` | Append-only answer sets; checkpoints; revisions (full re-solve + diff + changelog) |
| 10 | `build_mode/` | One step at a time with timestamped sign-offs; structural mode; vision flag generator |
| — | `webapp/` | The app: intake, question turns, the design agent's synthesize/critique/repair loop, job worker, release |
| — | `generative/` | Designs with no template: the parametric IR the model authors, its whitelisted evaluator, the compiler, and the deterministic placement and prose audits that feed repair |

### The allowance layer (the highest-value abstraction)

A finish system imposes a per-face offset between substrate and finished surface.
Tile, veneer, plaster, drywall, laminate, paint, powder coat and upholstery are
the same transform with different numbers. Three facts the code encodes:

- **Exposure is assembly, not geometry.** A face buried against another element or
  on the floor receives no allowance. The solver reads the assembly graph, never a
  bounding box.
- **Direction is not always subtractive.** Seven of the fixture's eight parts are
  cut smaller; the plinth is cut 3/8 *taller* because the slab edge occludes its
  top. `core/allowance.py` has both directions and a property test exercises each.
- **Stages are non-additive across co-planar overlaps.** `13-3/8 + 3 = 16-3/8`, but
  overall height is `16` — the slab underside skin sits co-planar with the plinth
  top and does not stack. The invariant checker handles this explicitly; a naive
  "heights must sum" check would reject the correct solve.

### Where each law lives

- **Law 1** — no arithmetic in `nodes/*` beyond calls into `core/allowance.py`
  primitives; Gate 1 (`gates/gates.py`) traces every prose dimension to a field.
- **Law 2** — `core/solver.py` imports only catalog data + pure arithmetic; a
  content hash is stable across processes (`test_fixture.py`).
- **Law 3** — `persistence/answer_set.py` exposes no setter; `append_turn` refuses
  to overwrite; only `revise()` mints a new version.
- **Law 4** — `persistence/revisions.py` always calls the full `solve()` and diffs.
- **Law 5** — `build.py` will not emit a released PDF path unless every gate passes.

### Adding a new leaf node

Add a module to the `nodes/` manifest with `NODE_ID`, `SCHEMA`, a
`build(answers) -> SolveDraft` recipe (relationships, not arithmetic), joinery
data and a question set — then register it in `schema/registry.py`. The solver,
allowance layer, invariants, nesting, drawing and document engines are **not
touched**. `floating_shelf` demonstrates this (`test_pipeline.py::
test_new_node_zero_engine_changes`).

## Tests

`run_tests.py` is a stdlib runner (no pytest). Coverage:

- `test_fixture.py` — the golden fixture: 21 scalars, 8 part types / 15 pieces,
  all three hard assertions, both allowance directions, co-planar overlap,
  determinism, input-change regeneration.
- `test_nesting.py` — plywood 1 sheet @ 88.6%, cut-order fires, cement-board waste
  panel, claimable ≥9×18 offcut.
- `test_drawings.py` — fraction formatting, no coordinate-derived default labels,
  every drawing declares its stage, no label overflow, per-stage drawings differ.
- `test_document_gates.py` — full document build + all three gates pass + every
  fixture number appears (requires Chromium; skips with a notice if absent).
- `test_pipeline.py` — question graph ordering + UI contract, LLM boundary
  validation, intake disambiguation, review queue, completeness two-judge,
  append-only persistence, revision diff, build-mode timestamps, extensibility.

## Notes on the reference material

`build_assistant_spec.json` is the normative contract (catalog shapes, laws,
dimension contract, fixture, gate definitions). One reconciliation: the brief's
prose seeds 3/4 plywood at actual `0.703`, but the fixture's numbers only
reproduce at `0.75` (`2.25 = 3 × 0.75`; util `4084.75 / 4608 = 88.6%`). The golden
test governs, so the coffee_table path uses a 3/4 structural panel of actual
`0.75`; the `0.703` birch entry is retained for other paths. This is documented in
`catalog/materials.py` and the spec file.
