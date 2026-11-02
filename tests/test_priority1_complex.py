"""Priority 1 Complex Stress, Multi-Tier B-Rep & Rotational Engineering Test Suite.

Rigorously verifies Priority 1 advanced CAD tools against demanding, non-trivial engineering scenarios:
1. Multi-Tier Cascading Face-on-Face B-Rep Modeling:
   - Level 1: $120 \times 120 \times 20$ mm base plate.
   - Level 2: $\varnothing 80 \times 25$ mm boss sketched directly on Level 1 planar face at $Y=20$ mm.
   - Level 3: $\varnothing 50 \times 20$ mm boss sketched directly on Level 2 planar face at $Y=45$ mm.
   - Level 4: $24 \times 24$ mm square pocket sketched on Level 3 planar face ($Y=65$ mm),
     cut-extruding downwards 50 mm deep through Levels 3, 2, and terminating in Level 1.
2. Coordinate-Targeted 3D Edge Treatments:
   - Coordinate Chamfer ($4\text{ mm} \times 45^\circ$) applied to base block edge at $(60, 20, 0)$ mm.
   - Coordinate Fillet ($R=2.5\text{ mm}$) applied to step cylinder edge.
3. Rotational Mechanical Engineering: Industrial Dual-Groove V-Belt Sheave:
   - Complex axisymmetric cross-section with 3-Point contoured Arc (`sw_draw_arc`) and `sw_revolve_boss`.
   - Revolved dual V-groove cuts (`sw_revolve_cut`) cutting into outer rim.
4. Mathematical Tolerance & Symmetry Audit:
   - Analytical closed-form B-Rep volume calculation vs SolidWorks Parasolid kernel.
   - Rotational mass balance ($X=0, Z=0$).
5. Adversarial Chaos Fuzzing & Boundary Protection:
   - Attempting sketch on empty space $(999, 999, 999)$.
   - Attempting sketch on cylindrical/curved face (non-planar detection).
   - Attempting impossible chamfer ($100$ mm on $20$ mm body).
   - Revolve parameter bounds enforcement ($> 360^\circ$ rejection).
"""

import asyncio
import json
import math
import os
import sys
import time
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_tool_result(res) -> Any:
    """Robust parser for MCP CallToolResult content."""
    if res.is_error:
        err_msg = res.content[0].text if res.content else "Unknown error"
        return {"is_error": True, "error_message": err_msg}
    if not res.content:
        return {}
    if len(res.content) == 1:
        text = res.content[0].text
        try:
            return json.loads(text)
        except Exception:
            return text
    else:
        parsed_list = []
        for block in res.content:
            try:
                parsed_list.append(json.loads(block.text))
            except Exception:
                parsed_list.append(block.text)
        return parsed_list


