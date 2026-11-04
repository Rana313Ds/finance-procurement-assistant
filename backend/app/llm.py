"""Thin provider clients with one job: return JSON matching a schema, or raise LLMError."""
from __future__ import annotations

import json
import os
from typing import Protocol

import httpx


class LLMError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 1500) -> dict: ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._http = httpx.Client(
            base_url="https://api.anthropic.com",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            timeout=45,
            transport=transport,
        )

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 1500) -> dict:
        # A forced tool call is how we get schema-shaped output from this API.
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": "respond", "description": "Return the result.", "input_schema": schema}],
            "tool_choice": {"type": "tool", "name": "respond"},
        }
        data = _post(self._http, "/v1/messages", payload)
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return block["input"]
        raise LLMError("Model returned no structured output")


class OllamaClient:
    def __init__(self, base_url: str, model: str, transport: httpx.BaseTransport | None = None):
        self.model = model
        self._http = httpx.Client(base_url=base_url, timeout=120, transport=transport)

    def complete_json(self, system: str, user: str, schema: dict, max_tokens: int = 1500) -> dict:
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": max_tokens},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        data = _post(self._http, "/api/chat", payload)
        try:
            return json.loads(data["message"]["content"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("Model returned invalid JSON") from exc


def _post(http: httpx.Client, path: str, payload: dict) -> dict:
    try:
        response = http.post(path, json=payload)
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach the LLM provider: {exc}") from exc
    if response.status_code >= 400:
        retryable = response.status_code == 429 or response.status_code >= 500
        raise LLMError(f"LLM provider returned HTTP {response.status_code}", retryable)
    return response.json()


def build_client() -> LLMClient | None:
    """Returns the configured client, or None for stub mode. Never falls back silently."""
    provider = os.getenv("LLM_PROVIDER", "stub").lower()
    if provider == "stub":
        return None
    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicClient(key, os.getenv("LLM_MODEL", "claude-sonnet-5-5"))
    if provider == "ollama":
        return OllamaClient(os.getenv("OLLAMA_URL", "http://localhost:11434"),
                            os.getenv("LLM_MODEL", "llama3.1"))
    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider}")
