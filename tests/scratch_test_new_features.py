"""Scratch exploration script for Circular Pattern, Sweep, and Section View APIs."""
import os
import win32com.client
import pythoncom

def main():
    app = win32com.client.Dispatch("SldWorks.Application")
    print("Connected to SolidWorks 2026:", app.RevisionNumber)

    # 1. Inspect Circular Pattern methods on FeatureManager
    feat_mgr = app.ActiveDoc.FeatureManager if app.ActiveDoc else None
    if not feat_mgr:
        # Create a new part to inspect
        tmpl = app.GetUserPreferenceStringValue(15) # or part
        part_tmpl = app.GetUserPreferenceStringValue(16) # swDefaultTemplatePart = 16 or query
        if not part_tmpl or not os.path.exists(part_tmpl):
            part_tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Part.prtdot"
        doc = app.NewDocument(part_tmpl, 0, 0.0, 0.0)
        feat_mgr = doc.FeatureManager

    print("Checking FeatureManager members:")
    for name in ["FeatureCircularPattern", "FeatureCircularPattern4", "FeatureCircularPattern5",
                 "InsertSweptBoss", "InsertSweptBoss1", "InsertCutSwept", "InsertCutSwept4",
                 "CreateFeature", "CreateDefinition"]:
        val = getattr(feat_mgr, name, None)
        print(f" -> {name}: {type(val)}")

    if app.ActiveDoc:
        app.CloseDoc(app.ActiveDoc.GetTitle)

if __name__ == "__main__":
    main()
