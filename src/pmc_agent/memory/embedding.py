from __future__ import annotations

import json
import os
from typing import Protocol
import urllib.request

from pmc_agent.env import load_env_file


class EmbeddingClient(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class OpenAIEmbeddingClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        load_env_file(override=False)
        self.model = model or os.getenv("PMC_AGENT_MEMORY_EMBEDDING_MODEL") or os.getenv("OPENAI_EMBEDDING_MODEL") or "text-embedding-3-large"
        self.dimensions = _optional_int(os.getenv("PMC_AGENT_MEMORY_EMBEDDING_DIMENSIONS"))
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout or float(os.getenv("PMC_AGENT_HTTP_TIMEOUT", "30"))
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIEmbeddingClient.")

    def embed(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text}
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            raw = json.loads(response.read().decode("utf-8"))
        data = raw.get("data") or []
        if not data or not isinstance(data[0].get("embedding"), list):
            raise RuntimeError("Embedding response did not include data[0].embedding.")
        return [float(item) for item in data[0]["embedding"]]


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None
