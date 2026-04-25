"""Google AI (Gemini) provider — Gemini for completions, text-embedding for embeddings."""

from __future__ import annotations
import os


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
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=self._query_model,
                contents=f"{system}\n\n{prompt}",
                config={"max_output_tokens": max_tokens},
            ),
        )
        return result.text

    async def complete_classify(self, system: str, prompt: str) -> str:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._client.models.generate_content(
                model=self._classification_model,
                contents=f"{system}\n\n{prompt}",
                config={"max_output_tokens": 500},
            ),
        )
        return result.text

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import asyncio
        loop = asyncio.get_event_loop()
        results = []
        for text in texts:
            result = await loop.run_in_executor(
                None,
                lambda t=text: self._client.models.embed_content(
                    model=self._embedding_model,
                    contents=t,
                ),
            )
            results.append(result.embeddings[0].values)
        return results
