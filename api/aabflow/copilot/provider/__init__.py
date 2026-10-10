"""Hosted model access through the official OpenAI SDK Responses API (T11.4).

``Provider.respond`` sends instructions, tools and input items and returns the
completed output items. Within a turn the loop continues with
``previous_response_id`` so required items (reasoning, function calls) are preserved
by the provider; function outputs are correlated by ``call_id``. Streaming partial
JSON is never executed: only completed ``function_call`` items are dispatched.
API keys stay on the server and never enter logs.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Typed hosted-assistant failure (T9.3); core analytics stay available."""

    def __init__(self, code: str, detail: str, *, retryable: bool = False):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments: str

    def parsed(self) -> dict[str, Any]:
        return json.loads(self.arguments or "{}")


@dataclass
class ProviderResponse:
    response_id: str
    calls: list[FunctionCall]
    text: str
    latency_ms: int
    usage: dict[str, Any] = field(default_factory=dict)
    raw_types: list[str] = field(default_factory=list)


class Provider(Protocol):
    model: str

    async def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
        tool_choice: str = "auto",
    ) -> ProviderResponse: ...


def configured_model() -> str:
    return os.environ.get("AABFLOW_OPENAI_MODEL", "gpt-6.1-sol")


def key_configured() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


class OpenAIResponsesProvider:
    """Server-side Responses API loop with strict tools; hosted tools (browsing, code) are never enabled."""

    def __init__(self, model: str | None = None, *, timeout_s: float = 60.0, max_retries: int = 1):
        from openai import AsyncOpenAI

        if not key_configured():
            raise ProviderError(
                "PROVIDER_NOT_CONFIGURED", "no API key is configured for the hosted assistant"
            )
        self.model = model or configured_model()
        self.client = AsyncOpenAI(timeout=timeout_s, max_retries=max_retries)

    async def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        previous_response_id: str | None,
        tool_choice: str = "auto",
    ) -> ProviderResponse:
        import openai

        t0 = time.perf_counter()
        try:
            resp = await self.client.responses.create(
                model=self.model,
                instructions=instructions,
                input=input_items,
                tools=tools,
                tool_choice=tool_choice,
                previous_response_id=previous_response_id,
                parallel_tool_calls=True,
            )
        except openai.APITimeoutError as exc:
            raise ProviderError(
                "PROVIDER_TIMEOUT", "the hosted model did not respond in time", retryable=True
            ) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(
                "PROVIDER_UNAVAILABLE", "cannot reach the hosted model", retryable=True
            ) from exc
        except openai.RateLimitError as exc:
            raise ProviderError(
                "PROVIDER_RATE_LIMITED", "the hosted model is rate limited", retryable=True
            ) from exc
        except openai.AuthenticationError as exc:
            raise ProviderError(
                "PROVIDER_AUTH", "the hosted model rejected the configured credentials"
            ) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(
                "PROVIDER_ERROR",
                f"hosted model error (HTTP {exc.status_code})",
                retryable=exc.status_code >= 500,
            ) from exc
        calls = [
            FunctionCall(call_id=i.call_id, name=i.name, arguments=i.arguments)
            for i in resp.output
            if getattr(i, "type", None) == "function_call"
        ]
        usage = {}
        if getattr(resp, "usage", None) is not None:
            try:
                usage = resp.usage.model_dump()
            except Exception:  # noqa: BLE001
                usage = {}
        return ProviderResponse(
            response_id=resp.id,
            calls=calls,
            text=resp.output_text or "",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            usage={
                k: usage.get(k)
                for k in ("input_tokens", "output_tokens", "total_tokens")
                if k in usage
            },
            raw_types=[getattr(i, "type", "?") for i in resp.output],
        )


def default_provider() -> Provider:
    return OpenAIResponsesProvider()
