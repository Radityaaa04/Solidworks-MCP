"""Test CreateSectionView on a live drawing."""
import os
import win32com.client
import pythoncom
from sw_mcp.cad.session import get_cad_session

def test_section_view():
    sess = get_cad_session()
    drw_mgr = sess.drawing
    doc_mgr = sess.document
    app = sess.client.app

    # 1. We have our housing model or test_circ_pat.sldprt
    model_path = os.path.abspath(r"tests\output\p3_pillow_housing.sldprt")
    assert os.path.exists(model_path)

    # 2. Create new drawing
    drw_res = drw_mgr.new_drawing()
    print("New drawing:", drw_res["title"])
    draw_doc = drw_mgr.get_active_drawing()

    # 3. Create Front View at X=100mm, Y=100mm
    v_front = drw_mgr.create_drawing_view(
        model_path=model_path,
        orientation="*Front",
        x_mm=100.0,
        y_mm=100.0,
        scale="1:2"
    )
    print("Front view created:", v_front["name"])

    # 4. Activate Front View and draw a vertical section cutting line through the center
    draw_doc.ActivateView(v_front["name"])
    
    # In sheet coordinates, Front View is at (0.100, 0.100) m
    # Let's draw a line from (0.100, 0.060) to (0.100, 0.140)
    line = draw_doc.CreateLine2(0.100, 0.060, 0.0, 0.100, 0.140, 0.0)
    print("Created cut line:", line is not None)

    # 5. Create Section View at X=200mm, Y=100mm
    # CreateSectionViewAt5(X, Y, Z, SectionLabel, Options, ExcludedComponents, SectionDepth)
    # Options: 0 = default, ExcludedComponents = dispatch None, SectionDepth = 0.0
    v_disp_none = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    
    sec_view = None
    try:
        sec_view = draw_doc.CreateSectionViewAt5(0.200, 0.100, 0.0, "A", 0, v_disp_none, 0.0)
    except Exception as e:
        print("CreateSectionViewAt5 error:", e)
        try:
            # Fallback to CreateSectionViewAt2
            sec_view = draw_doc.CreateSectionViewAt2(0.200, 0.100, 0.0, False, False, "A", False, True, False, False)
        except Exception as e2:
            print("CreateSectionViewAt2 error:", e2)

    print("Created Section View:", sec_view.GetName2 if sec_view else None)

    # List all views on sheet to verify SECTION A-A is present
    views = drw_mgr.list_drawing_views()
    for v in views:
        print(f" -> View: {v['name']} ({v['type']}) at {v['position_mm']} mm")

    # Export PDF to inspect
    out_pdf = os.path.abspath(r"tests\output\test_section_view.pdf")
    exp = drw_mgr.export_drawing(out_pdf, "pdf")
    print("Exported PDF:", exp)

    app.CloseDoc(draw_doc.GetTitle)

if __name__ == "__main__":
    test_section_view()
