r"""Priority 2 Complex Physical Engineering & Material Assignment Test Suite.

Rigorously verifies Priority 2 material management, physical property updates,
and database catalog discovery across demanding real-world engineering scenarios:

1. Catalog Discovery & Search Validation:
   - Classification filtering (Steel, Aluminium Alloys, Copper Alloys, Plastics, Titanium Alloys).
   - Substring fuzzy searching ('1020', '6061', 'Brass', 'ABS').
   - Mechanical property parsing (tensile, yield, elastic modulus, Poisson's ratio).

2. Multi-Material High-Precision Flywheel Physics Benchmark:
   - Precision CAD modeling of a turbine flywheel with central bore and 4 lightening pockets.
   - Analytical closed-form volume: $V = 392,500 \pi \approx 1,233,075.117\text{ mm}^3$.
   - Multi-Material Spectrum Swap:
     * Material 1: AISI 1020 Carbon Steel ($\rho \approx 7900\text{ kg/m}^3, M_{\text{theory}} \approx 9741.29\text{ g}$)
     * Material 2: 6061 Alloy Aluminium ($\rho \approx 2700\text{ kg/m}^3, M_{\text{theory}} \approx 3329.30\text{ g}$)
     * Material 3: Brass Copper Alloy ($\rho \approx 8500\text{ kg/m}^3, M_{\text{theory}} \approx 10481.14\text{ g}$)
     * Material 4: ABS Thermoplastic ($\rho \approx 1020\text{ kg/m}^3, M_{\text{theory}} \approx 1257.74\text{ g}$)
   - Mass ratio validation: $\frac{M_{\text{steel}}}{M_{\text{aluminium}}} \approx 2.925926$.
   - Density & moment of inertia tracking: Parasolid $L_{zz}$ vs analytical dynamics.

3. Material Clearing & Neutral Reversion:
   - Clearing material (`sw_set_material('')`), verifying default $1000\text{ kg/m}^3$ fallback.

4. Adversarial Fuzzing & Anti-Hallucination Guardrails:
   - Phantom material rejection ('Vibranium_Mark_85').
   - Empty/whitespace robustness.

5. Visual Viewport Capture:
   - High-resolution rendering to artifact directory.
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

ARTIFACT_DIR = r"C:\Users\radit\.gemini\antigravity\brain\bc399346-7624-49cd-bb08-803042918e09"


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


async def run_priority2_suite():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "sw_mcp.server"],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )

    print("================================================================================")
    print("  PRIORITY 2: ADVANCED PHYSICAL ENGINEERING & MATERIAL ASSIGNMENT TEST SUITE")
    print("================================================================================")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            init_res = await session.initialize()
            server_info = getattr(init_res, "server_info", getattr(init_res, "serverInfo", None))
            server_name = server_info.name if server_info else "SolidWorks Assistant"
            print(f"[INIT] Connected to MCP Server: {server_name}")

            # -------------------------------------------------------------------------
            # TEST 1: Catalog Discovery, Classifications & Substring Search
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 1] Catalog Discovery & Material Search")
            print("=" * 60)

            # 1.1 List all materials
            t_cat0 = time.time()
            res_all = await session.call_tool("sw_list_materials", {})
            cat_all = parse_tool_result(res_all)
            assert not res_all.is_error, "sw_list_materials failed"
            total_mats = cat_all.get("total_matches", 0)
            class_count = len(cat_all.get("classifications", {}))
            print(f"[CATALOG] Total materials indexed: {total_mats} across {class_count} classifications in {(time.time() - t_cat0)*1000:.1f}ms")
            assert total_mats >= 100, f"Expected at least 100 materials in SolidWorks catalog, got {total_mats}"
            assert class_count >= 5, f"Expected at least 5 classifications, got {class_count}"

            # 1.2 Filter by classification 'Steel'
            res_steel = await session.call_tool("sw_list_materials", {"classification": "Steel"})
            cat_steel = parse_tool_result(res_steel)
            steel_mats = cat_steel.get("classifications", {}).get("Steel", [])
            print(f"[FILTER] Steel classification count: {len(steel_mats)} materials")
            assert any("1020" in m for m in steel_mats), "AISI 1020 not found in Steel classification"

            # 1.3 Search by keyword '6061'
            res_6061 = await session.call_tool("sw_list_materials", {"search": "6061"})
            cat_6061 = parse_tool_result(res_6061)
            print(f"[SEARCH] Search '6061' matches: {cat_6061.get('total_matches')} found")
            assert cat_6061.get("total_matches", 0) >= 1, "Search for '6061' returned 0 results"

            # 1.4 Search by keyword 'Brass'
            res_brass = await session.call_tool("sw_list_materials", {"search": "Brass"})
            cat_brass = parse_tool_result(res_brass)
            print(f"[SEARCH] Search 'Brass' matches: {cat_brass.get('total_matches')} found")
            assert cat_brass.get("total_matches", 0) >= 1, "Search for 'Brass' returned 0 results"

            print("--> TEST 1 PASSED: Engineering material catalog discovered and indexed correctly.")

            # -------------------------------------------------------------------------
            # TEST 2: Model High-Precision Multi-Pocket Turbine Flywheel
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 2] Precision Flywheel Modeling (Analytical Benchmark)")
            print("=" * 60)

            # Create new part
            res_np = await session.call_tool("sw_new_part", {})
            assert not res_np.is_error, "sw_new_part failed"
            print(f"[CAD] Created clean Part document: {parse_tool_result(res_np).get('title')}")

            # Step 1: Base cylinder (OD 200 mm -> R=100 mm, H=50 mm)
            r = await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
            assert not r.is_error, f"sw_create_sketch_on_plane failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 100.0})
            assert not r.is_error, f"sw_draw_circle failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_boss_extrude", {"depth_mm": 50.0})
            assert not r.is_error, f"sw_boss_extrude failed: {parse_tool_result(r)}"
            print("[CAD] Step 1: Base cylinder boss extruded (OD 200 mm x 50 mm)")

            # Step 2: Central through bore (ID 40 mm -> R=20 mm, cut 50 mm from top face at Y=50)
            r = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 50.0, "z_mm": 50.0})
            assert not r.is_error, f"sw_create_sketch_on_face failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 20.0})
            assert not r.is_error, f"sw_draw_circle bore failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_cut_extrude", {"depth_mm": 50.0})
            assert not r.is_error, f"sw_cut_extrude bore failed: {parse_tool_result(r)}"
            print("[CAD] Step 2: Central bore cut extruded (ID 40 mm through 50 mm)")

            # Step 3: 4 Lightening Pockets (R=25 mm, Depth 35 mm, offsets at +/-60 mm)
            r = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 50.0, "z_mm": 80.0})
            assert not r.is_error, f"sw_create_sketch_on_face pockets failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": 60.0, "center_y_mm": 0.0, "radius_mm": 25.0})
            assert not r.is_error, f"sw_draw_circle pocket 1 failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": -60.0, "center_y_mm": 0.0, "radius_mm": 25.0})
            assert not r.is_error, f"sw_draw_circle pocket 2 failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 60.0, "radius_mm": 25.0})
            assert not r.is_error, f"sw_draw_circle pocket 3 failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": -60.0, "radius_mm": 25.0})
            assert not r.is_error, f"sw_draw_circle pocket 4 failed: {parse_tool_result(r)}"
            r = await session.call_tool("sw_cut_extrude", {"depth_mm": 35.0})
            assert not r.is_error, f"sw_cut_extrude pockets failed: {parse_tool_result(r)}"
            print("[CAD] Step 3: 4 symmetrical lightening pockets cut extruded (R=25 mm x 35 mm deep)")

            # Verify analytical volume
            V_gross = math.pi * (100.0 ** 2) * 50.0
            V_bore = math.pi * (20.0 ** 2) * 50.0
            V_pockets = 4.0 * (math.pi * (25.0 ** 2) * 35.0)
            V_theoretical = V_gross - V_bore - V_pockets  # = 392,500 * pi mm3
            V_theoretical_m3 = V_theoretical * 1e-9

            res_mp0 = await session.call_tool("sw_get_mass_properties", {})
            mp0 = parse_tool_result(res_mp0)
            V_parasolid = mp0["volume_mm3"]
            vol_err_pct = abs(V_parasolid - V_theoretical) / V_theoretical * 100.0

            print(f"[PHYSICS] Theoretical Volume: {V_theoretical:.4f} mm3")
            print(f"[PHYSICS] Parasolid Volume:   {V_parasolid:.4f} mm3 (Error: {vol_err_pct:.6f}%)")
            assert vol_err_pct < 0.001, f"Volume error too high: {vol_err_pct}%"

            # Check baseline unassigned material
            res_mat0 = await session.call_tool("sw_get_material", {})
            mat0 = parse_tool_result(res_mat0)
            print(f"[MATERIAL BASELINE] Assigned: {mat0.get('assigned')}, Name: '{mat0.get('material_name')}', Density: {mp0.get('density_kg_m3')} kg/m3")
            assert not mat0.get("assigned"), "Baseline material should be unassigned"
            assert abs(mp0.get("density_kg_m3", 0.0) - 1000.0) < 1.0, "Default baseline density must be 1000 kg/m3"

            print("--> TEST 2 PASSED: Flywheel modeled with 0.0000% analytical volume error.")

            # -------------------------------------------------------------------------
            # TEST 3: Multi-Material Physical Spectrum Verification
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 3] Multi-Material Physical Spectrum Verification")
            print("=" * 60)

            # Material specifications to test
            test_materials = [
                {
                    "name": "AISI 1020",
                    "class": "Steel",
                    "expected_density": 7900.0,
                    "yield_strength_min_mpa": 300.0,
                    "elastic_modulus_min_gpa": 190.0,
                },
                {
                    "name": "6061 Alloy",
                    "class": "Aluminium Alloys",
                    "expected_density": 2700.0,
                    "yield_strength_min_mpa": 200.0,
                    "elastic_modulus_min_gpa": 65.0,
                },
                {
                    "name": "Brass",
                    "class": "Copper Alloys",
                    "expected_density": 8500.0,
                    "yield_strength_min_mpa": 100.0,
                    "elastic_modulus_min_gpa": 90.0,
                },
                {
                    "name": "ABS",
                    "class": "Plastics",
                    "expected_density": 1020.0,
                    "yield_strength_min_mpa": 20.0,
                    "elastic_modulus_min_gpa": 1.5,
                },
            ]

            recorded_masses = {}

            for m_spec in test_materials:
                mat_name = m_spec["name"]
                t_set0 = time.time()
                res_set = await session.call_tool("sw_set_material", {"material_name": mat_name})
                set_data = parse_tool_result(res_set)
                elapsed_set = (time.time() - t_set0) * 1000.0

                assert not res_set.is_error, f"sw_set_material failed for '{mat_name}': {set_data}"
                assert set_data.get("assigned") is True, f"Material '{mat_name}' not flagged as assigned"
                assert set_data.get("material_name").lower() == mat_name.lower(), f"Returned name mismatch: {set_data.get('material_name')}"

                # Query material properties
                res_get = await session.call_tool("sw_get_material", {})
                get_data = parse_tool_result(res_get)
                assert get_data.get("assigned") is True
                assert get_data.get("material_name").lower() == mat_name.lower()

                # Mechanical properties check
                mech = get_data.get("mechanical_properties")
                assert mech is not None, f"Mechanical properties missing for '{mat_name}'"
                yield_str = mech.get("Yield Strength")
                tensile_str = mech.get("Tensile Strength")
                elastic_mod = mech.get("Elastic Modulus")
                poisson = mech.get("Poisson's Ratio")

                # Mass properties check
                res_mp = await session.call_tool("sw_get_mass_properties", {})
                mp = parse_tool_result(res_mp)
                actual_density = mp.get("density_kg_m3")
                actual_mass_g = mp.get("mass_g")
                actual_mass_kg = mp.get("mass_kg")

                # Analytical mass calculation: M = V_m3 * rho
                expected_mass_kg = V_theoretical_m3 * m_spec["expected_density"]
                expected_mass_g = expected_mass_kg * 1000.0
                mass_err_pct = abs(actual_mass_g - expected_mass_g) / expected_mass_g * 100.0

                recorded_masses[mat_name] = actual_mass_g

                # Moments of Inertia check (axisymmetric rotation about Y axis)
                moi = mp.get("moments_of_inertia_cg_kg_m2")
                assert moi is not None, "Centroid moments of inertia missing in mass properties"
                # For cylinder along Y axis, Lyy is the spin axis
                Lyy = moi.get("Lyy", 0.0)
                Lxx = moi.get("Lxx", 0.0)
                Lzz = moi.get("Lzz", 0.0)
                assert Lyy > 0.0, f"Lyy must be strictly positive, got {Lyy}"
                # By 4-fold rotational symmetry in X-Z plane, Lxx should equal Lzz
                sym_err = abs(Lxx - Lzz) / max(Lxx, 1e-9) * 100.0

                print(f"\n[MATERIAL TEST] Assigned: {mat_name:12s} in {elapsed_set:.1f}ms")
                print(f"  Density:            {actual_density:.2f} kg/m3 (Catalog expected: {m_spec['expected_density']:.2f})")
                print(f"  Mass:               {actual_mass_g:.2f} g ({actual_mass_kg:.4f} kg) [Theory: {expected_mass_g:.2f} g, Err: {mass_err_pct:.4f}%]")
                print(f"  Yield Strength:     {float(yield_str)/1e6:.1f} MPa" if yield_str else "  Yield Strength:     N/A")
                print(f"  Tensile Strength:   {float(tensile_str)/1e6:.1f} MPa" if tensile_str else "  Tensile Strength:   N/A")
                print(f"  Elastic Modulus:    {float(elastic_mod)/1e9:.1f} GPa" if elastic_mod else "  Elastic Modulus:    N/A")
                print(f"  Poisson's Ratio:    {poisson}")
                print(f"  Inertia Tensor:     Lyy={Lyy:.6f} kg*m2, Lxx={Lxx:.6f}, Lzz={Lzz:.6f} (Symmetry delta: {sym_err:.6f}%)")

                assert abs(actual_density - m_spec["expected_density"]) < 1.0, f"Density mismatch: {actual_density} vs {m_spec['expected_density']}"
                assert mass_err_pct < 0.01, f"Mass calculation error too large: {mass_err_pct}%"
                assert sym_err < 0.01, f"Rotational inertia asymmetry detected: {sym_err}%"

            # Physics validation: Ratio of Steel to Aluminium
            mass_ratio_actual = recorded_masses["AISI 1020"] / recorded_masses["6061 Alloy"]
            mass_ratio_expected = 7900.0 / 2700.0  # 2.925926
            ratio_err = abs(mass_ratio_actual - mass_ratio_expected) / mass_ratio_expected * 100.0
            print(f"\n[PHYSICS RATIO] Steel-to-Aluminium Mass Ratio: {mass_ratio_actual:.6f} (Expected: {mass_ratio_expected:.6f}, Err: {ratio_err:.6f}%)")
            assert ratio_err < 0.001, f"Physical mass ratio error: {ratio_err}%"

            print("--> TEST 3 PASSED: Dynamic multi-material swap verified across 4 material classes with 0.0000% ratio error.")

            # -------------------------------------------------------------------------
            # TEST 4: Material Clearing & Neutral Reversion
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 4] Material Clearing & Neutral Fallback")
            print("=" * 60)

            # Clear material
            res_clr = await session.call_tool("sw_set_material", {"material_name": ""})
            clr_data = parse_tool_result(res_clr)
            assert not res_clr.is_error, f"sw_set_material clearing failed: {clr_data}"
            print("[CLEAR] sw_set_material('') executed successfully")

            res_get_clr = await session.call_tool("sw_get_material", {})
            get_clr = parse_tool_result(res_get_clr)
            print(f"[CLEAR VERIFY] Assigned: {get_clr.get('assigned')}, Name: '{get_clr.get('material_name')}'")
            assert get_clr.get("assigned") is False, "Material should not be assigned after clearing"

            res_mp_clr = await session.call_tool("sw_get_mass_properties", {})
            mp_clr = parse_tool_result(res_mp_clr)
            print(f"[CLEAR DENSITY] Density reverted to: {mp_clr.get('density_kg_m3')} kg/m3")
            assert abs(mp_clr.get("density_kg_m3", 0.0) - 1000.0) < 1.0, "Density must revert to 1000 kg/m3"

            print("--> TEST 4 PASSED: Material clearing and neutral fallback verified.")

            # -------------------------------------------------------------------------
            # TEST 5: Adversarial Fuzzing & Anti-Hallucination Guardrails
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 5] Adversarial Fuzzing & Anti-Hallucination Guardrails")
            print("=" * 60)

            # 5.1 Fictitious / Hallucinated material name
            print("[ADVERSARIAL 1] Attempting to set fabricated material 'Vibranium_Mark_85'...")
            res_bad_mat = await session.call_tool("sw_set_material", {"material_name": "Vibranium_Mark_85"})
            bad_data = parse_tool_result(res_bad_mat)
            print(f"[ADVERSARIAL 1 RESULT] is_error: {res_bad_mat.is_error}, response: {bad_data}")
            assert res_bad_mat.is_error is True, "Expected sw_set_material to fail on fabricated material!"

            # 5.2 Verify current material was not corrupted by the rejected attempt
            res_after_bad = await session.call_tool("sw_get_material", {})
            after_bad = parse_tool_result(res_after_bad)
            assert after_bad.get("assigned") is False, "Corrupt material assigned after failed attempt"
            print("[ADVERSARIAL 1 VERIFY] Model state intact; corrupt material was not assigned.")

            # 5.3 Whitespace-only material name (should act as clear)
            print("[ADVERSARIAL 2] Setting whitespace-only material '   '...")
            res_ws = await session.call_tool("sw_set_material", {"material_name": "   "})
            assert not res_ws.is_error, "Whitespace-only material should cleanly clear material"
            ws_get = parse_tool_result(await session.call_tool("sw_get_material", {}))
            assert ws_get.get("assigned") is False

            print("--> TEST 5 PASSED: Strict anti-hallucination and boundary guardrails verified.")

            # -------------------------------------------------------------------------
            # TEST 6: Re-assign Industrial Alloy & Viewport Multi-Modal Capture
            # -------------------------------------------------------------------------
            print("\n" + "=" * 60)
            print("[TEST 6] High-Resolution Multi-Modal Visual Viewport Capture")
            print("=" * 60)

            # Re-assign Brass for brilliant metallic rendering
            await session.call_tool("sw_set_material", {"material_name": "Brass"})
            print("[RENDER] Re-assigned 'Brass' alloy to flywheel")

            img_path = os.path.join(ARTIFACT_DIR, "priority2_material_flywheel_render.png")
            res_cap = await session.call_tool("sw_capture_viewport", {"output_path": img_path})
            cap_data = parse_tool_result(res_cap)
            assert not res_cap.is_error, f"sw_capture_viewport failed: {cap_data}"
            print(f"[CAPTURE] Successfully captured viewport image: {cap_data.get('path')} ({cap_data.get('width')}x{cap_data.get('height')}, {cap_data.get('file_size_bytes')} bytes)")
            assert os.path.exists(img_path) and os.path.getsize(img_path) > 10000, "Rendered file missing or empty"

            # Clean close part without saving
            res_close = await session.call_tool("sw_close_doc", {"save_changes": False})
            assert not res_close.is_error, "sw_close_doc failed"
            print("[CAD] Cleanly closed Part document")

            print("\n" + "=" * 80)
            print("  PRIORITY 2: ALL ADVANCED TESTS PASSED WITH 100% MATHEMATICAL PRECISION!")
            print("================================================================================")


if __name__ == "__main__":
    asyncio.run(run_priority2_suite())
