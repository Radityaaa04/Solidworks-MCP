"""Final bounded evidence checks; no production fixes and no SolidWorks termination."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
import traceback

from live_followup import FollowUp, call0
from live_validation import Blocked, require


class FinalChecks(FollowUp):
    def __init__(self, project, output, audit_root):
        super().__init__(project, output)
        self.block_path = output / "models" / "r4_baseline_50x30x20.sldprt"
        self.audit_root = audit_root.resolve()

    def first_angle(self):
        self.new("drawing")
        self.save("r4_first_angle_fixture.slddrw")
        def configure(app, doc):
            sheet = call0(doc, "GetCurrentSheet")
            properties = list(call0(sheet, "GetProperties"))
            sheet.SetProperties(int(properties[0]), int(properties[1]), properties[2],
                                properties[3], True, properties[5], properties[6])
            actual = list(call0(sheet, "GetProperties"))
            if not actual[4]:
                raise Blocked(f"Native fixture did not become first-angle: {actual!r}")
            return {"setup": "native COM first-angle audit sheet only", "before": properties, "after": actual}
        settings = self.native(configure)
        views = self.call("sw_create_standard_views", model_path=str(self.block_path),
                          center_x_mm=140, center_y_mm=100, spacing_mm=50, include_isometric=False)
        self.call("sw_save_doc")
        by_orientation = {v["orientation"].lstrip("*").lower(): v for v in views}
        front, top, right = (by_orientation[key]["position_mm"] for key in ["front", "top", "right"])
        evidence = {"sheet": settings, "views": views,
                    "expected": "On first-angle sheet, Top is below Front and Right is left of Front"}
        (self.output / "live_first_angle_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        require(top[1] < front[1] and right[0] < front[0],
                f"First-angle sheet still received third-angle layout: Front={front}, Top={top}, Right={right}")
        return evidence

    def cleanup_audit_documents(self):
        # Earlier runs intentionally preserved the first failure's renamed test
        # document. Its exact saved path is inside this newly-created audit root,
        # so it is ours, not an existing user design, and can now be closed safely.
        closed = []
        before = self.wire.call("sw_list_open_documents", {})
        for _ in range(100):
            title = self.info().get("active_document")
            inventory = self.wire.call("sw_list_open_documents", {})
            current = next((d for d in inventory if d.get("title") == title), None)
            if current is None:
                break
            path = current.get("path")
            audit_path = bool(path) and Path(path).resolve().is_relative_to(self.audit_root)
            if not audit_path and title not in self.owned:
                break
            self.owned.add(title)
            self.expected = title
            self.call("sw_close_doc", save_changes=False)
            closed.append(current)
            self.expected = None
        after = self.wire.call("sw_list_open_documents", {})
        protected = [d for d in before if d.get("path") and
                     not Path(d["path"]).resolve().is_relative_to(self.audit_root)]
        require(all(d in after for d in protected), f"Protected non-audit document changed: {protected!r}, {after!r}")
        evidence = {"closed_audit_documents_only": closed, "remaining_documents": after,
                    "protected_non_audit_documents_preserved": True, "solidworks_processes_terminated": 0}
        (self.audit_root / "live_cleanup_final.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return evidence

    def run(self):
        self.case("mcp.initialize_and_discover_48", self.initialize, live=False)
        self.case("session.connect_and_inventory", self.connect, live=False)
        self.case("geometry.baseline_block_50x30x20_volume_30000", self.make_block)
        block = self.block_verified
        self.case("parameters.dimension_changes_physical_volume", self.dimension, condition=block)
        for kind in ["fillet", "chamfer"]:
            self.case(f"geometry.{kind}_native_preselected_control", lambda k=kind: self.native_selected_edge(k), condition=block)
        self.case("assembly.requested_configuration_actual_reference", self.configuration_evidence, condition=block)
        self.case("drawing.first_angle_sheet_requires_first_angle_layout", self.first_angle, condition=block)
        self.case("safety.pre_existing_documents_preserved", self.final_inventory)
        self.case("safety.close_only_owned_prior_audit_documents", self.cleanup_audit_documents)
        self.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    require(root.is_dir() and root.parent == Path("D:/New folder (2)").resolve(), "Unauthorized output root")
    output = root / "live_final_r4"
    output.mkdir()
    for name in ["live_final_checks.py", "live_followup.py", "live_validation.py"]:
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    audit = FinalChecks(args.project_root.resolve(), output, root)
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
        print(json.dumps({"final_checks_counts": counts, "connected": audit.connected,
                          "fatal": audit.fatal, "server_child_exit_code": child_exit}, indent=2), flush=True)
        (output / "live_execution.json").write_text(json.dumps({
            "command": [sys.executable, "-B", str(Path(__file__).resolve()),
                        "--output-root", str(root), "--project-root", str(args.project_root.resolve())],
            "counts": counts, "server_child_exit_code": child_exit,
            "native_setup_and_evidence": "explicitly tagged; all feature/mate/view operations remain real MCP calls",
        }, indent=2), encoding="utf-8")
    return 1 if any(r["status"] == "fail" for r in audit.records) else 0


if __name__ == "__main__":
    raise SystemExit(main())
