#!/usr/bin/env python3
"""Minimal stdlib test runner (no pytest dependency).

Discovers ``test_*`` functions in ``tests/test_*.py`` modules, runs them, and
reports pass/fail. Exit code is non-zero on any failure.
"""

from __future__ import annotations

import importlib
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def discover() -> list[str]:
    tdir = os.path.join(ROOT, "tests")
    return sorted(
        f"tests.{n[:-3]}" for n in os.listdir(tdir)
        if n.startswith("test_") and n.endswith(".py")
    )


def main(argv: list[str]) -> int:
    only = argv[1] if len(argv) > 1 else None
    modules = discover()
    passed = failed = 0
    failures: list[str] = []
    for modname in modules:
        if only and only not in modname:
            continue
        mod = importlib.import_module(modname)
        fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_") and callable(getattr(mod, n))]
        print(f"\n== {modname} ({len(fns)} tests) ==")
        for fn in fns:
            try:
                fn()
                passed += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failures.append(f"{modname}.{fn.__name__}: {exc}")
                print(f"  [FAIL] {fn.__name__}: {exc}")
                traceback.print_exc()
    print(f"\n{'='*50}\n{passed} passed, {failed} failed")
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
