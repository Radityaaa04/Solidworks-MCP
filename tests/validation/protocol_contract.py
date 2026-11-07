"""Offline/guarded MCP contract validation; never connect to SolidWorks.

Run with the project's existing Python (no pytest or downloads required)::

    python -B tests/validation/protocol_contract.py --output-dir <existing-dir>

Only this script and protocol_* artifacts in the output directory are written.
The stdio child runs the real server entrypoint with fail-closed side-effect
tripwires. Successful tool calls run only in-process with FakeSession/FakeWorker.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import itertools
import json
import os
import queue
import re
import runpy
import shutil
import subprocess
import sys
import threading
import time
import traceback
import unittest
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest import mock


REQUEST_TIMEOUT = 8.0
RUN_BUDGET = 98.0
TYPE_NAMES = {"str": "string", "float": "number", "int": "integer", "bool": "boolean"}
# Independent forwarding oracle, not extracted from the wrapper's implementation.
# Values: domain, method, positional/keyword style, public parameter order.
ROUTES = {
    "sw_get_session_info": ("client", "get_session_info", "pos", ()),
    "sw_new_part": ("document", "new_part", "pos", ("template_path",)),
    "sw_new_assembly": ("document", "new_assembly", "pos", ("template_path",)),
    "sw_open_doc": ("document", "open_doc", "pos", ("file_path", "doc_type")),
    "sw_save_doc": ("document", "save_doc", "pos", ("output_path",)),
    "sw_close_doc": ("document", "close_doc", "pos", ("save_changes",)),
    "sw_list_open_documents": ("document", "list_open_documents", "pos", ()),
    "sw_export_cad": ("document", "export_cad", "pos", ("output_path",)),
    "sw_create_sketch_on_plane": ("sketcher", "create_sketch", "pos", ("plane_name",)),
    "sw_create_sketch_on_face": ("sketcher", "create_sketch_on_face", "pos", ("x_mm", "y_mm", "z_mm")),
    "sw_close_sketch": ("sketcher", "close_sketch", "pos", ()),
    "sw_draw_line": ("sketcher", "draw_line", "pos", ("x1_mm", "y1_mm", "x2_mm", "y2_mm")),
    "sw_draw_centerline": ("sketcher", "draw_centerline", "pos", ("x1_mm", "y1_mm", "x2_mm", "y2_mm")),
    "sw_draw_rectangle": ("sketcher", "draw_rectangle", "pos", ("x1_mm", "y1_mm", "x2_mm", "y2_mm")),
    "sw_draw_circle": ("sketcher", "draw_circle", "pos", ("center_x_mm", "center_y_mm", "radius_mm")),
    "sw_draw_arc": ("sketcher", "draw_arc", "pos", ("x1_mm", "y1_mm", "x2_mm", "y2_mm", "x3_mm", "y3_mm")),
    "sw_create_3d_sketch": ("sketcher", "create_3d_sketch", "pos", ()),
    "sw_draw_3d_line": ("sketcher", "draw_3d_line", "pos", ("x1_mm", "y1_mm", "z1_mm", "x2_mm", "y2_mm", "z2_mm")),
    "sw_add_sketch_constraint": ("sketcher", "add_sketch_constraint", "kw", ("constraint_type", "x1_mm", "y1_mm", "x2_mm", "y2_mm")),
    "sw_boss_extrude": ("features", "boss_extrude", "pos", ("depth_mm", "flip_dir")),
    "sw_cut_extrude": ("features", "cut_extrude", "pos", ("depth_mm", "flip_dir")),
    "sw_revolve_boss": ("features", "revolve_boss", "pos", ("angle_deg", "reverse_dir")),
    "sw_revolve_cut": ("features", "revolve_cut", "pos", ("angle_deg", "reverse_dir")),
    "sw_fillet": ("features", "fillet", "pos", ("radius_mm", "edge_x_mm", "edge_y_mm", "edge_z_mm")),
    "sw_chamfer": ("features", "chamfer", "pos", ("distance_mm", "angle_deg", "edge_x_mm", "edge_y_mm", "edge_z_mm")),
    "sw_rebuild": ("features", "rebuild", "pos", ()),
    "sw_circular_pattern": ("features", "circular_pattern", "kw", ()),
    "sw_boss_sweep": ("features", "boss_sweep", "kw", ()),
    "sw_cut_sweep": ("features", "cut_sweep", "kw", ()),
    "sw_create_reference_plane": ("features", "create_reference_plane", "kw", ("plane_name", "first_reference", "constraint_type", "distance_mm", "angle_deg", "second_reference", "flip")),
    "sw_mirror_feature": ("features", "mirror_feature", "kw", ("plane_name", "feature_name", "mirror_body", "geometry_pattern")),
    "sw_linear_pattern": ("features", "linear_pattern", "kw", ("feature_name", "spacing1_mm", "instances1", "dir1_entity", "spacing2_mm", "instances2", "dir2_entity", "flip_dir1", "flip_dir2")),
    "sw_shell": ("features", "shell", "kw", ("thickness_mm", "face_x_mm", "face_y_mm", "face_z_mm", "shell_outward")),
    "sw_hole_wizard": ("features", "hole_wizard", "kw", ("hole_type", "standard", "fastener_size", "diameter_mm", "depth_mm", "x_mm", "y_mm", "z_mm", "through_all", "counterbore_diameter_mm", "counterbore_depth_mm", "countersink_angle_deg")),
    "sw_loft_boss": ("features", "loft_boss", "kw", ("profile1_sketch", "profile2_sketch", "guide_curve_sketch", "closed_loft", "thin_feature", "thin_thickness_mm")),
    "sw_get_equations": ("equations", "get_equations", "pos", ()),
    "sw_set_global_variable": ("equations", "set_global_variable", "pos", ("name", "value", "unit")),
    "sw_modify_dimension": ("equations", "modify_dimension", "pos", ("dimension_name", "value_mm")),
    "sw_get_mass_properties": ("inspection", "get_mass_properties", "pos", ()),
    "sw_get_feature_tree": ("inspection", "list_feature_tree", "pos", ()),
    "sw_capture_viewport": ("inspection", "capture_viewport", "pos", ("output_path",)),
    "sw_set_material": ("material", "set_material", "kw", ("material_name", "database_name", "config_name")),
    "sw_get_material": ("material", "get_material", "kw", ("config_name",)),
    "sw_list_materials": ("material", "list_materials", "kw", ("classification", "search")),
    "sw_insert_component": ("assembly", "insert_component", "kw", ("component_path", "x_mm", "y_mm", "z_mm", "config_name")),
    "sw_add_mate": ("assembly", "add_mate", "kw", ("mate_type", "entity1", "entity2", "alignment", "flip", "distance_mm", "angle_deg")),
    "sw_list_components": ("assembly", "list_components", "kw", ("top_level_only",)),
    "sw_check_interference": ("assembly", "check_interference", "kw", ("treat_coincidence_as_interference",)),
    "sw_set_component_fixed": ("assembly", "set_component_fixed", "kw", ("component_name", "fixed")),
    "sw_new_drawing": ("drawing", "new_drawing", "kw", ("template_path",)),
    "sw_create_drawing_view": ("drawing", "create_drawing_view", "kw", ("model_path", "orientation", "x_mm", "y_mm", "scale")),
    "sw_create_standard_views": ("drawing", "create_standard_views", "kw", ("model_path", "center_x_mm", "center_y_mm", "spacing_mm", "include_isometric", "scale")),
    "sw_list_drawing_views": ("drawing", "list_drawing_views", "kw", ()),
    "sw_auto_dimension": ("drawing", "auto_dimension", "kw", ("view_name", "scheme", "horizontal_placement", "vertical_placement")),
    "sw_add_drawing_note": ("drawing", "add_drawing_note", "kw", ("text", "x_mm", "y_mm")),
    "sw_export_drawing": ("drawing", "export_drawing", "kw", ("output_path", "format_type")),
    "sw_create_section_view": ("drawing", "create_section_view", "kw", ("parent_view_name", "cut_start_x_mm", "cut_start_y_mm", "cut_end_x_mm", "cut_end_y_mm", "placement_x_mm", "placement_y_mm", "section_label", "reverse_direction")),
    "sw_insert_bom_table": ("drawing", "insert_bom_table", "kw", ("view_name", "x_mm", "y_mm", "bom_type", "configuration", "table_template")),
}
DOMAIN_CLASSES = {
    "client": ("client", "SolidWorksClient"),
    "document": ("document", "DocumentManager"),
    "sketcher": ("sketcher", "SketchManager"),
    "features": ("features", "FeatureManager"),
    "equations": ("equations", "EquationManager"),
    "inspection": ("inspection", "InspectionManager"),
    "material": ("material", "MaterialManager"),
    "assembly": ("assembly", "AssemblyManager"),
    "drawing": ("drawing", "DrawingManager"),
}
IDEMPOTENT = {
    "sw_get_session_info", "sw_list_open_documents", "sw_get_equations",
    "sw_get_mass_properties", "sw_get_feature_tree", "sw_capture_viewport",
    "sw_get_material", "sw_list_materials", "sw_list_components",
    "sw_check_interference", "sw_list_drawing_views",
}
ALIASES = {
    "sw_save_doc": {"file_path"},
    "sw_boss_sweep": {"diameter_mm"},
    "sw_cut_sweep": {"diameter_mm"},
    "sw_circular_pattern": {"spacing_deg", "axis_name", "reverse_dir"},
    "sw_set_component_fixed": {"is_fixed"},
}


def require(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def json_file(path: Path, data: Any) -> None:
    require(path.name.startswith("protocol_"), "Artifact prefix violation")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def serialized(model: Any) -> dict:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def schema_of(tool: dict, output: bool = False) -> dict:
    return tool.get("outputSchema" if output else "inputSchema", tool.get("output_schema" if output else "input_schema", {}))


def annotation_types(node: Any) -> set[str]:
    import ast
    if isinstance(node, ast.Name) and node.id in TYPE_NAMES:
        return {TYPE_NAMES[node.id]}
    if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "Optional":
        return annotation_types(node.slice) | {"null"}
    raise AssertionError(f"Unhandled contract annotation: {ast.unparse(node)}")



def schema_types(schema: dict) -> set[str]:
    if "anyOf" in schema:
        return set().union(*(schema_types(item) for item in schema["anyOf"]))
    value = schema.get("type")
    return set(value) if isinstance(value, list) else ({value} if value else set())


def validate_json(value: Any, schema: dict, root: dict | None = None, location: str = "$") -> None:
    """Small local validator for the schema constructs these tools expose."""
    root = root or schema
    if "$ref" in schema:
        target = root
        require(schema["$ref"].startswith("#/"), "External schema reference is not allowed")
        for part in schema["$ref"][2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        validate_json(value, target, root, location)
        return
    if "anyOf" in schema:
        for alternative in schema["anyOf"]:
            try:
                validate_json(value, alternative, root, location)
                return
            except AssertionError:
                pass
        raise AssertionError(f"{location}: value does not match anyOf: {value!r}")
    expected = schema.get("type")
    if expected:
        checks = {
            "null": value is None,
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "string": isinstance(value, str),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }
        types = expected if isinstance(expected, list) else [expected]
        require(any(checks.get(t, False) for t in types), f"{location}: expected {expected}, got {value!r}")
    if "enum" in schema:
        require(value in schema["enum"], f"{location}: invalid enum value")
    if isinstance(value, dict):
        require(set(schema.get("required", ())) <= set(value), f"{location}: missing required properties")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate_json(item, properties[key], root, location + "." + key)
            elif schema.get("additionalProperties") is False:
                raise AssertionError(f"{location}: unexpected property {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_json(item, schema["additionalProperties"], root, location + "." + key)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            validate_json(item, schema["items"], root, f"{location}[{index}]")


class BoundaryViolation(RuntimeError):
    pass


class BoundaryGuards:
    """Fail-closed tripwires, never a fake successful CAD operation."""

    def __init__(self) -> None:
        self.stack = contextlib.ExitStack()
        self.attempts: list[dict] = []
        self.labels: list[str] = []
        self.worker_module = None
        self.session_module = None

    def block(self, obj: Any, name: str, label: str) -> None:
        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self.attempts.append({"boundary": label, "thread": threading.current_thread().name})
            print("PROTOCOL_COM_BOUNDARY_FORBIDDEN: " + label, file=sys.stderr, flush=True)
            raise BoundaryViolation("PROTOCOL_COM_BOUNDARY_FORBIDDEN: " + label)
        self.stack.enter_context(mock.patch.object(obj, name, forbidden))
        self.labels.append(label)

    def install(self) -> BoundaryGuards:
        # Importing pywin32 is permitted; connecting/dispatching is not.
        win_client = importlib.import_module("win32com.client")
        pythoncom = importlib.import_module("pythoncom")
        for name in ("Dispatch", "DispatchEx", "GetActiveObject", "GetObject"):
            if hasattr(win_client, name):
                self.block(win_client, name, "win32com.client." + name)
        for name in ("CoCreateInstance", "CoCreateInstanceEx", "GetActiveObject"):
            if hasattr(pythoncom, name):
                self.block(pythoncom, name, "pythoncom." + name)
        if hasattr(win_client, "gencache"):
            self.block(win_client.gencache, "EnsureDispatch", "win32com.client.gencache.EnsureDispatch")
        self.worker_module = importlib.import_module("sw_mcp.core.sta_worker")
        self.session_module = importlib.import_module("sw_mcp.cad.session")
        self.block(self.worker_module, "get_sta_worker", "get_sta_worker")
        self.block(self.worker_module.STAWorker, "start", "STAWorker.start")
        self.block(self.session_module, "get_cad_session", "get_cad_session")
        self.block(self.session_module.CADSession, "__init__", "CADSession.__init__")
        self.block(self.session_module.SolidWorksClient, "connect", "SolidWorksClient.connect")
        return self

    def state(self) -> dict:
        return {
            "mode": "fail_closed_tripwires_not_successful_mocks",
            "guarded_boundaries": self.labels,
            "attempts": self.attempts,
            "attempt_count": len(self.attempts),
            "sta_worker_created": bool(self.worker_module and self.worker_module._global_worker is not None),
            "cad_session_created": bool(self.session_module and self.session_module._session is not None),
            "sta_threads": [t.name for t in threading.enumerate() if "SolidWorks-STA" in t.name],
        }

    def close(self) -> None:
        self.stack.close()


def parse_parameters(node: Any) -> list[dict]:
    import ast
    require(not node.args.posonlyargs and not node.args.kwonlyargs and node.args.vararg is None and node.args.kwarg is None, "Unexpected public signature shape")
    arguments = node.args.args
    default_start = len(arguments) - len(node.args.defaults)
    result = []
    for index, argument in enumerate(arguments):
        item = {"name": argument.arg, "types": sorted(annotation_types(argument.annotation)), "required": index < default_start}
        if not item["required"]:
            item["default"] = ast.literal_eval(node.args.defaults[index - default_start])
        result.append(item)
    return result


def parse_contracts(workspace: Path) -> tuple[dict, list[str]]:
    import ast
    contracts = {}
    occurrences = []
    for path in sorted((workspace / "src/sw_mcp/tools").glob("*_tools.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("sw_"):
                occurrences.append(node.name)
                require(node.name not in contracts, "Duplicate AST tool name: " + node.name)
                assert node.returns is not None, "Public tool is missing its return annotation"
                contracts[node.name] = {
                    "file": str(path.relative_to(workspace)), "line": node.lineno,
                    "parameters": parse_parameters(node),
                    "return_annotation": ast.unparse(node.returns),
                    "list_result": isinstance(node.returns, ast.Subscript) and ast.unparse(node.returns.value) == "List",
                }
    return contracts, occurrences


def parameters_map(contract: dict) -> dict:
    return {p["name"]: p for p in contract["parameters"]}


def sample_value(parameter: dict, output: Path, salt: int = 1) -> Any:
    name = parameter["name"]
    types = set(parameter["types"]) - {"null"}
    if "boolean" in types:
        return not parameter.get("default", False)
    if "integer" in types:
        return 7 + salt
    if "number" in types:
        return 12.375 + salt
    examples = {
        "doc_type": "part", "mate_type": "distance", "entity1": "FACE:0,1,2",
        "entity2": "Top Plane@protocol_part-1", "alignment": "anti_aligned",
        "orientation": "*Isometric", "scale": "2:1", "unit": "deg",
        "scheme": "chain", "horizontal_placement": "below", "vertical_placement": "left",
        "format_type": "pdf", "plane_name": "Right Plane", "material_name": "6061 Alloy",
        "database_name": "SolidWorks Materials", "section_label": "B",
    }
    if name in examples:
        return examples[name]
    if name.endswith("path"):
        return str(output / f"protocol_mock_{name}_{salt}.sldprt")
    return f"protocol_{name}_{salt}_\u00d8\nDTO"


def minimal_arguments(contract: dict, output: Path) -> dict:
    return {p["name"]: sample_value(p, output, i + 1) for i, p in enumerate(contract["parameters"]) if p["required"]}


def effective_arguments(fn: Any, arguments: dict) -> dict:
    bound = inspect.signature(fn).bind(**arguments)
    bound.apply_defaults()
    return dict(bound.arguments)


def expected_forward(name: str, values: dict) -> tuple[str, str, list, dict]:
    domain, method, style, fields = ROUTES[name]
    if name == "sw_save_doc":
        return domain, method, [values["output_path"] or values["file_path"]], {}
    if name == "sw_set_component_fixed":
        return domain, method, [], {"component_name": values["component_name"], "fixed": values["fixed"] if values["is_fixed"] is None else values["is_fixed"]}
    if name in ("sw_boss_sweep", "sw_cut_sweep"):
        diameter = values["diameter_mm"] if values["circular_profile_diameter_mm"] is None else values["circular_profile_diameter_mm"]
        return domain, method, [], {"path_sketch_name": values["path_sketch_name"], "profile_sketch_name": values["profile_sketch_name"], "circular_profile_diameter_mm": diameter}
    if name == "sw_circular_pattern":
        coordinates = [values[key] for key in ("axis_x_mm", "axis_y_mm", "axis_z_mm")]
        return domain, method, [], {
            "feature_name": values["feature_name"], "total_instances": values["total_instances"],
            "total_angle_deg": values["total_angle_deg"] if values["spacing_deg"] is None else values["spacing_deg"],
            "equal_spacing": values["equal_spacing"],
            "axis_coord_mm": coordinates if all(value is not None for value in coordinates) else None,
            "axis_entity_name": values["axis_name"] or values["axis_entity_name"],
            "flip_dir": values["flip_dir"] or values["reverse_dir"],
        }
    if style == "pos":
        return domain, method, [values[field] for field in fields], {}
    return domain, method, [], {field: values[field] for field in fields}


class FakeDomain:
    def __init__(self, session: FakeSession, domain: str, real_class: Any) -> None:
        self.session = session
        self.domain = domain
        self.real_class = real_class

    def __getattr__(self, method: str) -> Any:
        real_method = getattr(self.real_class, method)
        signature = inspect.signature(real_method)
        signature = signature.replace(parameters=list(signature.parameters.values())[1:])

        def call(*args: Any, **kwargs: Any) -> Any:
            require(self.session.inside_worker, "Domain accessed outside FakeWorker.run")
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            record = {"domain": self.domain, "method": method, "args": list(args), "kwargs": kwargs, "bound_arguments": dict(bound.arguments)}
            self.session.calls.append(record)
            if self.session.error:
                raise RuntimeError(self.session.error)
            row = {
                "mocked": True, "tool": self.session.tool_name, "domain": self.domain,
                "method": method, "received": dict(bound.arguments),
                "unicode": "mm \u00b0 \u00d8 \u03b1", "nested": [0, 1.25, False, None, {"dto": "only primitives"}],
            }
            self.session.dto = [row, {"mocked": True, "second": {"empty": []}}] if self.session.list_result else row
            return self.session.dto
        return call


class FakeSession:
    def __init__(self, tool_name: str, list_result: bool, classes: dict, error: str | None = None) -> None:
        self.tool_name = tool_name
        self.list_result = list_result
        self.error = error
        self.inside_worker = False
        self.calls: list[dict] = []
        self.dto: Any = None
        for domain, real_class in classes.items():
            setattr(self, domain, FakeDomain(self, domain, real_class))


class FakeWorker:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.runs: list[bool] = []

    async def run(self, function: Any, idempotent: bool = False) -> Any:
        self.runs.append(idempotent)
        require(not self.session.inside_worker, "Unexpected nested worker submission")
        self.session.inside_worker = True
        try:
            return function()
        finally:
            self.session.inside_worker = False


def tool_error(value: Any = None, exception: Exception | None = None) -> str | None:
    if exception is not None:
        parts = []
        current: BaseException | None = exception
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            parts.append(type(current).__name__ + ": " + str(current))
            current = current.__cause__ or current.__context__
        return "\nCaused by: ".join(parts)
    data = serialized(value) if hasattr(value, "model_dump") else value
    if isinstance(data, dict) and (data.get("error") is not None or data.get("isError", data.get("is_error", False))):
        return json.dumps(data, ensure_ascii=True)
    return None


@dataclass
class Context:
    workspace: Path
    output: Path
    guards: BoundaryGuards
    server: Any = None
    contracts: Any = None
    imported_tools: Any = None
    schemas: Any = None
    classes: Any = None
    wire: Any = None

    def fn(self, name: str) -> Any:
        return self.server.mcp._tool_manager.get_tool(name).fn


def exercise_mock(ctx: Context, name: str, arguments: dict, through_mcp: bool = True, failure: bool = False) -> dict:
    fn = ctx.fn(name)
    contract = ctx.contracts[name]
    expected = expected_forward(name, effective_arguments(fn, arguments))
    marker = "protocol_fake_domain_failure:" + name
    session = FakeSession(name, contract["list_result"], ctx.classes, marker if failure else None)
    worker = FakeWorker(session)
    module = importlib.import_module(fn.__module__)

    def session_factory() -> FakeSession:
        require(session.inside_worker, "get_cad_session must be called inside the worker callback")
        return session

    exception = None
    result = None
    with mock.patch.object(module, "get_sta_worker", return_value=worker) as worker_getter, mock.patch.object(module, "get_cad_session", side_effect=session_factory) as session_getter:
        try:
            operation = ctx.server.mcp.call_tool(name, arguments) if through_mcp else fn(**arguments)
            result = asyncio.run(asyncio.wait_for(operation, REQUEST_TIMEOUT))
        except Exception as exc:  # noqa: BLE001 - record arbitrary tool failures
            exception = exc
        require(worker_getter.call_count == 1, f"Expected one worker lookup, got {worker_getter.call_count}; exception={exception!r}")
        require(session_getter.call_count == 1, f"Expected one session lookup, got {session_getter.call_count}; exception={exception!r}")
    require(worker.runs == [name in IDEMPOTENT], f"Wrong idempotency or duplicate submission: {worker.runs}")
    require(len(session.calls) == 1, f"Expected one domain call: {session.calls}")
    call = session.calls[0]
    actual = (call["domain"], call["method"], call["args"], call["kwargs"])
    require(actual == expected, f"Incorrect forwarding\nExpected: {expected!r}\nActual: {actual!r}")
    if failure:
        message = tool_error(result, exception)
        require(message is not None and marker in message, f"Domain failure was lost: {result!r}, {exception!r}")
        return {"arguments": arguments, "call": call, "idempotent": worker.runs[0], "expected_domain_error": message, "mode": "mocked_domain_error"}
    if exception is not None:
        raise exception
    require(json.loads(json.dumps(session.dto, ensure_ascii=True, allow_nan=False)) == session.dto, "Fake DTO is not JSON-safe")
    if through_mcp:
        data = serialized(result)
        require(not data.get("isError", False), f"MCP result is an error: {data}")
        structured = data.get("structuredContent", data.get("structured_content"))
        require(structured == {"result": session.dto}, f"Structured DTO changed: {structured!r}")
        validate_json(structured, schema_of(ctx.schemas[name], output=True))
        content = data.get("content", [])
        require(all(item.get("type") == "text" for item in content), "Unexpected non-text content for JSON DTO")
        texts = [json.loads(item["text"]) for item in content]
        expected_texts = session.dto if contract["list_result"] else [session.dto]
        require(texts == expected_texts, "MCP text DTO differs from structured DTO")
        require(json.loads(json.dumps(data, allow_nan=False)) == data, "CallToolResult is not JSON-safe")
    else:
        require(result is session.dto, "Wrapper did not return the worker DTO unchanged")
    return {"arguments": arguments, "call": call, "idempotent": worker.runs[0], "mode": "mocked_mcp" if through_mcp else "mocked_direct_wrapper", "dto_shape": "list[dict]" if contract["list_result"] else "dict", "dto_json_roundtrip": True}


class ContractCase(unittest.TestCase):
    def __init__(self, name: str, category: str, body: Any, details: dict | None = None) -> None:
        super().__init__("runTest")
        self.case_name = name
        self.category = category
        self.body = body
        self.details = details or {}

    def id(self) -> str:
        return self.category + ":" + self.case_name

    def __str__(self) -> str:
        return self.id()

    def runTest(self) -> None:
        result = self.body()
        if isinstance(result, dict):
            self.details.update(result)


class RecordingResult(unittest.TextTestResult):
    def __init__(self, stream: Any, descriptions: bool, verbosity: int, sink: list) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.sink = sink

    def startTest(self, test: Any) -> None:
        self.started = time.perf_counter()
        super().startTest(test)

    def record(self, test: Any, status: str, error: Any = None, reason: str | None = None) -> None:
        self.sink.append({
            "id": test.id(), "category": test.category, "name": test.case_name,
            "status": status, "duration_seconds": round(time.perf_counter() - self.started, 6),
            "details": test.details, "reason": reason,
            "exception_type": error[0].__name__ if error else None,
            "traceback": "".join(traceback.format_exception(*error)) if error else None,
        })

    def addSuccess(self, test: Any) -> None:
        self.record(test, "pass")
        super().addSuccess(test)

    def addFailure(self, test: Any, err: Any) -> None:
        self.record(test, "fail", err)
        super().addFailure(test, err)

    def addError(self, test: Any, err: Any) -> None:
        self.record(test, "fail", err)
        super().addError(test, err)

    def addSkip(self, test: Any, reason: str) -> None:
        self.record(test, "skip", reason=reason)
        super().addSkip(test, reason)


def run_cases(cases: list, log: Any, records: list) -> None:
    def factory(stream: Any, descriptions: bool, verbosity: int) -> RecordingResult:
        return RecordingResult(stream, descriptions, verbosity, records)
    unittest.TextTestRunner(stream=log, verbosity=2, resultclass=factory).run(unittest.TestSuite(cases))
    log.flush()


class WireClient:
    def __init__(self, command: list[str], output: Path, env: dict, deadline: float) -> None:
        self.command = command
        self.output = output
        self.deadline = deadline
        self.responses = queue.Queue()
        self.stdout_lines: list[str] = []
        self.stderr_lines: list[str] = []
        self.sent: list[dict] = []
        self.received: list[dict] = []
        self.request_id = 0
        self.shutdown = None
        self.request_log = (output / "protocol_wire_requests.jsonl").open("w", encoding="utf-8")
        self.process = subprocess.Popen(command, cwd=str(output), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.stdout_thread = threading.Thread(target=self.read_stdout, name="protocol-stdout-reader", daemon=True)
        self.stderr_thread = threading.Thread(target=self.read_stderr, name="protocol-stderr-reader", daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()

    def read_stdout(self) -> None:
        with (self.output / "protocol_wire_stdout.jsonl").open("w", encoding="utf-8") as target:
            stdout = self.process.stdout
            assert stdout is not None
            for line in stdout:
                self.stdout_lines.append(line)
                target.write(line)
                target.flush()
                self.responses.put(line)
        self.responses.put(None)

    def read_stderr(self) -> None:
        with (self.output / "protocol_wire_stderr.log").open("w", encoding="utf-8") as target:
            stderr = self.process.stderr
            assert stderr is not None
            for line in stderr:
                self.stderr_lines.append(line)
                target.write(line)
                target.flush()

    def send(self, message: dict) -> None:
        self.sent.append(message)
        line = json.dumps(message, ensure_ascii=True, allow_nan=False) + "\n"
        self.request_log.write(line)
        self.request_log.flush()
        stdin = self.process.stdin
        assert stdin is not None
        stdin.write(line)
        stdin.flush()

    def notify(self, method: str, params: dict | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def request(self, method: str, params: dict | None = None) -> dict:
        self.request_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": self.request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        deadline = min(self.deadline, time.monotonic() + REQUEST_TIMEOUT)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Request {self.request_id} {method} exceeded {REQUEST_TIMEOUT}s; stderr={''.join(self.stderr_lines)[-1500:]}")
            try:
                line = self.responses.get(timeout=remaining)
            except queue.Empty as exc:
                raise TimeoutError(f"Request {self.request_id} {method} timed out after {REQUEST_TIMEOUT}s") from exc
            require(line is not None, f"Server exited before response; exit={self.process.poll()}, stderr={''.join(self.stderr_lines)[-1500:]}")
            frame = json.loads(line)
            validate_frame(frame)
            self.received.append(frame)
            if "id" not in frame:
                require("method" in frame, "Unexpected notification")
                continue
            require(frame["id"] == self.request_id, f"Unexpected response ID: {frame!r}")
            return frame

    def close(self) -> dict:
        if self.shutdown is not None:
            return self.shutdown
        forced = None
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            exitcode = self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            # This Popen handle belongs to this test; never enumerate/kill user processes.
            forced = "terminate_owned_child_after_EOF_timeout"
            self.process.terminate()
            try:
                exitcode = self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                forced = "kill_owned_child_after_terminate_timeout"
                self.process.kill()
                exitcode = self.process.wait(timeout=3)
        self.stdout_thread.join(timeout=2)
        self.stderr_thread.join(timeout=2)
        self.request_log.close()
        for pipe in (self.process.stdout, self.process.stderr):
            if pipe:
                pipe.close()
        self.shutdown = {"pid": self.process.pid, "exitcode": exitcode, "cleanup": forced or "graceful_EOF", "stdout_reader_alive": self.stdout_thread.is_alive(), "stderr_reader_alive": self.stderr_thread.is_alive()}
        return self.shutdown


def validate_frame(frame: Any) -> None:
    require(isinstance(frame, dict) and frame.get("jsonrpc") == "2.0", f"Non-JSON-RPC stdout frame: {frame!r}")
    if "method" in frame:
        require(isinstance(frame["method"], str) and "result" not in frame and "error" not in frame, "Malformed JSON-RPC method frame")
    else:
        require("id" in frame and (("result" in frame) != ("error" in frame)), "Malformed JSON-RPC response frame")


def bootstrap(ctx: Context) -> dict:
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        ctx.server = importlib.import_module("sw_mcp.server")
        imported = asyncio.run(asyncio.wait_for(ctx.server.mcp.list_tools(), REQUEST_TIMEOUT))
    require(captured.getvalue() == "", f"Import/list_tools polluted stdout: {captured.getvalue()!r}")
    require(Path(ctx.server.__file__).resolve() == (ctx.workspace / "src/sw_mcp/server.py").resolve(), "Imported a different sw_mcp server than the workspace")
    ctx.imported_tools = [serialized(tool) for tool in imported]
    ctx.schemas = {tool["name"]: tool for tool in ctx.imported_tools}
    ctx.contracts, occurrences = parse_contracts(ctx.workspace)
    ctx.classes = {}
    for domain, (module_name, class_name) in DOMAIN_CLASSES.items():
        ctx.classes[domain] = getattr(importlib.import_module("sw_mcp.cad." + module_name), class_name)
    require(not ctx.guards.attempts, "Import/list_tools touched a CAD boundary")
    return {"mode": "real_import_real_registration_with_fail_closed_tripwires", "server_class": str(type(ctx.server.mcp)), "server_file": str(ctx.server.__file__), "imported_tool_count": len(imported), "unique_tool_count": len(ctx.schemas), "ast_tool_count": len(occurrences), "stdout_bytes": len(captured.getvalue()), "guards": ctx.guards.state()}


def schema_test(ctx: Context, name: str) -> dict:
    contract = ctx.contracts[name]
    schema = schema_of(ctx.schemas[name])
    require(schema.get("type") == "object", "Tool input schema must be an object")
    params = parameters_map(contract)
    properties = schema.get("properties", {})
    require(set(properties) == set(params), f"Schema properties differ from AST: {set(properties) ^ set(params)}")
    expected_required = {p["name"] for p in params.values() if p["required"]}
    require(set(schema.get("required", ())) == expected_required, "Required parameters differ from AST")
    signature = inspect.signature(ctx.fn(name))
    require(list(signature.parameters) == list(params), "Runtime signature differs from AST")
    for field, parameter in params.items():
        require(schema_types(properties[field]) == set(parameter["types"]), f"{name}.{field}: schema type differs from AST")
        if parameter["required"]:
            require("default" not in properties[field], f"Required field has a default: {field}")
            require(signature.parameters[field].default is inspect.Parameter.empty, "Runtime requiredness mismatch")
        else:
            require("default" in properties[field] and properties[field]["default"] == parameter["default"], f"{name}.{field}: schema default differs from AST")
            require(signature.parameters[field].default == parameter["default"], "Runtime default differs from AST")
            validate_json(parameter["default"], properties[field])
    require(bool(ctx.schemas[name].get("description")), "Tool description is empty")
    require(bool(schema_of(ctx.schemas[name], True)), "Missing output DTO schema")
    return {"tool": name, "parameter_count": len(params), "required": sorted(expected_required), "nullable": [p["name"] for p in params.values() if "null" in p["types"]], "source": {"file": contract["file"], "line": contract["line"]}}


def registration_cases(ctx: Context) -> list:
    def counts() -> dict:
        names = [tool["name"] for tool in ctx.imported_tools]
        require(len(names) == 58, f"Expected 58 tools, got {len(names)}")
        require(len(set(names)) == len(names), "Duplicate registered tool names")
        require(set(names) == set(ctx.contracts) == set(ROUTES), "Registration/AST/independent route catalog mismatch")
        require(len(ctx.server.mcp._tool_manager.list_tools()) == 58, "Internal registry count mismatch")
        return {"real_import_count": len(names), "unique_names": len(set(names)), "independent_routes": len(ROUTES)}
    cases = [ContractCase("real_registration_count_and_unique_names", "real_import", counts)]
    for name in ctx.contracts:
        cases.append(ContractCase(name, "schema_ast_runtime", lambda name=name: schema_test(ctx, name)))
    return cases


def mock_cases(ctx: Context) -> list:
    cases = []
    for name, contract in ctx.contracts.items():
        base = minimal_arguments(contract, ctx.output)
        canonical = dict(base)
        for index, parameter in enumerate(contract["parameters"]):
            if parameter["name"] not in ALIASES.get(name, set()):
                canonical[parameter["name"]] = sample_value(parameter, ctx.output, index + 3)
        for label, arguments, through in (("direct_defaults", base, False), ("mcp_defaults", base, True), ("direct_canonical", canonical, False), ("mcp_canonical", canonical, True)):
            cases.append(ContractCase(name + ":" + label, "mock_forward_dto", lambda name=name, arguments=arguments, through=through: exercise_mock(ctx, name, arguments, through), {"tool": name}))
        for index, parameter in enumerate(contract["parameters"]):
            arguments = dict(base)
            arguments[parameter["name"]] = sample_value(parameter, ctx.output, index + 23)
            cases.append(ContractCase(name + ":" + parameter["name"], "mock_each_parameter", lambda name=name, arguments=arguments: exercise_mock(ctx, name, arguments), {"tool": name, "parameter": parameter["name"]}))
            if "null" in parameter["types"]:
                nullable = dict(base, **{parameter["name"]: None})
                cases.append(ContractCase(name + ":" + parameter["name"] + "=null", "mock_nullable", lambda name=name, arguments=nullable: exercise_mock(ctx, name, arguments)))
        for through in (False, True):
            cases.append(ContractCase(name + (":mcp" if through else ":direct"), "mock_error_propagation", lambda name=name, arguments=base, through=through: exercise_mock(ctx, name, arguments, through, True)))
    return cases


def alias_cases(ctx: Context) -> list:
    cases = []
    scenarios = {
        "sw_save_doc": [
            ("in_place", {}), ("canonical", {"output_path": "protocol_canonical.sldprt"}),
            ("alias", {"file_path": "protocol_alias.sldprt"}),
            ("conflict_canonical_wins", {"output_path": "protocol_canonical.sldprt", "file_path": "protocol_alias.sldprt"}),
            ("empty_canonical_falls_back", {"output_path": "", "file_path": "protocol_alias.sldprt"}),
            ("null_canonical_falls_back", {"output_path": None, "file_path": "protocol_alias.sldprt"}),
            ("empty_alias_is_preserved", {"file_path": ""}),
        ],
        "sw_set_component_fixed": [
            ("default", {}), ("canonical_false", {"fixed": False}), ("alias_false", {"is_fixed": False}),
            ("conflict_alias_false_wins", {"fixed": True, "is_fixed": False}),
            ("conflict_alias_true_wins", {"fixed": False, "is_fixed": True}),
            ("null_alias_falls_back", {"fixed": False, "is_fixed": None}),
        ],
        "sw_circular_pattern": [
            ("canonical", {"total_angle_deg": 270.0, "axis_entity_name": "CanonicalAxis", "flip_dir": True}),
            ("aliases", {"spacing_deg": 45.0, "axis_name": "AliasAxis", "reverse_dir": True}),
            ("conflict_angle_alias_wins", {"total_angle_deg": 270.0, "spacing_deg": 45.0}),
            ("zero_angle_alias_preserved", {"total_angle_deg": 270.0, "spacing_deg": 0.0}),
            ("null_angle_alias_falls_back", {"total_angle_deg": 270.0, "spacing_deg": None}),
            ("conflict_axis_alias_wins", {"axis_entity_name": "CanonicalAxis", "axis_name": "AliasAxis"}),
            ("empty_axis_alias_falls_back", {"axis_entity_name": "CanonicalAxis", "axis_name": ""}),
            ("reverse_true_or_flip_false", {"flip_dir": False, "reverse_dir": True}),
            ("reverse_false_cannot_override_flip_true", {"flip_dir": True, "reverse_dir": False}),
            ("both_directions_false", {"flip_dir": False, "reverse_dir": False}),
        ],
        "sw_rebuild": [("default_force_ignored", {}), ("true_force_ignored", {"force": True}), ("false_force_ignored", {"force": False})],
    }
    for name in ("sw_boss_sweep", "sw_cut_sweep"):
        scenarios[name] = [
            ("canonical", {"circular_profile_diameter_mm": 12.0}), ("alias", {"diameter_mm": 9.0}),
            ("conflict_canonical_wins", {"circular_profile_diameter_mm": 12.0, "diameter_mm": 9.0}),
            ("null_canonical_falls_back", {"circular_profile_diameter_mm": None, "diameter_mm": 9.0}),
            ("zero_canonical_preserved", {"circular_profile_diameter_mm": 0.0, "diameter_mm": 9.0}),
            ("both_null", {"circular_profile_diameter_mm": None, "diameter_mm": None}),
        ]
    for bits in itertools.product((False, True), repeat=3):
        coordinates = {field: (0.0 if present else None) for field, present in zip(("axis_x_mm", "axis_y_mm", "axis_z_mm"), bits)}
        scenarios["sw_circular_pattern"].append(("axis_presence_" + "".join(str(int(bit)) for bit in bits), coordinates))
    for name, variants in scenarios.items():
        for label, overrides in variants:
            arguments = minimal_arguments(ctx.contracts[name], ctx.output)
            arguments.update(overrides)
            cases.append(ContractCase(name + ":" + label, "mock_alias_semantics", lambda name=name, arguments=arguments: exercise_mock(ctx, name, arguments), {"tool": name, "scenario": label}))
    return cases


def extra_argument_case(ctx: Context) -> dict:
    name = "sw_insert_component"
    arguments = minimal_arguments(ctx.contracts[name], ctx.output)
    arguments["fixed"] = True
    session = FakeSession(name, False, ctx.classes)
    worker = FakeWorker(session)
    module = importlib.import_module(ctx.fn(name).__module__)
    exception = None
    with mock.patch.object(module, "get_sta_worker", return_value=worker), mock.patch.object(module, "get_cad_session", return_value=session):
        try:
            result = asyncio.run(asyncio.wait_for(ctx.server.mcp.call_tool(name, arguments), REQUEST_TIMEOUT))
        except Exception as exc:  # noqa: BLE001 - characterize SDK validation failures
            exception = exc
            result = None
    message = tool_error(result, exception)
    if message:
        require(not session.calls, "Unknown argument rejected only after a domain operation")
        return {"behavior": "rejected_before_domain", "error": message}
    require(len(session.calls) == 1, "Expected a mocked domain call")
    require("fixed" not in session.calls[0]["kwargs"], "Unknown fixed parameter leaked to domain")
    return {"behavior": "silently_ignored", "call": session.calls[0], "finding": "MCP accepts an unsupported fixed key but does not ground the component"}


def docs_cases(ctx: Context) -> tuple[list, dict]:
    import ast
    cases = []
    skill_path = ctx.workspace / "skills/solidworks-cad/SKILL.md"
    rules_path = ctx.workspace / "rules/AGENTS.md"
    texts = {str(p.relative_to(ctx.workspace)): p.read_text(encoding="utf-8") for p in (skill_path, rules_path)}
    skill = texts[str(skill_path.relative_to(ctx.workspace))]
    catalog = skill.split("## 2.", 1)[0]
    entries = []
    for index, line in enumerate(catalog.splitlines(), 1):
        match = re.match(r"- `(sw_\w+\(.*\))`:", line)
        if match:
            snippet = match.group(1)
            node = ast.parse("def " + snippet + ":\n    pass\n").body[0]
            assert isinstance(node, ast.FunctionDef)
            entries.append({"name": node.name, "line": index, "parameters": parse_parameters(node), "signature": snippet})
    def coverage() -> dict:
        names = {entry["name"] for entry in entries}
        require(names == set(ctx.schemas), f"Skill catalog coverage mismatch: missing={set(ctx.schemas) - names}, unknown={names - set(ctx.schemas)}")
        return {"entries": len(entries), "unique_names": len(names), "duplicates": {k: v for k, v in Counter(e["name"] for e in entries).items() if v > 1}}
    cases.append(ContractCase("catalog_covers_all_real_tools", "documentation", coverage))
    for entry in entries:
        def documented_signature(entry: dict = entry, exact: bool = False) -> dict:
            name = entry["name"]
            require(name in ctx.contracts, "Unknown documented tool: " + name)
            actual = parameters_map(ctx.contracts[name])
            documented = {p["name"]: p for p in entry["parameters"]}
            require(set(documented) <= set(actual), f"Invented parameters: {set(documented) - set(actual)}")
            for field, spec in documented.items():
                require(spec == actual[field], f"Incorrect documented type/default/requiredness for {name}.{field}: {spec} != {actual[field]}")
            require({p["name"] for p in actual.values() if p["required"]} <= set(documented), "Documented signature omits a required parameter")
            if exact:
                require(set(documented) == set(actual), f"Catalog advertises exact schemas but omits parameters for {name}: {sorted(set(actual) - set(documented))}")
            return {"tool": name, "line": entry["line"], "documented": list(documented), "actual": list(actual), "missing_optional_parameters": sorted(set(actual) - set(documented))}
        context = {"source": "skills/solidworks-cad/SKILL.md", "line": entry["line"], "signature": entry["signature"]}
        cases.append(ContractCase(f"{entry['name']}:line_{entry['line']}", "doc_signature_binding", documented_signature, dict(context)))
        cases.append(ContractCase(f"{entry['name']}:line_{entry['line']}", "doc_exact_schema", lambda entry=entry: documented_signature_for_exact(ctx, entry), dict(context)))
    headings = list(re.finditer(r"^### ([A-H])\..*?\((\d+) Tools\)", catalog, re.MULTILINE))
    sections = []
    for index, match in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(catalog)
        actual = len(re.findall(r"^- `sw_\w+\(", catalog[match.end():end], re.MULTILINE))
        section = {"section": match.group(1), "declared": int(match.group(2)), "actual": actual}
        sections.append(section)
        def check_section(section: dict = section) -> dict:
            require(section["declared"] == section["actual"], f"Skill section {section['section']} claims {section['declared']} tools but lists {section['actual']}")
            return section
        cases.append(ContractCase("catalog_section_" + section["section"], "documentation", check_section, dict(section)))
    call_counts = {}
    placeholder_count = 0
    for relative, text in texts.items():
        refs = set(re.findall(r"\bsw_[a-z_]+\b", text))
        def references(refs: set = refs, relative: str = relative) -> dict:
            require(refs <= set(ctx.schemas), f"Unknown tool references in {relative}: {refs - set(ctx.schemas)}")
            return {"source": relative, "unique_referenced_tools": len(refs)}
        cases.append(ContractCase(relative + ":known_tool_references", "documentation", references))
        snippets = []
        for match in re.finditer(r"`([^`\n]+)`", text):
            snippet = match.group(1)
            if relative.endswith("SKILL.md") and match.start() < text.find("## 2."):
                continue
            try:
                tree = ast.parse(snippet, mode="eval")
            except SyntaxError:
                continue
            if isinstance(tree.body, ast.Call) and isinstance(tree.body.func, ast.Name) and tree.body.func.id.startswith("sw_"):
                call = tree.body
                line = text.count("\n", 0, match.start()) + 1
                placeholders = sum(isinstance(n, ast.Name) or (isinstance(n, ast.Constant) and n.value is Ellipsis) for n in itertools.chain(call.args, (k.value for k in call.keywords)))
                placeholder_count += placeholders
                snippets.append({"call": call, "snippet": snippet, "line": line, "placeholders": placeholders})
        call_counts[relative] = len(snippets)
        for item in snippets:
            def binding(item: dict = item, relative: str = relative) -> dict:
                call = item["call"]
                name = call.func.id
                require(name in ctx.contracts, "Unknown documented call: " + name)
                require(all(k.arg is not None for k in call.keywords), "Unverifiable **kwargs example")
                positional = [object() for _ in call.args]
                keywords = {k.arg: object() for k in call.keywords}
                signature = inspect.signature(ctx.fn(name))
                bound = signature.bind(*positional, **keywords)
                schema = schema_of(ctx.schemas[name])
                fields = list(signature.parameters)
                literals_checked = 0
                for field, expression in itertools.chain(zip(fields, call.args), ((k.arg, k.value) for k in call.keywords)):
                    try:
                        value = ast.literal_eval(expression)
                    except (ValueError, TypeError):
                        continue
                    if value is Ellipsis:
                        continue
                    validate_json(value, schema["properties"][field])
                    literals_checked += 1
                return {"source": relative, "line": item["line"], "snippet": item["snippet"], "tool": name, "bound_fields": list(bound.arguments), "literal_values_checked": literals_checked, "non_executable_placeholders": item["placeholders"], "executed": False}
            cases.append(ContractCase(f"{relative}:line_{item['line']}:{item['snippet']}", "doc_workflow_rule_binding", binding, {"source": relative, "line": item["line"], "snippet": item["snippet"]}))
    config = json.loads((ctx.workspace / "mcp_config.json").read_text(encoding="utf-8"))
    aliases = set(config["mcpServers"])
    for relative, text in texts.items():
        referenced = re.findall(r"`([^`]+)` MCP server", text)
        def server_alias(relative: str = relative, referenced: list = referenced) -> dict:
            require(set(referenced) <= aliases, f"{relative} names MCP server(s) {referenced}, but mcp_config.json configures {sorted(aliases)}")
            return {"documented_server_names": referenced, "configured_server_names": sorted(aliases)}
        cases.append(ContractCase(relative + ":configured_server_alias", "documentation", server_alias, {"documented_server_names": referenced, "configured_server_names": sorted(aliases)}))
    rules = texts[str(rules_path.relative_to(ctx.workspace))]
    required_match = re.search(r"For `sw_circular_pattern`, provide required (.+?), and either", rules)
    if required_match:
        claimed = re.findall(r"`([^`]+)`", required_match.group(1))
        actual_required = schema_of(ctx.schemas["sw_circular_pattern"]).get("required", [])
        def requiredness() -> dict:
            require(set(claimed) == set(actual_required), f"Rules label {claimed} required, but schema requires only {actual_required}")
            return {"claimed": claimed, "schema_required": actual_required}
        cases.append(ContractCase("rules_pattern_requiredness", "documentation", requiredness, {"claimed_required": claimed, "schema_required": actual_required}))
    def unsupported_fixed() -> dict:
        require("fixed" not in schema_of(ctx.schemas["sw_insert_component"])["properties"], "Rules say insert_component does not accept fixed")
        require("diameter_mm" in schema_of(ctx.schemas["sw_boss_sweep"])["properties"], "Rules reference an unavailable sweep alias")
        return {"insert_fixed_absent_from_schema": True, "sweep_diameter_alias_exists": True}
    cases.append(ContractCase("rules_explicit_parameter_guidance", "documentation", unsupported_fixed))
    workflows = list(re.finditer(r"^### Workflow (\d+): (.+)$", skill, re.MULTILINE))
    expected_order = {
        "1": ["sw_new_part", "sw_create_sketch_on_plane", "sw_close_sketch", "sw_boss_extrude", "sw_save_doc"],
        "2": ["sw_new_assembly", "sw_insert_component", "sw_set_component_fixed", "sw_add_mate", "sw_check_interference", "sw_save_doc"],
        "3": ["sw_new_drawing", "sw_create_standard_views", "sw_create_section_view", "sw_add_drawing_note", "sw_export_drawing"],
    }
    for index, workflow in enumerate(workflows):
        end = workflows[index + 1].start() if index + 1 < len(workflows) else skill.find("## 3.", workflow.end())
        block = skill[workflow.end():end if end >= 0 else len(skill)]
        number = workflow.group(1)
        def sequence(block: str = block, number: str = number) -> dict:
            positions = [block.find(name + "(") for name in expected_order[number]]
            require(all(p >= 0 for p in positions) and positions == sorted(positions), f"Workflow {number} operation ordering is inconsistent")
            return {"workflow": number, "static_order": expected_order[number], "executed": False}
        cases.append(ContractCase("workflow_" + number + "_static_order", "documentation", sequence))
    return cases, {"catalog_entries": len(entries), "catalog_unique_tools": len({e["name"] for e in entries}), "catalog_duplicates": {k: v for k, v in Counter(e["name"] for e in entries).items() if v > 1}, "catalog_sections": sections, "documented_call_counts": call_counts, "non_executable_placeholders": placeholder_count, "inline_workflow_count": len(workflows), "external_workflow_files": [], "scope": "AST/schema/signature validation only; no documented CAD workflow was executed"}


def documented_signature_for_exact(ctx: Context, entry: dict) -> dict:
    actual = parameters_map(ctx.contracts[entry["name"]])
    documented = {p["name"]: p for p in entry["parameters"]}
    require(documented == actual, f"Catalog advertises exact schemas but differs for {entry['name']}: omitted={sorted(set(actual) - set(documented))}, invented={sorted(set(documented) - set(actual))}")
    return {"tool": entry["name"], "line": entry["line"], "exact": True}


def wire_error_case(ctx: Context, name: str, arguments: dict, field: str | None, kind: str) -> dict:
    frame = ctx.wire.request("tools/call", {"name": name, "arguments": arguments})
    message = tool_error(frame.get("result")) if "result" in frame else tool_error(frame)
    assert message is not None, f"Invalid tool arguments were not rejected: {frame}"
    require("PROTOCOL_COM_BOUNDARY_FORBIDDEN" not in message, "Rejection happened at a CAD boundary instead of input validation")
    if field:
        require(field in message, f"Error does not identify invalid/missing field {field}: {message}")
    if kind == "missing_required":
        require("missing" in message.lower() or "required" in message.lower(), "Error does not describe a missing required field")
    return {"tool": name, "parameter": field, "arguments": arguments, "request_id": frame["id"], "response": frame, "expected_error": kind, "mode": "real_stdio_guarded_no_tool_body_expected"}


def start_wire(ctx: Context, command: list[str], env: dict, deadline: float) -> dict:
    import mcp.types
    ctx.wire = WireClient(command, ctx.output, env, deadline)
    protocol = mcp.types.LATEST_PROTOCOL_VERSION
    frame = ctx.wire.request("initialize", {"protocolVersion": protocol, "capabilities": {}, "clientInfo": {"name": "solidworks-protocol-contract", "version": "1.0"}})
    require("result" in frame, f"Initialization failed: {frame}")
    result = frame["result"]
    negotiated = result.get("protocolVersion")
    supported_by_test = {protocol, "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}
    require(negotiated in supported_by_test, f"Server selected an unsupported protocol: {result}")
    ctx.wire.requested_protocol = protocol
    ctx.wire.negotiated_protocol = negotiated
    require(bool(result.get("serverInfo", {}).get("name")), "Missing server identity")
    require("tools" in result.get("capabilities", {}), "Tools capability not advertised")
    ctx.wire.notify("notifications/initialized")
    return {"command": command, "protocol_requested": protocol, "protocol_negotiated": negotiated, "version_fallback": negotiated != protocol, "response": frame, "mode": "real_stdio_guarded"}


def wire_cases(ctx: Context) -> list:
    cases = []
    def list_tools() -> dict:
        frame = ctx.wire.request("tools/list", {})
        require("result" in frame, f"tools/list failed: {frame}")
        tools = frame["result"]["tools"]
        require(not frame["result"].get("nextCursor"), "Unexpected pagination; validation must enumerate all tools")
        names = [tool["name"] for tool in tools]
        require(len(names) == 58 and len(set(names)) == 58, f"Wire count/uniqueness mismatch: {len(names)}/{len(set(names))}")
        require(set(names) == set(ctx.schemas), "Real wire/import registration mismatch")
        for tool in tools:
            require(schema_of(tool) == schema_of(ctx.schemas[tool["name"]]), "Wire/import input schema mismatch")
            require(schema_of(tool, True) == schema_of(ctx.schemas[tool["name"]], True), "Wire/import output schema mismatch")
        ctx.wire.tools = tools
        return {"tool_count": len(tools), "unique_names": len(set(names)), "request_id": frame["id"], "names": names, "mode": "real_stdio_guarded"}
    cases.append(ContractCase("tools_list_count_unique_and_exact_schemas", "real_wire", list_tools))
    for name, contract in ctx.contracts.items():
        required = [p for p in contract["parameters"] if p["required"]]
        base = minimal_arguments(contract, ctx.output)
        if required:
            cases.append(ContractCase(name + ":all_required_omitted", "real_wire_missing_required", lambda name=name: wire_error_case(ctx, name, {}, None, "missing_required"), {"tool": name}))
        for parameter in required:
            arguments = {k: v for k, v in base.items() if k != parameter["name"]}
            cases.append(ContractCase(name + ":" + parameter["name"], "real_wire_missing_required", lambda name=name, arguments=arguments, field=parameter["name"]: wire_error_case(ctx, name, arguments, field, "missing_required"), {"tool": name, "parameter": parameter["name"]}))
        for parameter in contract["parameters"]:
            arguments = dict(base)
            arguments[parameter["name"]] = {"protocol_invalid_scalar": ["never invoke COM"]}
            cases.append(ContractCase(name + ":" + parameter["name"], "real_wire_invalid_type", lambda name=name, arguments=arguments, field=parameter["name"]: wire_error_case(ctx, name, arguments, field, "invalid_type"), {"tool": name, "parameter": parameter["name"]}))
    def unknown_tool() -> dict:
        frame = ctx.wire.request("tools/call", {"name": "protocol__definitely_unknown_tool", "arguments": {}})
        message = tool_error(frame.get("result")) if "result" in frame else tool_error(frame)
        assert message is not None, f"Unknown tool not rejected: {frame}"
        require("protocol__definitely_unknown_tool" in message, f"Unknown tool name missing from error: {frame}")
        require("PROTOCOL_COM_BOUNDARY_FORBIDDEN" not in message, "Unknown tool reached a CAD boundary")
        return {"response": frame}
    cases.append(ContractCase("unknown_tool", "real_wire", unknown_tool))
    def protocol_error(params: dict) -> dict:
        frame = ctx.wire.request("tools/call", params)
        require("error" in frame, f"Malformed tools/call did not return a JSON-RPC error: {frame}")
        require(frame["error"]["code"] == -32602, f"Expected Invalid params: {frame}")
        require("PROTOCOL_COM_BOUNDARY_FORBIDDEN" not in json.dumps(frame), "Malformed request reached a CAD boundary")
        return {"response": frame}
    cases.append(ContractCase("missing_tool_name", "real_wire", lambda: protocol_error({"arguments": {}})))
    cases.append(ContractCase("arguments_not_an_object", "real_wire", lambda: protocol_error({"name": "sw_open_doc", "arguments": ["invalid"]})))
    def missing_arguments() -> dict:
        frame = ctx.wire.request("tools/call", {"name": "sw_open_doc"})
        message = tool_error(frame.get("result")) if "result" in frame else tool_error(frame)
        assert message is not None, f"Omitted arguments not rejected: {frame}"
        require("file_path" in message, f"Omitted arguments error does not identify file_path: {frame}")
        require("PROTOCOL_COM_BOUNDARY_FORBIDDEN" not in message, "Omitted arguments reached CAD")
        return {"response": frame}
    cases.append(ContractCase("missing_arguments_for_required_tool", "real_wire", missing_arguments))
    def unknown_method() -> dict:
        frame = ctx.wire.request("protocol/definitelyUnknownMethod", {})
        require(frame.get("error", {}).get("code") == -32601, f"Expected Method not found: {frame}")
        return {"response": frame}
    cases.append(ContractCase("unknown_jsonrpc_method", "real_wire", unknown_method))
    def ping() -> dict:
        frame = ctx.wire.request("ping")
        require("result" in frame, f"Server stopped responding after invalid requests: {frame}")
        return {"response": frame}
    cases.append(ContractCase("ping_after_rejections", "real_wire", ping))
    cases.append(ContractCase("tools_list_stable_after_rejections", "real_wire", list_tools))
    return cases


def final_wire_cases(ctx: Context) -> list:
    def clean_shutdown() -> dict:
        shutdown = ctx.wire.close()
        require(shutdown["exitcode"] == 0 and shutdown["cleanup"] == "graceful_EOF", f"Child did not exit cleanly: {shutdown}")
        require(not shutdown["stdout_reader_alive"] and not shutdown["stderr_reader_alive"], "Pipe reader leaked")
        return shutdown
    def stdout_only_jsonrpc() -> dict:
        lines = ctx.wire.stdout_lines
        require(bool(lines), "No wire stdout captured")
        frames = []
        for index, line in enumerate(lines, 1):
            require(bool(line.strip()), f"Blank/non-JSON stdout line {index}")
            frame = json.loads(line)
            validate_frame(frame)
            frames.append(frame)
        requests = [m["id"] for m in ctx.wire.sent if "id" in m]
        responses = [m["id"] for m in frames if "id" in m and ("result" in m or "error" in m)]
        require(Counter(requests) == Counter(responses), "Missing or duplicate JSON-RPC responses")
        return {"stdout_lines": len(lines), "jsonrpc_frames": len(frames), "requests": len(requests), "notifications_sent": len(ctx.wire.sent) - len(requests), "response_ids_complete_and_unique": True, "non_json_lines": 0}
    def guard_check() -> dict:
        state = json.loads((ctx.output / "protocol_wire_guard.json").read_text(encoding="utf-8"))
        require(state["attempt_count"] == 0, f"Wire touched forbidden CAD boundaries: {state}")
        require(not state["cad_session_created"] and not state["sta_worker_created"] and not state["sta_threads"], "Real CAD session/worker was created")
        require("PROTOCOL_COM_BOUNDARY_FORBIDDEN" not in "".join(ctx.wire.stderr_lines), "CAD tripwire marker in stderr")
        require(any("Starting SolidWorks 2026 MCP Server" in line for line in ctx.wire.stderr_lines), "Real server startup log missing from stderr")
        return state
    return [ContractCase("owned_child_graceful_EOF", "real_wire", clean_shutdown), ContractCase("stdout_exclusively_jsonrpc", "real_wire", stdout_only_jsonrpc), ContractCase("zero_CAD_boundary_attempts", "real_wire_safety", guard_check)]


def source_hashes(workspace: Path) -> dict:
    paths = sorted((workspace / "src/sw_mcp").rglob("*.py"))
    paths += [workspace / "skills/solidworks-cad/SKILL.md", workspace / "rules/AGENTS.md", workspace / "mcp_config.json"]
    return {str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def configure_runtime(output: Path) -> None:
    sys.dont_write_bytecode = True
    temporary = output / "protocol_tmp"
    temporary.mkdir(exist_ok=True)
    for name in ("TEMP", "TMP", "TMPDIR"):
        os.environ[name] = str(temporary)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONUNBUFFERED"] = "1"


def child_main(args: Any) -> int:
    output = Path(args.output_dir).resolve()
    configure_runtime(output)
    guards = BoundaryGuards()
    try:
        guards.install()
        runpy.run_module("sw_mcp.server", run_name="__main__")
        return 0
    finally:
        json_file(output / "protocol_wire_guard.json", guards.state())
        guards.close()


def main(args: Any) -> int:
    started = time.monotonic()
    workspace = Path(args.workspace).resolve() if args.workspace else Path(__file__).resolve().parents[2]
    output = Path(args.output_dir).resolve()
    require(output.is_dir(), "Output directory must already exist")
    require((workspace / "src/sw_mcp/server.py").is_file(), "Invalid workspace")
    configure_runtime(output)
    copied_script = output / "protocol_contract.py"
    source_script = workspace / "tests/validation/protocol_contract.py"
    if source_script.resolve() != copied_script.resolve():
        shutil.copy2(source_script, copied_script)
    manifest_before = source_hashes(workspace)
    records: list[dict] = []
    guards = BoundaryGuards()
    ctx = Context(workspace, output, guards)
    metadata: dict = {}
    fatal = None
    exitcode = 1
    child_command = None
    with (output / "protocol_tests.log").open("w", encoding="utf-8", buffering=1) as log:
        log.write("SolidWorks MCP protocol contract validation\n")
        log.write("Successful tool calls: MOCKED ONLY. Real stdio: initialize/list/negative requests/ping.\n")
        log.write("Invocation: " + subprocess.list2cmdline([sys.executable] + sys.argv) + "\n")
        try:
            guards.install()
            run_cases([ContractCase("real_server_import_and_registration", "real_import", lambda: bootstrap(ctx))], log, records)
            require(ctx.server is not None and ctx.contracts is not None, "Server bootstrap failed; see testcase traceback")
            run_cases(registration_cases(ctx), log, records)
            document_cases, metadata = docs_cases(ctx)
            run_cases(document_cases, log, records)
            run_cases(mock_cases(ctx) + alias_cases(ctx) + [ContractCase("unsupported_fixed_keyword_characterization", "mock_extra_arguments", lambda: extra_argument_case(ctx))], log, records)
            config = json.loads((workspace / "mcp_config.json").read_text(encoding="utf-8"))
            require(len(config["mcpServers"]) == 1, "Expected one configured MCP server")
            config_name, launch = next(iter(config["mcpServers"].items()))
            def launch_contract() -> dict:
                require(Path(launch["command"]).is_file(), "Configured Python is missing")
                require(Path(launch["command"]).resolve() == Path(sys.executable).resolve(), "Validation Python differs from configured server Python")
                require(launch.get("args") == ["-m", "sw_mcp.server"], "Unexpected server entrypoint")
                require(launch.get("env", {}).get("PYTHONUNBUFFERED") == "1", "Unbuffered stdio not configured")
                return {"configured_name": config_name, "command": launch["command"], "args": launch["args"], "env": launch.get("env", {})}
            run_cases([ContractCase("configured_entrypoint_and_interpreter", "configuration", launch_contract)], log, records)
            child_command = [launch["command"], "-B", str(copied_script), "--wire-child", "--workspace", str(workspace), "--output-dir", str(output)]
            child_env = os.environ.copy()
            child_env.update(launch.get("env", {}))
            child_env["PYTHONDONTWRITEBYTECODE"] = "1"
            child_env["PYTHONIOENCODING"] = "utf-8"
            log.write("Guarded real-server command: " + subprocess.list2cmdline(child_command) + "\n")
            run_cases([ContractCase("stdio_initialize", "real_wire", lambda: start_wire(ctx, child_command, child_env, started + RUN_BUDGET))], log, records)
            require(ctx.wire is not None and records[-1]["status"] == "pass", "Real stdio initialization failed; see testcase traceback")
            run_cases(wire_cases(ctx), log, records)
            run_cases(final_wire_cases(ctx), log, records)
        except Exception:  # noqa: BLE001 - preserve the report after runner/setup failures
            fatal = traceback.format_exc()
            log.write("FATAL SETUP/RUNNER ERROR\n" + fatal)
        finally:
            if ctx.wire is not None:
                try:
                    ctx.wire.close()
                except Exception:  # noqa: BLE001 - report cleanup failure without losing results
                    log.write("Child cleanup error\n" + traceback.format_exc())
            def main_safety() -> dict:
                state = guards.state()
                require(state["attempt_count"] == 0 and not state["cad_session_created"] and not state["sta_worker_created"] and not state["sta_threads"], f"Main process crossed a real CAD boundary: {state}")
                return state
            def sources_unchanged() -> dict:
                after = source_hashes(workspace)
                require(after == manifest_before, "Production source/docs/config changed during this run (possibly concurrent work)")
                require(hashlib.sha256(copied_script.read_bytes()).hexdigest() == hashlib.sha256(source_script.read_bytes()).hexdigest(), "Output script copy differs from source")
                return {"production_files_hashed": len(after), "unchanged": True, "script_copy_sha256": hashlib.sha256(copied_script.read_bytes()).hexdigest()}
            def live_execution_excluded() -> None:
                raise unittest.SkipTest("Live SolidWorks/COM execution is deliberately excluded; owned by the parent task. No successful real-server tool calls are permitted here.")
            run_cases([ContractCase("zero_real_CAD_boundary_attempts", "mock_safety", main_safety), ContractCase("production_sources_unchanged_and_script_copied", "write_scope", sources_unchanged), ContractCase("live_COM_execution_delegated_to_parent", "scope_exclusion", live_execution_excluded)], log, records)
            guard_state = guards.state()
            guards.close()
            counts = dict(Counter(record["status"] for record in records))
            for key in ("pass", "fail", "skip"):
                counts.setdefault(key, 0)
            counts["total"] = len(records)
            failures = [record for record in records if record["status"] == "fail"]
            exitcode = 1 if counts["fail"] or fatal else 0
            category_counts = {}
            for record in records:
                category_counts.setdefault(record["category"], Counter())[record["status"]] += 1
            metadata.update({
                "imported_tool_count": len(ctx.imported_tools or []),
                "unique_tool_count": len(ctx.schemas or {}),
                "ast_tool_count": len(ctx.contracts or {}),
                "input_parameter_count": sum(len(c["parameters"]) for c in (ctx.contracts or {}).values()),
                "required_parameter_count": sum(p["required"] for c in (ctx.contracts or {}).values() for p in c["parameters"]),
                "nullable_parameter_count": sum("null" in p["types"] for c in (ctx.contracts or {}).values() for p in c["parameters"]),
                "read_idempotent_wrappers": len(IDEMPOTENT),
                "mocked_tools_with_mcp_success": len({r["details"].get("tool") for r in records if r["category"] == "mock_forward_dto" and r["name"].endswith(":mcp_canonical") and r["status"] == "pass"}),
            })
            schemas = {"mode": "real_import_and_real_stdio_schemas_not_mocked", "counts": metadata, "real_import_tools": ctx.imported_tools or [], "real_wire_tools": getattr(ctx.wire, "tools", []), "ast_contracts": ctx.contracts or {}}
            json_file(output / "protocol_schemas.json", schemas)
            observations = [
                {"severity": "warning", "topic": "force_ignored", "detail": "sw_rebuild accepts force=True/False but always calls features.rebuild() without a force argument; tested with mocks."},
                {"severity": "warning", "topic": "alias_conflict_precedence", "detail": "Conflicting aliases are not rejected. Save uses truthy output_path over file_path; sweep uses non-null canonical diameter; fixed uses non-null is_fixed; pattern spacing_deg and nonempty axis_name override canonical fields, while reverse_dir OR flip_dir determines direction."},
                {"severity": "warning", "topic": "partial_axis_coordinates", "detail": "Circular pattern forwards axis coordinates only when all three are non-null; any partial tuple is discarded. All-zero coordinates are preserved."},
                {"severity": "info", "topic": "spacing_alias_meaning", "detail": "spacing_deg is forwarded unchanged as total_angle_deg, not multiplied by instance count."},
                {"severity": "info", "topic": "catalog_cross_listing", "detail": "The catalog repeats new_assembly and new_drawing in their specialist categories; unique coverage is tested separately from entry counts."},
                {"severity": "limitation", "topic": "no_COM_or_live_geometry", "detail": "No successful real tool calls or CAD workflows were executed. Fake domain results validate forwarding and serialization, not SolidWorks geometry or real STA behavior."},
                {"severity": "info", "topic": "wire_guard_mode", "detail": "The child executes runpy.run_module('sw_mcp.server', run_name='__main__') with real MCP registration/transport/validation. Only CAD side-effect boundaries are replaced by raising tripwires, never successful fake results."},
            ]
            for record in records:
                if record["category"] == "mock_extra_arguments" and record["status"] == "pass":
                    observations.append({"severity": "warning", "topic": "unknown_argument_handling", "detail": record["details"]})
            report = {
                "suite": "solidworks_mcp_protocol_contract", "runner": "stdlib unittest", "workspace": str(workspace), "output_root": str(output),
                "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - (time.monotonic() - started))),
                "duration_seconds": round(time.monotonic() - started, 3), "exitcode": exitcode,
                "environment": {"python": sys.version, "executable": sys.executable, "packages": {package: importlib.metadata.version(package) for package in ("mcp", "pydantic", "pywin32", "pillow")}, "dependency_installations": [], "network_requests": 0, "bytecode_writes_disabled": sys.dont_write_bytecode},
                "commands": {"runner": [sys.executable] + sys.argv, "runner_exitcode": exitcode, "guarded_stdio_child": child_command, "child_shutdown": ctx.wire.shutdown if ctx.wire else None, "request_timeout_seconds": REQUEST_TIMEOUT, "outer_command_timeout_ms": 120000, "suite_request_budget_seconds": RUN_BUDGET},
                "counts": counts, "coverage": metadata, "categories": {key: dict(value) for key, value in category_counts.items()},
                "real_wire": {"mode": "real_server_guarded_stdio_no_successful_tool_calls", "requested_protocol": getattr(ctx.wire, "requested_protocol", None), "negotiated_protocol": getattr(ctx.wire, "negotiated_protocol", None), "request_count": sum("id" in m for m in ctx.wire.sent) if ctx.wire else 0, "notification_count": sum("id" not in m for m in ctx.wire.sent) if ctx.wire else 0, "stdout_line_count": len(ctx.wire.stdout_lines) if ctx.wire else 0, "wire_tool_count": len(getattr(ctx.wire, "tools", [])) if ctx.wire else 0, "guard_report": "protocol_wire_guard.json"},
                "mocked": {"mode": "real_wrappers_and_MCP_call_tool_with_FakeWorker_FakeSession", "independent_routes": len(ROUTES), "real_domain_methods_executed": 0, "real_STA_workers_started": 0},
                "main_process_guards": guard_state, "production_manifest_before": manifest_before,
                "failure_ids": [r["id"] for r in failures], "observations": observations, "fatal_runner_error": fatal,
                "testcases": records,
                "artifacts": sorted(path.name for path in output.glob("protocol_*")),
            }
            # Include the report itself before it exists on the first run.
            report["artifacts"] = sorted(set(report["artifacts"]) | {"protocol_report.json"})
            json_file(output / "protocol_report.json", report)
            log.write("\nFINAL COUNTS " + json.dumps(counts) + "\n")
            log.write("COVERAGE " + json.dumps(metadata) + "\n")
            log.write("EXITCODE " + str(exitcode) + "\n")
    print("protocol_contract: " + json.dumps({"counts": counts, "coverage": metadata, "wire_requests": report["real_wire"]["request_count"], "child_exitcode": report["commands"]["child_shutdown"]["exitcode"] if report["commands"]["child_shutdown"] else None, "exitcode": exitcode}, ensure_ascii=True))
    print("protocol_report: " + str(output / "protocol_report.json"))
    for record in failures:
        print("FAIL " + record["id"])
    if fatal:
        print("FATAL " + fatal)
    return exitcode


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--workspace")
    parser.add_argument("--wire-child", action="store_true", help=argparse.SUPPRESS)
    parsed = parser.parse_args()
    try:
        sys.exit(child_main(parsed) if parsed.wire_child else main(parsed))
    except Exception:  # noqa: BLE001 - CLI must expose all unexpected failures
        traceback.print_exc()
        sys.exit(2)
