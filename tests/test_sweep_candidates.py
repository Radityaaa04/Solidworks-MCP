"""Check sweep methods on ModelDoc2."""
import win32com.client

app = win32com.client.Dispatch("SldWorks.Application")
part_tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Part.prtdot"
doc = app.NewDocument(part_tmpl, 0, 0.0, 0.0)

candidates = [
    "InsertSweep", "InsertSweptBoss", "InsertSweptBody", "InsertSweptSurface",
    "FeatureSweep", "FeatureSweptBoss", "CreateSweep", "InsertCutSwept",
    "InsertSweptBossExtrusion", "InsertProtrusionSweep"
]

print("--- Checking ModelDoc2 for Sweep ---")
for c in candidates:
    v = getattr(doc, c, None)
    if v is not None:
        print(f"Doc.{c} -> FOUND ({type(v)})")

# Also check FeatureManager with other variations
fm = doc.FeatureManager
candidates_fm2 = [
    "InsertSweptBoss", "InsertSweptSurface", "InsertSweepRefSurface",
    "FeatureSweep", "InsertSweep2", "InsertSweep3", "InsertSweep4",
    "InsertSweptBossRef", "CreateSweepFeatureData"
]
for c in candidates_fm2:
    v = getattr(fm, c, None)
    if v is not None:
        print(f"FM.{c} -> FOUND ({type(v)})")

app.CloseDoc(doc.GetTitle)
