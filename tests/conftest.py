"""Shared fixtures for bRAInZ tests."""

import asyncio
import os
import shutil
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

# Make backend importable
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

TESTDATA = Path(__file__).parent / "testdata"
PDF_SMALL = TESTDATA / "MS-IR-Guidebook-Final.pdf"
PDF_MEDIUM = TESTDATA / "abusing_wcf_endpoints.pdf"
PDF_LARGE = TESTDATA / "TrimarcBlogPost - Owner or Pwned.pdf"

# Base directory for test data — kept inside the tests/ tree so it maps
# cleanly to the Docker volume mount (./data:/tests/data).
_TESTS_DATA_BASE = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Session-level cleanup: wipe all test data before the run starts
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _clean_test_data_dir():
    if _TESTS_DATA_BASE.exists():
        shutil.rmtree(_TESTS_DATA_BASE, ignore_errors=True)
    _TESTS_DATA_BASE.mkdir(parents=True, exist_ok=True)
    yield
    if _TESTS_DATA_BASE.exists():
        shutil.rmtree(_TESTS_DATA_BASE, ignore_errors=True)


# ---------------------------------------------------------------------------
# Temp data directory
# ---------------------------------------------------------------------------

@pytest.fixture()
def data_dir():
    """Isolated data directory under tests/data/<uuid>/."""
    run_dir = _TESTS_DATA_BASE / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    (run_dir / "library").mkdir()
    (run_dir / "embeddings").mkdir()
    (run_dir / "skills").mkdir()
    (run_dir / "inbox").mkdir()
    # Point config module at the temp dir
    os.environ["DATA_DIR"] = str(run_dir)
    import config
    config._config = None
    config._taxonomy = None
    config._taxonomy_mtime = None
    yield run_dir
    # Cleanup and reset so config is reloaded next test
    shutil.rmtree(run_dir, ignore_errors=True)
    import config
    config._config = None
    config._taxonomy = None
    config._taxonomy_mtime = None


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

    async def _complete_with_thinking(system, prompt, max_tokens=4096):
        return (
            '{"category": "netsec", "tags": ["mitm", "pivoting"], '
            '"summary": "A guide to network attacks."}',
            "",
        )

    async def _embed(texts):
        # Return tiny normalised vectors
        import math
        dim = 4
        v = [1.0 / math.sqrt(dim)] * dim
        return [v for _ in texts]

    llm.complete = _complete
    llm.complete_classify = _complete_classify
    llm.complete_with_thinking = _complete_with_thinking
    llm.embed = _embed
    return llm


# ---------------------------------------------------------------------------
# Populated ItemIndex
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture()
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
    api_module.DATA_DIR = data_dir

    from storage.index import ItemIndex
    idx = ItemIndex(data_dir)
    asyncio.get_event_loop().run_until_complete(idx.load())
    api_module._index = idx
    api_module._vector_index = None

    # Bypass auth
    os.environ["API_KEYS"] = ""

    client = TestClient(api_module.app)
    return client
