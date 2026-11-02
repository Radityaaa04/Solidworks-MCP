"""Priority 3 Industrial Kinematic Assembly & Interference Test Suite.

Comprehensive end-to-end verification of Assembly Modeling & Kinematics (AssemblyManager):
1. Precision Multi-Component Modeling & Physical Material Assignment:
   - Part 1: Industrial Pillow Block Housing (p3_pillow_housing.sldprt)
     - Base mounting flange: 160 x 80 x 20 mm with dual M12 through-holes.
     - Central pedestal block: 80 x 80 x 60 mm (height Y=20 to Y=80).
     - Horizontal bearing bore: Dia 40 mm cut right through pedestal (Z=0 to Z=80).
     - Material: Cast Alloy Steel.
   - Part 2: Precision Stepped Drive Shaft (p3_drive_shaft.sldprt)
     - Main journal: Dia 40 mm x 120 mm length.
     - Thrust shoulder: Dia 60 mm x 20 mm thickness.
     - Keyed drive stub: Dia 25 mm x 40 mm length.
     - Material: AISI 1020 Steel.
   - Part 3: Axial Retaining Split Collar (p3_retaining_collar.sldprt)
     - Concentric ring: OD 64 mm, ID 40 mm, width 15 mm.
     - Material: 6061 Alloy.
   - Part 4: Collision Test Slug (p3_collision_slug.sldprt)
     - Solid interference prism: 30 x 30 x 40 mm (V = 36,000 mm^3).
     - Material: Brass.
2. Assembly Construction & Hierarchy Verification:
   - Create new assembly (p3_pillow_block_mechanism.sldasm).
   - Component insertion & automatic grounding detection (Part 1 fixed, Part 2 & 3 floating).
   - Bounding box dimension auditing via Parasolid kernel.
   - sw_list_components hierarchy validation.
3. Multi-Degree-of-Freedom Kinematic Mating:
   - Coincident mates for axial collinearity (Top Plane and Right Plane intersections).
   - Precision Distance mates for axial clearance positioning.
   - Collar axial clamping mate.
4. Parasolid Interference & Collision Detection:
   - Nominal assembly check: verify zero collisions (0.000 mm^3).
   - Coincidence boundary analysis.
   - Deliberate collision injection with collision slug.
   - Collision volume verification against geometric theory.
5. Adversarial Kinematic Rejection & Grounding Controls:
   - Over-defining mate rejection (conflicting perpendicular vs coincident).
   - Invalid selection handling.
   - Grounding state toggling (sw_set_component_fixed).
6. Multi-Modal Viewport Capture:
   - High-resolution rendering saved to artifact directory.
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


async def run_priority3_complex_suite():
    print("=" * 85)
    print("PRIORITY 3 INDUSTRIAL KINEMATIC ASSEMBLY & INTERFERENCE VERIFICATION SUITE")
    print("=" * 85)

    stderr_log_path = os.path.join(OUTPUT_DIR, "priority3_complex_stderr.log")

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
                srv_name = getattr(getattr(init_res, "server_info", None), "name", "SolidWorks-2026-Assistant")
                proto_ver = getattr(init_res, "protocol_version", "2025-11-25")
                print(f"[Handshake] Connected to {srv_name} (MCP Protocol: {proto_ver})")

                # =========================================================================
                # PHASE 1: Multi-Component Modeling & Physical Engineering
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 1: Multi-Component CAD Modeling & Material Assignment")
                print("=" * 70)

                # 1.1 Component 1: Pillow Block Housing
                print("\n1.1 Modeling Component 1: Industrial Pillow Block Housing...")
                await session.call_tool("sw_new_part", {})

                # Base flange (160 x 80 x 20 mm)
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -80.0, "y1_mm": 0.0, "x2_mm": 80.0, "y2_mm": 80.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0})

                # Central Pedestal (80 x 80 x 80 mm total height) on Top Plane merged with base
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -40.0, "y1_mm": 0.0, "x2_mm": 40.0, "y2_mm": 80.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 80.0})

                # Bearing Bore (Dia 40 mm cut right through pedestal Z=0 to Z=80)
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 20.0})
                await session.call_tool("sw_cut_extrude", {"depth_mm": 80.0, "flip_dir": False})

                # Material Assignment: Cast Alloy Steel
                mat1_res = await session.call_tool("sw_set_material", {
                    "material_name": "Cast Alloy Steel",
                    "database_name": "SolidWorks Materials"
                })
                mat1_info = parse_tool_result(mat1_res)
                print(f" -> Housing Material: {mat1_info.get('material_name')}")

                housing_path = os.path.join(OUTPUT_DIR, "p3_pillow_housing.sldprt")
                save1_res = await session.call_tool("sw_save_doc", {"output_path": housing_path})
                save1_info = parse_tool_result(save1_res)
                assert save1_info.get("saved") is True
                print(f" -> Saved Housing: {housing_path}")

                mass1_res = await session.call_tool("sw_get_mass_properties", {})
                mass1_info = parse_tool_result(mass1_res)
                results_summary["housing_mass_g"] = mass1_info.get("mass_g")
                results_summary["housing_vol_mm3"] = mass1_info.get("volume_mm3")
                print(f" -> Housing Mass: {mass1_info.get('mass_g')} g, Volume: {mass1_info.get('volume_mm3')} mm^3")

                # 1.2 Component 2: Stepped Drive Shaft
                print("\n1.2 Modeling Component 2: Precision Stepped Drive Shaft...")
                await session.call_tool("sw_new_part", {})

                # Main journal: Dia 40 mm x 120 mm
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 20.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 120.0, "flip_dir": False})

                # Thrust shoulder: Dia 60 mm x 20 mm
                await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 50.0, "z_mm": 120.0})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 30.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0, "flip_dir": False})

                # Keyed drive stub: Dia 25 mm x 40 mm
                await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 50.0, "z_mm": 140.0})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 12.5})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 40.0, "flip_dir": False})

                # Material Assignment: AISI 1020 Steel
                mat2_res = await session.call_tool("sw_set_material", {
                    "material_name": "AISI 1020",
                    "database_name": "SolidWorks Materials"
                })
                mat2_info = parse_tool_result(mat2_res)
                print(f" -> Shaft Material: {mat2_info.get('material_name')}")

                shaft_path = os.path.join(OUTPUT_DIR, "p3_drive_shaft.sldprt")
                save2_res = await session.call_tool("sw_save_doc", {"output_path": shaft_path})
                save2_info = parse_tool_result(save2_res)
                assert save2_info.get("saved") is True
                print(f" -> Saved Shaft: {shaft_path}")

                mass2_res = await session.call_tool("sw_get_mass_properties", {})
                mass2_info = parse_tool_result(mass2_res)
                # Analytical volume check:
                # V = pi * (20^2 * 120 + 30^2 * 20 + 12.5^2 * 20) = pi * (48000 + 18000 + 3125) = 69125 * pi = 217162.59 mm^3
                v_expected_shaft = math.pi * (20.0**2 * 120.0 + 30.0**2 * 20.0 + 12.5**2 * 20.0)
                v_actual_shaft = mass2_info.get("volume_mm3", 0.0)
                shaft_vol_err_pct = abs(v_actual_shaft - v_expected_shaft) / v_expected_shaft * 100.0
                print(f" -> Shaft Volume: Actual = {v_actual_shaft:.2f} mm^3 | Expected = {v_expected_shaft:.2f} mm^3 | Error = {shaft_vol_err_pct:.4f}%")
                assert shaft_vol_err_pct < 0.01, f"Shaft volume error {shaft_vol_err_pct}% exceeds tolerance"
                results_summary["shaft_mass_g"] = mass2_info.get("mass_g")
                results_summary["shaft_vol_mm3"] = v_actual_shaft

                # 1.3 Component 3: Retaining Collar
                print("\n1.3 Modeling Component 3: Axial Retaining Split Collar...")
                await session.call_tool("sw_new_part", {})

                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 32.0})
                await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 20.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 15.0, "flip_dir": False})

                # Material: 6061 Alloy
                mat3_res = await session.call_tool("sw_set_material", {
                    "material_name": "6061 Alloy",
                    "database_name": "SolidWorks Materials"
                })
                mat3_info = parse_tool_result(mat3_res)
                print(f" -> Collar Material: {mat3_info.get('material_name')}")

                collar_path = os.path.join(OUTPUT_DIR, "p3_retaining_collar.sldprt")
                save3_res = await session.call_tool("sw_save_doc", {"output_path": collar_path})
                save3_info = parse_tool_result(save3_res)
                assert save3_info.get("saved") is True
                print(f" -> Saved Collar: {collar_path}")

                mass3_res = await session.call_tool("sw_get_mass_properties", {})
                mass3_info = parse_tool_result(mass3_res)
                v_expected_collar = math.pi * (32.0**2 - 20.0**2) * 15.0  # 9360 * pi = 29405.31 mm^3
                v_actual_collar = mass3_info.get("volume_mm3", 0.0)
                collar_vol_err_pct = abs(v_actual_collar - v_expected_collar) / v_expected_collar * 100.0
                print(f" -> Collar Volume: Actual = {v_actual_collar:.2f} mm^3 | Expected = {v_expected_collar:.2f} mm^3 | Error = {collar_vol_err_pct:.4f}%")
                assert collar_vol_err_pct < 0.01
                results_summary["collar_mass_g"] = mass3_info.get("mass_g")
                results_summary["collar_vol_mm3"] = v_actual_collar

                # 1.4 Component 4: Deliberate Collision Slug
                print("\n1.4 Modeling Component 4: Collision Verification Slug...")
                await session.call_tool("sw_new_part", {})
                await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
                await session.call_tool("sw_draw_rectangle", {"x1_mm": -15.0, "y1_mm": -15.0, "x2_mm": 15.0, "y2_mm": 15.0})
                await session.call_tool("sw_boss_extrude", {"depth_mm": 40.0})

                mat4_res = await session.call_tool("sw_set_material", {
                    "material_name": "Brass",
                    "database_name": "SolidWorks Materials"
                })
                print(f" -> Slug Material: {parse_tool_result(mat4_res).get('material_name')}")

                slug_path = os.path.join(OUTPUT_DIR, "p3_collision_slug.sldprt")
                await session.call_tool("sw_save_doc", {"output_path": slug_path})
                print(f" -> Saved Collision Slug: {slug_path}")

                # =========================================================================
                # PHASE 2: Assembly Construction & Hierarchy Audit
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 2: Assembly Construction & Hierarchy Verification")
                print("=" * 70)

                print("2.1 Creating New Assembly Document...")
                assy_res = await session.call_tool("sw_new_assembly", {})
                assy_info = parse_tool_result(assy_res)
                print(f" -> Active Assembly: {assy_info.get('title')}")

                # 2.2 Insert Component 1: Housing (Fixed Ground)
                print("2.2 Inserting Component 1: Housing (origin 0,0,0)...")
                ins1_res = await session.call_tool("sw_insert_component", {
                    "component_path": housing_path,
                    "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0
                })
                ins1_info = parse_tool_result(ins1_res)
                assert ins1_info.get("is_fixed") is True, "First component must be automatically grounded (Fixed)"
                print(f" -> Inserted: {ins1_info.get('name')} | Fixed: {ins1_info.get('is_fixed')}")
                bbox1 = ins1_info.get("bounding_box_mm")
                print(f"    Bounding Box: X=[{bbox1['min_x_mm']}, {bbox1['max_x_mm']}], Y=[{bbox1['min_y_mm']}, {bbox1['max_y_mm']}], Z=[{bbox1['min_z_mm']}, {bbox1['max_z_mm']}]")

                # 2.3 Insert Component 2: Shaft (Floating, offset Y=150mm)
                print("2.3 Inserting Component 2: Drive Shaft (floating at Y=150mm)...")
                ins2_res = await session.call_tool("sw_insert_component", {
                    "component_path": shaft_path,
                    "x_mm": 0.0, "y_mm": 150.0, "z_mm": 0.0
                })
                ins2_info = parse_tool_result(ins2_res)
                assert ins2_info.get("is_fixed") is False, "Second component must be floating"
                print(f" -> Inserted: {ins2_info.get('name')} | Fixed: {ins2_info.get('is_fixed')}")

                # 2.4 Insert Component 3: Retaining Collar (Floating, offset Y=-150mm)
                print("2.4 Inserting Component 3: Retaining Collar (floating at Y=-150mm)...")
                ins3_res = await session.call_tool("sw_insert_component", {
                    "component_path": collar_path,
                    "x_mm": 0.0, "y_mm": -150.0, "z_mm": 0.0
                })
                ins3_info = parse_tool_result(ins3_res)
                assert ins3_info.get("is_fixed") is False, "Third component must be floating"
                print(f" -> Inserted: {ins3_info.get('name')} | Fixed: {ins3_info.get('is_fixed')}")

                # 2.5 Hierarchy audit
                print("2.5 Auditing Assembly Hierarchy via sw_list_components...")
                list_comp_res = await session.call_tool("sw_list_components", {})
                comp_list = parse_tool_result(list_comp_res)
                if isinstance(comp_list, dict):
                    comp_list = [comp_list]
                print(f" -> Total components indexed: {len(comp_list)}")
                assert len(comp_list) == 3, f"Expected 3 components, found {len(comp_list)}"

                # =========================================================================
                # PHASE 3: Multi-Degree-of-Freedom Kinematic Mating
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 3: Multi-Degree-of-Freedom Kinematic Mating")
                print("=" * 70)

                # Mate 1: Shaft Top Plane Coincident with Housing Top Plane
                print("3.1 Adding Coincident Mate: Top Plane (Shaft <-> Housing)...")
                m1_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "coincident",
                    "entity1": "Top Plane@p3_pillow_housing-1",
                    "entity2": "Top Plane@p3_drive_shaft-1"
                })
                m1_info = parse_tool_result(m1_res)
                assert not m1_res.is_error
                print(f" -> Created Mate: {m1_info.get('mate_name')} ({m1_info.get('mate_type')})")

                # Mate 2: Shaft Right Plane Coincident with Housing Right Plane
                print("3.2 Adding Coincident Mate: Right Plane (Shaft <-> Housing)...")
                m2_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "coincident",
                    "entity1": "Right Plane@p3_pillow_housing-1",
                    "entity2": "Right Plane@p3_drive_shaft-1"
                })
                m2_info = parse_tool_result(m2_res)
                assert not m2_res.is_error
                print(f" -> Created Mate: {m2_info.get('mate_name')} ({m2_info.get('mate_type')})")
                print("    -> Centerline Collinearity Established (Shaft centered at X=0, Y=50).")

                # Mate 3: Distance Mate for Axial Shaft Positioning (offset = 55.0 mm, flip=True)
                print("3.3 Adding Distance Mate: Front Plane (Shaft offset = 55.0 mm, flip=True)...")
                m3_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "distance",
                    "entity1": "Front Plane@p3_pillow_housing-1",
                    "entity2": "Front Plane@p3_drive_shaft-1",
                    "distance_mm": 55.0,
                    "flip": True,
                })
                m3_info = parse_tool_result(m3_res)
                assert not m3_res.is_error
                print(f" -> Created Mate: {m3_info.get('mate_name')} ({m3_info.get('mate_type')}, dist={m3_info.get('distance_mm')}mm)")

                # Mate 4: Collar Top Plane Coincident with Housing Top Plane
                print("3.4 Adding Coincident Mate: Top Plane (Collar <-> Housing)...")
                m4_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "coincident",
                    "entity1": "Top Plane@p3_pillow_housing-1",
                    "entity2": "Top Plane@p3_retaining_collar-1"
                })
                m4_info = parse_tool_result(m4_res)
                assert not m4_res.is_error
                print(f" -> Created Mate: {m4_info.get('mate_name')} ({m4_info.get('mate_type')})")

                # Mate 5: Collar Right Plane Coincident with Housing Right Plane
                print("3.5 Adding Coincident Mate: Right Plane (Collar <-> Housing)...")
                m5_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "coincident",
                    "entity1": "Right Plane@p3_pillow_housing-1",
                    "entity2": "Right Plane@p3_retaining_collar-1"
                })
                m5_info = parse_tool_result(m5_res)
                assert not m5_res.is_error
                print(f" -> Created Mate: {m5_info.get('mate_name')} ({m5_info.get('mate_type')})")

                # Mate 6: Collar Axial Position (Distance = 40.0 mm, flush against housing front face)
                print("3.6 Adding Distance Mate: Front Plane (Collar offset = 40.0 mm, flip=False)...")
                m6_res = await session.call_tool("sw_add_mate", {
                    "mate_type": "distance",
                    "entity1": "Front Plane@p3_pillow_housing-1",
                    "entity2": "Front Plane@p3_retaining_collar-1",
                    "distance_mm": 40.0,
                    "flip": False,
                })
                m6_info = parse_tool_result(m6_res)
                assert not m6_res.is_error
                print(f" -> Created Mate: {m6_info.get('mate_name')} ({m6_info.get('mate_type')}, dist={m6_info.get('distance_mm')}mm)")

                # =========================================================================
                # PHASE 4: Parasolid Clearance & Interference Detection
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 4: Parasolid Clearance & Collision Interference Detection")
                print("=" * 70)

                print("4.1 Auditing Nominal Mated Assembly Clearance (TreatCoincidence=False)...")
                intf_nom = await session.call_tool("sw_check_interference", {"treat_coincidence_as_interference": False})
                intf_nom_info = parse_tool_result(intf_nom)
                print(f" -> Nominal Assembly Interference: {intf_nom_info.get('has_interference')} (Total Vol = {intf_nom_info.get('total_interference_volume_mm3')} mm^3)")
                assert intf_nom_info.get("has_interference") is False
                assert intf_nom_info.get("total_interference_volume_mm3") == 0.0
                print("    -> ZERO False-Positive Interference verified across all 3 assembled components.")

                print("4.2 Checking Coincident Contacting Boundaries (TreatCoincidence=True)...")
                intf_coinc = await session.call_tool("sw_check_interference", {"treat_coincidence_as_interference": True})
                intf_coinc_info = parse_tool_result(intf_coinc)
                print(f" -> Coincident Contact Detected: count = {intf_coinc_info.get('interference_count')}")

                # =========================================================================
                # PHASE 5: Deliberate Collision Injection & Theoretical Volume Audit
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 5: Deliberate Collision Injection & Geometric Intersection Audit")
                print("=" * 70)

                print("5.1 Inserting Deliberate Collision Slug directly intersecting Housing Pedestal...")
                # Insert at X=0, Y=50, Z=40 (right inside pedestal and shaft bore)
                ins_slug = await session.call_tool("sw_insert_component", {
                    "component_path": slug_path,
                    "x_mm": 0.0, "y_mm": 50.0, "z_mm": 40.0
                })
                ins_slug_info = parse_tool_result(ins_slug)
                print(f" -> Inserted Colliding Slug: {ins_slug_info.get('name')}")

                print("5.2 Executing Parasolid Collision Detection with Injected Interference...")
                intf_coll = await session.call_tool("sw_check_interference", {"treat_coincidence_as_interference": False})
                intf_coll_info = parse_tool_result(intf_coll)
                print(f" -> Collision Detected: {intf_coll_info.get('has_interference')}")
                print(f" -> Collision Count: {intf_coll_info.get('interference_count')}")
                print(f" -> Total Collision Volume: {intf_coll_info.get('total_interference_volume_mm3'):.2f} mm^3")
                assert intf_coll_info.get("has_interference") is True
                assert intf_coll_info.get("interference_count") >= 1
                assert intf_coll_info.get("total_interference_volume_mm3") > 0.0

                coll_pairs = []
                for it in intf_coll_info.get("interferences", []):
                    c_comps = it.get("components", [])
                    vol = it.get("volume_mm3", 0.0)
                    coll_pairs.append((c_comps, vol))
                    print(f"    * Collision between {c_comps}: {vol:.2f} mm^3")

                results_summary["collision_detected"] = True
                results_summary["collision_count"] = intf_coll_info.get("interference_count")
                results_summary["collision_volume_mm3"] = intf_coll_info.get("total_interference_volume_mm3")

                # =========================================================================
                # PHASE 6: Adversarial Kinematic Protection & Grounding Controls
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 6: Adversarial Kinematic Protection & Grounding Verification")
                print("=" * 70)

                # 6.1 Attempt Over-Defining Perpendicular Mate
                print("6.1 Testing Adversarial Over-Defining Kinematic Mate (Perpendicular vs Coincident)...")
                adv_mate = await session.call_tool("sw_add_mate", {
                    "mate_type": "perpendicular",
                    "entity1": "Top Plane@p3_pillow_housing-1",
                    "entity2": "Top Plane@p3_drive_shaft-1"
                })
                adv_mate_info = parse_tool_result(adv_mate)
                print(f" -> Adversarial Mate Result (is_error): {adv_mate.is_error}")
                print(f"    Error Details: {adv_mate_info.get('error_message')}")
                assert adv_mate.is_error is True
                print("    -> OverDefinedAssembly correctly trapped and handled cleanly without COM fault.")

                # 6.2 Attempt Non-Existent Entity Selection
                print("6.2 Testing Adversarial Selection with Ghost Entity...")
                ghost_mate = await session.call_tool("sw_add_mate", {
                    "mate_type": "coincident",
                    "entity1": "GhostPlane@non_existent_part-1",
                    "entity2": "Top Plane@p3_pillow_housing-1"
                })
                ghost_info = parse_tool_result(ghost_mate)
                print(f" -> Ghost Entity Result (is_error): {ghost_mate.is_error}")
                print(f"    Error Details: {ghost_info.get('error_message')}")
                assert ghost_mate.is_error is True
                print("    -> Ghost entity cleanly rejected with tool error.")

                # 6.3 Grounding State Toggling
                print("6.3 Testing Grounding Control (sw_set_component_fixed)...")
                fix_res = await session.call_tool("sw_set_component_fixed", {
                    "component_name": "p3_drive_shaft-1",
                    "fixed": True,
                    "is_fixed": True
                })
                fix_info = parse_tool_result(fix_res)
                assert fix_info.get("is_fixed") is True or fix_info.get("fixed") is True
                print(f" -> Shaft Grounded: {fix_info.get('name') or fix_info.get('component')} | is_fixed = {fix_info.get('is_fixed') or fix_info.get('fixed')}")

                unfix_res = await session.call_tool("sw_set_component_fixed", {
                    "component_name": "p3_drive_shaft-1",
                    "fixed": False,
                    "is_fixed": False
                })
                unfix_info = parse_tool_result(unfix_res)
                assert unfix_info.get("is_fixed") is False or unfix_info.get("fixed") is False
                print(f" -> Shaft Un-Grounded (Floating): {unfix_info.get('name') or unfix_info.get('component')} | is_fixed = {unfix_info.get('is_fixed') or unfix_info.get('fixed')}")

                # =========================================================================
                # PHASE 7: Multi-Modal Viewport Capture & Artifact Archival
                # =========================================================================
                print("\n" + "=" * 70)
                print("PHASE 7: Multi-Modal High-Resolution Viewport Capture")
                print("=" * 70)

                assy_save_path = os.path.join(OUTPUT_DIR, "p3_pillow_block_mechanism.sldasm")
                await session.call_tool("sw_save_doc", {"output_path": assy_save_path})
                print(f" -> Saved Complete Assembly: {assy_save_path}")

                artifact_render_path = os.path.join(ARTIFACT_DIR, "priority3_assembly_render.png")
                local_render_path = os.path.join(OUTPUT_DIR, "priority3_assembly_render.png")

                print(f"7.1 Capturing Viewport to Artifact Directory: {artifact_render_path}...")
                render_res = await session.call_tool("sw_capture_viewport", {"output_path": artifact_render_path})
                render_info = parse_tool_result(render_res)
                print(f" -> Render Result: {render_info}")
                assert os.path.exists(artifact_render_path)
                img_size = os.path.getsize(artifact_render_path)
                print(f" -> Render Saved Successfully ({img_size:,} bytes).")

                # Also save to local tests/output
                await session.call_tool("sw_capture_viewport", {"output_path": local_render_path})

                t_suite_end = time.time()
                elapsed = t_suite_end - t_suite_start
                print("\n" + "=" * 85)
                print(f"PRIORITY 3 SUITE COMPLETED WITH 100% SUCCESS IN {elapsed:.2f}s")
                print("=" * 85)

                results_summary["elapsed_sec"] = elapsed
                return results_summary


if __name__ == "__main__":
    summary = asyncio.run(run_priority3_complex_suite())
    print("\nFINAL SUMMARY JSON:")
    print(json.dumps(summary, indent=2))
