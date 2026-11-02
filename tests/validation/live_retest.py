"""Repeat the live audit with an isolated baseline and disposable save-failure fixture.

The first run demonstrated that a failed native SaveAs can still rename the
in-memory document, keeping its original identity loaded and blocking reopen.
Do not change production code; retain the failed first run as evidence and use
an independent baseline namespace for the repeat.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys
import traceback

from live_validation import LiveAudit, SafetyAbort, near, require


class IsolatedAudit(LiveAudit):
    def __init__(self, project, output):
        super().__init__(project, output)
        self.block_path = output / "models" / "r2_baseline_50x30x20.sldprt"

    def save_failure(self):
        # Deliberately never use the shared baseline for a failure-injection case.
        self.new()
        self.sketch()
        self.rectangle(0, 0, 8, 6)
        self.finish_sketch()
        self.call("sw_boss_extrude", depth_mm=4)
        near(self.volume()["volume_mm3"], 192)
        self.save("r2_disposable_save_failure.sldprt")
        before = self.expected
        target = self.output / "models" / "invalid_r2:name.sldprt"
        rejected = self.invalid_before_com("sw_save_doc", {"output_path": str(target)})
        actual = self.info().get("active_document")
        documents = self.wire.call("sw_list_open_documents", {})
        if actual != before:
            document = next((d for d in documents if d.get("title") == actual), None)
            if not document or not document.get("path"):
                raise SafetyAbort(f"Failed SaveAs left an unidentifiable document: {documents!r}")
            actual_path = Path(document["path"]).resolve()
            if not actual_path.is_relative_to(self.output.resolve()):
                raise SafetyAbort(f"Failed SaveAs selected a document outside audit output: {document!r}")
            self.claim_current()
        volume = self.volume()["volume_mm3"]
        evidence = {"before_title": before, "after_title": actual,
                    "save_error": rejected, "documents": documents, "volume_mm3": volume}
        (self.output / "live_failed_save_side_effect.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8")
        near(volume, 192)
        require(actual == before,
                f"Failed SaveAs changed active title {before!r} -> {actual!r}; "
                "disposable fixture claimed for safe cleanup; shared baseline untouched")
        return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    root = args.output_root.resolve()
    require(root.is_dir() and root.parent == Path("D:/New folder (2)").resolve(),
            "Output must be beneath the explicitly authorized existing audit root")
    output = root / "live_isolated_r2"
    output.mkdir()
    shutil.copyfile(__file__, output / "live_retest.py")
    shutil.copyfile(Path(__file__).with_name("live_validation.py"), output / "live_validation.py")
    audit = IsolatedAudit(args.project_root.resolve(), output)
    exit_code = 0
    try:
        audit.run()
    except Exception:
        (output / "live_harness_exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        exit_code = 2
        raise
    finally:
        if audit.connected and not audit.fatal:
            try:
                audit.close_active_owned()
            except Exception:
                (output / "live_cleanup_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        child_exit = audit.wire.close()
        audit.flush()
        counts = dict(Counter(r["status"] for r in audit.records))
        print(json.dumps({"isolated_live_counts": counts, "connected": audit.connected,
                          "fatal": audit.fatal, "server_child_exit_code": child_exit}, indent=2), flush=True)
        (output / "live_execution.json").write_text(json.dumps({
            "command": [sys.executable, "-B", str(Path(__file__).resolve()),
                        "--output-root", str(root), "--project-root", str(args.project_root.resolve())],
            "counts": counts, "connected": audit.connected, "fatal": audit.fatal,
            "server_child_exit_code": child_exit,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "why_repeat": "Isolate failure-injection state from shared geometry baseline; no source fixes",
        }, indent=2), encoding="utf-8")
        if counts.get("fail"):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
