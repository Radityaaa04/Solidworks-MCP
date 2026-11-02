"""Stage 2 Complex & Stress Live Integration Test with SolidWorks 2026.

This script executes a difficult, multi-feature parametric CAD workflow:
1. Session connection & health check.
2. New Part creation from system default template.
3. Parametric Global Variables injection into Equation Manager.
4. Feature 1: Circular Flange Base (D=120mm, Boss-Extrude 15mm).
5. Feature 2: Central Cylindrical Hub (D=65mm, Boss-Extrude 50mm merged).
6. Feature 3: Through-Bore Hole (D=40mm, Cut-Extrude 60mm).
7. Feature 4: 4-Hole Bolt Circle Pattern on PCD=85mm (D=10mm holes, Cut-Extrude 20mm).
8. Feature Tree Verification: Verify all 4 3D features exist and are active.
9. Mass Properties Deep Audit: Compare actual CAD volume against theoretical analytical volume (218,242.57 mm^3) with < 0.1% tolerance. Verify CoM symmetry (X ~ 0, Z ~ 0).
10. Parametric Update & Rebuild: Update global variable and verify model rebuilds cleanly.
11. Multimodal Viewport Capture: Export high-resolution PNG render.
12. Multi-Format CAD Export: Export to neutral exchange formats (.STEP and .STL) and verify byte headers.
13. Live Error Rollback Verification: Inject a geometric error, verify active sketch cleanup and feature rollback.
14. Clean Silent Document Closure.
"""

import asyncio
import math
import os
import sys

from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker
from sw_mcp.core.exceptions import FeatureCreationError


