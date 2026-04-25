"""Anthropic LLM provider — Claude for completions, Voyage for embeddings."""

from __future__ import annotations
import logging
import time
import os

_log = logging.getLogger(__name__)


class AnthropicProvider:
    def __init__(self, config: dict):
        try:
            import anthropic as _anthropic
        except ImportError:
            raise ImportError(
                "Anthropic provider requires: pip install 'brainz[anthropic]'"
            )
        self._classification_model = config.get("classification_model", "claude-haiku-4-5-20251001")
        self._query_model = config.get("query_model", "claude-sonnet-4-6")
        self._vision_model = config.get("vision_model", self._classification_model)
        self._embedding_model = config.get("embedding_model", "voyage-3")
        self._embedding_dimensions = config.get("embedding_dimensions", 1024)

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)

        # Voyageai is initialised lazily to give a clear error at call time
        self._voyage = None

    def _get_voyage(self):
        if self._voyage is not None:
            return self._voyage
        try:
            import voyageai
        except ImportError:
            raise ImportError(
                "Voyage embeddings require: pip install 'brainz[anthropic]'"
            )
        self._voyage = voyageai.Client(api_key=os.environ.get("VOYAGE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        return self._voyage

    @property
    def embedding_dimensions(self) -> int:
        return self._embedding_dimensions

    @property
    def provider_name(self) -> str:
        return f"anthropic/{self._query_model}"

    async def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        t0 = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._query_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        _log.info("llm complete %s in=%d out=%d %.2fs",
                  self._query_model, msg.usage.input_tokens, msg.usage.output_tokens, time.perf_counter() - t0)
        return msg.content[0].text

    async def complete_classify(self, system: str, prompt: str) -> str:
        t0 = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._classification_model,
            max_tokens=500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        _log.info("llm classify %s in=%d out=%d %.2fs",
                  self._classification_model, msg.usage.input_tokens, msg.usage.output_tokens, time.perf_counter() - t0)
        return msg.content[0].text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        voyage = self._get_voyage()
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: voyage.embed(texts, model=self._embedding_model),
        )
        _log.info("llm embed %s n=%d %.2fs", self._embedding_model, len(texts), time.perf_counter() - t0)
        return result.embeddings
