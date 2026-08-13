# Harness

The instruments that tell you whether the product works, as opposed to whether
the code runs. `run_tests.py` covers the second; these cover the first, by
driving the running app over HTTP exactly as a browser would.

They need a live server with a real model behind it:

```bash
export ANTHROPIC_API_KEY=...        # never written to a file or committed
sh harness/serve.sh out/server.log  # restarts, then prints the git build it serves
```

`serve.sh` prints the commit it is actually serving. A server started before your
last edit will happily answer requests with the old code and quietly invalidate a
run — check the build before believing a result.

## corpus.py

Twelve real descriptions, three at a time, end to end: intake, question planning,
answers, design loop, document, gates. Reports per design whether it released,
how long it took, how many pages, and — when it did not — the exact reason, so
failures are counted by kind rather than guessed at.

```bash
python3 harness/corpus.py
```

This is the reliability measure. A change to the design loop, the audit or the
prompts is not evaluated until this has run.

## sofa.py

One deliberately hard case: an upholstered frame in the style of an RH Mara,
84 x 38 x 29. It is harder than anything in the corpus — many parts, no sheet
goods, joinery throughout — and every defect it has surfaced so far was real.

```bash
SOFA_PHOTOS=/path/to/reference/shots python3 harness/sofa.py
```

Photos are optional; without them it runs from the description alone.