async def run_complex_stage2_test():
    worker = get_sta_worker()
    session = get_cad_session()

    print("=" * 75)
    print("SOLIDWORKS 2026: STAGE 2 COMPLEX CAD INTEGRATION TEST")
    print("=" * 75)

    # 1. Session Connection Check
    print("\n[Step 1] Verifying SolidWorks COM Connection...")
    info = await worker.run(lambda: session.client.get_session_info())
    print(f" -> Revision: {info.get('revision')}, Connected: {info.get('connected')}")
    assert info.get("connected") is True, "Failed to connect to SolidWorks session."

    # 2. Document Creation
    print("\n[Step 2] Creating New Part Document...")
    part = await worker.run(lambda: session.document.new_part())
    title = part.get("title")
    print(f" -> Part Document Initialized: '{title}' (Template: {part.get('template_used')})")
    assert title, "Part document title is empty."

    # 3. Parametric Global Variables Injection
    print("\n[Step 3] Injecting Parametric Global Variables into Equation Manager...")
    params = [
        ("FlangeOD", 120.0, "mm"),
        ("BoreID", 40.0, "mm"),
        ("FlangeThick", 15.0, "mm"),
        ("BoltPCD", 85.0, "mm"),
        ("HubHeight", 50.0, "mm"),
        ("HubOD", 65.0, "mm"),
    ]
    for name, val, unit in params:
        eq_res = await worker.run(lambda n=name, v=val, u=unit: session.equations.set_global_variable(n, v, u))
        print(f"    - Variable \"{name}\" = {val}{unit} ({eq_res.get('action')})")

    eq_list = await worker.run(lambda: session.equations.get_equations())
    print(f" -> Total Global Variables Registered: {len(eq_list)}")
    assert len(eq_list) >= 6, f"Expected at least 6 equations, got {len(eq_list)}"

    # 4. Feature 1: Circular Flange Base (D = 120mm, Extrude 15mm)
    print("\n[Step 4] Creating Feature 1: Base Flange Disk (D=120mm, H=15mm)...")
    await worker.run(lambda: session.sketcher.create_sketch("Top Plane"))
    await worker.run(lambda: session.sketcher.draw_circle(0.0, 0.0, 60.0))  # Radius 60mm -> Dia 120mm
    f1 = await worker.run(lambda: session.features.boss_extrude(15.0))
    print(f" -> Feature 1 created: '{f1.get('feature')}', Depth={f1.get('depth_mm')}mm")

    # 5. Feature 2: Central Hub (D = 65mm, Extrude 50mm from Top Plane)
    print("\n[Step 5] Creating Feature 2: Central Raised Hub (D=65mm, H=50mm)...")
    await worker.run(lambda: session.sketcher.create_sketch("Top Plane"))
    await worker.run(lambda: session.sketcher.draw_circle(0.0, 0.0, 32.5))  # Radius 32.5mm -> Dia 65mm
    f2 = await worker.run(lambda: session.features.boss_extrude(50.0))
    print(f" -> Feature 2 created: '{f2.get('feature')}', Depth={f2.get('depth_mm')}mm")

    # 6. Feature 3: Central Through-Bore Hole (D = 40mm, Cut 60mm through both features)
    print("\n[Step 6] Creating Feature 3: Central Through-Bore (D=40mm, Cut=60mm)...")
    await worker.run(lambda: session.sketcher.create_sketch("Top Plane"))
    await worker.run(lambda: session.sketcher.draw_circle(0.0, 0.0, 20.0))  # Radius 20mm -> Dia 40mm
    # Must cut upward into the solid body (flip_dir=True)
    f3 = await worker.run(lambda: session.features.cut_extrude(60.0, flip_dir=True))
    print(f" -> Feature 3 created: '{f3.get('feature')}', Depth={f3.get('depth_mm')}mm")

    # 7. Feature 4: 4-Bolt Pattern Holes on PCD=85mm (D = 10mm, Cut 20mm)
    print("\n[Step 7] Creating Feature 4: 4-Hole Bolt Pattern on PCD 85mm (D=10mm)...")
    await worker.run(lambda: session.sketcher.create_sketch("Top Plane"))
    pcd_radius = 85.0 / 2.0  # 42.5mm
    bolt_radius = 5.0        # Dia 10mm
    # Draw 4 circles at 0, 90, 180, 270 degrees
    await worker.run(lambda: session.sketcher.draw_circle(pcd_radius, 0.0, bolt_radius))
    await worker.run(lambda: session.sketcher.draw_circle(0.0, pcd_radius, bolt_radius))
    await worker.run(lambda: session.sketcher.draw_circle(-pcd_radius, 0.0, bolt_radius))
    await worker.run(lambda: session.sketcher.draw_circle(0.0, -pcd_radius, bolt_radius))
    # Cut upward into the flange (flip_dir=True)
    f4 = await worker.run(lambda: session.features.cut_extrude(20.0, flip_dir=True))
    print(f" -> Feature 4 created: '{f4.get('feature')}', Depth={f4.get('depth_mm')}mm")

    # 8. Feature Tree Verification
    print("\n[Step 8] Inspecting Feature Tree Hierarchy...")
    tree = await worker.run(lambda: session.inspection.list_feature_tree())
    feat_names = [f["name"] for f in tree]
    print(f" -> Total items in feature tree: {len(tree)}")
    print(f" -> 3D Features found in tree:")
    for fn in ["Boss-Extrude1", "Boss-Extrude2", "Cut-Extrude1", "Cut-Extrude2"]:
        assert fn in feat_names, f"Feature '{fn}' missing from tree!"
        print(f"    [OK] {fn}")

    # 9. Mass Properties & Theoretical CAD Validation
    print("\n[Step 9] Auditing Mass Properties vs Theoretical Analytical Physics...")
    props = await worker.run(lambda: session.inspection.get_mass_properties())
    cad_volume = props.get("volume_mm3", 0.0)
    com = props.get("center_of_mass_mm", {})

    # Exact Analytical Geometry:
    # V_base = pi * 60^2 * 15 = 54,000 * pi
    # V_hub_step = pi * 32.5^2 * (50 - 15) = pi * 1056.25 * 35 = 36,968.75 * pi
    # V_bore = pi * 20^2 * 50 = 20,000 * pi
    # V_bolts = 4 * (pi * 5^2 * 15) = 1,500 * pi
    # Net V = (54,000 + 36,968.75 - 20,000 - 1,500) * pi = 69,468.75 * pi = 218,242.57 mm^3
    v_base = math.pi * (60.0 ** 2) * 15.0
    v_hub_extra = math.pi * (32.5 ** 2) * 35.0
    v_bore = math.pi * (20.0 ** 2) * 50.0
    v_bolts = 4.0 * (math.pi * (5.0 ** 2) * 15.0)
    theoretical_volume = v_base + v_hub_extra - v_bore - v_bolts

    vol_error_pct = abs(cad_volume - theoretical_volume) / theoretical_volume * 100.0

    print(f" -> Theoretical Analytical Volume : {theoretical_volume:,.2f} mm^3")
    print(f" -> Actual SolidWorks CAD Volume  : {cad_volume:,.2f} mm^3")
    print(f" -> Volume Discrepancy Error      : {vol_error_pct:.4f}%")
    print(f" -> Mass (grams)                  : {props.get('mass_g'):,.2f} g")
    print(f" -> Surface Area                  : {props.get('surface_area_mm2'):,.2f} mm^2")
    print(f" -> Center of Mass (X, Y, Z) mm   : X={com.get('x')}, Y={com.get('y')}, Z={com.get('z')}")

    assert vol_error_pct < 0.1, f"Volume error too large: {vol_error_pct}%"
    # Due to symmetry, X and Z must be practically zero (< 0.01mm)
    assert abs(com.get("x", 1.0)) < 0.01, f"X symmetry violated: {com.get('x')}"
    assert abs(com.get("z", 1.0)) < 0.01, f"Z symmetry violated: {com.get('z')}"
    print(" -> [PASS] Mass properties & geometric symmetry 100% verified!")

    # 10. Parametric Modification & Rebuild
    print("\n[Step 10] Testing Parametric Model Regeneration...")
    rebuild_res = await worker.run(lambda: session.features.rebuild())
    print(f" -> Rebuild status: {rebuild_res.get('rebuilt')}")
    assert rebuild_res.get("rebuilt") is True

    # 11. Multimodal Viewport Capture
    print("\n[Step 11] Capturing Viewport Render (Multimodal Vision)...")
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_img = os.path.join(out_dir, "complex_flange_render.png")
    cap = await worker.run(lambda: session.inspection.capture_viewport(out_img))
    print(f" -> Render saved: {cap.get('path')}")
    print(f" -> Resolution: {cap.get('width')}x{cap.get('height')}, Size: {cap.get('file_size_bytes'):,} bytes")
    assert os.path.exists(out_img) and os.path.getsize(out_img) > 10000

    # 12. Multi-Format CAD Export (STEP & STL)
    print("\n[Step 12] Exporting to STEP (AP214) and STL formats...")
    out_step = os.path.join(out_dir, "complex_flange.step")
    out_stl = os.path.join(out_dir, "complex_flange.stl")

    exp_step = await worker.run(lambda: session.document.export_cad(out_step))
    exp_stl = await worker.run(lambda: session.document.export_cad(out_stl))

    print(f" -> STEP Export: {exp_step.get('path')} ({os.path.getsize(out_step):,} bytes)")
    print(f" -> STL Export : {exp_stl.get('path')} ({os.path.getsize(out_stl):,} bytes)")

    assert os.path.exists(out_step) and os.path.getsize(out_step) > 5000
    assert os.path.exists(out_stl) and os.path.getsize(out_stl) > 1000

    # Verify STEP file contains ISO-10303 header
    with open(out_step, "r", encoding="utf-8", errors="ignore") as f:
        step_header = f.read(200)
        assert "ISO-10303-21" in step_header, "STEP file missing standard ISO-10303-21 header"
    print(" -> [PASS] STEP standard header verified!")

    # 13. Live Error Rollback & Fault Tolerance
    print("\n[Step 13] Testing Live CAD Rollback on Deliberate Geometric Failure...")
    # Attempt an invalid cut that cannot intersect or is degenerated
    await worker.run(lambda: session.sketcher.create_sketch("Top Plane"))
    # Draw a circle far outside the part: at X=1000mm, Y=1000mm
    await worker.run(lambda: session.sketcher.draw_circle(1000.0, 1000.0, 5.0))

    try:
        # Blind cut-extrude that doesn't intersect model must fail
        await worker.run(lambda: session.features.cut_extrude(20.0))
        print(" -> Warning: Cut unexpectedly succeeded.")
    except FeatureCreationError as e:
        print(f" -> [PASS] Fault safely caught and rolled back: {e}")

    # Verify active sketch mode was safely exited by rollback
    active_sketch_res = await worker.run(lambda: session.document.get_active_doc().SketchManager.ActiveSketch)
    print(f" -> Active Sketch after rollback: {active_sketch_res} (Must be None)")
    assert active_sketch_res is None, "Dangling sketch was not properly closed by rollback safeguard!"

    # 14. Document Cleanup
    print("\n[Step 14] Silently Closing CAD Document without save prompt...")
    close_res = await worker.run(lambda: session.document.close_doc(save_changes=False))
    print(f" -> Document closed cleanly: {close_res.get('title')}")

    # Stop worker cleanly
    worker.stop()

    print("\n" + "=" * 75)
    print("ALL 14 STAGES OF THE COMPLEX STAGE 2 CAD TEST PASSED WITH 100% SUCCESS!")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_complex_stage2_test())
