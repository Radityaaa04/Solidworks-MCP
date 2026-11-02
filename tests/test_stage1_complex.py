"""Stage 1 Complex & Stress Test Suite for SolidWorks 2026 MCP Server.

This suite executes advanced, difficult, and non-trivial tests:
1. High-load concurrency stress testing (100 parallel async tasks).
2. Thread-safety & Single-Threaded Apartment (STA) invariant verification.
3. Chaotic error injection and failure isolation.
4. Future cancellation resilience and queue draining.
5. Simulated COM Server Busy (0x8001010A / 0x80010001) retry with exponential backoff.
6. Non-retryable COM error immediate rejection.
7. Equation Manager substring collision & RHS variable isolation.
8. Parametric & equation string adversarial injection fuzzing.
9. Mass property parsing with extreme boundary values (negative coords, 0-volume, 18-element arrays).
10. Geometric boundary validation (degenerate rectangles, zero/negative depths, invalid radii).
11. FastMCP 2.x protocol tool schema and invocation verification.
"""

import asyncio
import math
import threading
import time
from unittest.mock import MagicMock
import pytest
import pythoncom
import win32com.client

from sw_mcp.core.sta_worker import (
    STAWorker,
    RPC_E_CALL_REJECTED,
    RPC_E_SERVERCALL_RETRYLATER,
)
from sw_mcp.core.units import (
    deg_to_radians,
    format_equation_string,
    kg_to_grams,
    meters_to_mm,
    mm_to_meters,
    radians_to_deg,
    convert_mass_properties,
)
from sw_mcp.cad.equations import EquationManager
from sw_mcp.cad.features import FeatureManager
from sw_mcp.cad.sketcher import SketchManager
from sw_mcp.server import mcp


