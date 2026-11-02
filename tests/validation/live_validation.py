"""Bounded end-to-end SolidWorks validation through the real MCP stdio server.

Creates and mutates only audit-owned documents and files beneath --output-dir.
Never terminates SolidWorks or closes pre-existing documents. A timed-out tool
aborts further CAD calls because cancelling a request cannot cancel COM safely.
No production modules are patched. Offline fault injection lives in other files.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import glob
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback


class WireTimeout(RuntimeError):
    pass


class ToolFailure(RuntimeError):
    pass


class SafetyAbort(RuntimeError):
    pass


class Blocked(RuntimeError):
    pass


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def near(actual, expected, tolerance=0.1):
    require(isinstance(actual, (int, float)) and math.isfinite(actual),
            f"Expected finite number, received {actual!r}")
    require(abs(actual - expected) <= tolerance,
            f"Expected {expected} +/- {tolerance}, received {actual}")


class Wire:
    def __init__(self, project, output):
        self.output = output
        self.requests = []
        self.responses = queue.Queue()
        self.serial = 0
        self.broken = False
        self.stdout_file = (output / "live_wire_stdout.jsonl").open("w", encoding="utf-8")
        self.stderr_file = (output / "live_server_stderr.log").open("w", encoding="utf-8")
        env = os.environ.copy()
        env.update(PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-m", "sw_mcp.server"],
            cwd=str(project), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.err_reader = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start()
        self.err_reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.stdout_file.write(line)
                self.stdout_file.flush()
                try:
                    self.responses.put(json.loads(line))
                except Exception as exc:
                    self.responses.put({"wire_error": repr(exc), "raw": line})
        finally:
            self.responses.put({"wire_eof": True})

    def _stderr(self):
        for line in self.process.stderr:
            self.stderr_file.write(line)
            self.stderr_file.flush()

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=35):
        if self.broken:
            raise WireTimeout("MCP transport is unsafe after an earlier timeout")
        self.serial += 1
        message = {"jsonrpc": "2.0", "id": self.serial, "method": method}
        if params is not None:
            message["params"] = params
        record = {"request": message, "started_at": datetime.now().astimezone().isoformat()}
        self.requests.append(record)
        started = time.monotonic()
        self.process.stdin.write(json.dumps(message, allow_nan=False) + "\n")
        self.process.stdin.flush()
        try:
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise queue.Empty
                response = self.responses.get(timeout=remaining)
                if "wire_error" in response or "wire_eof" in response:
                    raise RuntimeError(f"Invalid/closed MCP transport: {response}")
                if response.get("id") == self.serial:
                    record["response"] = response
                    record["duration_s"] = round(time.monotonic() - started, 4)
                    if "error" in response:
                        raise ToolFailure(json.dumps(response["error"], ensure_ascii=False))
                    return response.get("result")
        except queue.Empty as exc:
            self.broken = True
            record["timeout_s"] = timeout
            raise WireTimeout(f"MCP request {self.serial} ({method}) exceeded {timeout}s") from exc
        finally:
            (self.output / "live_wire_requests.json").write_text(
                json.dumps(self.requests, indent=2, ensure_ascii=False), encoding="utf-8")

    def call(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise ToolFailure(f"Non-object tools/call result: {result!r}")
        if result.get("isError"):
            text = "\n".join(c.get("text", "") for c in result.get("content", []))
            raise ToolFailure(text or repr(result))
        if "structuredContent" in result:
            structured = result["structuredContent"]
            if isinstance(structured, dict) and set(structured) == {"result"}:
                return structured["result"]
            return structured
        texts = [c["text"] for c in result.get("content", []) if c.get("type") == "text"]
        if len(texts) == 1:
            try:
                return json.loads(texts[0])
            except ValueError:
                return texts[0]
        decoded = []
        for text in texts:
            try:
                decoded.append(json.loads(text))
            except ValueError:
                decoded.append(text)
        return decoded

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # This is exclusively the Python MCP child started by this harness.
            # Never terminate SLDWORKS.exe or any pre-existing process.
            self.process.terminate()
            self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.err_reader.join(timeout=2)
        self.stdout_file.close()
        self.stderr_file.close()
        return self.process.returncode


class LiveAudit:
    def __init__(self, project, output):
        self.project = project
        self.output = output
        self.records = []
        self.connected = False
        self.initial_documents = []
        self.owned = set()
        self.expected = None
        self.fatal = None
        self.deadline = time.monotonic() + 245
        self.block_path = output / "models" / "validation_block.sldprt"
        self.block_verified = False
        self.baseline_feature_name = None
        self.material_name = None
        self.front_view = None
        self.assembly_name = None
        self.components = []
        self.templates = {}
        patterns = [
            "C:/ProgramData/SOLIDWORKS/SOLIDWORKS */templates/*.*dot",
            "C:/Program Files/SOLIDWORKS Corp/SOLIDWORKS/data/templates/*.*dot",
        ]
        for pattern in patterns:
            for path in sorted(glob.glob(pattern)):
                ext = Path(path).suffix.lower()
                self.templates.setdefault(ext, path)
        for directory in ["models", "exports", "images"]:
            (output / directory).mkdir(exist_ok=True)
        self.wire = Wire(project, output)

    def flush(self):
        counts = Counter(r["status"] for r in self.records)
        called = Counter(
            r["request"].get("params", {}).get("name")
            for r in self.wire.requests if r["request"]["method"] == "tools/call")
        report = {
            "kind": "real MCP stdio / live SolidWorks; no mocked CAD results",
            "counts": dict(counts), "case_count": len(self.records),
            "tool_attempt_counts": dict(sorted(called.items())),
            "distinct_tools_attempted": len(called),
            "connected": self.connected, "fatal": self.fatal,
            "initial_documents": self.initial_documents,
            "owned_titles": sorted(self.owned), "expected_active_title": self.expected,
            "templates_discovered": self.templates,
            "records": self.records,
        }
        (self.output / "live_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    def case(self, name, function, live=True, condition=True, reason="Prerequisite failed"):
        record = {"name": name, "started_at": datetime.now().astimezone().isoformat()}
        self.records.append(record)
        started = time.monotonic()
        if self.fatal or (live and not self.connected) or not condition:
            record.update(status="skip", reason=self.fatal or
                          ("Live SolidWorks connection unavailable" if live and not self.connected else reason))
        elif time.monotonic() > self.deadline:
            self.fatal = "Audit wall-clock budget reached; no further CAD calls"
            record.update(status="skip", reason=self.fatal)
        else:
            first_request = len(self.wire.requests)
            try:
                evidence = function()
                record.update(status="pass", evidence=evidence)
            except Blocked as exc:
                record.update(status="skip", reason=str(exc))
            except (WireTimeout, SafetyAbort) as exc:
                self.fatal = str(exc)
                record.update(status="fail", error=str(exc), traceback=traceback.format_exc())
            except Exception as exc:
                record.update(status="fail", error=str(exc), traceback=traceback.format_exc())
            record["request_ids"] = [r["request"]["id"] for r in self.wire.requests[first_request:]]
        record["duration_s"] = round(time.monotonic() - started, 4)
        print(f"{record['status'].upper():4} {name}: {record.get('error', record.get('reason', 'OK'))}", flush=True)
        self.flush()
        return record["status"] == "pass"

    def info(self):
        return self.wire.call("sw_get_session_info", {})

    def guard(self):
        actual = self.info().get("active_document")
        if actual not in self.owned:
            raise SafetyAbort(f"Refusing to mutate unowned active document {actual!r}; expected {self.expected!r}")
        require(actual == self.expected,
                f"Active document drifted to another audit document: {actual!r}, expected {self.expected!r}")

    def call(self, tool_name, **arguments):
        self.guard()
        return self.wire.call(tool_name, arguments)

    def claim_current(self):
        title = self.info().get("active_document")
        require(isinstance(title, str) and title, f"No active title after creation/open: {title!r}")
        protected = {d.get("title") for d in self.initial_documents}
        if title in protected:
            raise SafetyAbort(f"Creation/open selected a protected pre-existing document: {title}")
        self.owned.add(title)
        self.expected = title
        return title

    def new(self, kind="part", default=False):
        self.close_active_owned()
        method = {"part": "sw_new_part", "assembly": "sw_new_assembly", "drawing": "sw_new_drawing"}[kind]
        ext = {"part": ".prtdot", "assembly": ".asmdot", "drawing": ".drwdot"}[kind]
        arguments = {} if default else {"template_path": self.templates.get(ext, "")}
        result = self.wire.call(method, arguments)
        self.claim_current()
        return result

    def open_block(self):
        if not self.block_verified:
            raise Blocked("No independently volume-verified saved baseline block")
        self.close_active_owned()
        result = self.wire.call("sw_open_doc", {"file_path": str(self.block_path)})
        self.claim_current()
        return result

    def close_active_owned(self):
        if not self.connected or self.wire.broken:
            return
        title = self.info().get("active_document")
        if title in self.owned:
            self.expected = title
            self.call("sw_close_doc", save_changes=False)
            self.expected = None

    def volume(self):
        result = self.call("sw_get_mass_properties")
        require(isinstance(result, dict), f"Mass properties must be a dict: {result!r}")
        value = result.get("volume_mm3")
        require(isinstance(value, (int, float)) and math.isfinite(value) and value > 0,
                f"Invalid solid volume: {result!r}")
        return result

    def save(self, name, **extra):
        path = self.output / "models" / name
        result = self.call("sw_save_doc", output_path=str(path), **extra)
        self.claim_current()
        require(path.is_file() and path.stat().st_size > 0, f"Missing/empty saved file: {path}")
        return result

    def sketch(self, plane="Front Plane"):
        return self.call("sw_create_sketch_on_plane", plane_name=plane)

    def rectangle(self, x1, y1, x2, y2):
        return self.call("sw_draw_rectangle", x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2)

    def circle(self, x, y, radius):
        return self.call("sw_draw_circle", center_x_mm=x, center_y_mm=y, radius_mm=radius)

    def finish_sketch(self):
        return self.call("sw_close_sketch")

    def make_block(self):
        self.new()
        self.sketch()
        self.rectangle(0, 0, 50, 30)
        self.finish_sketch()
        feature = self.call("sw_boss_extrude", depth_mm=20)
        self.baseline_feature_name = feature["feature"]
        props = self.volume()
        near(props["volume_mm3"], 30000)
        self.save(self.block_path.name)
        self.block_verified = True
        return {"feature": feature, "mass_properties": props, "path": str(self.block_path)}

    def connect(self):
        info = self.info()
        require(info.get("connected") is True, f"Not connected: {info!r}")
        documents = self.wire.call("sw_list_open_documents", {})
        require(isinstance(documents, list), f"Document inventory must be a list: {documents!r}")
        self.initial_documents = documents
        self.connected = True
        (self.output / "live_session_initial.json").write_text(
            json.dumps({"info": info, "documents": documents}, indent=2), encoding="utf-8")
        return {"info": info, "pre_existing_documents": documents}

    def initialize(self):
        result = self.wire.request("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "solidworks-bounded-live-validation", "version": "1.0"}})
        self.wire.notify("notifications/initialized")
        tools = self.wire.request("tools/list")["tools"]
        require(len(tools) == 48 and len({t["name"] for t in tools}) == 48,
                f"Expected 48 unique tools, received {len(tools)}")
        return {"initialize": result, "tool_count": len(tools)}

    def invalid_before_com(self, tool, arguments):
        try:
            result = self.wire.call(tool, arguments)
        except ToolFailure as exc:
            return {"rejected": True, "message": str(exc)}
        raise AssertionError(f"Invalid input was accepted: {tool} {arguments!r} -> {result!r}")

    def inspect_tree(self):
        self.open_block()
        tree = self.call("sw_get_feature_tree")
        require(isinstance(tree, list) and any("extrud" in str(f).lower() for f in tree),
                f"Extrusion missing from tree: {tree!r}")
        return tree

    def capture(self):
        self.open_block()
        path = self.output / "images" / "validation_block.png"
        result = self.call("sw_capture_viewport", output_path=str(path))
        from PIL import Image, ImageStat
        require(path.is_file() and path.stat().st_size > 100, "No non-empty viewport PNG")
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            require(min(image.size) > 100, f"Viewport unexpectedly tiny: {image.size}")
            require(max(ImageStat.Stat(image.convert("RGB")).stddev) > 0,
                    "Viewport image is a single flat color")
        return result

    def dimension(self):
        self.open_block()
        tree = self.call("sw_get_feature_tree")
        boss = self.baseline_feature_name
        require(boss is not None and any(f["name"] == boss for f in tree),
                f"Created baseline feature identity was not found: {boss!r}, {tree!r}")
        result = self.call("sw_modify_dimension", dimension_name=f"D1@{boss}", value_mm=25)
        props = self.volume()
        near(props["volume_mm3"], 37500)
        self.call("sw_modify_dimension", dimension_name=f"D1@{boss}", value_mm=20)
        near(self.volume()["volume_mm3"], 30000)
        return {"modified": result, "volume_after_change": props["volume_mm3"]}

    def equation(self, update=False):
        self.open_block()
        self.call("sw_set_global_variable", name="AuditLength", value=50, unit="mm")
        if update:
            self.call("sw_set_global_variable", name="AuditLength", value=60, unit="mm")
        equations = self.call("sw_get_equations")
        expected = "60" if update else "50"
        require(any("AuditLength" in e.get("equation", "") and expected in e.get("equation", "")
                    for e in equations), f"Equation readback did not match: {equations!r}")
        return equations

    def material_catalog(self):
        result = self.wire.call("sw_list_materials", {"search": "6061"})
        names = [name for group in result.get("classifications", {}).values() for name in group]
        if not names:
            raise Blocked("Installed material catalog has no 6061 entry; material test not fabricated")
        self.material_name = next((n for n in names if n.lower() == "6061 alloy"), names[0])
        return result

    def material(self, clear=False):
        self.open_block()
        if not self.material_name:
            raise Blocked("No available material name discovered")
        assigned = self.call("sw_set_material", material_name=self.material_name)
        readback = self.call("sw_get_material")
        require(readback.get("assigned") and readback.get("material_name", "").lower() == self.material_name.lower(),
                f"Material assignment not reflected: {readback!r}")
        props = self.volume()
        density = readback.get("density_kg_m3", 0)
        require(density > 0, f"No positive material density: {readback!r}")
        near(props["mass_g"], props["volume_mm3"] * 1e-6 * density, tolerance=0.15)
        if clear:
            self.call("sw_set_material", material_name="")
            readback = self.call("sw_get_material")
            require(readback.get("assigned") is False, f"Material clear not reflected: {readback!r}")
        return {"assigned": assigned, "readback": readback, "mass_properties": props}

    def export_model(self, extension):
        self.open_block()
        path = self.output / "exports" / ("validation_block." + extension)
        result = self.call("sw_export_cad", output_path=str(path))
        require(path.is_file() and path.stat().st_size > 50, f"Export missing/empty: {path}")
        header = path.read_bytes()[:4096]
        if extension == "step":
            require(b"ISO-10303-21" in header, f"Invalid STEP header: {header[:80]!r}")
        if extension == "stl":
            import struct
            size = path.stat().st_size
            binary_valid = size >= 84 and 84 + 50 * struct.unpack("<I", path.read_bytes()[80:84])[0] == size
            ascii_valid = header.lstrip().lower().startswith(b"solid") and b"facet" in header.lower()
            require(binary_valid or ascii_valid, "STL has neither valid binary structure nor ASCII facets")
        return {"result": result, "size_bytes": path.stat().st_size, "header_hex": header[:40].hex()}

    def in_place_and_alias_save(self):
        self.open_block()
        first = self.call("sw_save_doc")
        alias = self.output / "models" / "validation_block_alias.sldprt"
        second = self.call("sw_save_doc", file_path=str(alias))
        self.claim_current()
        require(alias.is_file() and alias.stat().st_size > 0, "Save file_path alias produced no file")
        return [first, second]

    def save_failure(self):
        self.open_block()
        before = self.expected
        target = self.output / "models" / "invalid:name.sldprt"
        rejected = self.invalid_before_com("sw_save_doc", {"output_path": str(target)})
        require(self.info().get("active_document") == before, "Failed SaveAs changed active title")
        near(self.volume()["volume_mm3"], 30000)
        return rejected

    def close_unsaved_failure(self):
        self.new()
        before = self.expected
        rejected = self.invalid_before_com("sw_close_doc", {"save_changes": True})
        titles = [d["title"] for d in self.wire.call("sw_list_open_documents", {})]
        require(before in titles and self.info().get("active_document") == before,
                "Document disappeared after failed save-on-close")
        return rejected

    def face_sketch(self):
        self.open_block()
        result = self.call("sw_create_sketch_on_face", x_mm=25, y_mm=15, z_mm=20)
        require(result.get("sketch_active") is True, f"Face sketch not active: {result!r}")
        self.finish_sketch()
        return result

    def cut(self):
        self.open_block()
        self.sketch()
        self.circle(25, 15, 5)
        self.finish_sketch()
        feature = self.call("sw_cut_extrude", depth_mm=20, flip_dir=True)
        props = self.volume()
        near(props["volume_mm3"], 30000 - math.pi * 5 ** 2 * 20)
        self.save("validation_cut.sldprt")
        return {"feature": feature, "mass_properties": props}

    def edge_feature(self, kind):
        self.open_block()
        arguments = {"edge_x_mm": 0, "edge_y_mm": 0, "edge_z_mm": 10}
        if kind == "fillet":
            result = self.call("sw_fillet", radius_mm=2, **arguments)
        else:
            result = self.call("sw_chamfer", distance_mm=1, angle_deg=45, **arguments)
        volume = self.volume()["volume_mm3"]
        require(0 < volume < 30000, f"{kind} did not remove material: {volume}")
        self.save(f"validation_{kind}.sldprt")
        return {"feature": result, "volume_mm3": volume}

    def triangle(self):
        self.new()
        self.sketch()
        for x1, y1, x2, y2 in [(0, 0, 30, 0), (30, 0, 0, 40), (0, 40, 0, 0)]:
            self.call("sw_draw_line", x1_mm=x1, y1_mm=y1, x2_mm=x2, y2_mm=y2)
        self.finish_sketch()
        feature = self.call("sw_boss_extrude", depth_mm=10)
        props = self.volume()
        near(props["volume_mm3"], 6000)
        self.save("validation_triangle.sldprt")
        return {"feature": feature, "mass_properties": props}

    def semicircle(self):
        self.new()
        self.sketch()
        arc = self.call("sw_draw_arc", x1_mm=-10, y1_mm=0, x2_mm=10, y2_mm=0, x3_mm=0, y3_mm=10)
        self.call("sw_draw_line", x1_mm=10, y1_mm=0, x2_mm=-10, y2_mm=0)
        self.finish_sketch()
        self.call("sw_boss_extrude", depth_mm=10)
        props = self.volume()
        near(props["volume_mm3"], 0.5 * math.pi * 10 ** 2 * 10)
        self.save("validation_semicircle.sldprt")
        return {"arc": arc, "mass_properties": props}

    def revolve(self, cut=False):
        self.new()
        self.sketch()
        self.rectangle(0, 0, 10, 20)
        self.call("sw_draw_centerline", x1_mm=0, y1_mm=-5, x2_mm=0, y2_mm=25)
        self.finish_sketch()
        feature = self.call("sw_revolve_boss", angle_deg=360)
        expected = math.pi * 10 ** 2 * 20
        near(self.volume()["volume_mm3"], expected)
        if cut:
            self.sketch()
            self.rectangle(5, 4, 8, 8)
            self.call("sw_draw_centerline", x1_mm=0, y1_mm=-5, x2_mm=0, y2_mm=25)
            self.finish_sketch()
            feature = self.call("sw_revolve_cut", angle_deg=360)
            expected -= math.pi * (8 ** 2 - 5 ** 2) * 4
        props = self.volume()
        near(props["volume_mm3"], expected)
        self.save("validation_revolve_cut.sldprt" if cut else "validation_revolve.sldprt")
        return {"feature": feature, "mass_properties": props}

    def sweep(self, cut=False, alias=False):
        self.open_block() if cut else self.new()
        self.sketch()
        self.call("sw_draw_line", x1_mm=10 if cut else 0, y1_mm=15 if cut else 0,
                  x2_mm=40 if cut else 0, y2_mm=15 if cut else 40)
        self.finish_sketch()
        tree = self.call("sw_get_feature_tree")
        sketches = [f["name"] for f in tree if "profilefeature" in f["type"].lower() or "sketch" in f["type"].lower()]
        require(sketches, f"No sketch in feature tree: {tree!r}")
        key = "diameter_mm" if alias else "circular_profile_diameter_mm"
        result = self.call("sw_cut_sweep" if cut else "sw_boss_sweep",
                           path_sketch_name=sketches[-1], **{key: 4})
        props = self.volume()
        if cut:
            require(0 < props["volume_mm3"] < 30000, f"Sweep did not cut material: {props!r}")
        else:
            near(props["volume_mm3"], math.pi * 2 ** 2 * 40)
        self.save(f"validation_{'cut' if cut else 'boss'}_sweep{'_alias' if alias else ''}.sldprt")
        return {"feature": result, "mass_properties": props}

    def circular_pattern(self):
        self.new()
        self.sketch()
        self.circle(0, 0, 30)
        self.finish_sketch()
        self.call("sw_boss_extrude", depth_mm=10)
        self.sketch()
        self.circle(15, 0, 2)
        self.finish_sketch()
        seed = self.call("sw_cut_extrude", depth_mm=10, flip_dir=True)
        result = self.call("sw_circular_pattern", feature_name=seed["feature"], total_instances=6,
                           total_angle_deg=360, axis_x_mm=30, axis_y_mm=0, axis_z_mm=5)
        props = self.volume()
        near(props["volume_mm3"], math.pi * 30 ** 2 * 10 - 6 * math.pi * 2 ** 2 * 10)
        self.save("validation_pattern.sldprt")
        return {"feature": result, "mass_properties": props}

    def unknown_plane(self):
        self.new()
        return self.invalid_before_com("sw_create_sketch_on_plane", {"plane_name": "__AUDIT_MISSING_PLANE__"})

    def rebuild(self, force):
        self.open_block()
        result = self.call("sw_rebuild", force=force)
        near(self.volume()["volume_mm3"], 30000)
        return result

    def prepare_assembly(self, overlap=False):
        if not self.block_verified:
            raise Blocked("No baseline part for assembly insertion")
        self.new("assembly")
        self.assembly_name = self.expected
        self.components = []
        first = self.call("sw_insert_component", component_path=str(self.block_path))
        self.components.append(first)
        second = self.call("sw_insert_component", component_path=str(self.block_path), x_mm=25 if overlap else 100)
        self.components.append(second)
        components = self.call("sw_list_components")
        require(len(components) == 2, f"Expected 2 components: {components!r}")
        return components

    def interference(self, overlap):
        components = self.prepare_assembly(overlap=overlap)
        result = self.call("sw_check_interference")
        require(bool(result.get("has_interference")) == overlap,
                f"Interference result disagrees with fixture: {result!r}, components={components!r}")
        if overlap:
            require(result.get("total_interference_volume_mm3", 0) > 0,
                    f"Overlap reported without positive volume: {result!r}")
        self.save("validation_overlap.sldasm" if overlap else "validation_clearance.sldasm")
        return {"components": components, "interference": result}

    def ground(self):
        self.prepare_assembly()
        name = self.components[0]["name"]
        self.call("sw_set_component_fixed", component_name=name, fixed=False)
        floating = self.call("sw_list_components")
        require(next(c for c in floating if c["name"] == name)["is_fixed"] is False,
                f"Component did not float: {floating!r}")
        self.call("sw_set_component_fixed", component_name=name, is_fixed=True)
        fixed = self.call("sw_list_components")
        require(next(c for c in fixed if c["name"] == name)["is_fixed"] is True,
                f"Component did not fix: {fixed!r}")
        return fixed

    def mate(self, kind):
        self.prepare_assembly()
        first, second = (c["name"] for c in self.components)
        self.call("sw_set_component_fixed", component_name=first, fixed=True)
        self.call("sw_set_component_fixed", component_name=second, fixed=False)
        plane = "Right Plane" if kind == "distance" else "Front Plane"
        result = self.call("sw_add_mate", mate_type=kind,
                           entity1=f"{plane}@{first}", entity2=f"{plane}@{second}",
                           distance_mm=100 if kind == "distance" else 0)
        require(result.get("status", "").lower() == "created", f"Mate not created: {result!r}")
        tree = self.call("sw_get_feature_tree")
        require("mate_name" in result, f"Mate response has no identity: {result!r}")
        self.save(f"validation_mate_{kind}.sldasm")
        return {"mate": result, "tree": tree}

    def prepare_drawing(self):
        if not self.block_verified:
            raise Blocked("No saved baseline model for drawing references")
        self.new("drawing")
        return self.call("sw_create_drawing_view", model_path=str(self.block_path),
                         orientation="*Front", x_mm=100, y_mm=80, scale="1:1")

    def drawing(self):
        view = self.prepare_drawing()
        self.front_view = view.get("name")
        near(view.get("scale_decimal"), 1, tolerance=0.0001)
        views = self.call("sw_list_drawing_views")
        require(any(v.get("name") == self.front_view for v in views), f"New drawing view not listed: {views!r}")
        self.save("validation_drawing.slddrw")
        return {"view": view, "views": views}

    def standard_views(self):
        self.new("drawing")
        result = self.call("sw_create_standard_views", model_path=str(self.block_path),
                           center_x_mm=100, center_y_mm=80, spacing_mm=60, include_isometric=True)
        views = self.call("sw_list_drawing_views")
        require(len(result) == 4 and len(views) >= 4,
                f"Four views were not created/listed: created={result!r}, listed={views!r}")
        self.save("validation_standard_views.slddrw")
        return {"created": result, "listed": views}

    def drawing_note(self):
        self.prepare_drawing()
        result = self.call("sw_add_drawing_note", text="MCP VALIDATION ONLY\nNOT FOR MANUFACTURING", x_mm=20, y_mm=20)
        self.save("validation_drawing_note.slddrw")
        return result

    def auto_dimension(self):
        view = self.prepare_drawing()
        result = self.call("sw_auto_dimension", view_name=view["name"])
        require(result.get("status") == "success", f"AutoDimension did not report success: {result!r}")
        self.save("validation_drawing_dimensions.slddrw")
        return {"tool_response": result,
                "limitation": "A success DTO alone is not proof of complete manufacturing dimensioning"}

    def section(self, reverse=False):
        view = self.prepare_drawing()
        result = self.call("sw_create_section_view", parent_view_name=view["name"],
                           cut_start_x_mm=100, cut_start_y_mm=50, cut_end_x_mm=100, cut_end_y_mm=110,
                           placement_x_mm=200, placement_y_mm=80, section_label="B" if reverse else "A",
                           reverse_direction=reverse)
        views = self.call("sw_list_drawing_views")
        require(any(v.get("name") == result.get("name") for v in views), f"Section not listed: {result!r}, {views!r}")
        self.save("validation_section_reverse.slddrw" if reverse else "validation_section.slddrw")
        return {"section": result, "views": views}

    def drawing_export(self, extension):
        self.prepare_drawing()
        path = self.output / "exports" / ("validation_drawing." + extension)
        result = self.call("sw_export_drawing", output_path=str(path), format_type=extension)
        require(path.is_file() and path.stat().st_size > 100, f"Drawing export missing/empty: {path}")
        header = path.read_bytes()[:4096]
        if extension == "pdf":
            require(header.startswith(b"%PDF-"), f"Not a PDF: {header[:40]!r}")
        elif extension == "dxf":
            require(b"SECTION" in header or b"AutoCAD Binary DXF" in header, "No DXF header/section")
        elif extension == "dwg":
            require(header.startswith(b"AC10"), f"Not a DWG: {header[:40]!r}")
        return {"result": result, "bytes": path.stat().st_size}

    def stress(self, iteration):
        self.new()
        self.sketch("Top Plane" if iteration % 2 else "Front Plane")
        self.rectangle(-5, -4, 5, 4)
        self.finish_sketch()
        self.call("sw_boss_extrude", depth_mm=3)
        near(self.volume()["volume_mm3"], 240)
        self.save(f"validation_repeat_{iteration}.sldprt")
        self.close_active_owned()
        return {"iteration": iteration, "volume_mm3": 240}

    def final_inventory(self):
        self.close_active_owned()
        documents = self.wire.call("sw_list_open_documents", {})
        current = {d.get("title"): d for d in documents}
        for original in self.initial_documents:
            require(original["title"] in current, f"Pre-existing document disappeared: {original!r}")
            require(current[original["title"]].get("path") == original.get("path"),
                    f"Pre-existing document path changed: {original!r}")
        (self.output / "live_session_after.json").write_text(json.dumps(documents, indent=2), encoding="utf-8")
        return {"documents": documents, "pre_existing_documents_preserved": True}

    def run(self):
        self.case("mcp.initialize_and_discover_48", self.initialize, live=False)
        self.case("validation.reject_zero_circle_radius", lambda: self.invalid_before_com(
            "sw_draw_circle", {"center_x_mm": 0, "center_y_mm": 0, "radius_mm": 0}), live=False)
        self.case("validation.reject_zero_extrusion_depth", lambda: self.invalid_before_com(
            "sw_boss_extrude", {"depth_mm": 0}), live=False)
        self.case("validation.reject_missing_file", lambda: self.invalid_before_com(
            "sw_open_doc", {"file_path": str(self.output / "never_created.sldprt")}), live=False)
        self.case("materials.discover_6061_catalog", self.material_catalog, live=False)
        self.case("session.connect_and_inventory", self.connect, live=False)
        self.case("document.new_part_default_template", lambda: self.new(default=True))
        self.case("geometry.baseline_block_50x30x20_volume_30000", self.make_block)
        block = self.block_verified
        self.case("inspection.feature_tree_contains_extrusion", self.inspect_tree, condition=block)
        self.case("inspection.viewport_png_nonblank", self.capture, condition=block)
        self.case("document.save_in_place_and_file_path_alias", self.in_place_and_alias_save, condition=block)
        self.case("document.save_reopen_preserves_volume", lambda: (self.open_block(), near(self.volume()["volume_mm3"], 30000)), condition=block)
        self.case("document.invalid_save_does_not_discard_model", self.save_failure, condition=block)
        self.case("document.failed_save_on_close_keeps_document_open", self.close_unsaved_failure)
        self.case("parameters.dimension_changes_physical_volume", self.dimension, condition=block)
        self.case("parameters.global_variable_create_readback", self.equation, condition=block)
        self.case("parameters.global_variable_update_readback", lambda: self.equation(update=True), condition=block)
        self.case("materials.assignment_density_mass_readback", self.material, condition=block)
        self.case("materials.clear_assignment_readback", lambda: self.material(clear=True), condition=block)
        for extension in ["step", "stl", "x_t", "iges"]:
            self.case(f"export.model_{extension}_file_integrity", lambda ext=extension: self.export_model(ext), condition=block)
        self.case("sketch.planar_face_activation", self.face_sketch, condition=block)
        self.case("sketch.unknown_plane_must_not_silently_use_front", self.unknown_plane)
        self.case("geometry.cut_cylinder_expected_removed_volume", self.cut, condition=block)
        for kind in ["fillet", "chamfer"]:
            self.case(f"geometry.{kind}_changes_volume", lambda k=kind: self.edge_feature(k), condition=block)
        self.case("geometry.lines_triangle_volume_6000", self.triangle)
        self.case("geometry.arc_semicircle_expected_volume", self.semicircle)
        self.case("geometry.revolve_cylinder_expected_volume", self.revolve)
        self.case("geometry.revolve_cut_expected_volume", lambda: self.revolve(cut=True))
        self.case("geometry.boss_sweep_expected_volume", self.sweep)
        self.case("geometry.boss_sweep_legacy_diameter_alias", lambda: self.sweep(alias=True))
        self.case("geometry.cut_sweep_removes_material", lambda: self.sweep(cut=True), condition=block)
        self.case("geometry.circular_pattern_six_holes_expected_volume", self.circular_pattern)
        for force in [True, False]:
            self.case(f"geometry.rebuild_force_{force}", lambda f=force: self.rebuild(f), condition=block)
        self.case("assembly.new_default_template", lambda: self.new("assembly", default=True))
        self.case("assembly.separated_components_have_no_interference", lambda: self.interference(False), condition=block)
        self.case("assembly.overlap_reports_positive_interference", lambda: self.interference(True), condition=block)
        self.case("assembly.fixed_floating_state_readback", self.ground, condition=block)
        for kind in ["coincident", "parallel", "distance"]:
            self.case(f"assembly.mate_{kind}", lambda k=kind: self.mate(k), condition=block)
        self.case("drawing.new_default_template", lambda: self.new("drawing", default=True))
        self.case("drawing.front_view_scale_and_list_readback", self.drawing, condition=block)
        self.case("drawing.standard_four_views_created", self.standard_views, condition=block)
        self.case("drawing.engineering_note", self.drawing_note, condition=block)
        self.case("drawing.auto_dimension_status", self.auto_dimension, condition=block)
        self.case("drawing.section_view", self.section, condition=block)
        self.case("drawing.section_reverse_view", lambda: self.section(reverse=True), condition=block)
        for extension in ["pdf", "dxf", "dwg", "slddrw"]:
            self.case(f"drawing.export_{extension}", lambda ext=extension: self.drawing_export(ext), condition=block)
        for iteration in range(1, 6):
            self.case(f"repeat.create_measure_save_close_{iteration}", lambda i=iteration: self.stress(i), condition=block)
        self.case("safety.pre_existing_documents_preserved", self.final_inventory)
        self.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(output.is_dir() and output.parent == Path("D:/New folder (2)").resolve(),
            "Refusing output outside the explicitly requested fresh audit directory")
    shutil.copyfile(__file__, output / "live_validation.py")
    audit = LiveAudit(args.project_root.resolve(), output)
    exit_code = 0
    try:
        audit.run()
    except Exception:
        (output / "live_harness_exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        exit_code = 2
        raise
    finally:
        # No cleanup CAD calls after a timeout or document-ownership safety abort.
        if audit.connected and not audit.fatal:
            try:
                audit.close_active_owned()
            except Exception:
                (output / "live_cleanup_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        child_exit = audit.wire.close()
        audit.flush()
        counts = dict(Counter(r["status"] for r in audit.records))
        print(json.dumps({"live_counts": counts, "connected": audit.connected,
                          "fatal": audit.fatal, "server_child_exit_code": child_exit}, indent=2), flush=True)
        (output / "live_execution.json").write_text(json.dumps({
            "command": [sys.executable, "-B", str(Path(__file__).resolve()), "--output-dir", str(output)],
            "counts": counts, "connected": audit.connected,
            "fatal": audit.fatal, "server_child_exit_code": child_exit,
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }, indent=2), encoding="utf-8")
        if counts.get("fail"):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
