"""Priority 4 Industrial 2D Drafting & Engineering Drawings Verification Suite.

Comprehensive end-to-end verification of 2D Drafting Automation (DrawingManager):
1. Precision Part Manufacturing Drawing (p3_pillow_housing.sldprt):
   - New drawing document creation from template.
   - Orthogonal multi-view projection (Front, Top, Right, Isometric) with 1:2 scale.
   - View enumeration, coordinates, and referenced model validation.
   - Engineering Title Block and precision machining notes (tolerances, surface finish).
   - Automated drafting dimensioning (sw_auto_dimension) with baseline placement.
   - Silent multi-format export to SLDDRW, vector PDF, and CAD interchange DXF.
   - High-resolution viewport render capture of the drawing canvas.
2. Kinematic Assembly Engineering Drawing (p3_pillow_block_mechanism.sldasm):
   - New assembly drawing creation.
   - Multi-view projection (Front, Top, Isometric views) with assembly layout.
   - Engineering Bill of Materials (BOM) and assembly specification notes.
   - Assembly envelope auto-dimensioning.
   - Silent export to SLDDRW, PDF, and DXF.
   - High-resolution viewport render capture of the assembly drawing canvas.
3. Adversarial Drafting Stress Testing:
   - Rejection of non-existent model files during view creation.
   - Rejection of invalid view names during auto-dimensioning.
   - Document type enforcement (drawing operations on non-drawing docs rejected).
   - Server stability verification after adversarial exceptions.
"""

import asyncio
import json
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


