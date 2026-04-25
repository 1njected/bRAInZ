"""Google AI (Gemini) provider — Gemini for completions, text-embedding for embeddings."""

from __future__ import annotations
import logging
import time
import os

_log = logging.getLogger(__name__)


class GoogleProvider:
    def __init__(self, config: dict):
        try:
            from google import genai as _genai
        except ImportError:
            raise ImportError(
                "Google AI provider requires: pip install google-genai"
            )
        self._classification_model = config.get("classification_model", "gemini-2.0-flash")
        self._query_model = config.get("query_model", "gemini-2.5-pro-preview-05-06")
        self._vision_model = config.get("vision_model", self._classification_model)
        self._embedding_model = config.get("embedding_model", "text-embedding-004")
        self._embedding_dimensions = config.get("embedding_dimensions", 768)

        api_key = os.environ.get("GOOGLE_AI_API_KEY")
        self._client = _genai.Client(api_key=api_key)

    @property
    def embedding_dimensions(self) -> int:
        return self._embedding_dimensions

    @property
    def provider_name(self) -> str:
        return f"google/{self._query_model}"

    async def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        import asyncio
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._client.models.generate_content(
                    model=self._query_model,
                    contents=f"{system}\n\n{prompt}",
                    config={"max_output_tokens": max_tokens},
                ),
            )
        except Exception as e:
            _log.error("llm complete %s error: %s", self._query_model, e)
            raise
        u = result.usage_metadata
        _log.info("llm complete %s in=%d out=%d %.2fs",
                  self._query_model, u.prompt_token_count, u.candidates_token_count, time.perf_counter() - t0)
        return result.text

    async def complete_classify(self, system: str, prompt: str) -> str:
        import asyncio
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: self._client.models.generate_content(
                    model=self._classification_model,
                    contents=f"{system}\n\n{prompt}",
                    config={"max_output_tokens": 500},
                ),
            )
        except Exception as e:
            _log.error("llm classify %s error: %s", self._classification_model, e)
            raise
        u = result.usage_metadata
        _log.info("llm classify %s in=%d out=%d %.2fs",
                  self._classification_model, u.prompt_token_count, u.candidates_token_count, time.perf_counter() - t0)
        return result.text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        t0 = time.perf_counter()
        loop = asyncio.get_event_loop()
        results = []
        try:
            for text in texts:
                result = await loop.run_in_executor(
                    None,
                    lambda t=text: self._client.models.embed_content(
                        model=self._embedding_model,
                        contents=t,
                    ),
                )
                results.append(result.embeddings[0].values)
        except Exception as e:
            _log.error("llm embed %s error: %s", self._embedding_model, e)
            raise
        _log.info("llm embed %s n=%d %.2fs", self._embedding_model, len(texts), time.perf_counter() - t0)
        return results
