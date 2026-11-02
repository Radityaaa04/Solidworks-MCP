"""Targeted live follow-up: corrected harness cases and independently checked CAD state.

MCP calls remain unmodified production calls. Native COM is used only to read
independent evidence or prepare selection/configuration in audit-owned fixtures.
Every native access verifies the active document path beneath the fresh output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import traceback

from live_validation import LiveAudit, Blocked, near, require


def call0(obj, member):
    value = getattr(obj, member)
    return value() if callable(value) and not hasattr(value, "_oleobj_") else value


class FollowUp(LiveAudit):
    def __init__(self, project, output):
        super().__init__(project, output)
        self.block_path = output / "models" / "r3_baseline_50x30x20.sldprt"
        self.native_evidence = []

    def native(self, action):
        self.guard()
        inventory = self.wire.call("sw_list_open_documents", {})
        current = next(d for d in inventory if d["title"] == self.expected)
        if not current.get("path"):
            raise Blocked("Native evidence requires a saved audit-owned fixture")
        expected_path = Path(current["path"]).resolve()
        require(expected_path.is_relative_to(self.output.resolve()),
                f"Native control refused external document {expected_path}")
        import pythoncom
        import win32com.client
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        app = doc = None
        try:
            try:
                app = win32com.client.GetActiveObject("SldWorks.Application")
            except Exception:
                app = win32com.client.Dispatch("SldWorks.Application")
            doc = app.ActiveDoc
            if doc is None or Path(doc.GetPathName).resolve() != expected_path:
                raise Blocked("Independent COM observer did not attach to the same audit document")
            evidence = action(app, doc)
            json.dumps(evidence, allow_nan=False)
            self.native_evidence.append({"active_path": str(expected_path), "evidence": evidence})
            (self.output / "live_native_evidence.json").write_text(
                json.dumps(self.native_evidence, indent=2), encoding="utf-8")
            return evidence
        finally:
            doc = app = None
            pythoncom.CoUninitialize()

    def public_edge(self, kind):
        self.open_block()
        args = {"edge_x_mm": 25, "edge_y_mm": 0, "edge_z_mm": 20}
        if kind == "fillet":
            result = self.call("sw_fillet", radius_mm=2, **args)
        else:
            result = self.call("sw_chamfer", distance_mm=1, angle_deg=45, **args)
        volume = self.volume()["volume_mm3"]
        require(0 < volume < 30000, f"Edge operation did not change solid volume: {volume}")
        self.save(f"r3_public_{kind}.sldprt")
        return {"feature": result, "volume_mm3": volume}

    def native_selected_edge(self, kind):
        self.open_block()
        def select(app, doc):
            bodies = doc.GetBodies2(0, False)
            require(bodies and len(bodies) == 1, "Expected one solid body")
            edges = call0(bodies[0], "GetEdges")
            require(edges, "No B-rep edges")
            data = call0(doc.SelectionManager, "CreateSelectData")
            doc.ClearSelection2(True)
            chosen = edges[0]
            start, end = call0(chosen, "GetStartVertex"), call0(chosen, "GetEndVertex")
            endpoints = [list(call0(start, "GetPoint")), list(call0(end, "GetPoint"))]
            require(chosen.Select4(False, data), "Native B-rep edge selection failed")
            return {"setup": "native COM B-rep selection only; feature creation remains public MCP",
                    "edge_count": len(edges), "selected_edge_endpoints_m": endpoints}
        selected = self.native(select)
        if kind == "fillet":
            result = self.call("sw_fillet", radius_mm=1)
        else:
            result = self.call("sw_chamfer", distance_mm=1, angle_deg=45)
        volume = self.volume()["volume_mm3"]
        require(0 < volume < 30000, f"Selected-edge {kind} did not change volume: {volume}")
        self.save(f"r3_native_selection_{kind}.sldprt")
        return {"selection_evidence": selected, "feature": result, "volume_mm3": volume}

    def dimensions_with_evidence(self):
        view = self.prepare_drawing()
        before_save = self.save("r3_dimension_evidence.slddrw")
        response = self.call("sw_auto_dimension", view_name=view["name"])
        def count_dimensions(app, doc):
            entries = []
            item = doc.GetFirstView
            for _ in range(100):
                if item is None:
                    break
                count = 0
                dimension = item.GetFirstDisplayDimension5
                for _ in range(200):
                    if dimension is None:
                        break
                    count += 1
                    dimension = dimension.GetNext5
                entries.append({"view": item.GetName2, "display_dimension_count": count})
                item = item.GetNextView
            return {"views": entries, "total": sum(e["display_dimension_count"] for e in entries)}
        actual = self.native(count_dimensions)
        self.call("sw_save_doc")
        require(actual["total"] > 0,
                f"AutoDimension response {response!r} but independent view traversal found no dimensions: {actual!r}")
        return {"response": response, "native_annotation_evidence": actual, "saved": before_save}

    def projection_evidence(self):
        self.new("drawing")
        result = self.call("sw_create_standard_views", model_path=str(self.block_path),
                           center_x_mm=100, center_y_mm=80, spacing_mm=60, include_isometric=True)
        self.save("r3_projection_evidence.slddrw")
        def sheet_info(app, doc):
            sheet = doc.GetCurrentSheet
            props = sheet.GetProperties
            return {"sheet_properties": list(props), "first_angle": bool(props[4])}
        sheet = self.native(sheet_info)
        views = {v["orientation"].lstrip("*").lower(): v for v in result}
        front, top, right = (views[key]["position_mm"] for key in ["front", "top", "right"])
        if sheet["first_angle"]:
            require(top[1] < front[1] and right[0] < front[0],
                    f"First-angle sheet has third-angle layout: {result!r}; {sheet!r}")
        else:
            require(top[1] > front[1] and right[0] > front[0],
                    f"Third-angle sheet has wrong layout: {result!r}; {sheet!r}")
        return {"views": result, "sheet": sheet,
                "limitation": "Only installed template projection convention exercised"}

    def configuration_evidence(self):
        self.open_block()
        fixture_path = self.output / "models" / "r3_configuration_fixture.sldprt"
        self.save(fixture_path.name)
        def add_configuration(app, doc):
            manager = doc.ConfigurationManager
            original = manager.ActiveConfiguration.Name
            manager.AddConfiguration("AuditAlternate", "Audit-only alternate configuration", "", 0, "", "")
            names = list(call0(doc, "GetConfigurationNames"))
            if "AuditAlternate" not in names:
                raise Blocked(f"Native configuration fixture was not created; available={names!r}")
            activation_status = doc.ShowConfiguration2("AuditAlternate")
            active = manager.ActiveConfiguration.Name
            if active != "AuditAlternate":
                raise Blocked(f"Native fixture activation unavailable: status={activation_status!r}, active={active!r}")
            return {"setup": "native COM configuration fixture only", "requested": original,
                    "last_active": active, "activation_status": activation_status, "names": names}
        fixture = self.native(add_configuration)
        self.call("sw_save_doc")
        self.new("assembly")
        component = self.call("sw_insert_component", component_path=str(fixture_path),
                              config_name=fixture["requested"])
        self.save("r3_configuration_assembly.sldasm")
        def referenced(app, doc):
            components = doc.GetComponents(True)
            return {"components": [{"name": c.Name2, "configuration": c.ReferencedConfiguration}
                                   for c in components]}
        actual = self.native(referenced)
        require(actual["components"] and actual["components"][0]["configuration"] == fixture["requested"],
                f"Requested configuration {fixture['requested']!r}, but actual component is {actual!r}; fixture={fixture!r}")
        return {"fixture": fixture, "insert_response": component, "native_reference": actual}

    def run(self):
        self.case("mcp.initialize_and_discover_48", self.initialize, live=False)
        self.case("session.connect_and_inventory", self.connect, live=False)
        self.case("geometry.baseline_block_50x30x20_volume_30000", self.make_block)
        block = self.block_verified
        self.case("parameters.dimension_changes_physical_volume", self.dimension, condition=block)
        self.case("parameters.global_variable_create_readback", self.equation, condition=block)
        self.case("parameters.global_variable_update_readback", lambda: self.equation(update=True), condition=block)
        self.case("export.model_igs_file_integrity", lambda: self.export_model("igs"), condition=block)
        for kind in ["fillet", "chamfer"]:
            self.case(f"geometry.{kind}_front_visible_edge", lambda k=kind: self.public_edge(k), condition=block)
            self.case(f"geometry.{kind}_native_preselected_control", lambda k=kind: self.native_selected_edge(k), condition=block)
        self.case("drawing.auto_dimension_independent_annotation_count", self.dimensions_with_evidence, condition=block)
        self.case("drawing.standard_views_follow_sheet_projection", self.projection_evidence, condition=block)
        self.case("assembly.requested_configuration_actual_reference", self.configuration_evidence, condition=block)
        self.case("safety.pre_existing_documents_preserved", self.final_inventory)
        self.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    require(root.is_dir() and root.parent == Path("D:/New folder (2)").resolve(), "Unauthorized output root")
    output = root / "live_followup_r3"
    output.mkdir()
    for name in ["live_followup.py", "live_validation.py"]:
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    audit = FollowUp(args.project_root.resolve(), output)
    try:
        audit.run()
    finally:
        if audit.connected and not audit.fatal:
            try:
                audit.close_active_owned()
            except Exception:
                (output / "live_cleanup_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        child_exit = audit.wire.close()
        audit.flush()
        counts = dict(Counter(r["status"] for r in audit.records))
        print(json.dumps({"followup_counts": counts, "connected": audit.connected,
                          "fatal": audit.fatal, "server_child_exit_code": child_exit}, indent=2), flush=True)
        (output / "live_execution.json").write_text(json.dumps({
            "command": [sys.executable, "-B", str(Path(__file__).resolve()),
                        "--output-root", str(root), "--project-root", str(args.project_root.resolve())],
            "counts": counts, "server_child_exit_code": child_exit,
            "note": "Corrected harness name collision/Boss type selector; independent COM evidence explicitly tagged",
        }, indent=2), encoding="utf-8")
    return 1 if any(r["status"] == "fail" for r in audit.records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
