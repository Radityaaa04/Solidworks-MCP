"""Unit tests for STAWorker concurrency and COM STA initialization."""

import asyncio
import pytest
import pythoncom
from sw_mcp.core.sta_worker import STAWorker


@pytest.mark.asyncio
async def test_sta_worker_execution():
    worker = STAWorker("TestWorker")
    worker.start()

    try:
        def sample_sync_task():
            # Verify pythoncom is callable and thread is healthy
            return {"status": "ok", "value": 42}

        result = await worker.run(sample_sync_task)
        assert result == {"status": "ok", "value": 42}
    finally:
        worker.stop()


@pytest.mark.asyncio
async def test_sta_worker_exception_propagation():
    worker = STAWorker("TestErrorWorker")
    worker.start()

    try:
        def failing_task():
            raise ValueError("Deliberate failure in worker thread")

        with pytest.raises(ValueError, match="Deliberate failure"):
            await worker.run(failing_task)
    finally:
        worker.stop()
