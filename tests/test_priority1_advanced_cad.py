"""Priority 1 Advanced CAD Operations Live Verification Test Suite.

Rigorously verifies the 6 newly added Priority 1 advanced CAD tools on live SolidWorks 2026:
1. `sw_create_sketch_on_face`: Direct planar face selection and sketch activation on extruded 3D solid bodies.
2. `sw_chamfer`: Coordinate-targeted and selection-based edge chamfering with angle-distance options.
3. `sw_fillet` (enhanced): Coordinate-targeted 3D edge filleting.
4. `sw_draw_centerline`: 2D construction axis generation for symmetry and rotational features.
5. `sw_draw_arc`: 3-point circular contour sketching.
6. `sw_revolve_boss`: Full 360° rotational solid body revolution.
7. `sw_revolve_cut`: Internal rotational cavity/bore cutting.
8. Viewport rendering and STEP export of the advanced components.
"""

import asyncio
import json
import math
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def parse_tool_result(res):
    if res.is_error:
        err_msg = res.content[0].text if res.content else "Unknown error"
        raise RuntimeError(f"MCP Tool returned error: {err_msg}")
    if not res.content:
        return {}
    try:
        return json.loads(res.content[0].text)
    except Exception:
        return res.content[0].text


async def run_priority1_test_suite():
    print("=" * 80)
    print("TESTING PRIORITY 1: ADVANCED B-REP & ROTATIONAL CAD OPERATIONS")
    print("=" * 80)

    stderr_log_path = os.path.join(OUTPUT_DIR, "priority1_test_stderr.log")

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT,
        env={"PYTHONUNBUFFERED": "1"},
    )

    t0 = time.time()

    with open(stderr_log_path, "w+", encoding="utf-8") as stderr_file:
        async with stdio_client(server_params, errlog=stderr_file) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_res = await session.initialize()
                srv_name = getattr(getattr(init_res, "server_info", None), "name", "SolidWorks-2026-Assistant")
                proto_ver = getattr(init_res, "protocol_version", "2025-11-25")
                print(f"[Handshake] Connected to {srv_name} (Protocol: {proto_ver})")

                # =====================================================================
                # PART 1: B-Rep Planar Face Sketching, Edge Fillet & Chamfer
                # =====================================================================
                print("\n" + "-" * 70)
                print("SCENARIO 1: Planar Face Sketching, Coordinate Chamfer & Fillet")
                print("-" * 70)

                # 1.1 New Part
                print("1.1 Creating Part 1 for B-Rep Face Operations...")
                p1_res = await session.call_tool("sw_new_part", {})
                p1_info = parse_tool_result(p1_res)
                print(f" -> Active Document: {p1_info.get('title')}")

                # 1.2 Base Block on Top Plane (100mm x 80mm x 30mm)
                print("1.2 Sketching Base Block (100x80mm) on Top Plane...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -50.0, "y1_mm": -40.0, "x2_mm": 50.0, "y2_mm": 40.0})
                b1_res = await session.call_tool("sw_boss_extrude", {"depth_mm": 30.0})
                b1_info = parse_tool_result(b1_res)
                print(f" -> Base Block Extruded: {b1_info.get('feature')}, Height = 30.0 mm")

                # 1.3 Sketch directly on the TOP PLANAR FACE of the extruded block!
                # In SolidWorks Top Plane extrusion, height along Y is 30mm. Top face is at y = 30mm, (x=0, z=0).
                print("1.3 Testing 'sw_create_sketch_on_face' at (0, 30, 0) mm...")
                face_sk_res = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 30.0, "z_mm": 0.0})
                face_sk_info = parse_tool_result(face_sk_res)
                print(f" -> Sketch active on planar face: {face_sk_info.get('sketch_active')}")
                assert face_sk_info.get("sketch_active") is True

                # 1.4 Draw a circular boss on that face and extrude it
                print("1.4 Drawing boss circle (Dia 40mm) directly on the face and extruding 20mm...")
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 20.0})
                b2_res = await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0})
                b2_info = parse_tool_result(b2_res)
                print(f" -> Second stage boss created on top face: {b2_info.get('feature')}")

                # 1.5 Test 'sw_chamfer' targeted at an edge by 3D coordinates!
                # Base plate top edge: x=50mm, y=30mm, z=0mm
                print("1.5 Testing 'sw_chamfer' at edge coordinates (50, 30, 0) mm with 3mm x 45°...")
                chamfer_res = await session.call_tool(
                    "sw_chamfer",
                    {
                        "distance_mm": 3.0,
                        "angle_deg": 45.0,
                        "edge_x_mm": 50.0,
                        "edge_y_mm": 30.0,
                        "edge_z_mm": 0.0,
                    }
                )
                chamfer_info = parse_tool_result(chamfer_res)
                print(f" -> Chamfer feature created: {chamfer_info.get('feature')}, type: {chamfer_info.get('type')}")
                assert chamfer_info.get("created") is True

                # 1.6 Test 'sw_fillet' targeted at another edge by 3D coordinates!
                # Opposite top edge: x=-50mm, y=30mm, z=0mm
                print("1.6 Testing 'sw_fillet' at edge coordinates (-50, 30, 0) mm with R=4mm...")
                fillet_res = await session.call_tool(
                    "sw_fillet",
                    {
                        "radius_mm": 4.0,
                        "edge_x_mm": -50.0,
                        "edge_y_mm": 30.0,
                        "edge_z_mm": 0.0,
                    }
                )
                fillet_info = parse_tool_result(fillet_res)
                print(f" -> Fillet feature created: {fillet_info.get('feature')}, type: {fillet_info.get('type')}")
                assert fillet_info.get("created") is True

                # 1.7 Capture render of Scenario 1
                out_render1 = os.path.join(OUTPUT_DIR, "priority1_brep_block_render.png")
                await session.call_tool("sw_capture_viewport", {"output_path": out_render1})
                print(f" -> Render captured: {out_render1} ({os.path.getsize(out_render1):,} bytes)")

                # Close Part 1
                await session.call_tool("sw_close_doc", {"save_changes": False})
                print(" -> Part 1 closed cleanly.")

                # =====================================================================
                # PART 2: Stepped Shaft with Centerline, Arc, Revolve Boss & Revolve Cut
                # =====================================================================
                print("\n" + "-" * 70)
                print("SCENARIO 2: Rotational Modeling (Centerline, Arc, Revolve Boss & Cut)")
                print("-" * 70)

                # 2.1 New Part
                print("2.1 Creating Part 2 for Rotational Shaft Modeling...")
                p2_res = await session.call_tool("sw_new_part", {})
                p2_info = parse_tool_result(p2_res)
                print(f" -> Active Document: {p2_info.get('title')}")

                # 2.2 Create Sketch on Front Plane
                print("2.2 Opening Sketch on Front Plane...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})

                # 2.3 Draw Centerline along Y axis (0, 0) to (0, 100mm)
                print("2.3 Drawing revolution axis Centerline via 'sw_draw_centerline' (0,0) to (0,100)...")
                cl_res = await session.call_tool("sw_draw_centerline", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 0.0, "y2_mm": 100.0})
                cl_info = parse_tool_result(cl_res)
                assert cl_info.get("entity") == "centerline"

                # 2.4 Draw Stepped Profile with Lines and 3-Point Arc
                print("2.4 Constructing closed cross-sectional profile (Shaft with Flange & Contoured Crown)...")
                # Base step: (0, 0) -> (15, 0) -> (15, 30) (Journal: Dia 30mm x 30mm)
                await session.call_tool("sw_draw_line", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 15.0, "y2_mm": 0.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 15.0, "y1_mm": 0.0, "x2_mm": 15.0, "y2_mm": 30.0})

                # Flange collar step: (15, 30) -> (30, 30) -> (30, 50) (Flange: Dia 60mm x 20mm)
                await session.call_tool("sw_draw_line", {"x1_mm": 15.0, "y1_mm": 30.0, "x2_mm": 30.0, "y2_mm": 30.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 30.0, "y1_mm": 30.0, "x2_mm": 30.0, "y2_mm": 50.0})

                # Step-down to upper section: (30, 50) -> (18, 50)
                await session.call_tool("sw_draw_line", {"x1_mm": 30.0, "y1_mm": 50.0, "x2_mm": 18.0, "y2_mm": 50.0})

                # 3-Point Arc for contoured transition: start at (18, 50), end at (18, 80), passing through (22, 65)
                print(" -> Drawing 3-Point Contoured Arc via 'sw_draw_arc'...")
                arc_res = await session.call_tool(
                    "sw_draw_arc",
                    {
                        "x1_mm": 18.0, "y1_mm": 50.0,
                        "x2_mm": 18.0, "y2_mm": 80.0,
                        "x3_mm": 22.0, "y3_mm": 65.0,
                    }
                )
                arc_info = parse_tool_result(arc_res)
                assert arc_info.get("entity") == "arc"

                # Close profile back to centerline: (18, 80) -> (0, 80) -> (0, 0)
                await session.call_tool("sw_draw_line", {"x1_mm": 18.0, "y1_mm": 80.0, "x2_mm": 0.0, "y2_mm": 80.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 0.0, "y1_mm": 80.0, "x2_mm": 0.0, "y2_mm": 0.0})

                # 2.5 Revolve Boss 360°
                print("2.5 Testing 'sw_revolve_boss' (360°)...")
                rev_res = await session.call_tool("sw_revolve_boss", {"angle_deg": 360.0})
                rev_info = parse_tool_result(rev_res)
                print(f" -> Revolve Boss Created: {rev_info.get('feature')}, type: {rev_info.get('type')}")
                assert rev_info.get("created") is True

                # 2.6 Test Revolve Cut: Cut an internal stepped center bore through the shaft
                print("2.6 Testing 'sw_revolve_cut' for internal bore...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_centerline", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 0.0, "y2_mm": 100.0})
                # Internal bore rectangle profile: radius 8mm (Dia 16mm) from Y=0 to Y=60mm
                await session.call_tool("sw_draw_line", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 8.0, "y2_mm": 0.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 8.0, "y1_mm": 0.0, "x2_mm": 8.0, "y2_mm": 60.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 8.0, "y1_mm": 60.0, "x2_mm": 0.0, "y2_mm": 60.0})
                await session.call_tool("sw_draw_line", {"x1_mm": 0.0, "y1_mm": 60.0, "x2_mm": 0.0, "y2_mm": 0.0})

                rev_cut_res = await session.call_tool("sw_revolve_cut", {"angle_deg": 360.0})
                rev_cut_info = parse_tool_result(rev_cut_res)
                print(f" -> Revolve Cut Created: {rev_cut_info.get('feature')}, type: {rev_cut_info.get('type')}")
                assert rev_cut_info.get("created") is True

                # 2.7 Verify Mass Properties
                mass_res = await session.call_tool("sw_get_mass_properties", {})
                mass_info = parse_tool_result(mass_res)
                print(f" -> Shaft Mass Properties:")
                print(f"    Volume : {mass_info.get('volume_mm3'):,.2f} mm^3")
                print(f"    Mass   : {mass_info.get('mass_g'):,.2f} g")
                print(f"    Center of Mass: {mass_info.get('center_of_mass_mm')}")
                assert mass_info.get("volume_mm3") > 50000

                # 2.8 Multimodal Viewport Capture and STEP Export
                out_render2 = os.path.join(OUTPUT_DIR, "priority1_revolved_shaft_render.png")
                out_step2 = os.path.join(OUTPUT_DIR, "priority1_revolved_shaft.step")
                await session.call_tool("sw_capture_viewport", {"output_path": out_render2})
                await session.call_tool("sw_export_cad", {"output_path": out_step2})
                print(f" -> Viewport Render Saved: {out_render2} ({os.path.getsize(out_render2):,} bytes)")
                print(f" -> Production STEP Export: {out_step2} ({os.path.getsize(out_step2):,} bytes)")

                # Close Part 2
                await session.call_tool("sw_close_doc", {"save_changes": False})
                print(" -> Part 2 closed cleanly.")

    t_total = time.time() - t0
    print("\n" + "=" * 80)
    print(f"ALL PRIORITY 1 ADVANCED CAD OPERATIONS VERIFIED IN {t_total:.2f}s!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_priority1_test_suite())
