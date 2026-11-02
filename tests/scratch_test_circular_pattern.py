"""Test Circular Pattern using CADSession."""
import math
import pythoncom
import win32com.client
from sw_mcp.cad.session import get_cad_session

def test_circular_pattern():
    sess = get_cad_session()
    doc_mgr = sess.document
    sk = sess.sketcher
    ft = sess.features

    # 1. New Part
    p = doc_mgr.new_part()
    print("New part:", p)

    # 2. Draw base circle Dia 100mm on Front Plane, extrude 20mm
    sk.create_sketch("Front Plane")
    sk.draw_circle(0.0, 0.0, 50.0) # R=50mm
    base = ft.boss_extrude(20.0)
    print("Created base cylinder:", base)

    # 3. Cut Hole at X=35mm, Y=0, Dia=10mm, depth=20mm
    sk.create_sketch("Front Plane")
    sk.draw_circle(35.0, 0.0, 5.0) # R=5mm
    cut = ft.cut_extrude(20.0, flip_dir=True)
    print("Created cut feature:", cut)

    # 4. Circular Pattern around cylinder
    doc = doc_mgr.get_active_doc()
    ext = doc.Extension
    fm = doc.FeatureManager
    doc.ClearSelection2(True)
    v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

    # Mark 1: Cylindrical face at (0.050, 0.0, 0.010)
    s_axis = ext.SelectByID2("", "FACE", 0.050, 0.0, 0.010, False, 1, v_call, 0)
    print("Selected axis (Mark 1):", s_axis)

    # Mark 4: Cut feature
    s_feat = ext.SelectByID2(cut["feature"], "BODYFEATURE", 0, 0, 0, True, 4, v_call, 0)
    print(f"Selected {cut['feature']} (Mark 4):", s_feat)

    pat_feat = fm.FeatureCircularPattern4(
        6,                  # 6 instances
        2 * math.pi,        # 360 degrees
        False,              # Flip direction
        "",                 # DName
        False,              # Geometry pattern
        True,               # Equal spacing
        False               # Vary instance
    )
    print("Created Circular Pattern:", pat_feat.Name if pat_feat else None)
    if pat_feat:
        print("Pattern error code:", pat_feat.GetErrorCode)

    # 5. Measure mass properties to verify 6 holes cut
    mp = sess.inspection.get_mass_properties()
    print("Mass properties with 6 patterned holes:", mp["volume_mm3"])

    # Theoretical volume:
    # Base cylinder: pi * 50^2 * 20 = 50,000 * pi = 157,079.63 mm^3
    # 6 holes: 6 * (pi * 5^2 * 20) = 6 * 500 * pi = 3,000 * pi = 9,424.78 mm^3
    # Net: 47,000 * pi = 147,654.85 mm^3
    expected_vol = 47000.0 * math.pi
    actual_vol = mp["volume_mm3"]
    err_pct = abs(actual_vol - expected_vol) / expected_vol * 100.0
    print(f"Theoretical Volume: {expected_vol:.2f} mm^3 | Actual: {actual_vol:.2f} mm^3 | Error: {err_pct:.4f}%")

    doc_mgr.close_active_doc(save=False)

if __name__ == "__main__":
    test_circular_pattern()
