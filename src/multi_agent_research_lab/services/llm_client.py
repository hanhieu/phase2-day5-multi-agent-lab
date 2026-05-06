"""LLM client abstraction.

Production note: agents should depend on this interface instead of importing an SDK directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tenacity import retry, stop_after_attempt, wait_exponential

from multi_agent_research_lab.core.config import get_settings

logger = logging.getLogger(__name__)

# Cost per 1M tokens (USD) for gpt-4o-mini
_COST_INPUT_PER_M = 0.150
_COST_OUTPUT_PER_M = 0.600


@dataclass(frozen=True)
class LLMResponse:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class LLMClient:
    """Provider-agnostic LLM client backed by OpenAI."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment / .env")
        # Import here so the rest of the package works without the llm extra installed
        from openai import OpenAI  # noqa: PLC0415

        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Return a model completion with retry, timeout, and token logging."""

        logger.debug("LLMClient.complete model=%s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=get_settings().timeout_seconds,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else None
        output_tokens = usage.completion_tokens if usage else None

        cost: float | None = None
        if input_tokens is not None and output_tokens is not None:
            cost = (
                input_tokens * _COST_INPUT_PER_M + output_tokens * _COST_OUTPUT_PER_M
            ) / 1_000_000

        logger.debug(
            "LLMClient response tokens in=%s out=%s cost=$%.6f",
            input_tokens,
            output_tokens,
            cost or 0,
        )
        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
        )
