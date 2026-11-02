"""Candidate testing script for SolidWorks COM methods."""
import win32com.client
import os

app = win32com.client.Dispatch("SldWorks.Application")
part_tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Part.prtdot"
drw_tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Drawing.drwdot"

doc = app.NewDocument(part_tmpl, 0, 0.0, 0.0)
fm = doc.FeatureManager

print("--- FeatureManager Methods ---")
candidates_fm = [
    "InsertSweptBoss", "InsertSweptBoss1", "InsertSweptBoss2", "InsertSweptBoss3", "InsertSweptBoss4", "InsertSweptBoss5",
    "InsertCutSwept", "InsertCutSwept1", "InsertCutSwept2", "InsertCutSwept3", "InsertCutSwept4",
    "FeatureCircularPattern", "FeatureCircularPattern2", "FeatureCircularPattern3", "FeatureCircularPattern4", "FeatureCircularPattern5",
    "FeatureLinearPattern", "FeatureLinearPattern2", "FeatureLinearPattern3", "FeatureLinearPattern4", "FeatureLinearPattern5",
    "CreateDefinition", "CreateFeature"
]
for c in candidates_fm:
    v = getattr(fm, c, None)
    if v is not None:
        print(f"FM.{c} -> FOUND ({type(v)})")

app.CloseDoc(doc.GetTitle)

# Now DrawingDoc
drw = app.NewDocument(drw_tmpl, 0, 0.0, 0.0)
print("\n--- DrawingDoc Methods ---")
candidates_drw = [
    "CreateSectionView", "CreateSectionViewAt", "CreateSectionViewAt2", "CreateSectionViewAt3", "CreateSectionViewAt4", "CreateSectionViewAt5", "CreateSectionViewAt6",
    "CreateBreakOutSection", "CreateDetailViewAt", "CreateDetailViewAt2", "CreateDetailViewAt3", "CreateAuxiliaryViewAt"
]
for c in candidates_drw:
    v = getattr(drw, c, None)
    if v is not None:
        print(f"DRW.{c} -> FOUND ({type(v)})")

app.CloseDoc(drw.GetTitle)
