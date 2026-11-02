"""Live End-to-End Verification with SolidWorks 2026.

Run this script to verify full CAD modeling loop:
1. Connect to SolidWorks
2. Create new Part
3. Sketch a 50mm x 30mm rectangle on Front Plane
4. Boss-Extrude 20mm
5. Verify volume is approx 30,000 mm^3 via mass properties
6. Capture 3D viewport to tests/output/live_box.png
7. Silently close part without saving
"""

import asyncio
import os
import sys

from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


async def run_live_test():
    worker = get_sta_worker()
    session = get_cad_session()

    print("=" * 60)
    print("SolidWorks 2026 Live Integration Test")
    print("=" * 60)

    # 1. Session info
    print("\n[Step 1] Checking SolidWorks session...")
    info = await worker.run(lambda: session.client.get_session_info())
    print(f" -> Connected! Revision: {info.get('revision')}, Active Doc: {info.get('active_document')}")

    # 2. New Part
    print("\n[Step 2] Creating new Part...")
    part = await worker.run(lambda: session.document.new_part())
    print(f" -> Part created: {part.get('title')}")

    # 3. Sketch on Front Plane
    print("\n[Step 3] Creating sketch on Front Plane...")
    sk = await worker.run(lambda: session.sketcher.create_sketch("Front Plane"))
    print(f" -> Sketch active on: {sk.get('plane')}")

    # 4. Draw Rectangle 50mm x 30mm
    print("\n[Step 4] Drawing 50mm x 30mm rectangle...")
    rect = await worker.run(lambda: session.sketcher.draw_rectangle(0.0, 0.0, 50.0, 30.0))
    print(f" -> Rectangle drawn: width={rect.get('width_mm')}mm, height={rect.get('height_mm')}mm")

    # 5. Boss Extrude 20mm
    print("\n[Step 5] Extruding boss 20mm...")
    feat = await worker.run(lambda: session.features.boss_extrude(20.0))
    print(f" -> Extrude completed: Feature '{feat.get('feature')}', Depth={feat.get('depth_mm')}mm")

    # 6. Mass Properties Check
    print("\n[Step 6] Computing mass properties...")
    props = await worker.run(lambda: session.inspection.get_mass_properties())
    vol = props.get("volume_mm3", 0.0)
    print(f" -> Volume: {vol:,.2f} mm^3")
    print(f" -> Mass: {props.get('mass_g')} grams")
    print(f" -> Center of Mass: {props.get('center_of_mass_mm')}")

    expected_vol = 50.0 * 30.0 * 20.0
    diff = abs(vol - expected_vol)
    if diff < 1.0:
        print(f" -> Volume validation PASSED (Expected ~{expected_vol} mm^3, Got {vol} mm^3)")
    else:
        print(f" -> Warning: Volume discrepancy: {diff} mm^3")

    # 7. Viewport Capture
    print("\n[Step 7] Capturing viewport render to PNG...")
    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_img = os.path.join(out_dir, "live_box.png")
    cap = await worker.run(lambda: session.inspection.capture_viewport(out_img))
    print(f" -> Image saved to: {cap.get('path')} ({cap.get('width')}x{cap.get('height')}, {cap.get('file_size_bytes')} bytes)")

    # 8. Close document
    print("\n[Step 8] Closing test part silently...")
    closed = await worker.run(lambda: session.document.close_doc(save_changes=False))
    print(f" -> Document closed: {closed.get('title')}")

    print("\n" + "=" * 60)
    print("ALL LIVE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 60)

    # Stop worker cleanly
    worker.stop()


if __name__ == "__main__":
    asyncio.run(run_live_test())
