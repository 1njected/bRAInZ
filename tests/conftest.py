"""Shared fixtures for bRAInZ tests."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Make backend importable
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

TESTDATA = Path(__file__).parent / "testdata"
PDF_SMALL = TESTDATA / "MS-IR-Guidebook-Final.pdf"
PDF_MEDIUM = TESTDATA / "abusing_wcf_endpoints.pdf"
PDF_LARGE = TESTDATA / "TrimarcBlogPost - Owner or Pwned.pdf"


# ---------------------------------------------------------------------------
# Temp data directory
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir(tmp_path):
    """Temporary /data directory with minimal config."""
    (tmp_path / "library").mkdir()
    (tmp_path / "embeddings").mkdir()
    (tmp_path / "skills").mkdir()
    (tmp_path / "inbox").mkdir()
    # Point config module at the temp dir
    os.environ["DATA_DIR"] = str(tmp_path)
    yield tmp_path
    # Reset so config is reloaded next test
    import config
    config._config = None


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_llm():
    """LLM provider that returns deterministic responses without network calls."""
    llm = MagicMock()
    llm.provider_name = "mock/test"
    llm.embedding_dimensions = 4  # tiny for tests

    async def _complete(system, prompt, max_tokens=2000):
        return (
            '{"category": "netsec", "tags": ["mitm", "pivoting"], '
            '"summary": "A guide to network attacks."}'
        )

    async def _complete_classify(system, prompt):
        return (
            '{"category": "netsec", "tags": ["mitm", "pivoting"], '
            '"summary": "A guide to network attacks."}'
        )

    async def _embed(texts):
        # Return tiny normalised vectors
        import math
        dim = 4
        v = [1.0 / math.sqrt(dim)] * dim
        return [v for _ in texts]

    llm.complete = _complete
    llm.complete_classify = _complete_classify
    llm.embed = _embed
    return llm


# ---------------------------------------------------------------------------
# Populated ItemIndex
# ---------------------------------------------------------------------------

@pytest.fixture()
async def index(data_dir):
    from storage.index import ItemIndex
    idx = ItemIndex(data_dir)
    await idx.load()
    return idx


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture()
def api_client(data_dir, mock_llm):
    """FastAPI TestClient with auth bypassed and mocked LLM."""
    from fastapi.testclient import TestClient
    import api as api_module

    api_module._llm = mock_llm

    from storage.index import ItemIndex
    idx = ItemIndex(data_dir)
    asyncio.get_event_loop().run_until_complete(idx.load())
    api_module._index = idx
    api_module._vector_index = None

    # Bypass auth
    os.environ["API_KEYS"] = ""

    client = TestClient(api_module.app)
    return client
