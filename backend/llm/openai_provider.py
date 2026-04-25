"""OpenAI / OpenAI-compatible LLM provider.

Supports a `preset` key in config to load known-provider defaults.
Any field in the config section overrides the preset value.

Built-in presets: openai, mistral, ollama_cloud
"""

from __future__ import annotations
import logging
import time
import os

_log = logging.getLogger(__name__)

_PRESETS: dict[str, dict] = {
    "openai": {
        "base_url": None,  # use SDK default
        "api_key_env": "OPENAI_API_KEY",
        "classification_model": "gpt-4o-mini",
        "query_model": "gpt-4o",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimensions": 1536,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "classification_model": "mistral-small-latest",
        "query_model": "mistral-large-latest",
        "embedding_model": "mistral-embed",
        "embedding_dimensions": 1024,
    },
    "ollama_cloud": {
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_CLOUD_API_KEY",
        "classification_model": "gemma3:12b",
        "query_model": "gemma3:27b",
        # Ollama Cloud has no /v1/embeddings — fall back to a local Ollama instance
        "embed_base_url": "http://host.docker.internal:11434",
        "embedding_model": "mxbai-embed-large",
        "embedding_dimensions": 1024,
    },
}


class OpenAIProvider:
    def __init__(self, config: dict):
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError(
                "OpenAI provider requires: pip install openai"
            )

        preset_name = config.get("preset", "openai")
        preset = dict(_PRESETS.get(preset_name, _PRESETS["openai"]))

        self._classification_model = config.get("classification_model", preset.get("classification_model", "gpt-4o-mini"))
        self._query_model = config.get("query_model", preset.get("query_model", "gpt-4o"))
        self._vision_model = config.get("vision_model", self._classification_model)
        self._embedding_model = config.get("embedding_model", preset.get("embedding_model", "text-embedding-3-small"))
        self._embedding_dimensions = config.get("embedding_dimensions", preset.get("embedding_dimensions", 1536))
        self._preset = preset_name

        api_key_env = preset.get("api_key_env", "OPENAI_API_KEY")
        api_key = os.environ.get(api_key_env, config.get("api_key", ""))
        base_url = config.get("base_url", preset.get("base_url"))

        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

        self._client = AsyncOpenAI(**kwargs)

        # Some presets (ollama_cloud) can't use /v1/embeddings and need a separate endpoint
        self._embed_base_url: str | None = config.get("embed_base_url", preset.get("embed_base_url"))

    @property
    def embedding_dimensions(self) -> int:
        return self._embedding_dimensions

    @property
    def provider_name(self) -> str:
        return f"{self._preset}/{self._query_model}"

    async def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._query_model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        _log.info("llm complete %s in=%d out=%d %.2fs",
                  self._query_model, resp.usage.prompt_tokens, resp.usage.completion_tokens, time.perf_counter() - t0)
        return resp.choices[0].message.content

    async def complete_classify(self, system: str, prompt: str) -> str:
        t0 = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._classification_model,
            max_tokens=500,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        _log.info("llm classify %s in=%d out=%d %.2fs",
                  self._classification_model, resp.usage.prompt_tokens, resp.usage.completion_tokens, time.perf_counter() - t0)
        return resp.choices[0].message.content

    async def embed(self, texts: list[str]) -> list[list[float]]:
        t0 = time.perf_counter()
        if self._embed_base_url:
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._embed_base_url}/api/embed",
                    json={"model": self._embedding_model, "input": texts},
                    timeout=120,
                )
                resp.raise_for_status()
            _log.info("llm embed %s n=%d %.2fs", self._embedding_model, len(texts), time.perf_counter() - t0)
            return resp.json()["embeddings"]

        resp = await self._client.embeddings.create(
            model=self._embedding_model,
            input=texts,
        )
        _log.info("llm embed %s n=%d %.2fs", self._embedding_model, len(texts), time.perf_counter() - t0)
        return [item.embedding for item in resp.data]
