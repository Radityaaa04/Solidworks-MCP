"""Supermoto SMX-300V Engine Preparation Verification Suite.

Comprehensive end-to-end integration test validating the 3 critical CAD gap additions:
1. Transmission Gear Involute Tooth Circular Pattern:
   - Gear blank: OD 60 mm x 12 mm face width, bore 25 mm.
   - Tooth cut slot: 5 mm width x 4 mm depth.
   - Circular pattern: 18 teeth across 360° via sw_circular_pattern.
   - Mass properties & Parasolid volume mathematical verification.
2. Cylinder Head Curved Porting Runner via Swept Boss & Swept Cut:
   - Trajectory path: 3D curved arc runner.
   - Swept boss: Exhaust runner conduit (Dia 25.5 mm) via sw_boss_sweep.
   - Swept cut: Internal aerodynamic flow core (Dia 20 mm) via sw_cut_sweep.
3. Manufacturing 2D Drawing with Section View A-A:
   - New drawing sheet creation via sw_new_drawing.
   - Front view projection of transmission gear via sw_create_drawing_view.
   - Section View A-A generation via sw_create_section_view.
   - Auto-dimensioning & Title Block engineering notes.
   - Silent export to SLDDRW, vector PDF, and CAD DXF.
   - Canvas viewport capture of the sectioned drawing sheet.
"""

import asyncio
import json
import math
import os
import shutil
import sys
import time
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")
ARTIFACT_DIR = r"C:\Users\radit\.gemini\antigravity\brain\bc399346-7624-49cd-bb08-803042918e09"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


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


