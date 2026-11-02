"""Test CreateDefinition for Sweep."""
import win32com.client

app = win32com.client.Dispatch("SldWorks.Application")
part_tmpl = r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Part.prtdot"
doc = app.NewDocument(part_tmpl, 0, 0.0, 0.0)
fm = doc.FeatureManager

for val in [0, 1, 2, 3, 4, 5, 6, "Sweep", "sweep", "SwFeatureDataSweep"]:
    try:
        defn = fm.CreateDefinition(val)
        if defn is not None:
            print(f"CreateDefinition({val}) -> {type(defn)}")
    except Exception as e:
        pass

app.CloseDoc(doc.GetTitle)
