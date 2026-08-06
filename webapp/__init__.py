"""Mobile web app for the Build Assistant — the conversational front door.

Landing -> New / Resume -> intake -> inspiration photos -> guided multiple-choice
turns -> generate -> PDF. Backed by SQLite (projects library + append-only answer
versions + photo store) and driven by the deterministic engine in
``build_assistant``. AI is confined to the injectable boundary (Law 1).
"""
