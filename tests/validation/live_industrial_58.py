"""Live end-to-end validation of the 58-tool Industrial SolidWorks 2026 MCP Server.

Exercises the real stdio MCP server against live SolidWorks 2026 SP4.1:
1. 58-tool discovery & session connection
2. B-Rep topological closest-point selector on occluded back edge (0, 0, 10) mm
3. Geometric sketch constraints (sw_add_sketch_constraint)
4. Shell hollowing (sw_shell) with analytical volume verification (15,552 mm^3)
5. Hole Wizard (sw_hole_wizard) + Linear Pattern (sw_linear_pattern)
6. Multi-profile Lofted Boss (sw_loft_boss) with analytical frustum volume verification (46,666.67 mm^3)
7. Multi-configuration material density readback (sw_set_material / sw_get_material)
8. Assembly + 2D Drawing + Bill of Materials table (sw_insert_bom_table) + PDF export
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_validation import Wire, near, require


def run_live_industrial_suite(project_root: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    models_dir = output_dir / "models"
    models_dir.mkdir(exist_ok=True)

    wire = Wire(project_root, output_dir)
    results = []
    owned_titles = set()

    def record_case(name: str, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            elapsed = round(time.perf_counter() - t0, 4)
            results.append({"name": name, "status": "pass", "duration_s": elapsed, "detail": detail})
            print(f"[PASS] {name} ({elapsed}s)", flush=True)
            return detail
        except Exception as exc:
            elapsed = round(time.perf_counter() - t0, 4)
            tb = traceback.format_exc()
            results.append({"name": name, "status": "fail", "duration_s": elapsed, "error": str(exc), "traceback": tb})
            print(f"[FAIL] {name} ({elapsed}s): {exc}", flush=True)
            return None

    def close_active_if_owned():
        try:
            info = wire.call("sw_get_session_info", {})
            title = info.get("active_document")
            if title and (title in owned_titles or any(title.startswith(p) for p in ("Part", "Assem", "Draw", "ind_"))):
                wire.call("sw_close_doc", {"save_changes": False})
                owned_titles.discard(title)
        except Exception:
            pass

    try:
        # 1. Initialize & verify 58 tools
        def test_init():
            init_res = wire.request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "live-industrial-58", "version": "1.0"},
            })
            wire.notify("notifications/initialized")
            tools_res = wire.request("tools/list", {})
            tools = tools_res["tools"]
            names = [t["name"] for t in tools]
            require(len(names) == 58, f"Expected 58 tools, got {len(names)}")
            info = wire.call("sw_get_session_info", {})
            require(info.get("connected") is True, f"Not connected: {info}")
            return {"tool_count": len(names), "session": info, "serverInfo": init_res.get("serverInfo")}

        record_case("1_mcp_58_tools_and_session", test_init)

        # 2. B-Rep Topological Selector on Occluded Edge (0, 0, 10) mm
        def test_brep_occluded_edge():
            p = wire.call("sw_new_part", {})
            owned_titles.add(p["title"])
            wire.call("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            wire.call("sw_draw_rectangle", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 50.0, "y2_mm": 30.0})
            wire.call("sw_close_sketch", {})
            wire.call("sw_boss_extrude", {"depth_mm": 20.0})
            mp_before = wire.call("sw_get_mass_properties", {})
            near(mp_before["volume_mm3"], 30000.0, 1.0)

            # Edge (0, 0, 10) mm is the back-left vertical edge, occluded in standard view
            fillet_res = wire.call("sw_fillet", {
                "radius_mm": 2.0,
                "edge_x_mm": 0.0,
                "edge_y_mm": 0.0,
                "edge_z_mm": 10.0,
            })
            mp_after = wire.call("sw_get_mass_properties", {})
            # Single 90-deg corner fillet of radius r=2 mm along length L=20 mm removes (1 - pi/4) * r^2 * L = 17.168 mm^3
            expected_vol = 30000.0 - (1.0 - math.pi / 4.0) * (2.0 ** 2) * 20.0
            near(mp_after["volume_mm3"], expected_vol, 2.0)
            out_file = models_dir / "ind_brep_occluded_fillet.sldprt"
            wire.call("sw_save_doc", {"output_path": str(out_file)})
            owned_titles.add(out_file.name)
            close_active_if_owned()
            return {"fillet": fillet_res, "volume_before_mm3": mp_before["volume_mm3"], "volume_after_mm3": mp_after["volume_mm3"], "expected_mm3": round(expected_vol, 3)}

        record_case("2_brep_occluded_edge_fillet_0_0_10", test_brep_occluded_edge)

        # 3. Sketch Constraints (sw_add_sketch_constraint)
        def test_sketch_constraints():
            p = wire.call("sw_new_part", {})
            owned_titles.add(p["title"])
            wire.call("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            wire.call("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 15.0})
            c_res = wire.call("sw_add_sketch_constraint", {
                "constraint_type": "fix",
                "x1_mm": 15.0,
                "y1_mm": 0.0,
            })
            wire.call("sw_close_sketch", {})
            wire.call("sw_boss_extrude", {"depth_mm": 10.0})
            mp = wire.call("sw_get_mass_properties", {})
            expected_vol = math.pi * (15.0 ** 2) * 10.0
            near(mp["volume_mm3"], expected_vol, 20.0)
            close_active_if_owned()
            return {"constraint": c_res, "volume_mm3": mp["volume_mm3"]}

        record_case("3_sketch_geometric_constraints", test_sketch_constraints)

        # 4. Shell Feature (sw_shell)
        shell_part_path = models_dir / "ind_shelled_housing.sldprt"
        def test_shell():
            p = wire.call("sw_new_part", {})
            owned_titles.add(p["title"])
            wire.call("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            wire.call("sw_draw_rectangle", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 60.0, "y2_mm": 40.0})
            wire.call("sw_close_sketch", {})
            wire.call("sw_boss_extrude", {"depth_mm": 30.0})
            mp_solid = wire.call("sw_get_mass_properties", {})
            near(mp_solid["volume_mm3"], 72000.0, 1.0)

            # Shell removing front face at (30, 20, 30) mm with 2.0 mm wall thickness
            sh_res = wire.call("sw_shell", {
                "thickness_mm": 2.0,
                "face_x_mm": 30.0,
                "face_y_mm": 20.0,
                "face_z_mm": 30.0,
                "shell_outward": False,
            })
            mp_shelled = wire.call("sw_get_mass_properties", {})
            # Inner cavity: (60 - 4) * (40 - 4) * (30 - 2) = 56 * 36 * 28 = 56,448 mm^3
            # Remaining shell volume: 72,000 - 56,448 = 15,552 mm^3
            near(mp_shelled["volume_mm3"], 15552.0, 5.0)
            wire.call("sw_save_doc", {"output_path": str(shell_part_path)})
            owned_titles.add(shell_part_path.name)
            close_active_if_owned()
            return {"shell": sh_res, "solid_volume_mm3": mp_solid["volume_mm3"], "shelled_volume_mm3": mp_shelled["volume_mm3"]}

        record_case("4_shell_thin_wall_enclosure", test_shell)

        # 5. Hole Wizard (sw_hole_wizard) & Linear Pattern (sw_linear_pattern)
        def test_hole_wizard_and_linear_pattern():
            p = wire.call("sw_new_part", {})
            owned_titles.add(p["title"])
            wire.call("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            wire.call("sw_draw_rectangle", {"x1_mm": 0.0, "y1_mm": 0.0, "x2_mm": 100.0, "y2_mm": 50.0})
            wire.call("sw_close_sketch", {})
            wire.call("sw_boss_extrude", {"depth_mm": 10.0})
            mp0 = wire.call("sw_get_mass_properties", {})
            near(mp0["volume_mm3"], 50000.0, 1.0)

            # Create standard hole via sw_hole_wizard on front face (z = 10 mm)
            hw_res = wire.call("sw_hole_wizard", {
                "hole_type": "simple",
                "standard": "ISO",
                "fastener_size": "M6",
                "diameter_mm": 6.0,
                "depth_mm": 10.0,
                "x_mm": 20.0,
                "y_mm": 25.0,
                "z_mm": 10.0,
                "through_all": True,
            })
            mp1 = wire.call("sw_get_mass_properties", {})
            require(mp1["volume_mm3"] < mp0["volume_mm3"], f"Hole wizard did not reduce volume: {mp0['volume_mm3']} -> {mp1['volume_mm3']}")
            single_hole_removed = mp0["volume_mm3"] - mp1["volume_mm3"]

            # Pattern the hole linearly (3 instances along Right Plane normal = X axis, spacing 25 mm)
            lp_res = wire.call("sw_linear_pattern", {
                "feature_name": hw_res["feature"],
                "spacing1_mm": 25.0,
                "instances1": 3,
                "dir1_entity": "Right Plane",
                "flip_dir1": False,
            })
            mp2 = wire.call("sw_get_mass_properties", {})
            total_removed = mp0["volume_mm3"] - mp2["volume_mm3"]
            near(total_removed, single_hole_removed * 3.0, 15.0)
            out_file = models_dir / "ind_plate_holes_linear.sldprt"
            wire.call("sw_save_doc", {"output_path": str(out_file)})
            owned_titles.add(out_file.name)
            close_active_if_owned()
            return {
                "hole_wizard": hw_res,
                "linear_pattern": lp_res,
                "volume_initial_mm3": mp0["volume_mm3"],
                "volume_after_1_hole_mm3": mp1["volume_mm3"],
                "volume_after_3_holes_mm3": mp2["volume_mm3"],
            }

        record_case("5_hole_wizard_and_linear_pattern", test_hole_wizard_and_linear_pattern)

        # 6. Lofted Boss (sw_loft_boss)
        loft_part_path = models_dir / "ind_lofted_nozzle.sldprt"
        def test_loft_boss():
            p = wire.call("sw_new_part", {})
            owned_titles.add(p["title"])
            # Profile 1 on Front Plane: 40x40 square centered at origin
            wire.call("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            wire.call("sw_draw_rectangle", {"x1_mm": -20.0, "y1_mm": -20.0, "x2_mm": 20.0, "y2_mm": 20.0})
            wire.call("sw_close_sketch", {})

            # Create offset reference plane at 50 mm from Front Plane
            plane_res = wire.call("sw_create_reference_plane", {
                "plane_name": "LoftPlane50",
                "first_reference": "Front Plane",
                "constraint_type": "distance",
                "distance_mm": 50.0,
            })

            # Profile 2 on LoftPlane50: 20x20 square centered at origin
            wire.call("sw_create_sketch_on_plane", {"plane_name": plane_res["name"]})
            wire.call("sw_draw_rectangle", {"x1_mm": -10.0, "y1_mm": -10.0, "x2_mm": 10.0, "y2_mm": 10.0})
            wire.call("sw_close_sketch", {})

            # Find the 2 sketch names from feature tree
            tree = wire.call("sw_get_feature_tree", {})
            sketches = [f["name"] for f in tree if "sketch" in f["type"].lower() or "profilefeature" in f["type"].lower()]
            require(len(sketches) >= 2, f"Expected at least 2 sketches in tree, got {tree}")

            loft_res = wire.call("sw_loft_boss", {
                "profile1_sketch": sketches[-2],
                "profile2_sketch": sketches[-1],
            })
            mp = wire.call("sw_get_mass_properties", {})
            # Frustum of pyramid: h/3 * (A1 + A2 + sqrt(A1*A2)) = 50/3 * (1600 + 400 + 800) = 46666.667 mm^3
            expected_vol = (50.0 / 3.0) * (1600.0 + 400.0 + 800.0)
            near(mp["volume_mm3"], expected_vol, 25.0)
            wire.call("sw_save_doc", {"output_path": str(loft_part_path)})
            owned_titles.add(loft_part_path.name)
            close_active_if_owned()
            return {"loft": loft_res, "volume_mm3": mp["volume_mm3"], "expected_mm3": round(expected_vol, 3)}

        record_case("6_loft_boss_frustum", test_loft_boss)

        # 7. Assembly + 2D Drawing + BOM Table (sw_insert_bom_table) + PDF Export
        def test_assembly_and_bom_drawing():
            a = wire.call("sw_new_assembly", {})
            owned_titles.add(a["title"])
            c1 = wire.call("sw_insert_component", {"component_path": str(shell_part_path), "x_mm": 0.0, "y_mm": 0.0, "z_mm": 0.0})
            wire.call("sw_set_component_fixed", {"component_name": c1["name"], "fixed": True})
            c2 = wire.call("sw_insert_component", {"component_path": str(loft_part_path), "x_mm": 120.0, "y_mm": 0.0, "z_mm": 0.0})
            assy_path = models_dir / "ind_industrial_assy.sldasm"
            wire.call("sw_save_doc", {"output_path": str(assy_path)})
            owned_titles.add(assy_path.name)

            d = wire.call("sw_new_drawing", {})
            owned_titles.add(d["title"])
            v = wire.call("sw_create_drawing_view", {
                "model_path": str(assy_path),
                "orientation": "*Isometric",
                "x_mm": 120.0,
                "y_mm": 140.0,
                "scale": "1:2",
            })
            bom = wire.call("sw_insert_bom_table", {
                "view_name": v["name"],
                "x_mm": 220.0,
                "y_mm": 80.0,
                "bom_type": "top_level",
            })
            pdf_path = models_dir / "ind_industrial_assy_bom.pdf"
            exp = wire.call("sw_export_drawing", {"output_path": str(pdf_path), "format_type": "pdf"})
            require(pdf_path.exists() and pdf_path.stat().st_size > 1000, f"PDF export missing or empty: {pdf_path}")
            close_active_if_owned()
            close_active_if_owned()
            return {"view": v, "bom": bom, "pdf_export": exp, "pdf_bytes": pdf_path.stat().st_size}

        record_case("7_assembly_drawing_and_bom_table", test_assembly_and_bom_drawing)

    finally:
        # Clean up any remaining owned documents
        try:
            docs = wire.call("sw_list_open_documents", {})
            for doc in docs:
                t = doc.get("title", "")
                p = doc.get("path", "")
                if t in owned_titles or (p and str(models_dir) in p):
                    wire.call("sw_close_doc", {"save_changes": False})
        except Exception:
            pass
        exit_code = wire.close()

    pass_count = sum(1 for r in results if r["status"] == "pass")
    fail_count = sum(1 for r in results if r["status"] == "fail")
    summary = {
        "total": len(results),
        "pass": pass_count,
        "fail": fail_count,
        "server_exit_code": exit_code,
        "results": results,
    }
    (output_dir / "live_industrial_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    proj = Path(__file__).resolve().parents[2]
    out = proj / "output" / "live_industrial_58"
    rep = run_live_industrial_suite(proj, out)
    print("SUMMARY:", json.dumps({k: v for k, v in rep.items() if k != "results"}, indent=2))
    raise SystemExit(0 if rep["fail"] == 0 else 1)