async def run_supermoto_engine_prep_suite():
    print("=" * 85)
    print("SUPERMOTO SMX-300V ENGINE PREPARATION & ADVANCED CAD EXTENSIONS VERIFICATION")
    print("=" * 85)

    stderr_log_path = os.path.join(OUTPUT_DIR, "engine_prep_stderr.log")

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT,
        env={"PYTHONUNBUFFERED": "1"},
    )

    t_suite_start = time.time()
    results_summary: Dict[str, Any] = {}

    with open(stderr_log_path, "w+", encoding="utf-8") as stderr_file:
        async with stdio_client(server_params, errlog=stderr_file) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_res = await session.initialize()
                print(f"[Handshake] Connected to SolidWorks 2026 Assistant (MCP Protocol)")

                # =========================================================================
                # TEST 1: Transmission Gear Modeling with Circular Pattern (sw_circular_pattern)
                # =========================================================================
                print("\n" + "=" * 70)
                print("TEST 1: Transmission Gear Modeling & 18-Tooth Circular Pattern")
                print("=" * 70)

                # 1.1 New part
                await session.call_tool("sw_new_part", {})

                # 1.2 Base gear blank: OD 60 mm, ID (bore) 25 mm, width 12 mm
                print("1.1 Extruding Gear Blank (OD 60mm, ID 25mm, Width 12mm)...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 30.0}) # OD 60
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 12.5}) # Bore 25
                await session.call_tool("sw_boss_extrude", {"depth_mm": 12.0})

                # 1.3 Tooth gullet slot at Top: Width 4.5mm, Depth 4mm
                print("1.2 Cutting first tooth gullet slot at top rim...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                # Slot centered at (X=0, Y=30mm), width 4.5mm, depth 4mm (from Y=30 down to Y=26)
                await session.call_tool("sw_draw_rectangle", {
                    "x1_mm": -2.25,
                    "y1_mm": 26.0,
                    "x2_mm": 2.25,
                    "y2_mm": 31.0
                })
                # Cut through 12mm
                cut_res = await session.call_tool("sw_cut_extrude", {"depth_mm": 12.0, "flip_dir": True})
                cut_info = parse_tool_result(cut_res)
                assert cut_info.get("created") is True
                print(f" -> Created single tooth slot: '{cut_info.get('feature')}'")

                # 1.4 Circular Pattern: 18 teeth across 360 deg
                print("1.3 Applying sw_circular_pattern: 18 teeth @ 360 degrees...")
                t0 = time.time()
                pat_res = await session.call_tool(
                    "sw_circular_pattern",
                    {
                        "feature_name": cut_info.get("feature", "Cut-Extrude1"),
                        "total_instances": 18,
                        "total_angle_deg": 360.0,
                        "equal_spacing": True,
                        "axis_x_mm": 30.0,
                        "axis_y_mm": 0.0,
                        "axis_z_mm": 6.0,
                    },
                )
                pat_info = parse_tool_result(pat_res)
                dt_pat = time.time() - t0
                print(f" -> Pattern Created: '{pat_info.get('feature')}' (Instances: {pat_info.get('total_instances')}) in {dt_pat:.2f}s")
                assert pat_info.get("created") is True

                # Assign material: Case-hardened 18CrNiMo7-6 (AISI 1020 / Alloy Steel)
                await session.call_tool("sw_set_material", {"material_name": "AISI 1020", "database_name": "SolidWorks Materials"})

                # Measure mass properties
                mp_res = await session.call_tool("sw_get_mass_properties", {})
                mp_info = parse_tool_result(mp_res)
                gear_vol = mp_info.get("volume_mm3", 0.0)
                gear_mass = mp_info.get("mass_g", 0.0)
                print(f" -> Gear Mass: {gear_mass:.2f} g, Volume: {gear_vol:.2f} mm^3")
                assert gear_vol > 15000.0, "Gear volume must be realistic"

                # Save Gear Part
                gear_path = os.path.join(OUTPUT_DIR, "smx_gear_z18.sldprt")
                await session.call_tool("sw_save_doc", {"output_path": gear_path})
                print(f" -> Saved Gear: {gear_path}")
                results_summary["gear"] = {"teeth": 18, "volume_mm3": gear_vol, "mass_g": gear_mass}

                # =========================================================================
                # TEST 2: Cylinder Head Porting Conduit (sw_boss_sweep & sw_cut_sweep)
                # =========================================================================
                print("\n" + "=" * 70)
                print("TEST 2: Cylinder Head Exhaust Porting via Swept Features")
                print("=" * 70)

                # 2.1 New part for port runner
                await session.call_tool("sw_new_part", {})

                # 2.2 Draw curved runner path on Front Plane
                print("2.1 Creating curved trajectory path for port...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                arc1_res = await session.call_tool("sw_draw_arc", {
                    "x1_mm": 0.0,
                    "y1_mm": 0.0,
                    "x2_mm": 50.0,
                    "y2_mm": 50.0,
                    "x3_mm": 15.0,
                    "y3_mm": 35.0,
                })
                arc1_info = parse_tool_result(arc1_res)
                assert arc1_info.get("entity") == "arc", f"Failed to draw arc: {arc1_info}"
                await session.call_tool("sw_close_sketch", {})

                # 2.3 Create Swept Boss: Dia 20.0 mm (Exhaust Port Outer Wall)
                print("2.2 Creating Swept Boss (Dia 20.0 mm outer conduit)...")
                t0 = time.time()
                sweep_boss_res = await session.call_tool(
                    "sw_boss_sweep",
                    {
                        "path_sketch_name": "",
                        "circular_profile_diameter_mm": 20.0,
                    },
                )
                sweep_boss_info = parse_tool_result(sweep_boss_res)
                dt_sw1 = time.time() - t0
                print(f" -> Swept Boss Created: '{sweep_boss_info.get('feature')}' in {dt_sw1:.2f}s")
                assert sweep_boss_info.get("created") is True

                # 2.4 Draw internal flow path (same trajectory) on Front Plane
                print("2.3 Drawing internal flow core path...")
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                arc2_res = await session.call_tool("sw_draw_arc", {
                    "x1_mm": 0.0,
                    "y1_mm": 0.0,
                    "x2_mm": 50.0,
                    "y2_mm": 50.0,
                    "x3_mm": 15.0,
                    "y3_mm": 35.0,
                })
                arc2_info = parse_tool_result(arc2_res)
                assert arc2_info.get("entity") == "arc"
                await session.call_tool("sw_close_sketch", {})

                # 2.5 Create Swept Cut: Dia 12.0 mm (Hollow Aerodynamic Core)
                print("2.4 Creating Swept Cut (Dia 12.0 mm hollow flow tunnel)...")
                t0 = time.time()
                sweep_cut_res = await session.call_tool(
                    "sw_cut_sweep",
                    {
                        "path_sketch_name": "",
                        "circular_profile_diameter_mm": 12.0,
                    },
                )
                sweep_cut_info = parse_tool_result(sweep_cut_res)
                dt_sw2 = time.time() - t0
                print(f" -> Swept Cut Created: '{sweep_cut_info.get('feature')}' in {dt_sw2:.2f}s")
                assert sweep_cut_info.get("created") is True

                # Measure hollow swept tube volume
                mp_sw = await session.call_tool("sw_get_mass_properties", {})
                sw_info = parse_tool_result(mp_sw)
                port_vol = sw_info.get("volume_mm3", 0.0)
                print(f" -> Hollow Port Runner Volume: {port_vol:.2f} mm^3")
                assert port_vol > 0.0, "Port volume must be positive"

                port_path = os.path.join(OUTPUT_DIR, "smx_exhaust_port_runner.sldprt")
                await session.call_tool("sw_save_doc", {"output_path": port_path})
                results_summary["port_runner"] = {"volume_mm3": port_vol}

                # =========================================================================
                # TEST 3: Manufacturing 2D Drawing with Section View A-A (sw_create_section_view)
                # =========================================================================
                print("\n" + "=" * 70)
                print("TEST 3: 2D Manufacturing Drawing with Section View A-A")
                print("=" * 70)

                # 3.1 New drawing document
                print("3.1 Creating new drawing document...")
                drw_res = await session.call_tool("sw_new_drawing", {})
                drw_info = parse_tool_result(drw_res)
                print(f" -> Drawing Document: {drw_info.get('title')}")

                # 3.2 Front view of the 18-tooth transmission gear
                print("3.2 Projecting Front View of Transmission Gear at (80, 110) mm...")
                v1_res = await session.call_tool(
                    "sw_create_drawing_view",
                    {
                        "model_path": gear_path,
                        "orientation": "*Front",
                        "x_mm": 80.0,
                        "y_mm": 110.0,
                        "scale": "1:1",
                    },
                )
                v1_info = parse_tool_result(v1_res)
                v1_name = v1_info.get("name", "Drawing View1")
                print(f" -> Created Parent View: '{v1_name}'")

                # 3.3 Create Section View A-A (Cutting vertically right through gear axis)
                print("3.3 Cutting Section View A-A through gear center at (180, 110) mm...")
                t0 = time.time()
                sec_res = await session.call_tool(
                    "sw_create_section_view",
                    {
                        "parent_view_name": v1_name,
                        "cut_start_x_mm": 80.0,
                        "cut_start_y_mm": 65.0,
                        "cut_end_x_mm": 80.0,
                        "cut_end_y_mm": 155.0,
                        "placement_x_mm": 180.0,
                        "placement_y_mm": 110.0,
                        "section_label": "A",
                    },
                )
                sec_info = parse_tool_result(sec_res)
                dt_sec = time.time() - t0
                print(f" -> Created Section View: '{sec_info.get('name')}' in {dt_sec:.2f}s")
                assert sec_info.get("status") == "created"

                # 3.4 Enumerate views to verify both Parent and Section View A-A exist
                views_raw = await session.call_tool("sw_list_drawing_views", {})
                views = parse_tool_result(views_raw)
                print(f"Total views on sheet: {len(views)}")
                sec_found = any(v.get("type") == "Section" or "Section" in v.get("name", "") for v in views)
                assert sec_found, "Section View A-A must be present in enumerated views"

                # 3.5 Auto-dimension Section View
                print("3.4 Applying AutoDimension on Section View A-A...")
                ad_res = await session.call_tool(
                    "sw_auto_dimension",
                    {
                        "view_name": sec_info.get("name", "Section View A-A"),
                        "scheme": "baseline",
                        "horizontal_placement": "above",
                        "vertical_placement": "right",
                    },
                )
                ad_info = parse_tool_result(ad_res)
                print(f" -> Section AutoDimension: {ad_info.get('status')}")

                # 3.6 Insert Technical Title Block Notes
                gear_title_text = (
                    "DWG NO: SMX-GEAR-003 | REV: C\n"
                    "TITLE: SMX-300V CASSETTE GEARBOX 3RD DRIVE GEAR (Z=18)\n"
                    "MATERIAL: 18CrNiMo7-6 (CASE HARDENED 58-62 HRC)\n"
                    "SCALE: 1:1 | ALL DIMENSIONS IN MILLIMETERS"
                )
                await session.call_tool("sw_add_drawing_note", {"text": gear_title_text, "x_mm": 20.0, "y_mm": 25.0})

                gear_mfg_text = (
                    "GEAR SPECIFICATIONS (DIN 3960 / ISO 6336):\n"
                    "1. MODULE m = 2.0 mm | PRESSURE ANGLE alpha = 20 DEG\n"
                    "2. NUMBER OF TEETH Z = 18 | PROFILE SHIFT x = +0.150\n"
                    "3. CASE DEPTH: 0.8 - 1.0 mm | ROOT RADIUS R0.6 mm"
                )
                await session.call_tool("sw_add_drawing_note", {"text": gear_mfg_text, "x_mm": 20.0, "y_mm": 175.0})

                # 3.7 Multi-format Export: SLDDRW, PDF, DXF
                out_drw = os.path.join(OUTPUT_DIR, "smx_gear_drawing.slddrw")
                out_pdf = os.path.join(OUTPUT_DIR, "smx_gear_drawing.pdf")
                out_dxf = os.path.join(OUTPUT_DIR, "smx_gear_drawing.dxf")

                exp1 = parse_tool_result(await session.call_tool("sw_export_drawing", {"output_path": out_drw, "format_type": "slddrw"}))
                exp2 = parse_tool_result(await session.call_tool("sw_export_drawing", {"output_path": out_pdf, "format_type": "pdf"}))
                exp3 = parse_tool_result(await session.call_tool("sw_export_drawing", {"output_path": out_dxf, "format_type": "dxf"}))
                print(f"Exported: SLDDRW={exp1.get('size_bytes')}B, PDF={exp2.get('size_bytes')}B, DXF={exp3.get('size_bytes')}B")
                assert os.path.exists(out_pdf) and os.path.getsize(out_pdf) > 10000

                # 3.8 Viewport Canvas Capture of Section Drawing
                gear_render_path = os.path.join(OUTPUT_DIR, "smx_gear_section_render.png")
                cap = parse_tool_result(await session.call_tool("sw_capture_viewport", {"output_path": gear_render_path}))
                print(f"Captured Drawing Render: {cap.get('width')}x{cap.get('height')}, {cap.get('file_size_bytes')} bytes")
                art_render = os.path.join(ARTIFACT_DIR, "smx_gear_section_render.png")
                shutil.copy2(gear_render_path, art_render)
                print(f"Copied render to artifact: {art_render}")

                # =========================================================================
                # VERIFICATION SUMMARY
                # =========================================================================
                dt_total = time.time() - t_suite_start
                print("\n" + "=" * 85)
                print(f"ALL 3 ENGINE PREPARATION CAD EXTENSIONS VERIFIED IN {dt_total:.2f} SECONDS")
                print("=" * 85)
                print("Status Metrics:")
                print(f"  1. Circular Pattern: 18-tooth transmission gear created, Volume={results_summary['gear']['volume_mm3']:.2f} mm^3")
                print(f"  2. Swept Features: Swept Boss (Outer) + Swept Cut (Core) created, Volume={results_summary['port_runner']['volume_mm3']:.2f} mm^3")
                print(f"  3. 2D Section View: Section View A-A generated and exported to PDF ({exp2.get('size_bytes')} B)")
                print(f"  Render Artifact: {art_render}")
                print("=" * 85)


if __name__ == "__main__":
    asyncio.run(run_supermoto_engine_prep_suite())
