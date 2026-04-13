"""Ollama LLM provider — uses Ollama REST API via httpx."""

from __future__ import annotations
import httpx


class OllamaProvider:
    def __init__(self, config: dict):
        self._config = config
        self._base_url = config.get("base_url", "http://host.docker.internal:11434").rstrip("/")
        self._classification_model = config.get("classification_model", "llama3.1:8b")
        self._query_model = config.get("query_model", "llama3.1:8b")
        self._vision_model = config.get("vision_model", self._classification_model)
        self._embedding_model = config.get("embedding_model", "nomic-embed-text")
        self._embedding_dimensions = config.get("embedding_dimensions", 768)
        self._query_num_ctx = config.get("query_num_ctx", 32768)
        self._query_temperature = config.get("query_temperature", 0.1)
        self._query_think = config.get("query_think", False)

    @property
    def embedding_dimensions(self) -> int:
        return self._embedding_dimensions

    @property
    def provider_name(self) -> str:
        return f"ollama/{self._query_model}"

    async def complete(self, system: str, prompt: str, max_tokens: int = 4096) -> str:
        answer, _ = await self._complete_raw(system, prompt, max_tokens)
        return answer

    async def complete_with_thinking(self, system: str, prompt: str, max_tokens: int = 4096) -> tuple[str, str]:
        """Returns (answer, thinking). thinking is empty string if model/config doesn't support it."""
        return await self._complete_raw(system, prompt, max_tokens)

    async def _complete_raw(self, system: str, prompt: str, max_tokens: int) -> tuple[str, str]:
        payload = {
            "model": self._query_model,
            "prompt": f"{system}\n\n{prompt}",
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "num_ctx": self._query_num_ctx,
                "temperature": self._query_temperature,
            },
        }
        if self._query_think:
            payload["think"] = True
        async with httpx.AsyncClient(timeout=float(self._config.get("query_timeout", 300))) as client:
            resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["response"], data.get("thinking") or ""

    async def complete_classify(self, system: str, prompt: str) -> str:
        """Use the classification model (may differ from query model)."""
        payload = {
            "model": self._classification_model,
            "prompt": f"{system}\n\n{prompt}",
            "stream": False,
            "options": {
                "num_predict": 2048,  # thinking models consume tokens for reasoning before output
                "num_ctx": 4096,      # enough context for system + 500-word excerpt
                "temperature": 0.1,   # low temp for deterministic classification
            },
        }
        async with httpx.AsyncClient(timeout=float(self._config.get("classify_timeout", 120))) as client:
            resp = await client.post(f"{self._base_url}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json()["response"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Sanitize: replace None/empty with a space; truncate to fit model context.
        # Configurable via embed_max_chars. Default 800 chars (~200 tokens) is safe for
        # mxbai-embed-large (512 token limit). Set higher (e.g. 8000) for nomic-embed-text.
        max_chars = self._config.get("embed_max_chars", 800)
        embed_num_ctx = self._config.get("embed_num_ctx", 512)
        clean = [(t.strip()[:max_chars] if t and t.strip() else " ") for t in texts]
        async with httpx.AsyncClient(timeout=float(self._config.get("embed_timeout", 120))) as client:
            payload = {
                "model": self._embedding_model,
                "input": clean,
                "options": {"num_ctx": embed_num_ctx},
            }
            resp = await client.post(f"{self._base_url}/api/embed", json=payload)
            if not resp.is_success:
                raise RuntimeError(f"Ollama embed error {resp.status_code}: {resp.text[:200]}")
            return resp.json()["embeddings"]
