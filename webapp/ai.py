"""AI wiring for the app — a thin adapter over the engine's LLM boundary.

The model only classifies intent, phrases questions and decomposes free text
(Law 1). It never produces a dimension. When ``ANTHROPIC_API_KEY`` is set the app
uses a live Claude client through the same strict-JSON boundary; otherwise it uses
the deterministic keyword classifier so the app runs with no external calls. The
caller cannot tell the difference — both return schema-validated JSON.
"""

from __future__ import annotations

import json
import os
import urllib.request

from build_assistant.elicitation.llm import LLMBoundary, DeterministicStubClient

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")


class AnthropicClient:
    """Live Claude client. Activated only when ANTHROPIC_API_KEY is present."""

    def __init__(self, api_key: str, registry):
        self.api_key = api_key
        self.base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        self.registry = registry
        self._fallback = DeterministicStubClient(registry)

    def complete(self, prompt: str, purpose: str) -> str:
        system = (
            "You are the intent classifier for a deterministic build system. Return "
            "ONLY JSON. You never compute or invent any dimension or number — you only "
            "classify intent and echo values the user literally typed. "
            f"Known buildable nodes: {self.registry.all_leaves()}."
        )
        body = json.dumps({
            "model": ANTHROPIC_MODEL, "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            f"{self.base}/v1/messages", data=body, method="POST",
            headers={"content-type": "application/json", "x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            text = "".join(b.get("text", "") for b in data.get("content", []))
            return _extract_json(text)
        except Exception:
            # fail safe to the deterministic classifier rather than break the flow
            return self._fallback.complete(prompt, purpose)


def _extract_json(text: str) -> str:
    a, b = text.find("{"), text.rfind("}")
    return text[a:b + 1] if a >= 0 and b > a else text


def get_boundary(registry) -> tuple[LLMBoundary, str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return LLMBoundary(AnthropicClient(key, registry)), "live Claude"
    return LLMBoundary(DeterministicStubClient(registry)), "heuristic"
