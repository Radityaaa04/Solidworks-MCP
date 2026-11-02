"""Scratch script to explore SolidWorks COM Drawing APIs."""
import os
import win32com.client
import pythoncom

def main():
    app = win32com.client.Dispatch("SldWorks.Application")
    model_path = os.path.abspath(r"tests\output\p3_pillow_housing.sldprt")
    assert os.path.exists(model_path), f"Model not found: {model_path}"

    # 1. Pre-open model silently
    v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    model_doc = app.OpenDoc6(model_path, 1, 1, "", v_err, v_warn)
    print("Opened model:", model_doc.GetTitle if model_doc else None)

    # 2. Create new drawing
    tmpl = app.GetUserPreferenceStringValue(15) # swDefaultTemplateDrawing = 15 or query
    if not tmpl or not os.path.exists(tmpl):
        tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Drawing.drwdot"
    draw_doc = app.NewDocument(tmpl, 0, 0.0, 0.0)
    print("Created drawing:", draw_doc.GetTitle)

    # 3. Create Views
    # CreateDrawViewFromModelView3(ModelName, ViewName, X, Y, Z)
    # Positions in meters: Sheet A4/A3 is roughly 0.42 x 0.297 m
    v_front = draw_doc.CreateDrawViewFromModelView3(model_path, "*Front", 0.10, 0.10, 0.0)
    print("Created Front View:", v_front.GetName2 if v_front else None)

    v_top = draw_doc.CreateDrawViewFromModelView3(model_path, "*Top", 0.10, 0.20, 0.0)
    print("Created Top View:", v_top.GetName2 if v_top else None)

    v_right = draw_doc.CreateDrawViewFromModelView3(model_path, "*Right", 0.25, 0.10, 0.0)
    print("Created Right View:", v_right.GetName2 if v_right else None)

    v_iso = draw_doc.CreateDrawViewFromModelView3(model_path, "*Isometric", 0.28, 0.22, 0.0)
    print("Created Isometric View:", v_iso.GetName2 if v_iso else None)

    # 4. Insert Note
    note = draw_doc.InsertNote("HOUSING SUB-ASSEMBLY - MATERIAL: CAST ALLOY STEEL")
    if note:
        print("Note created:", note.GetText)

    # 4.1 AutoDimension Front View
    # Activate and select Front View
    draw_doc.ActivateView("Drawing View1")
    draw_doc.ClearSelection2(True)
    v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    s1 = draw_doc.Extension.SelectByID2("Drawing View1", "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, v_call, 0)
    print("Selected Drawing View1:", s1)
    ad_res = draw_doc.AutoDimension(1, 0, 1, 0, 1)
    print("AutoDimension Front View status:", ad_res)

    # 4.2 AutoDimension Right View
    draw_doc.ActivateView("Drawing View3")
    draw_doc.ClearSelection2(True)
    s3 = draw_doc.Extension.SelectByID2("Drawing View3", "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, v_call, 0)
    print("Selected Drawing View3:", s3)
    ad_res3 = draw_doc.AutoDimension(1, 0, 1, 0, 2)
    print("AutoDimension Right View status:", ad_res3)

    # 5. List Views
    view = draw_doc.GetFirstView # Sheet view
    print("Sheet view:", view.GetName2)
    view = view.GetNextView
    while view:
        print(f" -> View: {view.GetName2}, Type: {view.Type}, Model: {view.GetReferencedModelName}")
        view = view.GetNextView

    # 6. Save as drawing and export PDF
    out_drw = os.path.abspath(r"tests\output\test_housing_drawing.slddrw")
    out_pdf = os.path.abspath(r"tests\output\test_housing_drawing.pdf")

    v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
    v_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
    v_opts = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

    s1 = draw_doc.Extension.SaveAs3(out_drw, 0, 1, v_data, v_opts, v_err, v_warn)
    print(f"Saved SLDDRW: {s1} (err: {v_err.value}) -> {out_drw}")

    # Export PDF via SaveAs3
    pdf_export_data = app.GetExportFileData(1) # swExportPDFData = 1
    s2 = draw_doc.Extension.SaveAs3(out_pdf, 0, 1, pdf_export_data, v_opts, v_err, v_warn)
    print(f"Exported PDF: {s2} (err: {v_err.value}) -> {out_pdf}")
    print("PDF exists:", os.path.exists(out_pdf), "Size:", os.path.getsize(out_pdf) if os.path.exists(out_pdf) else 0)

    # Export DXF via SaveAs3
    out_dxf = os.path.abspath(r"tests\output\test_housing_drawing.dxf")
    s3 = draw_doc.Extension.SaveAs3(out_dxf, 0, 1, v_data, v_opts, v_err, v_warn)
    print(f"Exported DXF: {s3} (err: {v_err.value}) -> {out_dxf}")
    print("DXF exists:", os.path.exists(out_dxf), "Size:", os.path.getsize(out_dxf) if os.path.exists(out_dxf) else 0)

    # Close drawing
    app.CloseDoc(draw_doc.GetTitle)
    print("Drawing closed.")

if __name__ == "__main__":
    main()
