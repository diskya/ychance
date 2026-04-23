from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Protocol

from audit import canonicalize


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    raw_json: dict[str, Any]


class LLMClient(Protocol):
    def complete(self, *, model: str, prompt: str, params: dict[str, Any]) -> LLMResponse:
        ...


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def params_hash(*, model: str, params: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize({"model": model, "params": params})).hexdigest()


class QwenOpenAICompatibleClient:
    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        api_base = os.environ.get("OPENAI_API_BASE")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required")
        if not api_base:
            raise RuntimeError("OPENAI_API_BASE is required")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=api_base)

    def complete(self, *, model: str, prompt: str, params: dict[str, Any]) -> LLMResponse:
        request: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        if "max_tokens" in params:
            request["max_tokens"] = params["max_tokens"]
        response = self._client.chat.completions.create(**request)
        dumped = response.model_dump()
        text = _extract_text(dumped)
        usage = dumped.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_json=dumped,
        )


class StubLLMClient:
    def __init__(self, responses: dict[tuple[str, str, str], LLMResponse]) -> None:
        self._responses = dict(responses)

    def complete(self, *, model: str, prompt: str, params: dict[str, Any]) -> LLMResponse:
        key = (model, prompt_hash(prompt), params_hash(model=model, params=params))
        try:
            return self._responses[key]
        except KeyError as exc:
            raise AssertionError("unexpected network call") from exc


def _extract_text(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    return "" if content is None else str(content)
