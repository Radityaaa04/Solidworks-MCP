"""Single-Threaded Apartment (STA) COM Worker for SolidWorks.

Ensures all SolidWorks COM API calls occur sequentially on a dedicated,
isolated Windows STA thread with Windows Message Pumping (pythoncom.PumpWaitingMessages()).

Zero COM Dispatch pointers cross the STA boundary to the asyncio main thread;
only serialized DTOs/primitives are returned.
"""

import asyncio
import logging
import queue
import sys
import threading
import time
from typing import Any, Callable, Tuple

import pythoncom

logger = logging.getLogger("sw_mcp.sta_worker")

# HRESULT constants for COM server busy / retry
RPC_E_CALL_REJECTED = -2147418111       # 0x80010001
RPC_E_SERVERCALL_RETRYLATER = -2147417846 # 0x8001010A


class STAWorker:
    """Dedicated STA worker thread ensuring thread-safe SolidWorks COM execution."""

    def __init__(self, name: str = "SolidWorks-STA-Worker"):
        self.name = name
        self._task_queue: queue.Queue[Tuple[Callable[[], Any], asyncio.Future, asyncio.AbstractEventLoop, bool] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> threading.Thread:
        """Start the STA background thread."""
        with self._lock:
            if self._running:
                return self._thread
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Cannot start new STA worker: previous worker thread is still alive/stopping.")
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, name=self.name, daemon=True)
            self._thread.start()
            logger.info("STA Worker thread '%s' started.", self.name)
            return self._thread

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the STA background thread cleanly."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._task_queue.put(None)  # Sentinel to break loop
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=timeout)
            if self._thread and not self._thread.is_alive():
                self._thread = None
                logger.info("STA Worker thread stopped.")
            else:
                logger.warning("STA Worker thread did not stop within timeout; retaining thread reference.")

    def _run_loop(self) -> None:
        """Worker thread entry point with COM STA initialization and message pumping."""
        # 1. Initialize thread as Single-Threaded Apartment (STA)
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        logger.debug("STA apartment initialized for worker thread.")

        try:
            while self._running:
                # 2. Pump pending Windows messages to prevent IPC deadlocks
                pythoncom.PumpWaitingMessages()

                try:
                    # Non-blocking poll with short timeout so PumpWaitingMessages runs regularly
                    item = self._task_queue.get(timeout=0.05)
                except queue.Empty:
                    continue

                if item is None:
                    # Sentinel received, balance queue accounting and exit
                    self._task_queue.task_done()
                    break

                fn, future, loop, idempotent = item

                # Skip job if already cancelled before execution began
                if future.cancelled():
                    self._task_queue.task_done()
                    continue

                try:
                    # Execute function with COM retry on Server Busy ONLY if idempotent
                    result = self._execute_with_retry(fn, retry=idempotent)
                    if not future.cancelled():
                        loop.call_soon_threadsafe(future.set_result, result)
                except Exception as exc:
                    logger.error("Error executing task on STA worker: %s", exc, exc_info=True)
                    if not future.cancelled():
                        loop.call_soon_threadsafe(future.set_exception, exc)
                finally:
                    self._task_queue.task_done()
                    pythoncom.PumpWaitingMessages()

        finally:
            # Drain any remaining pending futures so callers never hang indefinitely
            while not self._task_queue.empty():
                try:
                    item = self._task_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    if item is not None:
                        _, rem_future, rem_loop, _ = item
                        if not rem_future.done() and not rem_future.cancelled():
                            rem_loop.call_soon_threadsafe(
                                rem_future.set_exception,
                                RuntimeError("STAWorker stopped before task could be executed")
                            )
                finally:
                    self._task_queue.task_done()

            pythoncom.CoUninitialize()
            logger.debug("STA apartment uninitialized for worker thread.")

    def _execute_with_retry(
        self,
        fn: Callable[[], Any],
        max_retries: int = 5,
        base_delay: float = 0.2,
        retry: bool = True,
    ) -> Any:
        """
        Execute callable on the STA thread.
        If retry=True, retries with exponential backoff on COM Server Busy errors.
        If retry=False, executes once and raises immediately to prevent duplicate mutations.
        """
        if not retry:
            return fn()

        for attempt in range(max_retries):
            try:
                return fn()
            except pythoncom.com_error as err:
                hresult = err.hresult if hasattr(err, "hresult") else (err.args[0] if err.args else None)
                is_busy = (
                    hresult in (RPC_E_SERVERCALL_RETRYLATER, RPC_E_CALL_REJECTED)
                    or (hresult is not None and (hresult & 0xFFFFFFFF) in (0x8001010A, 0x80010001))
                )
                if is_busy and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "SolidWorks COM server busy (0x%08X), retrying idempotent read operation in %.2fs (attempt %d/%d)...",
                        (hresult & 0xFFFFFFFF) if hresult else 0,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(delay)
                    pythoncom.PumpWaitingMessages()
                else:
                    raise

    async def run(self, fn: Callable[[], Any], idempotent: bool = False) -> Any:
        """
        Submit a synchronous callable to be executed on the STA worker thread.
        Returns the result asynchronously via an asyncio.Future.

        idempotent: Set True for read-only / query operations that can be safely retried
                    on COM Server Busy without duplicating side effects.
        """
        if not self._running:
            self.start()

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._task_queue.put((fn, future, loop, idempotent))
        return await future


# Global singleton instance
_global_worker: STAWorker | None = None


def get_sta_worker() -> STAWorker:
    """Get or create the global STA worker instance."""
    global _global_worker
    if _global_worker is None:
        _global_worker = STAWorker()
        _global_worker.start()
    return _global_worker
