"""Shared dependency loader for CLI commands."""

from __future__ import annotations
import asyncio


def run_async(coro):
    """Run a coroutine, then drain the event loop so subprocess transports can
    close cleanly before the loop shuts down (avoids 'Event loop is closed'
    noise from monolith/snapshot subprocesses)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(coro)
    finally:
        try:
            # Cancel all remaining tasks
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            # Flush any remaining callbacks (e.g. subprocess transport cleanup)
            loop.run_until_complete(asyncio.sleep(0))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


def get_deps():
    """Load config, index, and LLM provider."""
    from config import get_config, DATA_DIR
    from llm.router import create_provider
    from storage.index import ItemIndex

    config = get_config()
    llm = create_provider(config)
    index = ItemIndex(DATA_DIR)
    asyncio.run(index.load())
    return config, llm, index, DATA_DIR
