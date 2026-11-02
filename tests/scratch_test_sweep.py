"""Test Swept Boss using CreateDefinition(17)."""
import os
import win32com.client
import pythoncom
from sw_mcp.cad.session import get_cad_session

def test_sweep():
    sess = get_cad_session()
    doc_mgr = sess.document
    sk = sess.sketcher
    ft = sess.features
    app = sess.client.app

    # 1. New Part
    p = doc_mgr.new_part()
    print("New part:", p["title"])
    doc = doc_mgr.get_active_doc()
    ext = doc.Extension
    sm = doc.SketchManager
    fm = doc.FeatureManager

    # 2. Create a Path sketch on Front Plane: An arc or spline or line
    # Let's draw an arc: from (0,0) to (50, 50) mm
    sk.create_sketch("Front Plane")
    sk.draw_arc(0.0, 0.0, 50.0, 50.0, 0.0, 50.0) # start, end, center
    doc.SketchManager.InsertSketch(True) # Exit path sketch
    path_sketch_name = "Sketch1"
    print("Path sketch created:", path_sketch_name)

    # 3. Create Sweep Definition (17 = swFmSweep)
    v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    sweep_data = fm.CreateDefinition(17) # swFmSweep = 17
    print("SweepData created:", type(sweep_data))

    path_feat = doc.FeatureByName(path_sketch_name)
    print("Found path feature:", path_feat.Name if path_feat else None)

    sweep_data.CircularProfile = True
    sweep_data.CircularProfileDiameter = 0.010 # 10mm diameter tube / rod
    sweep_data.Path = path_feat
    
    # Create the feature
    sweep_feat = fm.CreateFeature(sweep_data)
    print("Created Sweep Feature:", sweep_feat.Name if sweep_feat else None)
    if sweep_feat:
        print("Sweep error code:", sweep_feat.GetErrorCode)

    # Check volume
    mp = sess.inspection.get_mass_properties()
    print("Swept solid volume:", mp["volume_mm3"], "mm^3")

    # Close doc
    app.CloseDoc(doc.GetTitle)

if __name__ == "__main__":
    test_sweep()
