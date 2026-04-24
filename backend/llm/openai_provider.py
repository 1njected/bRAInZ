"""OpenAI / OpenAI-compatible LLM provider."""

from __future__ import annotations
import os


class OpenAIProvider:
    def __init__(self, config: dict, mode: str = "openai"):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI provider requires: pip install 'brainz[openai]'"
            )
        self._classification_model = config.get("classification_model", "gpt-4o-mini")
        self._query_model = config.get("query_model", "gpt-4o")
        self._vision_model = config.get("vision_model", self._classification_model)
        self._embedding_model = config.get("embedding_model", "text-embedding-3-small")
        self._embedding_dimensions = config.get("embedding_dimensions", 1536)
        self._mode = mode
        self._embed_base_url = None

        kwargs: dict = {}
        if mode == "openai_compatible":
            kwargs["base_url"] = config.get("base_url", "http://localhost:1234/v1")
            kwargs["api_key"] = config.get("api_key", "lm-studio")
        elif mode == "ollama_cloud":
            kwargs["base_url"] = config.get("base_url", "https://ollama.com/v1")
            kwargs["api_key"] = os.environ.get("OLLAMA_CLOUD_API_KEY", config.get("api_key", ""))
            # Native Ollama /api/embed endpoint for embeddings (cloud doesn't support /v1/embeddings)
            self._embed_base_url = config.get("embed_base_url", "http://host.docker.internal:11434")
        else:
            kwargs["api_key"] = os.environ.get("OPENAI_API_KEY")

        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(**kwargs)

    @property
    def embedding_dimensions(self) -> int:
        return self._embedding_dimensions

    @property
    def provider_name(self) -> str:
        return f"{self._mode}/{self._query_model}"

    async def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        resp = await self._client.chat.completions.create(
            model=self._query_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content

    async def complete_classify(self, system: str, prompt: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._classification_model,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return resp.choices[0].message.content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_base_url:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._embed_base_url}/api/embed",
                    json={"model": self._embedding_model, "input": texts},
                    timeout=120,
                )
                resp.raise_for_status()
                return resp.json()["embeddings"]

        resp = await self._client.embeddings.create(
            model=self._embedding_model,
            input=texts,
        )
        return [item.embedding for item in resp.data]