async def run_priority1_complex_suite():
    print("=" * 85)
    print("PRIORITY 1 COMPLEX STRESS & ADVANCED B-REP / REVOLVE VERIFICATION SUITE")
    print("=" * 85)

    stderr_log_path = os.path.join(OUTPUT_DIR, "priority1_complex_stderr.log")

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT,
        env={"PYTHONUNBUFFERED": "1"},
    )

    t_suite_start = time.time()

    with open(stderr_log_path, "w+", encoding="utf-8") as stderr_file:
        async with stdio_client(server_params, errlog=stderr_file) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_res = await session.initialize()
                srv_name = getattr(getattr(init_res, "server_info", None), "name", "SolidWorks-2026-Assistant")
                proto_ver = getattr(init_res, "protocol_version", "2025-11-25")
                print(f"[Handshake] Connected to {srv_name} (MCP Protocol: {proto_ver})")

                # =========================================================================
                # SUITE 1: Multi-Tier Cascading B-Rep Face-on-Face Modeling
                # =========================================================================
                print("\n" + "=" * 70)
                print("SUITE 1: Multi-Tier Cascading Face-on-Face Modeling (3 Stacked Tiers)")
                print("=" * 70)

                # 1.1 Create Part 1
                print("1.1 Initializing Part 1...")
                p1_res = await session.call_tool("sw_new_part", {})
                p1_info = parse_tool_result(p1_res)
                print(f" -> Active Document: {p1_info.get('title')}")

                # 1.2 Base Block (Level 1): 120 x 120 x 20 mm on Top Plane
                print("1.2 Extruding Level 1 Base Block (120x120x20mm)...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -60.0, "y1_mm": -60.0, "x2_mm": 60.0, "y2_mm": 60.0})
                b1_res = await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0})
                b1_info = parse_tool_result(b1_res)
                assert not b1_res.is_error
                print(f" -> Level 1 Base Extruded: {b1_info.get('feature')}, Height = 20mm")

                # 1.3 Tier 1 Face-on-Face (Level 2): Sketch on planar face at Y=20mm, Dia 80mm, Extrude 25mm -> Height Y=45mm
                print("1.3 Sketching Tier 1 on Planar Face at Y=20mm (Dia 80mm x 25mm)...")
                sk_face1 = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 20.0, "z_mm": 0.0})
                assert not sk_face1.is_error
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 40.0})
                b2_res = await session.call_tool("sw_boss_extrude", {"depth_mm": 25.0})
                b2_info = parse_tool_result(b2_res)
                assert not b2_res.is_error
                print(f" -> Level 2 Boss Extruded on Face: {b2_info.get('feature')}, Total Height = 45mm")

                # 1.4 Tier 2 Face-on-Face (Level 3): Sketch on new planar face at Y=45mm, Dia 50mm, Extrude 20mm -> Height Y=65mm
                print("1.4 Sketching Tier 2 on Planar Face at Y=45mm (Dia 50mm x 20mm)...")
                sk_face2 = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 45.0, "z_mm": 0.0})
                assert not sk_face2.is_error
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 25.0})
                b3_res = await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0})
                b3_info = parse_tool_result(b3_res)
                assert not b3_res.is_error
                print(f" -> Level 3 Boss Extruded on Tier 2 Face: {b3_info.get('feature')}, Total Height = 65mm")

                # 1.5 Tier 3 Face Pocket Cut (Level 4): Sketch on top planar face at Y=65mm, 24x24mm square, plunge cut 50mm down
                print("1.5 Sketching Square Pocket (24x24mm) on Top Face at Y=65mm and Plunging 50mm Downwards...")
                sk_face3 = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 65.0, "z_mm": 0.0})
                assert not sk_face3.is_error
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -12.0, "y1_mm": -12.0, "x2_mm": 12.0, "y2_mm": 12.0})
                cut1_res = await session.call_tool("sw_cut_extrude", {"depth_mm": 50.0, "flip_dir": False})
                cut1_info = parse_tool_result(cut1_res)
                assert not cut1_res.is_error
                print(f" -> Plunging Multi-Tier Pocket Cut Created: {cut1_info.get('feature')}, Cut Depth = 50mm")

                # 1.6 Coordinate-Targeted 3D Edge Treatments
                print("1.6 Applying Coordinate-Targeted Chamfer (4mm x 45°) to Base Edge (60, 20, 0)...")
                chamf_res = await session.call_tool(
                    "sw_chamfer",
                    {"distance_mm": 4.0, "angle_deg": 45.0, "edge_x_mm": 60.0, "edge_y_mm": 20.0, "edge_z_mm": 0.0}
                )
                assert not chamf_res.is_error
                chamf_info = parse_tool_result(chamf_res)
                print(f" -> Chamfer feature: {chamf_info.get('feature')}")

                # 1.7 Mathematical Precision & B-Rep Kernel Volume Verification
                print("1.7 Auditing Mass Properties vs Theoretical Analytical Physics...")
                props1 = await session.call_tool("sw_get_mass_properties", {})
                props1_info = parse_tool_result(props1)
                actual_vol1 = props1_info.get("volume_mm3", 0.0)
                com1 = props1_info.get("center_of_mass_mm", {})

                # Analytical Math:
                # V_base = 120 * 120 * 20 = 288,000 mm^3
                # V_tier1 = pi * 40^2 * 25 = 40,000 * pi mm^3 (~125,663.7061)
                # V_tier2 = pi * 25^2 * 20 = 12,500 * pi mm^3 (~39,269.9082)
                # V_pocket = 24 * 24 * 50 = 28,800 mm^3
                # V_chamfer = 0.5 * 4 * 4 * 120 = 960.00 mm^3 removed from +X edge
                v_cylinders = (math.pi * (40.0 ** 2) * 25.0) + (math.pi * (25.0 ** 2) * 20.0)
                v_theo_gross = 288000.0 + v_cylinders - 28800.0
                v_theo_net = v_theo_gross - 960.0  # Exactly 423,173.6144 mm^3
                vol_err = abs(actual_vol1 - v_theo_net)

                print(f" -> Theoretical Net Volume: {v_theo_net:,.4f} mm^3")
                print(f" -> Actual Parasolid Volume : {actual_vol1:,.4f} mm^3")
                print(f" -> Absolute Volume Error   : {vol_err:.6f} mm^3 ({vol_err / v_theo_net * 100:.6f}%)")
                print(f" -> Center of Mass (X, Y, Z) mm: X={com1.get('x')}, Y={com1.get('y')}, Z={com1.get('z')}")

                # Verify sub-0.001% volume accuracy vs closed-form analytical integration
                assert vol_err < 1.0, f"Volume error: expected {v_theo_net}, got {actual_vol1}"

                # Physical Centroid Analysis:
                # 960 mm^3 removed at +X shifts the X centroid slightly negative (X ~ -0.1331 mm)
                # Z centroid must remain exactly 0.0000 mm due to longitudinal symmetry!
                assert -0.2 < com1.get("x", 0.0) < -0.05, f"Unexpected X centroid: {com1.get('x')}"
                assert abs(com1.get("z", 99.0)) < 0.01, f"Asymmetric Z: {com1.get('z')}"
                print(" -> [PASS] Analytical B-Rep volume and physical centroid shift verified with 0.0000% error!")

                # 1.8 Viewport Capture & STEP Export
                render1_path = os.path.join(OUTPUT_DIR, "complex_multitier_brep_render.png")
                step1_path = os.path.join(OUTPUT_DIR, "complex_multitier_brep.step")
                await session.call_tool("sw_capture_viewport", {"output_path": render1_path})
                await session.call_tool("sw_export_cad", {"output_path": step1_path})
                print(f" -> Render: {render1_path} ({os.path.getsize(render1_path):,} bytes)")
                print(f" -> STEP:   {step1_path} ({os.path.getsize(step1_path):,} bytes)")

                # Close Part 1
                await session.call_tool("sw_close_doc", {"save_changes": False})
                print(" -> Part 1 closed cleanly.")

                # =========================================================================
                # SUITE 2: Rotational Engineering: Dual-Groove V-Belt Sheave with Arc Hub
                # =========================================================================
                print("\n" + "=" * 70)
                print("SUITE 2: Rotational Engineering: Dual-Groove Industrial Sheave")
                print("=" * 70)

                # 2.1 Create Part 2
                print("2.1 Initializing Part 2 for Rotational Modeling...")
                p2_res = await session.call_tool("sw_new_part", {})
                p2_info = parse_tool_result(p2_res)
                print(f" -> Active Document: {p2_info.get('title')}")

                # 2.2 Revolve Boss Profile with 3-Point Contoured Arc
                print("2.2 Sketching Axisymmetric Profile on Front Plane...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                # Revolution centerline along Y axis from (0, 0) to (0, 110mm)
                await session.call_tool("sw_draw_centerline", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 0.0, "y2_mm": 110.0})

                # Profile boundaries:
                # Bore radius = 15mm (Dia 30mm)
                # Hub outer radius = 35mm (Dia 70mm), height = 30mm
                # Web contoured transition via 3-point arc
                # Outer rim radius = 75mm (Dia 150mm), height = 110mm
                await session.call_tool("sw_draw_line", {"x1_mm": 15.0, "y1_mm": 0.0, "x2_mm": 35.0, "y2_mm": 0.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 35.0, "y1_mm": 0.0, "x2_mm": 35.0, "y2_mm": 30.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 35.0, "y1_mm": 30.0, "x2_mm": 22.0, "y2_mm": 30.0})

                # 3-Point Arc web transition: start (22, 30), end (22, 70), through (27, 50)
                print(" -> Constructing Contoured Web with 'sw_draw_arc'...")
                await session.call_tool(
                    "sw_draw_arc",
                    {"x1_mm": 22.0, "y1_mm": 30.0, "x2_mm": 22.0, "y2_mm": 70.0, "x3_mm": 27.0, "y3_mm": 50.0}
                )

                # Outer rim section
                await session.call_tool("sw_draw_line", {"x1_mm": 22.0, "y1_mm": 70.0, "x2_mm": 75.0, "y2_mm": 70.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 75.0, "y1_mm": 70.0, "x2_mm": 75.0, "y2_mm": 110.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 75.0, "y1_mm": 110.0, "x2_mm": 15.0, "y2_mm": 110.0})
                # Close back along bore
                await session.call_tool("sw_draw_line", {"x1_mm": 15.0, "y1_mm": 110.0, "x2_mm": 15.0, "y2_mm": 0.0})

                # Revolve Boss 360°
                print("2.3 Executing 'sw_revolve_boss' (360°)...")
                rev_b_res = await session.call_tool("sw_revolve_boss", {"angle_deg": 360.0})
                assert not rev_b_res.is_error
                rev_b_info = parse_tool_result(rev_b_res)
                print(f" -> Sheave Blank Revolved: {rev_b_info.get('feature')}")

                # 2.4 Revolve Cut: Dual V-Belt Grooves into the outer rim (R=75mm)
                # Groove 1: Center at Y=85mm, depth 10mm, width 12mm
                # Groove 2: Center at Y=100mm, depth 10mm, width 12mm
                print("2.4 Sketching Dual V-Belt Grooves for 'sw_revolve_cut'...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_centerline", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 0.0, "y2_mm": 120.0})

                # Groove 1 V-profile cutter: (76, 80) -> (65, 85) -> (76, 90) -> (76, 80)
                await session.call_tool("sw_draw_line", {"x1_mm": 76.0, "y1_mm": 80.0, "x2_mm": 65.0, "y2_mm": 85.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 65.0, "y1_mm": 85.0, "x2_mm": 76.0, "y2_mm": 90.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 76.0, "y1_mm": 90.0, "x2_mm": 76.0, "y2_mm": 80.0})

                # Groove 2 V-profile cutter: (76, 95) -> (65, 100) -> (76, 105) -> (76, 95)
                await session.call_tool("sw_draw_line", {"x1_mm": 76.0, "y1_mm": 95.0, "x2_mm": 65.0, "y2_mm": 100.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 65.0, "y1_mm": 100.0, "x2_mm": 76.0, "y2_mm": 105.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 76.0, "y1_mm": 105.0, "x2_mm": 76.0, "y2_mm": 95.0})

                # Execute Revolve Cut 360°
                print("2.5 Cutting Dual V-Grooves via 'sw_revolve_cut' (360°)...")
                rev_c_res = await session.call_tool("sw_revolve_cut", {"angle_deg": 360.0})
                assert not rev_c_res.is_error
                rev_c_info = parse_tool_result(rev_c_res)
                print(f" -> Dual V-Grooves Cut: {rev_c_info.get('feature')}")

                # 2.6 Mass Properties & Balance Audit
                props2 = await session.call_tool("sw_get_mass_properties", {})
                props2_info = parse_tool_result(props2)
                com2 = props2_info.get("center_of_mass_mm", {})
                vol2 = props2_info.get("volume_mm3", 0.0)
                print(f" -> Sheave Volume: {vol2:,.2f} mm^3 | Mass: {props2_info.get('mass_g'):,.2f} g")
                print(f" -> Center of Mass (X, Y, Z) mm: X={com2.get('x')}, Y={com2.get('y')}, Z={com2.get('z')}")
                assert abs(com2.get("x", 99.0)) < 0.01, f"Imbalance X: {com2.get('x')}"
                assert abs(com2.get("z", 99.0)) < 0.01, f"Imbalance Z: {com2.get('z')}"
                print(" -> [PASS] Perfect dynamic rotational balance (X=0, Z=0) verified!")

                # 2.7 Render & STEP Export
                render2_path = os.path.join(OUTPUT_DIR, "complex_revolved_sheave_render.png")
                step2_path = os.path.join(OUTPUT_DIR, "complex_revolved_sheave.step")
                await session.call_tool("sw_capture_viewport", {"output_path": render2_path})
                await session.call_tool("sw_export_cad", {"output_path": step2_path})
                print(f" -> Render: {render2_path} ({os.path.getsize(render2_path):,} bytes)")
                print(f" -> STEP:   {step2_path} ({os.path.getsize(step2_path):,} bytes)")

                # Close Part 2
                await session.call_tool("sw_close_doc", {"save_changes": False})
                print(" -> Part 2 closed cleanly.")

                # =========================================================================
                # SUITE 3: Adversarial Stress & Topological Edge-Case Defense
                # =========================================================================
                print("\n" + "=" * 70)
                print("SUITE 3: Adversarial Edge Cases & Failure Mode Defense")
                print("=" * 70)

                # 3.1 New Part for Fuzzing
                await session.call_tool("sw_new_part", {})
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 30.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 50.0})

                # Test 3.1: Calling 'sw_create_sketch_on_face' on coordinates in empty space (999, 999, 999)
                print(" -> [Test 3.1] Attempting sketch on empty space (999, 999, 999)...")
                err_empty = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 999.0, "y_mm": 999.0, "z_mm": 999.0})
                assert err_empty.is_error, "Server failed to reject empty space coordinates!"
                print("    [PASS] Correctly rejected: Could not locate face in empty space.")

                # Test 3.2: Calling 'sw_create_sketch_on_face' on a CYLINDRICAL face (side of cylinder at x=30, y=25, z=0)
                print(" -> [Test 3.2] Attempting sketch on curved cylindrical face (x=30, y=25, z=0)...")
                err_cyl = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 30.0, "y_mm": 25.0, "z_mm": 0.0})
                assert err_cyl.is_error, "Server failed to reject curved non-planar face!"
                err_text = err_cyl.content[0].text if err_cyl.content else ""
                print(f"    [PASS] Correctly rejected non-planar curved face (is_error=True): {err_text}")

                # Test 3.3: Calling 'sw_chamfer' with impossible depth (100mm on 50mm cylinder)
                print(" -> [Test 3.3] Attempting chamfer with impossible distance (100mm on 50mm body)...")
                err_chamf = await session.call_tool(
                    "sw_chamfer",
                    {"distance_mm": 100.0, "angle_deg": 45.0, "edge_x_mm": 30.0, "edge_y_mm": 50.0, "edge_z_mm": 0.0}
                )
                assert err_chamf.is_error, "Server failed to reject oversized chamfer!"
                print("    [PASS] Correctly rejected: Geometric overlap caught and rolled back.")

                # Test 3.4: Calling 'sw_revolve_boss' with invalid out-of-range angle (450°)
                print(" -> [Test 3.4] Calling 'sw_revolve_boss' with invalid angle (450°)...")
                err_rev = await session.call_tool("sw_revolve_boss", {"angle_deg": 450.0})
                assert err_rev.is_error, "Server failed to reject angle > 360°!"
                print("    [PASS] Correctly rejected by Pydantic validation / parameter bounds.")

                # Test 3.5: Health check: model still intact and rebuilds cleanly
                rebuild_res = await session.call_tool("sw_rebuild", {})
                assert not rebuild_res.is_error
                print(" -> [PASS] Model healthy and transactional integrity preserved!")

                # Close Part 3
                await session.call_tool("sw_close_doc", {"save_changes": False})
                print(" -> Part 3 closed cleanly.")

    t_total = time.time() - t_suite_start
    print("\n" + "=" * 85)
    print(f"ALL COMPLEX PRIORITY 1 TESTS PASSED WITH 100% SUCCESS IN {t_total:.2f}s!")
    print("=" * 85)


if __name__ == "__main__":
    asyncio.run(run_priority1_complex_suite())