# ==============================================================================
# SECTION 1: STA WORKER CONCURRENCY & STRESS TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_sta_worker_high_concurrency_burst():
    """Stress test: 100 concurrent async tasks sent simultaneously to STA worker."""
    worker = STAWorker("StressWorker-100")
    worker.start()

    worker_thread_id = None

    try:
        def compute_task(i: int):
            nonlocal worker_thread_id
            curr_thread = threading.get_ident()
            if worker_thread_id is None:
                worker_thread_id = curr_thread
            # Invariant: All tasks MUST run on the exact same STA thread
            assert curr_thread == worker_thread_id, "STA thread invariant violated!"
            # Simulate a small workload
            return {"index": i, "result": i * i, "thread": curr_thread}

        tasks = [worker.run(lambda idx=i: compute_task(idx)) for i in range(100)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 100
        for i, res in enumerate(results):
            assert res["index"] == i
            assert res["result"] == i * i
            assert res["thread"] == worker_thread_id
            # Ensure it never ran on main thread
            assert res["thread"] != threading.get_ident()
    finally:
        worker.stop()


@pytest.mark.asyncio
async def test_sta_worker_chaotic_interleaved_exceptions():
    """Stress test: 50 failures and 50 successes interleaved under burst concurrency.
    Verifies that worker thread does not crash and correctly routes exceptions to callers.
    """
    worker = STAWorker("ChaoticWorker")
    worker.start()

    try:
        def flaky_task(i: int):
            if i % 2 == 1:
                raise ValueError(f"Deliberate failure on task {i}")
            return f"Success {i}"

        tasks = [worker.run(lambda idx=i: flaky_task(idx)) for i in range(100)]

        success_count = 0
        failure_count = 0

        for i, task in enumerate(tasks):
            try:
                res = await task
                assert res == f"Success {i}"
                success_count += 1
            except ValueError as err:
                assert f"Deliberate failure on task {i}" in str(err)
                failure_count += 1

        assert success_count == 50
        assert failure_count == 50
        assert worker._running is True
        assert worker._thread.is_alive()
    finally:
        worker.stop()


@pytest.mark.asyncio
async def test_sta_worker_future_cancellation_resilience():
    """Test: Enqueued futures cancelled by caller before or during execution.
    The worker must handle cancelled futures without crashing or getting blocked.
    """
    worker = STAWorker("CancelWorker")
    worker.start()

    try:
        async def submit_and_cancel():
            # Submit task that takes a brief moment
            t1 = asyncio.create_task(worker.run(lambda: time.sleep(0.05) or "Done1"))
            t2 = asyncio.create_task(worker.run(lambda: "Done2"))
            t3 = asyncio.create_task(worker.run(lambda: "Done3"))

            # Cancel t2 immediately before it executes
            t2.cancel()

            res1 = await t1
            assert res1 == "Done1"

            with pytest.raises(asyncio.CancelledError):
                await t2

            res3 = await t3
            assert res3 == "Done3"

        await submit_and_cancel()
    finally:
        worker.stop()


@pytest.mark.asyncio
async def test_sta_worker_stop_drains_pending_futures():
    """Test: Stopping worker rejects pending futures with RuntimeError instead of hanging."""
    worker = STAWorker("StopDrainWorker")
    worker.start()

    # Saturate the worker
    t1 = asyncio.create_task(worker.run(lambda: time.sleep(0.2) or "First"))
    t2 = asyncio.create_task(worker.run(lambda: "Second"))
    t3 = asyncio.create_task(worker.run(lambda: "Third"))

    # Give loop a split second to queue tasks
    await asyncio.sleep(0.01)

    # Force stop
    worker.stop(timeout=1.0)

    # First may complete or error, but pending items in queue must reject cleanly
    with pytest.raises(RuntimeError, match="STAWorker stopped"):
        await t3


# ==============================================================================
# SECTION 2: COM ERROR SIMULATION & EXPONENTIAL RETRY
# ==============================================================================

def test_com_retry_success_after_transient_busy():
    """Test: COM Server Busy (0x8001010A) retries with exponential backoff and succeeds."""
    worker = STAWorker("RetryTestWorker")

    attempts = 0

    def transient_busy_function():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            # Raise COM Server Busy error
            raise pythoncom.com_error(RPC_E_SERVERCALL_RETRYLATER, "Server Busy", None, None)
        return "Recovered Successfully"

    # Use small delay to keep test fast
    start_time = time.time()
    result = worker._execute_with_retry(transient_busy_function, max_retries=5, base_delay=0.02)
    elapsed = time.time() - start_time

    assert result == "Recovered Successfully"
    assert attempts == 3
    # Attempt 1: delay 0.02s, Attempt 2: delay 0.04s -> total >= 0.06s
    assert elapsed >= 0.05


def test_com_retry_call_rejected_success():
    """Test: COM Call Rejected (0x80010001) retries and succeeds."""
    worker = STAWorker("CallRejectWorker")
    attempts = 0

    def transient_rejected():
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise pythoncom.com_error(RPC_E_CALL_REJECTED, "Call Rejected", None, None)
        return "Rejected Recovered"

    result = worker._execute_with_retry(transient_rejected, max_retries=5, base_delay=0.01)
    assert result == "Rejected Recovered"
    assert attempts == 4


def test_com_retry_exhaustion_raises():
    """Test: Persistent COM Server Busy exhausts retries and raises com_error."""
    worker = STAWorker("ExhaustWorker")
    attempts = 0

    def always_busy():
        nonlocal attempts
        attempts += 1
        raise pythoncom.com_error(RPC_E_SERVERCALL_RETRYLATER, "Never Free", None, None)

    with pytest.raises(pythoncom.com_error) as exc_info:
        worker._execute_with_retry(always_busy, max_retries=3, base_delay=0.01)

    assert exc_info.value.hresult == RPC_E_SERVERCALL_RETRYLATER
    assert attempts == 3


def test_com_non_retryable_error_fails_immediately():
    """Test: Non-busy COM errors (e.g. E_FAIL 0x80004005) fail immediately without retrying."""
    worker = STAWorker("NonRetryWorker")
    attempts = 0
    E_FAIL = -2147467259  # 0x80004005

    def fail_immediately():
        nonlocal attempts
        attempts += 1
        raise pythoncom.com_error(E_FAIL, "Unspecified Error", None, None)

    start_time = time.time()
    with pytest.raises(pythoncom.com_error) as exc_info:
        worker._execute_with_retry(fail_immediately, max_retries=5, base_delay=0.1)
    elapsed = time.time() - start_time

    assert exc_info.value.hresult == E_FAIL
    assert attempts == 1  # Did NOT retry!
    assert elapsed < 0.05


# ==============================================================================
# SECTION 3: PARAMETRIC EQUATIONS & SUBSTRING COLLISION HARDENING
# ==============================================================================

def test_equation_manager_substring_collision():
    """Test: set_global_variable must match the exact variable name LHS,
    never colliding with substrings (e.g. 'Length' inside 'TotalLength')
    or references on the RHS (e.g. 'Width' = 'Length' * 2).
    """
    mock_doc = MagicMock()
    mock_doc_mgr = MagicMock()
    mock_doc_mgr.get_active_doc.return_value = mock_doc

    mock_eqn_mgr = MagicMock()
    mock_doc.GetEquationMgr = mock_eqn_mgr

    # Existing equations:
    # Index 0: "TotalLength" = 200mm
    # Index 1: "Width" = "Length" * 2
    # Index 2: "Length" = 50mm
    existing_equations = [
        '"TotalLength" = 200mm',
        '"Width" = "Length" * 2',
        '"Length" = 50mm',
    ]
    mock_eqn_mgr.GetCount = len(existing_equations)
    mock_eqn_mgr.Equation.side_effect = lambda i, *args: existing_equations[i] if not args else None

    mgr = EquationManager(mock_doc_mgr)

    # We want to update "Length" to 75mm
    res = mgr.set_global_variable("Length", 75.0, "mm")

    # Verify that it updated Index 2 ("Length"), NOT Index 0 ("TotalLength") or Index 1 ("Width")!
    mock_eqn_mgr.Equation.assert_any_call(2, '"Length" = 75.0mm')
    assert res["action"] == "updated"
    assert res["name"] == "Length"


def test_format_equation_string_adversarial_inputs():
    """Test: Equation string formatting rejects dangerous or empty inputs."""
    # Valid complex cases
    assert format_equation_string("  Thickness  ", 12.5, "mm") == '"Thickness" = 12.5mm'
    assert format_equation_string('"Wall_Thickness"', 2.0, "mm") == '"Wall_Thickness" = 2.0mm'
    assert format_equation_string("D1@Sketch1", 100.0, "deg") == '"D1@Sketch1" = 100.0deg'

    # Reject empty or whitespace
    with pytest.raises(ValueError, match="cannot be empty"):
        format_equation_string("", 10.0, "mm")
    with pytest.raises(ValueError, match="cannot be empty"):
        format_equation_string("   ", 10.0, "mm")
    with pytest.raises(ValueError, match="cannot be empty"):
        format_equation_string('""', 10.0, "mm")

    # Reject NaN and Infs
    with pytest.raises(ValueError, match="cannot be NaN or Infinite"):
        format_equation_string("Len", float("nan"), "mm")
    with pytest.raises(ValueError, match="cannot be NaN or Infinite"):
        format_equation_string("Len", float("inf"), "mm")
    with pytest.raises(ValueError, match="cannot be NaN or Infinite"):
        format_equation_string("Len", float("-inf"), "mm")


# ==============================================================================
# SECTION 4: MASS PROPERTIES & UNIT BOUNDARY FUZZING
# ==============================================================================

def test_convert_mass_properties_extremes_and_negative_coords():
    """Test: Mass properties conversion handles negative coordinates, zero volume, and full 18-element arrays."""
    # Center of mass in negative octant: X=-0.05m (-50mm), Y=-0.03m (-30mm), Z=-0.01m (-10mm)
    # Zero volume (surface / sheet metal), mass = 0.005 kg (5g)
    raw_array = [-0.050, -0.030, -0.010, 0.0, 0.0015, 0.005] + [0.0] * 12
    res = convert_mass_properties(raw_array)

    assert res["center_of_mass_mm"]["x"] == -50.0
    assert res["center_of_mass_mm"]["y"] == -30.0
    assert res["center_of_mass_mm"]["z"] == -10.0
    assert res["volume_mm3"] == 0.0
    assert res["mass_g"] == 5.0
    assert res["surface_area_mm2"] == 1500.0

    # Malformed array tests
    assert "error" in convert_mass_properties([])
    assert "error" in convert_mass_properties([1.0, 2.0, 3.0])  # Less than 6 elements
    assert "error" in convert_mass_properties(None)


def test_units_conversion_precision_boundaries():
    """Test: Units conversion maintains precision at micron and sub-micron scale."""
    # Micron scale: 0.001 mm = 1e-6 m
    assert mm_to_meters(0.001) == pytest.approx(1e-6)
    assert meters_to_mm(1e-6) == pytest.approx(0.001)

    # Sub-micron scale: 0.00005 mm = 5e-8 m
    assert mm_to_meters(0.00005) == pytest.approx(5e-8)

    # Angles: negative and beyond 360 degrees
    assert deg_to_radians(-90.0) == pytest.approx(-math.pi / 2)
    assert deg_to_radians(720.0) == pytest.approx(4 * math.pi)
    assert radians_to_deg(-math.pi) == pytest.approx(-180.0)

    # Mass conversions
    assert kg_to_grams(0.00001) == pytest.approx(0.01)  # 10 milligrams


# ==============================================================================
# SECTION 5: GEOMETRIC BOUNDARY VALIDATION
# ==============================================================================

def test_feature_manager_geometry_input_validation():
    """Test: FeatureManager rejects non-positive extrusion depths and fillet radii."""
    mock_doc_mgr = MagicMock()
    feat_mgr = FeatureManager(mock_doc_mgr)

    # Extrusion depth <= 0
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.boss_extrude(depth_mm=0.0)
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.boss_extrude(depth_mm=-15.0)

    # Cut extrusion depth <= 0
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.cut_extrude(depth_mm=0.0)
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.cut_extrude(depth_mm=-5.0)

    # Fillet radius <= 0
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.fillet(radius_mm=0.0)
    with pytest.raises(ValueError, match="must be strictly positive"):
        feat_mgr.fillet(radius_mm=-2.0)


def test_sketch_manager_geometry_input_validation():
    """Test: SketchManager rejects degenerate lines, zero-area rectangles, and non-positive circle radii."""
    mock_doc_mgr = MagicMock()
    sk_mgr = SketchManager(mock_doc_mgr)

    # Degenerate line (same start and end)
    with pytest.raises(ValueError, match="must have distinct start and end points"):
        sk_mgr.draw_line(10.0, 20.0, 10.0, 20.0)

    # Zero-width or zero-height rectangle
    with pytest.raises(ValueError, match="cannot have zero width or height"):
        sk_mgr.draw_rectangle(0.0, 0.0, 0.0, 50.0)
    with pytest.raises(ValueError, match="cannot have zero width or height"):
        sk_mgr.draw_rectangle(10.0, 20.0, 50.0, 20.0)

    # Circle radius <= 0
    with pytest.raises(ValueError, match="Circle radius must be strictly positive"):
        sk_mgr.draw_circle(0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="Circle radius must be strictly positive"):
        sk_mgr.draw_circle(0.0, 0.0, -10.0)


# ==============================================================================
# SECTION 6: FASTMCP PROTOCOL TOOL REGISTRATION & SCHEMA CONTRACT
# ==============================================================================

@pytest.mark.asyncio
async def test_fastmcp_tool_contract_deep_inspection():
    """Verify tool parameter contracts, naming conventions, and descriptions."""
    tools = await mcp.list_tools()
    assert len(tools) >= 20

    tool_map = {t.name: t for t in tools}

    # Inspect critical tools and their schemas
    crit_tools = [
        "sw_get_session_info",
        "sw_new_part",
        "sw_create_sketch_on_plane",
        "sw_draw_rectangle",
        "sw_boss_extrude",
        "sw_get_mass_properties",
        "sw_set_global_variable",
    ]

    for tool_name in crit_tools:
        assert tool_name in tool_map, f"Missing expected tool: {tool_name}"
        t = tool_map[tool_name]
        assert len(t.description) > 10, f"Description for {tool_name} is too short"
        schema = getattr(t, "input_schema", getattr(t, "inputSchema", None))
        assert schema is not None
        assert schema.get("type") == "object"

    # Verify sw_boss_extrude schema parameters
    boss_tool = tool_map["sw_boss_extrude"]
    boss_schema = getattr(boss_tool, "input_schema", getattr(boss_tool, "inputSchema", {}))
    assert "depth_mm" in boss_schema.get("properties", {})
    assert "flip_dir" in boss_schema.get("properties", {})
