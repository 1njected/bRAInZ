"""LLM provider factory + unified Protocol interface."""

from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    async def complete(self, system: str, prompt: str, max_tokens: int = 2000) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def embedding_dimensions(self) -> int: ...
    @property
    def provider_name(self) -> str: ...


def create_provider(config: dict) -> LLMProvider:
    provider = config["llm"]["provider"]
    pc = config["llm"].get(provider, {})

    if provider == "ollama":
        from llm.ollama import OllamaProvider
        return OllamaProvider(pc)
    elif provider == "anthropic":
        from llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(pc)
    elif provider in ("openai", "openai_compatible", "ollama_cloud"):
        from llm.openai_provider import OpenAIProvider
        return OpenAIProvider(pc, provider)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose: ollama, ollama_cloud, anthropic, openai, openai_compatible")