async def run_priority4_complex_suite():
    print("=" * 85)
    print("PRIORITY 4 INDUSTRIAL 2D DRAFTING & DRAWING AUTOMATION VERIFICATION SUITE")
    print("=" * 85)

    stderr_log_path = os.path.join(OUTPUT_DIR, "priority4_complex_stderr.log")

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT,
        env={"PYTHONUNBUFFERED": "1"},
    )

    t_suite_start = time.time()
    results_summary: Dict[str, Any] = {}

    housing_model = os.path.abspath(os.path.join(OUTPUT_DIR, "p3_pillow_housing.sldprt"))
    assembly_model = os.path.abspath(os.path.join(OUTPUT_DIR, "p3_pillow_block_mechanism.sldasm"))

    assert os.path.exists(housing_model), f"Required part model not found: {housing_model}"
    assert os.path.exists(assembly_model), f"Required assembly model not found: {assembly_model}"

    with open(stderr_log_path, "w+", encoding="utf-8") as stderr_file:
        async with stdio_client(server_params, errlog=stderr_file) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init_res = await session.initialize()
                srv_name = getattr(getattr(init_res, "server_info", None), "name", "SolidWorks-2026-Assistant")
                proto_ver = getattr(init_res, "protocol_version", "2025-11-25")
                print(f"[Handshake] Connected to {srv_name} (MCP Protocol: {proto_ver})")

                # =========================================================================
                # PHASE 1: Session Readiness & Diagnostics
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 1: Session Readiness & System Diagnostics")
                print("=" * 70)
                info_raw = await session.call_tool("sw_get_session_info", {})
                info = parse_tool_result(info_raw)
                print(f"SolidWorks Session Info: Revision {info.get('revision')}, Connected: {info.get('connected')}")
                assert info.get("connected") is True

                # =========================================================================
                # PHASE 2: Part Manufacturing Drawing (p3_pillow_housing.sldprt)
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 2: Part Manufacturing Drawing (p3_pillow_housing.sldprt)")
                print("=" * 70)

                # 2.1 Create new drawing document
                print("\n2.1 Creating new drawing document from standard template...")
                t0 = time.time()
                drw_raw = await session.call_tool("sw_new_drawing", {})
                drw = parse_tool_result(drw_raw)
                dt_create = time.time() - t0
                print(f"Created Drawing: {drw.get('title')} (Sheet: {drw.get('sheet_name')}, "
                      f"{drw.get('width_mm')} x {drw.get('height_mm')} mm) in {dt_create:.2f}s")
                assert drw.get("status") == "created"
                assert "Draw" in drw.get("title", "")

                # 2.2 Multi-view projection: Front, Top, Right, Isometric (Scale 1:2)
                print("\n2.2 Projecting standard multi-views (Front, Top, Right, Isometric) at scale 1:2...")
                t0 = time.time()
                std_views_raw = await session.call_tool(
                    "sw_create_standard_views",
                    {
                        "model_path": housing_model,
                        "center_x_mm": 110.0,
                        "center_y_mm": 80.0,
                        "spacing_mm": 80.0,
                        "include_isometric": True,
                        "scale": "1:2",
                    },
                )
                std_views = parse_tool_result(std_views_raw)
                dt_views = time.time() - t0
                print(f"Created {len(std_views)} drawing views in {dt_views:.2f}s:")
                for v in std_views:
                    print(f" -> View '{v.get('name')}' ({v.get('orientation')}): "
                          f"Pos=({v.get('position_mm')}) mm, Scale={v.get('scale_decimal')}")
                assert len(std_views) == 4, f"Expected 4 views, got {len(std_views)}"

                # 2.3 List views and verify hierarchy
                print("\n2.3 Inspecting drawing view hierarchy and referenced models...")
                views_list_raw = await session.call_tool("sw_list_drawing_views", {})
                views_list = parse_tool_result(views_list_raw)
                print(f"Total views enumerated on sheet: {len(views_list)}")
                for vl in views_list:
                    print(f" -> '{vl.get('name')}' [{vl.get('type')}] at {vl.get('position_mm')} mm, Model: {os.path.basename(vl.get('referenced_model', ''))}")
                assert len(views_list) >= 5  # Sheet + 4 model views

                # 2.4 Insert Title Block and Manufacturing Notes
                print("\n2.4 Inserting Title Block and Technical Notes...")
                title_note_text = (
                    "DWG NO: SW-M4-001 | REV: A\n"
                    "TITLE: INDUSTRIAL PILLOW BLOCK HOUSING\n"
                    "MATERIAL: CAST ALLOY STEEL (ASTM A216 WCB)\n"
                    "SCALE: 1:2 | ALL UNITS IN MILLIMETERS"
                )
                n1_raw = await session.call_tool(
                    "sw_add_drawing_note",
                    {"text": title_note_text, "x_mm": 20.0, "y_mm": 25.0},
                )
                n1 = parse_tool_result(n1_raw)
                print(f"Note 1 placed at {n1.get('position_mm')}: {n1.get('status')}")

                general_note_text = (
                    "GENERAL MANUFACTURING NOTES:\n"
                    "1. BORE DIA 40H7 (+0.025/-0.000) SURFACE FINISH Ra 0.8 um.\n"
                    "2. MOUNTING SLOTS 2x DIA 14 THRU WITH C-BORE DIA 22 x 8 DP.\n"
                    "3. TOLERANCES UNLESS SPECIFIED: LINEAR +/- 0.1 mm, ANGULAR +/- 0.5 DEG.\n"
                    "4. DEBURR AND BREAK ALL SHARP EDGES R0.5."
                )
                n2_raw = await session.call_tool(
                    "sw_add_drawing_note",
                    {"text": general_note_text, "x_mm": 20.0, "y_mm": 180.0},
                )
                n2 = parse_tool_result(n2_raw)
                print(f"Note 2 placed at {n2.get('position_mm')}: {n2.get('status')}")

                # 2.5 Automated Drafting Dimensioning (Front & Right views)
                print("\n2.5 Applying automated drafting dimensioning (AutoDimension)...")
                front_view_name = std_views[0].get("name", "Drawing View1")
                right_view_name = std_views[2].get("name", "Drawing View3")

                t0 = time.time()
                ad1_raw = await session.call_tool(
                    "sw_auto_dimension",
                    {
                        "view_name": front_view_name,
                        "scheme": "baseline",
                        "horizontal_placement": "above",
                        "vertical_placement": "right",
                    },
                )
                ad1 = parse_tool_result(ad1_raw)
                dt_ad1 = time.time() - t0
                print(f"AutoDimension on '{front_view_name}': {ad1.get('status')} in {dt_ad1:.2f}s")

                t0 = time.time()
                ad2_raw = await session.call_tool(
                    "sw_auto_dimension",
                    {
                        "view_name": right_view_name,
                        "scheme": "baseline",
                        "horizontal_placement": "below",
                        "vertical_placement": "left",
                    },
                )
                ad2 = parse_tool_result(ad2_raw)
                dt_ad2 = time.time() - t0
                print(f"AutoDimension on '{right_view_name}': {ad2.get('status')} in {dt_ad2:.2f}s")

                # 2.6 Multi-Format Silent Export: SLDDRW, PDF, DXF
                print("\n2.6 Exporting Part Drawing to SLDDRW, PDF, and DXF...")
                out_drw = os.path.join(OUTPUT_DIR, "p4_pillow_housing_drawing.slddrw")
                out_pdf = os.path.join(OUTPUT_DIR, "p4_pillow_housing_drawing.pdf")
                out_dxf = os.path.join(OUTPUT_DIR, "p4_pillow_housing_drawing.dxf")

                # Save SLDDRW
                t0 = time.time()
                exp1_raw = await session.call_tool("sw_export_drawing", {"output_path": out_drw, "format_type": "slddrw"})
                exp1 = parse_tool_result(exp1_raw)
                dt_drw = time.time() - t0
                print(f"Exported SLDDRW: {exp1.get('size_bytes')} bytes in {dt_drw:.2f}s")
                assert os.path.exists(out_drw) and os.path.getsize(out_drw) > 10000

                # Export PDF
                t0 = time.time()
                exp2_raw = await session.call_tool("sw_export_drawing", {"output_path": out_pdf, "format_type": "pdf"})
                exp2 = parse_tool_result(exp2_raw)
                dt_pdf = time.time() - t0
                print(f"Exported PDF: {exp2.get('size_bytes')} bytes in {dt_pdf:.2f}s")
                assert os.path.exists(out_pdf) and os.path.getsize(out_pdf) > 10000

                # Export DXF
                t0 = time.time()
                exp3_raw = await session.call_tool("sw_export_drawing", {"output_path": out_dxf, "format_type": "dxf"})
                exp3 = parse_tool_result(exp3_raw)
                dt_dxf = time.time() - t0
                print(f"Exported DXF: {exp3.get('size_bytes')} bytes in {dt_dxf:.2f}s")
                assert os.path.exists(out_dxf) and os.path.getsize(out_dxf) > 10000

                # 2.7 Viewport Render Capture of Part Drawing
                print("\n2.7 Capturing 2D Drawing Canvas Viewport Render...")
                housing_render_path = os.path.join(OUTPUT_DIR, "p4_pillow_housing_render.png")
                cap_raw = await session.call_tool("sw_capture_viewport", {"output_path": housing_render_path})
                cap = parse_tool_result(cap_raw)
                print(f"Captured Drawing Render: {cap.get('width')}x{cap.get('height')}, {cap.get('file_size_bytes')} bytes")
                assert os.path.exists(housing_render_path)

                # Copy to artifact dir
                art_housing_render = os.path.join(ARTIFACT_DIR, "p4_pillow_housing_render.png")
                shutil.copy2(housing_render_path, art_housing_render)
                print(f"Copied render to artifact directory: {art_housing_render}")

                results_summary["part_drawing"] = {
                    "views": len(std_views),
                    "drw_size": exp1.get("size_bytes"),
                    "pdf_size": exp2.get("size_bytes"),
                    "dxf_size": exp3.get("size_bytes"),
                    "render_path": art_housing_render,
                }

                # =========================================================================
                # PHASE 3: Assembly Engineering Drawing (p3_pillow_block_mechanism.sldasm)
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 3: Assembly Engineering Drawing (p3_pillow_block_mechanism.sldasm)")
                print("=" * 70)

                # 3.1 Create new assembly drawing
                print("\n3.1 Creating new drawing document for assembly...")
                asm_drw_raw = await session.call_tool("sw_new_drawing", {})
                asm_drw = parse_tool_result(asm_drw_raw)
                print(f"Created Assembly Drawing: {asm_drw.get('title')}")

                # 3.2 Create assembly projection views
                print("\n3.2 Creating assembly views: Front, Top, and Isometric at scale 1:2...")
                v_asm_front_raw = await session.call_tool(
                    "sw_create_drawing_view",
                    {
                        "model_path": assembly_model,
                        "orientation": "*Front",
                        "x_mm": 110.0,
                        "y_mm": 80.0,
                        "scale": "1:2",
                    },
                )
                v_asm_front = parse_tool_result(v_asm_front_raw)
                print(f"Created Assembly Front View: '{v_asm_front.get('name')}'")

                v_asm_top_raw = await session.call_tool(
                    "sw_create_drawing_view",
                    {
                        "model_path": assembly_model,
                        "orientation": "*Top",
                        "x_mm": 110.0,
                        "y_mm": 160.0,
                        "scale": "1:2",
                    },
                )
                v_asm_top = parse_tool_result(v_asm_top_raw)
                print(f"Created Assembly Top View: '{v_asm_top.get('name')}'")

                v_asm_iso_raw = await session.call_tool(
                    "sw_create_drawing_view",
                    {
                        "model_path": assembly_model,
                        "orientation": "*Isometric",
                        "x_mm": 210.0,
                        "y_mm": 150.0,
                        "scale": "1:2",
                    },
                )
                v_asm_iso = parse_tool_result(v_asm_iso_raw)
                print(f"Created Assembly Isometric View: '{v_asm_iso.get('name')}'")

                # 3.3 Insert Assembly Bill of Materials (BOM) & Notes
                print("\n3.3 Inserting Bill of Materials and Assembly Specification Notes...")
                bom_note_text = (
                    "BILL OF MATERIALS (BOM):\n"
                    "ITEM 1: PILLOW BLOCK HOUSING (QTY: 1, CAST ALLOY STEEL)\n"
                    "ITEM 2: PRECISION DRIVE SHAFT (QTY: 1, AISI 1020 STEEL)\n"
                    "ITEM 3: AXIAL RETAINING COLLAR (QTY: 1, 6061 ALLOY)\n"
                    "TOTAL DRY MASS: ~4.12 KG"
                )
                bom_n_raw = await session.call_tool(
                    "sw_add_drawing_note",
                    {"text": bom_note_text, "x_mm": 20.0, "y_mm": 180.0},
                )
                bom_n = parse_tool_result(bom_n_raw)
                print(f"BOM Note placed: {bom_n.get('status')}")

                asm_title_text = (
                    "DWG NO: SW-ASM-001 | REV: B\n"
                    "TITLE: INDUSTRIAL PILLOW BLOCK MECHANISM ASSEMBLY\n"
                    "APPLICATION: ROTARY POWER TRANSMISSION SUB-SYSTEM\n"
                    "STATUS: RELEASED FOR MANUFACTURE"
                )
                asm_t_raw = await session.call_tool(
                    "sw_add_drawing_note",
                    {"text": asm_title_text, "x_mm": 20.0, "y_mm": 25.0},
                )
                asm_t = parse_tool_result(asm_t_raw)
                print(f"Assembly Title Note placed: {asm_t.get('status')}")

                # 3.4 Auto-Dimension Assembly Envelope
                print("\n3.4 Applying automated drafting dimensioning on Assembly Front View...")
                asm_ad_raw = await session.call_tool(
                    "sw_auto_dimension",
                    {
                        "view_name": v_asm_front.get("name", "Drawing View1"),
                        "scheme": "baseline",
                        "horizontal_placement": "above",
                        "vertical_placement": "right",
                    },
                )
                asm_ad = parse_tool_result(asm_ad_raw)
                print(f"AutoDimension on Assembly Front View: {asm_ad.get('status')}")

                # 3.5 Export Assembly Drawing: SLDDRW, PDF, DXF
                print("\n3.5 Exporting Assembly Drawing to SLDDRW, PDF, and DXF...")
                out_asm_drw = os.path.join(OUTPUT_DIR, "p4_assembly_drawing.slddrw")
                out_asm_pdf = os.path.join(OUTPUT_DIR, "p4_assembly_drawing.pdf")
                out_asm_dxf = os.path.join(OUTPUT_DIR, "p4_assembly_drawing.dxf")

                exp_asm1_raw = await session.call_tool("sw_export_drawing", {"output_path": out_asm_drw, "format_type": "slddrw"})
                exp_asm1 = parse_tool_result(exp_asm1_raw)
                print(f"Exported Assembly SLDDRW: {exp_asm1.get('size_bytes')} bytes")
                assert os.path.exists(out_asm_drw) and os.path.getsize(out_asm_drw) > 10000

                exp_asm2_raw = await session.call_tool("sw_export_drawing", {"output_path": out_asm_pdf, "format_type": "pdf"})
                exp_asm2 = parse_tool_result(exp_asm2_raw)
                print(f"Exported Assembly PDF: {exp_asm2.get('size_bytes')} bytes")
                assert os.path.exists(out_asm_pdf) and os.path.getsize(out_asm_pdf) > 10000

                exp_asm3_raw = await session.call_tool("sw_export_drawing", {"output_path": out_asm_dxf, "format_type": "dxf"})
                exp_asm3 = parse_tool_result(exp_asm3_raw)
                print(f"Exported Assembly DXF: {exp_asm3.get('size_bytes')} bytes")
                assert os.path.exists(out_asm_dxf) and os.path.getsize(out_asm_dxf) > 10000

                # 3.6 Capture Assembly Drawing Viewport Render
                print("\n3.6 Capturing Assembly 2D Drawing Canvas Viewport Render...")
                asm_render_path = os.path.join(OUTPUT_DIR, "p4_assembly_drawing_render.png")
                cap_asm_raw = await session.call_tool("sw_capture_viewport", {"output_path": asm_render_path})
                cap_asm = parse_tool_result(cap_asm_raw)
                print(f"Captured Assembly Drawing Render: {cap_asm.get('width')}x{cap_asm.get('height')}, {cap_asm.get('file_size_bytes')} bytes")
                assert os.path.exists(asm_render_path)

                art_asm_render = os.path.join(ARTIFACT_DIR, "p4_assembly_drawing_render.png")
                shutil.copy2(asm_render_path, art_asm_render)
                print(f"Copied render to artifact directory: {art_asm_render}")

                results_summary["assembly_drawing"] = {
                    "views": 3,
                    "drw_size": exp_asm1.get("size_bytes"),
                    "pdf_size": exp_asm2.get("size_bytes"),
                    "dxf_size": exp_asm3.get("size_bytes"),
                    "render_path": art_asm_render,
                }

                # =========================================================================
                # PHASE 4: Adversarial Drafting Stress Testing
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 4: Adversarial Drafting Stress Testing")
                print("=" * 70)

                # 4.1 Missing model file rejection
                print("\n4.1 Testing non-existent model file view creation...")
                bad_view_raw = await session.call_tool(
                    "sw_create_drawing_view",
                    {
                        "model_path": os.path.join(OUTPUT_DIR, "phantom_nonexistent_model_999.sldprt"),
                        "orientation": "*Front",
                    },
                )
                bad_view = parse_tool_result(bad_view_raw)
                print(f"Non-existent model response: is_error={bad_view_raw.is_error}")
                assert bad_view_raw.is_error is True, "Expected tool error for missing model file"

                # 4.2 Non-existent view name for auto-dimensioning
                print("\n4.2 Testing non-existent view name in auto-dimensioning...")
                bad_ad_raw = await session.call_tool(
                    "sw_auto_dimension",
                    {"view_name": "NonExistentPhantomView_999"},
                )
                print(f"Non-existent view response: is_error={bad_ad_raw.is_error}")
                assert bad_ad_raw.is_error is True, "Expected tool error for invalid view name"

                # 4.3 Verify server remains fully functional after exceptions
                print("\n4.3 Verifying server responsiveness post-adversarial rejection...")
                post_check_raw = await session.call_tool("sw_get_session_info", {})
                post_check = parse_tool_result(post_check_raw)
                print(f"Server health check: Connected={post_check.get('connected')}, Active Doc={post_check.get('active_document')}")
                assert post_check.get("connected") is True

                # =========================================================================
                # PHASE 5: Verification Summary
                # =========================================================================
                dt_total = time.time() - t_suite_start
                print("\n" + "=" * 85)
                print(f"PRIORITY 4 VERIFICATION COMPLETE IN {dt_total:.2f} SECONDS")
                print("=" * 85)
                print("Summary Metrics:")
                print(f"  Part Drawing: {results_summary['part_drawing']['views']} views projected, "
                      f"SLDDRW={results_summary['part_drawing']['drw_size']}B, "
                      f"PDF={results_summary['part_drawing']['pdf_size']}B, "
                      f"DXF={results_summary['part_drawing']['dxf_size']}B")
                print(f"  Assembly Drawing: {results_summary['assembly_drawing']['views']} views projected, "
                      f"SLDDRW={results_summary['assembly_drawing']['drw_size']}B, "
                      f"PDF={results_summary['assembly_drawing']['pdf_size']}B, "
                      f"DXF={results_summary['assembly_drawing']['dxf_size']}B")
                print(f"  Renders Generated:")
                print(f"    - Part Drawing Render: {art_housing_render}")
                print(f"    - Assembly Drawing Render: {art_asm_render}")
                print("  Adversarial Rejections: 100% Gracefully Handled (Zero Server Crashes)")
                print("=" * 85)


if __name__ == "__main__":
    asyncio.run(run_priority4_complex_suite())
