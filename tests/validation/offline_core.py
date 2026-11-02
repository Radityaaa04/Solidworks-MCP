"""Offline behavioral audit of the SolidWorks core; stdlib only, never real COM.

Run with Python -B and explicit --project-root / --output-root. This script writes
only core_report.json, core_tests.log, and its own copy core_offline.py to the
existing output root. It deliberately does not repair or relax production bugs.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import asyncio
import contextlib
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import traceback
import types
import unittest
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock


PROJECT_ROOT: Path
OUTPUT_ROOT: Path
units = sta = exceptions = client_mod = document_mod = sketcher_mod = features_mod = None
COM_EVENTS: list[dict] = []
COM_LOCK = threading.Lock()
CASE_SEQUENCE = 0
ASYNC_LIMIT = 1.0
JOIN_LIMIT = 0.4


class OfflineCOMError(Exception):
    def __init__(self, hresult=-2147467259, message="offline mock COM error", *, expose=True):
        super().__init__(hresult, message)
        if expose:
            self.hresult = hresult


class OfflineVariant:
    def __init__(self, variant_type, value):
        self.varianttype = variant_type
        self.value = value

    def __repr__(self):
        return f"OfflineVariant({self.varianttype}, {self.value!r})"


def com_event(action, *args):
    with COM_LOCK:
        COM_EVENTS.append({"action": action, "thread_id": threading.get_ident(), "args": args})


def install_com_mocks():
    if any(name in sys.modules for name in ("pythoncom", "win32com", "win32com.client")):
        raise RuntimeError("Refusing to run after real COM modules have already been imported")
    pycom = types.ModuleType("pythoncom")
    pycom.com_error = OfflineCOMError
    pycom.COINIT_APARTMENTTHREADED = 2
    pycom.VT_BYREF = 0x4000
    pycom.VT_I4 = 3
    pycom.VT_DISPATCH = 9
    pycom.CoInitializeEx = lambda flags: com_event("initialize", flags)
    pycom.CoUninitialize = lambda: com_event("uninitialize")
    pycom.PumpWaitingMessages = lambda: com_event("pump")
    pycom.CoCreateInstance = mock.Mock(side_effect=AssertionError("Real COM creation is forbidden"))
    pycom.GetActiveObject = mock.Mock(side_effect=AssertionError("Unconfigured COM lookup"))
    wincom = types.ModuleType("win32com")
    wincom.__path__ = []
    winclient = types.ModuleType("win32com.client")
    winclient.VARIANT = OfflineVariant
    for name in ("GetActiveObject", "Dispatch", "DispatchEx", "GetObject", "EnsureDispatch"):
        setattr(winclient, name, mock.Mock(name=name, side_effect=AssertionError("Unconfigured mock COM call: " + name)))
    wincom.client = winclient
    sys.modules.update({"pythoncom": pycom, "win32com": wincom, "win32com.client": winclient})
    return pycom, winclient


def safe_json(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else repr(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, OfflineVariant):
        return {"variant_type": value.varianttype, "value": safe_json(value.value)}
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [safe_json(v) for v in value]
    if isinstance(value, FakeFeature):
        return {"feature": value.Name, "error_code": value.GetErrorCode}
    if isinstance(value, mock.Mock):
        return repr(value)
    return repr(value)


def captured(fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, exc


def calls_of(method):
    return [{"args": safe_json(call.args), "kwargs": safe_json(call.kwargs)} for call in method.call_args_list]


class AuditCase(unittest.TestCase):
    category = "unknown"

    def setUp(self):
        self.actual_summary = {}

    def observe(self, **values):
        self.actual_summary.update(safe_json(values))

    def rejected_without_geometry(self, doc, fn):
        result, error = captured(fn)
        self.observe(result=result, exception=error, document=doc.snapshot())
        self.assertIsInstance(error, (ValueError, TypeError), "Invalid geometry must be rejected explicitly")
        self.assertEqual(doc.creation_calls(), [], "Invalid geometry reached a COM creation method")
        self.assertEqual(doc.SketchManager.InsertSketch.call_count, 0, "Invalid input mutated sketch mode")
        self.assertEqual(doc.ClearSelection2.call_count, 0, "Invalid input changed the user's selection")
        self.assertEqual(doc.EditDelete.call_count, 0, "Invalid input deleted geometry")


def register(cls, label, expected, fn):
    global CASE_SEQUENCE
    CASE_SEQUENCE += 1
    name = "test_" + f"{CASE_SEQUENCE:04d}_" + re.sub(r"[^a-zA-Z0-9_]+", "_", label).strip("_")
    fn.__name__ = name
    fn.__doc__ = expected
    fn.audit_expected = expected
    setattr(cls, name, fn)


class FakeFeature:
    def __init__(self, name="NewFeature", kind="Boss", error=0, doc=None):
        self.Name = name
        self.GetTypeName2 = kind
        self.GetErrorCode = error
        self.GetNextFeature = None
        self.doc = doc
        self.select_ok = True
        self.select_error = None
        self.Select2 = mock.Mock(name=name + ".Select2", side_effect=self._select)

    def _select(self, append, mark):
        if self.doc is not None:
            self.doc.events.append(["select", self.Name, append, mark])
        if self.select_error is not None:
            raise self.select_error
        if self.select_ok and self.doc is not None:
            if not append:
                self.doc.selection.clear()
            self.doc.selection.append(self.Name)
        return self.select_ok


FEATURE_COM_NAMES = (
    "FeatureExtrusion3", "FeatureCut4", "FeatureFillet", "InsertFeatureChamfer",
    "FeatureRevolve2", "FeatureCircularPattern4", "CreateFeature",
)
SKETCH_COM_NAMES = (
    "CreateLine", "CreateCornerRectangle", "CreateCircleByRadius", "CreateCenterLine", "Create3PointArc",
)


class FakeDocument:
    def __init__(self, *, active_sketch=True):
        self.events = []
        self.selection = ["ExistingUserFeature"]
        self.deleted = []
        self.delete_ok = True
        self.GetTitle = "OfflineAudit.SLDPRT"
        self.GetPathName = str(OUTPUT_ROOT / "core_mock_existing.SLDPRT")
        self.GetType = 1
        self.GetNext = None
        self.EditRebuild3 = True
        self.ClearSelection2 = mock.Mock(name="ClearSelection2", side_effect=self._clear)
        self.EditDelete = mock.Mock(name="EditDelete", side_effect=self._delete)
        self.SelectByID = mock.Mock(name="SelectByID", return_value=True)
        self.Extension = types.SimpleNamespace(
            SaveAs3=mock.Mock(name="SaveAs3"),
            SelectByID2=mock.Mock(name="SelectByID2", return_value=True),
            NewSelectData=object(),
        )
        self.SketchManager = types.SimpleNamespace(
            ActiveSketch=object() if active_sketch else None,
            InsertSketch=mock.Mock(name="InsertSketch", side_effect=self._toggle_sketch),
        )
        for name in SKETCH_COM_NAMES:
            setattr(self.SketchManager, name, mock.Mock(name=name, return_value=object()))
        self.created_feature = FakeFeature(doc=self)
        self.sweep_data = types.SimpleNamespace()
        self.FeatureManager = types.SimpleNamespace()
        for name in FEATURE_COM_NAMES:
            setattr(self.FeatureManager, name, mock.Mock(name=name, side_effect=self._create(name)))
        self.FeatureManager.CreateDefinition = mock.Mock(name="CreateDefinition", return_value=self.sweep_data)
        self.Save3 = mock.Mock(name="Save3", return_value=True)
        self.SaveAs = mock.Mock(name="SaveAs", return_value=True)
        self.GetBodies2 = mock.Mock(name="GetBodies2", return_value=[])
        self.path_feature = FakeFeature("PathSketch", "ProfileFeature", doc=self)
        self.profile_feature = FakeFeature("ProfileSketch", "ProfileFeature", doc=self)
        self.path_feature.GetNextFeature = self.profile_feature
        self.FirstFeature = self.path_feature
        self.FeatureByName = mock.Mock(name="FeatureByName", return_value=None)
        surface = types.SimpleNamespace(IsPlane=True)
        face = types.SimpleNamespace(GetSurface=surface)
        self.SelectionManager = types.SimpleNamespace(GetSelectedObject6=mock.Mock(return_value=face))

    def _create(self, name):
        def create(*args, **kwargs):
            self.events.append(["create", name])
            return self.created_feature
        return create

    def _clear(self, all_selections):
        self.events.append(["clear_selection", all_selections])
        self.selection.clear()

    def _toggle_sketch(self, update):
        self.events.append(["toggle_sketch", update])
        self.SketchManager.ActiveSketch = None if self.SketchManager.ActiveSketch is not None else object()

    def _delete(self):
        self.events.append(["delete", list(self.selection), self.delete_ok])
        if self.delete_ok:
            self.deleted.extend(self.selection)
            self.selection.clear()
        return self.delete_ok

    def creation_calls(self):
        return [name for name in FEATURE_COM_NAMES if getattr(self.FeatureManager, name).called] + [
            name for name in SKETCH_COM_NAMES if getattr(self.SketchManager, name).called
        ]

    def snapshot(self):
        methods = {}
        for owner, names in ((self.FeatureManager, FEATURE_COM_NAMES), (self.SketchManager, SKETCH_COM_NAMES)):
            for name in names:
                method = getattr(owner, name)
                if method.called:
                    methods[name] = calls_of(method)
        return {
            "creation_calls": methods,
            "sketch_active": self.SketchManager.ActiveSketch is not None,
            "insert_sketch_calls": self.SketchManager.InsertSketch.call_count,
            "clear_selection_calls": self.ClearSelection2.call_count,
            "selection": list(self.selection),
            "deleted": list(self.deleted),
            "delete_calls": self.EditDelete.call_count,
            "events": list(self.events),
        }


def doc_manager(doc):
    app = types.SimpleNamespace(ActiveDoc=doc, CloseDoc=mock.Mock(name="CloseDoc"))
    cli = types.SimpleNamespace(app=app)
    return document_mod.DocumentManager(cli), app


def feature_manager(doc):
    manager, _ = doc_manager(doc)
    return features_mod.FeatureManager(manager)


def sketch_manager(doc):
    manager, _ = doc_manager(doc)
    return sketcher_mod.SketchManager(manager)


class UnitAudit(AuditCase):
    category = "units"


def build_unit_cases():
    values = [-1e9, -1000.0, -25.4, -1.0, -1e-9, -0.0, 0, 1e-9, 0.001, 1, 12.5, 25.4, 360, 1000, 1e9]
    for index, value in enumerate(values):
        def length_case(self, value=value):
            meters = units.mm_to_meters(value)
            restored = units.meters_to_mm(meters)
            self.observe(input_mm=value, meters=meters, round_trip_mm=restored)
            self.assertTrue(math.isclose(restored, value, rel_tol=1e-12, abs_tol=1e-15))
            self.assertTrue(math.isclose(meters, float(Decimal(str(value)) / Decimal(1000)), rel_tol=1e-12, abs_tol=1e-15))
        register(UnitAudit, f"length_roundtrip_{index}", "Length conversion preserves magnitude and sign on a round trip", length_case)
        def meters_case(self, value=value):
            mm = units.meters_to_mm(value)
            restored = units.mm_to_meters(mm)
            self.observe(input_m=value, mm=mm, round_trip_m=restored)
            self.assertTrue(math.isclose(restored, value, rel_tol=1e-12, abs_tol=1e-15))
        register(UnitAudit, f"meters_roundtrip_{index}", "SI length round trip is accurate", meters_case)
    for index, value in enumerate([-720, -360, -180, -90, -0.0, 0, 0.001, 30, 45, 90, 180, 270, 360, 720, 1e6]):
        def angle_case(self, value=value):
            radians = units.deg_to_radians(value)
            restored = units.radians_to_deg(radians)
            self.observe(degrees=value, radians=radians, round_trip_degrees=restored)
            self.assertTrue(math.isclose(radians, value * math.pi / 180, rel_tol=1e-12, abs_tol=1e-15))
            self.assertTrue(math.isclose(restored, value, rel_tol=1e-12, abs_tol=1e-15))
        register(UnitAudit, f"angle_roundtrip_{index}", "Degree/radian conversions use the correct scale", angle_case)
    for value in ["25.4", Decimal("12.5"), 0, -0.25, 2.5]:
        def conversion_case(self, value=value):
            result = {"m": units.mm_to_meters(value), "mm": units.meters_to_mm(value), "g": units.kg_to_grams(value)}
            self.observe(input=repr(value), result=result)
            self.assertIsInstance(result["m"], float)
            self.assertAlmostEqual(result["m"], float(value) / 1000)
            self.assertAlmostEqual(result["mm"], float(value) * 1000)
            self.assertAlmostEqual(result["g"], float(value) * 1000)
        register(UnitAudit, f"numeric_coercion_{value}", "Conversion helpers consistently coerce numeric inputs", conversion_case)
    for function in ["mm_to_meters", "meters_to_mm", "deg_to_radians", "radians_to_deg", "kg_to_grams"]:
        for value in [None, "not-a-number", object()]:
            def invalid_conversion(self, function=function, value=value):
                result, error = captured(lambda: getattr(units, function)(value))
                self.observe(function=function, input=repr(value), result=result, exception=error)
                self.assertIsInstance(error, (TypeError, ValueError))
            register(UnitAudit, f"conversion_reject_{function}_{type(value).__name__}", "Non-numeric unit inputs are not silently accepted", invalid_conversion)
    for unit in ["mm", "cm", "m", "in", "ft", "deg", "rad", "g", "kg", ""]:
        for value in [-12.5, 0, 25.4]:
            def format_case(self, unit=unit, value=value):
                result = units.format_equation_string('  "Thickness"  ', value, unit)
                self.observe(unit=unit, value=value, equation=result)
                self.assertEqual(result, f'"Thickness" = {value}{unit}')
            register(UnitAudit, f"equation_format_{unit or 'dimensionless'}_{value}", "Equation formatting preserves an explicit unit suffix and cleans the name", format_case)
    for name in [None, "", " ", "\t\n", '"', ' "" ', '"""']:
        def bad_name(self, name=name):
            result, error = captured(lambda: units.format_equation_string(name, 1))
            self.observe(input_name=name, result=result, exception=error)
            self.assertIsInstance(error, ValueError)
        register(UnitAudit, f"equation_empty_name_{repr(name)}", "Empty equation names are rejected", bad_name)
    for value in [float("nan"), float("inf"), float("-inf")]:
        def bad_value(self, value=value):
            result, error = captured(lambda: units.format_equation_string("A", value))
            self.observe(value=value, result=result, exception=error)
            self.assertIsInstance(error, ValueError)
        register(UnitAudit, f"equation_nonfinite_{value}", "NaN/infinite equation values are rejected", bad_value)
    for name in ["Thickness", "D1@Sketch1", "Diameter Ø", "变量", 'A"B']:
        def name_case(self, name=name):
            result = units.format_equation_string(name, 2.5)
            self.observe(name=name, result=result)
            clean = name.replace('"', "")
            self.assertEqual(result, f'"{clean}" = 2.5mm')
        register(UnitAudit, f"equation_name_{name}", "Equation names are preserved apart from surrounding whitespace/quotes", name_case)
    datasets = [
        [0, 0, 0, 0, 0, 0],
        [0.01, -0.02, 0.03, 1e-6, 6e-4, 0.00785],
        [-1, 2, -3, 1, 1, 1],
        [0.001234567, -0.0001234567, 0.00456789, 0.0000123456789, 0.000123456789, 0.123456789],
    ]
    for index, data in enumerate(datasets):
        for length in [6, 7, 12, 15, 18, 24]:
            for container in [list, tuple]:
                def mass_case(self, data=data, length=length, container=container):
                    raw = container(data + [123.456] * (length - 6))
                    before = tuple(raw)
                    result = units.convert_mass_properties(raw)
                    def scale(i, multiplier, places):
                        return round(float(Decimal(str(data[i])) * Decimal(str(multiplier))), places)
                    expected = {
                        "mass_kg": scale(5, 1, 6), "mass_g": scale(5, 1000, 3),
                        "volume_mm3": scale(3, 1e9, 3), "volume_cm3": scale(3, 1e6, 3),
                        "surface_area_mm2": scale(4, 1e6, 3),
                        "center_of_mass_mm": {axis: scale(i, 1000, 4) for i, axis in enumerate("xyz")},
                    }
                    self.observe(input=raw, result=result, expected=expected, input_unchanged=tuple(raw) == before)
                    self.assertEqual(result, expected)
                    self.assertEqual(tuple(raw), before)
                register(UnitAudit, f"mass_{index}_length_{length}_{container.__name__}", "Mass arrays use the documented SI indices and do not mutate the input", mass_case)
    for raw in [None, [], (), [1], [1, 2], [1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 4, 5]]:
        def short_array(self, raw=raw):
            result = units.convert_mass_properties(raw)
            self.observe(input=raw, result=result)
            self.assertEqual(result, {"error": "Invalid mass properties array"})
        register(UnitAudit, f"mass_short_{repr(raw)}", "Missing/truncated mass arrays return an explicit error", short_array)
    for index in range(6):
        for value in [float("nan"), float("inf"), float("-inf")]:
            def nonfinite_mass(self, index=index, value=value):
                raw = [0.01, 0.02, 0.03, 1e-6, 6e-4, 0.01]
                raw[index] = value
                result, error = captured(lambda: units.convert_mass_properties(raw))
                self.observe(index=index, input=raw, result=result, exception=error)
                rejected = isinstance(error, (ValueError, TypeError)) or (isinstance(result, dict) and "error" in result)
                self.assertTrue(rejected, "Nonfinite physical properties were reported as usable measurements")
            register(UnitAudit, f"mass_nonfinite_index_{index}_{value}", "Invalid nonfinite mass properties must not be presented as valid measurements", nonfinite_mass)
    def ignored_tail(self):
        result = units.convert_mass_properties([0, 0, 0, 1e-6, 6e-4, 0.01] + [float("nan")] * 12)
        self.observe(result=result)
        self.assertEqual(result["mass_g"], 10.0)
        self.assertTrue(all(math.isfinite(result[k]) for k in ("mass_kg", "mass_g", "volume_mm3", "volume_cm3", "surface_area_mm2")))
    register(UnitAudit, "mass_ignores_inertia_tail", "Unused inertia slots do not contaminate the requested mass-property fields", ignored_tail)


class DocumentAudit(AuditCase):
    category = "document_save_close"


@contextlib.contextmanager
def save_fixture(*, status=True, error=0, warning=0, existing=False, saved=True, materialize=True):
    doc = FakeDocument()
    manager, app = doc_manager(doc)
    target = os.path.abspath(str(OUTPUT_ROOT / ("core_mock_old.SLDPRT" if existing else "core_mock_new.SLDPRT")))
    present = {doc.GetPathName}
    if existing:
        present.add(target)
    if not saved:
        doc.GetPathName = ""
    def save_as(path, version, options, data, advanced, v_error, v_warning):
        doc.events.append(["save_as", path])
        v_error.value, v_warning.value = error, warning
        if materialize and status and error == 0:
            present.add(path)
        return status
    def save_in_place(options, v_error, v_warning):
        doc.events.append(["save3"])
        v_error.value, v_warning.value = error, warning
        return status
    doc.Extension.SaveAs3.side_effect = save_as
    doc.Save3.side_effect = save_in_place
    app.CloseDoc.side_effect = lambda title: doc.events.append(["close", title])
    with mock.patch.object(document_mod.os.path, "exists", side_effect=lambda path: os.fspath(path) in present), mock.patch.object(document_mod.os, "makedirs") as mkdir:
        yield manager, doc, app, target, present, mkdir


def build_document_cases():
    errors = [0, 1, 2, 16, 32, 64, 128, 256, 19]
    for existing in [False, True]:
        for status in [False, True]:
            for error in errors:
                for warning in [0, 4]:
                    def save_as_case(self, existing=existing, status=status, error=error, warning=warning):
                        with save_fixture(status=status, error=error, warning=warning, existing=existing) as (mgr, doc, app, target, present, mkdir):
                            result, exc = captured(lambda: mgr.save_doc(target))
                            self.observe(status=status, error_code=error, warning=warning, preexisting=existing, result=result, exception=exc, save_as_calls=calls_of(doc.Extension.SaveAs3), close_calls=app.CloseDoc.call_count, target_exists=target in present)
                            if not status or error:
                                self.assertIsInstance(exc, exceptions.SolidWorksError)
                                self.assertIn(f"error_code={error}", str(exc))
                                self.assertIn("SaveAs failed", str(exc))
                            else:
                                self.assertIsNone(exc)
                                self.assertEqual(result, {"saved": True, "path": target, "warnings": warning})
                            self.assertEqual(doc.Save3.call_count, 0)
                            self.assertEqual(app.CloseDoc.call_count, 0)
                            args = doc.Extension.SaveAs3.call_args.args
                            self.assertEqual(args[:3], (target, 0, 1))
                            self.assertEqual([args[3].varianttype, args[4].varianttype], [9, 9])
                            self.assertEqual([args[5].varianttype, args[6].varianttype], [0x4003, 0x4003])
                            mkdir.assert_called_once_with(os.path.dirname(target), exist_ok=True)
                    register(DocumentAudit, f"saveas_{'existing' if existing else 'new'}_status_{status}_error_{error}_warning_{warning}", "SaveAs must reject False/nonzero errors even if a stale target already exists; warnings alone are success", save_as_case)
    for saved in [False, True]:
        for status in [False, True]:
            for error in errors:
                for warning in [0, 8]:
                    def save3_case(self, saved=saved, status=status, error=error, warning=warning):
                        with save_fixture(status=status, error=error, warning=warning, saved=saved) as (mgr, doc, app, target, present, mkdir):
                            result, exc = captured(mgr.save_doc)
                            self.observe(status=status, error_code=error, warning=warning, path_known=saved, result=result, exception=exc, save3_calls=calls_of(doc.Save3))
                            if not status or error or not saved:
                                self.assertIsInstance(exc, exceptions.SolidWorksError)
                            else:
                                self.assertIsNone(exc)
                                self.assertEqual(result, {"saved": True, "path": doc.GetPathName, "warnings": warning})
                            self.assertEqual(doc.Save3.call_count, 1)
                            self.assertEqual(doc.Extension.SaveAs3.call_count, 0)
                            self.assertEqual(app.CloseDoc.call_count, 0)
                            self.assertEqual(doc.Save3.call_args.args[0], 1)
                            self.assertEqual([arg.varianttype for arg in doc.Save3.call_args.args[1:]], [0x4003, 0x4003])
                            mkdir.assert_not_called()
                    register(DocumentAudit, f"save3_path_{saved}_status_{status}_error_{error}_warning_{warning}", "Save3 success requires a true status, zero errors, and an existing document path", save3_case)
    for warning in [0, 4, 128]:
        def lying_save(self, warning=warning):
            with save_fixture(status=True, warning=warning, materialize=False) as (mgr, doc, app, target, present, mkdir):
                result, exc = captured(lambda: mgr.save_doc(target))
                self.observe(result=result, exception=exc, target_exists=target in present, save_as_calls=calls_of(doc.Extension.SaveAs3))
                self.assertIsInstance(exc, exceptions.SolidWorksError)
                self.assertIn("reported success", str(exc))
                self.assertEqual(app.CloseDoc.call_count, 0)
        register(DocumentAudit, f"saveas_success_without_file_warning_{warning}", "SaveAs reporting success without creating a file is a failure", lying_save)
    for saved in [False, True]:
        for status in [False, True]:
            for error in [0, 1, 2, 16]:
                for warning in [0, 8]:
                    def close_case(self, saved=saved, status=status, error=error, warning=warning):
                        with save_fixture(status=status, error=error, warning=warning, saved=saved) as (mgr, doc, app, target, present, mkdir):
                            result, exc = captured(lambda: mgr.close_doc(save_changes=True))
                            self.observe(status=status, error_code=error, warning=warning, path_known=saved, result=result, exception=exc, close_calls=calls_of(app.CloseDoc), events=doc.events)
                            should_close = status and error == 0 and saved
                            self.assertEqual(app.CloseDoc.call_count, int(should_close), "CloseDoc MUST NOT run after a failed save")
                            if should_close:
                                self.assertIsNone(exc)
                                self.assertEqual(result, {"closed": True, "title": doc.GetTitle})
                                self.assertEqual(doc.events, [["save3"], ["close", doc.GetTitle]])
                            else:
                                self.assertIsInstance(exc, exceptions.SolidWorksError)
                                self.assertEqual(doc.events, [["save3"]])
                    register(DocumentAudit, f"close_save_path_{saved}_status_{status}_error_{error}_warning_{warning}", "Saving must complete successfully before CloseDoc is called", close_case)
    def close_without_save(self):
        with save_fixture(status=False, error=2) as (mgr, doc, app, target, present, mkdir):
            result = mgr.close_doc(False)
            self.observe(result=result, events=doc.events)
            doc.Save3.assert_not_called()
            app.CloseDoc.assert_called_once_with(doc.GetTitle)
    register(DocumentAudit, "close_explicit_discard", "An explicit close without saving does not invoke Save3", close_without_save)
    for method_name in ["save_doc", "close_doc", "get_active_doc"]:
        def no_active(self, method_name=method_name):
            mgr, app = doc_manager(None)
            result, exc = captured(lambda: getattr(mgr, method_name)())
            self.observe(result=result, exception=exc, close_calls=app.CloseDoc.call_count)
            self.assertIsInstance(exc, exceptions.DocumentNotFoundError)
            app.CloseDoc.assert_not_called()
        register(DocumentAudit, f"no_active_{method_name}", "Missing documents fail before save/close side effects", no_active)
    for use_save_as in [False, True]:
        def save_com_error(self, use_save_as=use_save_as):
            with save_fixture() as (mgr, doc, app, target, present, mkdir):
                error = OfflineCOMError(-2147024891, "access denied")
                if use_save_as:
                    doc.Extension.SaveAs3.side_effect = error
                    invoke = lambda: mgr.save_doc(target)
                else:
                    doc.Save3.side_effect = error
                    invoke = lambda: mgr.close_doc(True)
                result, exc = captured(invoke)
                self.observe(result=result, exception=exc, close_calls=app.CloseDoc.call_count)
                self.assertIs(exc, error)
                app.CloseDoc.assert_not_called()
        register(DocumentAudit, f"save_com_exception_saveas_{use_save_as}", "COM save exceptions propagate and never close the document", save_com_error)
    for code, words in [(0, ["No error"]), (2, ["read-only"]), (19, ["Generic", "read-only", "lock"]), (128, ["extension"]), (256, ["Unknown"]), (511, ["Generic", "read-only", "empty", "@", "lock", "format", "overwrite", "extension"])]:
        def decode_case(self, code=code, words=words):
            result = document_mod.DocumentManager._decode_save_error(code)
            self.observe(error_code=code, decoded=result)
            for word in words:
                self.assertIn(word.lower(), result.lower())
        register(DocumentAudit, f"decode_save_error_{code}", "Save bitmasks preserve all known actionable error messages", decode_case)


class ClientAudit(AuditCase):
    category = "client_connection"


@contextlib.contextmanager
def forbidden_process_operations():
    guards = []
    def tripwire(name):
        method = mock.Mock(name=name, side_effect=AssertionError("Forbidden process operation: " + name))
        guards.append(method)
        return method
    with contextlib.ExitStack() as stack:
        for module, names in [(os, ["kill", "system", "popen", "startfile"]), (subprocess, ["Popen", "run", "call", "check_call", "check_output"])]:
            for name in names:
                if hasattr(module, name):
                    stack.enter_context(mock.patch.object(module, name, tripwire(module.__name__ + "." + name)))
        fake_psutil = types.ModuleType("psutil")
        for name in ["process_iter", "Process", "Popen", "wait_procs"]:
            setattr(fake_psutil, name, tripwire("psutil." + name))
        fake_winapi = types.ModuleType("win32api")
        for name in ["TerminateProcess", "OpenProcess", "ShellExecute", "WinExec"]:
            setattr(fake_winapi, name, tripwire("win32api." + name))
        stack.enter_context(mock.patch.dict(sys.modules, {"psutil": fake_psutil, "win32api": fake_winapi}))
        yield guards


def new_mock_app():
    return types.SimpleNamespace(
        RevisionNumber="34.0.0", Visible=True, UserControl=False,
        SetUserPreferenceToggle=mock.Mock(name="SetUserPreferenceToggle"),
        GetUserPreferenceStringValue=mock.Mock(name="GetUserPreferenceStringValue", return_value=""),
        ActiveDoc=None, ExitApp=mock.Mock(name="ExitApp"),
    )


def build_client_cases():
    for fallback in [False, True]:
        for visible in [False, True]:
            for preference_error in [False, True]:
                def connect_case(self, fallback=fallback, visible=visible, preference_error=preference_error):
                    app = new_mock_app()
                    trace = []
                    if preference_error:
                        app.SetUserPreferenceToggle.side_effect = OfflineCOMError(message="preference unsupported")
                    def rot(progid):
                        trace.append(["GetActiveObject", progid])
                        if fallback:
                            raise OfflineCOMError(message="no running object")
                        return app
                    def dispatch(progid):
                        trace.append(["Dispatch", progid])
                        return app
                    with forbidden_process_operations() as guards, mock.patch.object(client_mod.win32com.client, "GetActiveObject", side_effect=rot) as get_active, mock.patch.object(client_mod.win32com.client, "Dispatch", side_effect=dispatch) as get_dispatch:
                        cli = client_mod.SolidWorksClient(visible=visible)
                        result = cli.connect()
                        self.observe(connection_trace=trace, visible=app.Visible, user_control=app.UserControl, preference_calls=calls_of(app.SetUserPreferenceToggle), forbidden_process_calls=sum(g.call_count for g in guards), connected=cli.is_connected())
                        self.assertIs(result, app)
                        self.assertEqual(get_active.call_count, 1)
                        self.assertEqual(get_dispatch.call_count, int(fallback))
                        self.assertEqual(app.Visible, visible)
                        self.assertTrue(app.UserControl)
                        self.assertEqual(sum(g.call_count for g in guards), 0)
                        app.ExitApp.assert_not_called()
                        if not preference_error:
                            self.assertEqual(app.SetUserPreferenceToggle.call_args_list, [mock.call(31, False), mock.call(320, True)])
                register(ClientAudit, f"connect_fallback_{fallback}_visible_{visible}_preference_error_{preference_error}", "Connect attaches first, falls back to Dispatch once, and never kills user processes", connect_case)
    for dispatch_error in [OfflineCOMError(message="class not registered"), RuntimeError("dispatch unavailable")]:
        def both_fail(self, dispatch_error=dispatch_error):
            with forbidden_process_operations() as guards, mock.patch.object(client_mod.win32com.client, "GetActiveObject", side_effect=OfflineCOMError(message="ROT unavailable")) as rot, mock.patch.object(client_mod.win32com.client, "Dispatch", side_effect=dispatch_error) as dispatch:
                cli = client_mod.SolidWorksClient()
                result, exc = captured(cli.connect)
                self.observe(result=result, exception=exc, rot_calls=rot.call_count, dispatch_calls=dispatch.call_count, forbidden_process_calls=sum(g.call_count for g in guards), app_reference=cli._app)
                self.assertIsInstance(exc, exceptions.COMConnectionError)
                self.assertIs(exc.__cause__, dispatch_error)
                self.assertEqual(dispatch.call_count, 1)
                self.assertEqual(sum(g.call_count for g in guards), 0)
                self.assertIsNone(cli._app)
        register(ClientAudit, f"connect_both_fail_{type(dispatch_error).__name__}", "Connection failure is actionable, bounded, and non-destructive", both_fail)
    def lazy_cache(self):
        app = new_mock_app()
        with mock.patch.object(client_mod.win32com.client, "GetActiveObject", return_value=app) as rot, mock.patch.object(client_mod.win32com.client, "Dispatch") as dispatch:
            cli = client_mod.SolidWorksClient()
            values = [cli.app, cli.app, cli.app]
            self.observe(rot_calls=rot.call_count, dispatch_calls=dispatch.call_count, same_object=all(v is app for v in values))
            self.assertTrue(all(v is app for v in values))
            rot.assert_called_once_with("SldWorks.Application")
            dispatch.assert_not_called()
    register(ClientAudit, "lazy_app_caches_connection", "Repeated app access does not reconnect or dispatch again", lazy_cache)
    for state in ["disconnected", "responsive", "unresponsive"]:
        def connection_state(self, state=state):
            cli = client_mod.SolidWorksClient()
            if state == "responsive":
                cli._app = new_mock_app()
            elif state == "unresponsive":
                class BrokenApp:
                    @property
                    def RevisionNumber(self):
                        raise OfflineCOMError(message="disconnected server")
                cli._app = BrokenApp()
            with mock.patch.object(cli, "connect") as connect:
                result = cli.is_connected()
                self.observe(state=state, connected=result, connect_calls=connect.call_count)
                self.assertEqual(result, state == "responsive")
                connect.assert_not_called()
        register(ClientAudit, f"is_connected_{state}", "Connection probes are read-only and do not launch a new session", connection_state)
    def disconnect_case(self):
        cli = client_mod.SolidWorksClient()
        app = new_mock_app()
        cli._app = app
        with forbidden_process_operations() as guards, mock.patch.object(client_mod.gc, "collect", return_value=0) as collect:
            cli.disconnect()
            cli.disconnect()
            self.observe(app_released=cli._app is None, collect_calls=collect.call_count, exit_app_calls=app.ExitApp.call_count, forbidden_process_calls=sum(g.call_count for g in guards))
            self.assertIsNone(cli._app)
            app.ExitApp.assert_not_called()
            self.assertEqual(sum(g.call_count for g in guards), 0)
    register(ClientAudit, "disconnect_releases_without_exit", "Disconnect releases references without terminating SolidWorks", disconnect_case)
    for doc_type, expected_id in [("part", 8), ("PART", 8), ("assembly", 9), ("drawing", 10), ("unknown", 8)]:
        for availability in ["exists", "missing", "empty", "error"]:
            def template_case(self, doc_type=doc_type, expected_id=expected_id, availability=availability):
                cli = client_mod.SolidWorksClient()
                app = new_mock_app()
                cli._app = app
                path = str(OUTPUT_ROOT / "core_mock_template.prtdot")
                app.GetUserPreferenceStringValue.return_value = "" if availability == "empty" else path
                if availability == "error":
                    app.GetUserPreferenceStringValue.side_effect = OfflineCOMError(message="preference missing")
                with mock.patch.object(client_mod.os.path, "exists", return_value=availability == "exists"):
                    result = cli.get_default_template(doc_type)
                self.observe(doc_type=doc_type, availability=availability, result=result, preference_calls=calls_of(app.GetUserPreferenceStringValue))
                self.assertEqual(result, path if availability == "exists" else "")
                app.GetUserPreferenceStringValue.assert_called_once_with(expected_id)
            register(ClientAudit, f"template_{doc_type}_{availability}", "Template lookup maps document types and rejects unavailable configured paths", template_case)
    for document_type in [None, 1, 2, 3, 99]:
        def session_case(self, document_type=document_type):
            cli = client_mod.SolidWorksClient()
            app = new_mock_app()
            cli._app = app
            if document_type is not None:
                app.ActiveDoc = types.SimpleNamespace(GetTitle="OfflineDoc", GetType=document_type)
            result = cli.get_session_info()
            self.observe(result=result)
            self.assertEqual(result["revision"], "34.0.0")
            self.assertEqual(result["active_document_type"], {1: "Part", 2: "Assembly", 3: "Drawing"}.get(document_type, "None"))
            self.assertEqual(result["active_document"], None if document_type is None else "OfflineDoc")
        register(ClientAudit, f"session_info_type_{document_type}", "Session information handles no document and unknown document types", session_case)


class SketchAudit(AuditCase):
    category = "sketch_geometry"


SHAPES = {
    "draw_line": ([0.0, 1.0, 20.0, 30.0], "CreateLine", [0, 0.001, 0, 0.02, 0.03, 0]),
    "draw_rectangle": ([-10.0, -20.0, 30.0, 40.0], "CreateCornerRectangle", [-0.01, -0.02, 0, 0.03, 0.04, 0]),
    "draw_circle": ([-10.0, 20.0, 5.0], "CreateCircleByRadius", [-0.01, 0.02, 0, 0.005]),
    "draw_centerline": ([-20.0, -30.0, 0.0, 0.0], "CreateCenterLine", [-0.02, -0.03, 0, 0, 0, 0]),
    "draw_arc": ([0.0, 0.0, 20.0, 0.0, 10.0, 10.0], "Create3PointArc", [0, 0, 0, 0.02, 0, 0, 0.01, 0.01, 0]),
}


def build_sketch_cases():
    for method, (args, com_name, expected_args) in SHAPES.items():
        def valid_shape(self, method=method, args=args, com_name=com_name, expected_args=expected_args):
            doc = FakeDocument()
            result = getattr(sketch_manager(doc), method)(*args)
            self.observe(input_mm=args, result=result, document=doc.snapshot())
            self.assertEqual(list(getattr(doc.SketchManager, com_name).call_args.args), expected_args)
            self.assertEqual(doc.EditDelete.call_count, 0)
            if method == "draw_rectangle":
                self.assertEqual([result["width_mm"], result["height_mm"]], [40, 60])
            if method == "draw_circle":
                self.assertEqual(result["diameter_mm"], 10)
        register(SketchAudit, f"valid_{method}_si_scaling", "Valid sketch coordinates/dimensions are converted from millimeters to SI exactly once", valid_shape)
        def no_geometry(self, method=method, args=args, com_name=com_name):
            doc = FakeDocument()
            getattr(doc.SketchManager, com_name).return_value = None
            result, exc = captured(lambda: getattr(sketch_manager(doc), method)(*args))
            self.observe(result=result, exception=exc, document=doc.snapshot())
            self.assertIsInstance(exc, exceptions.FeatureCreationError)
            self.assertEqual(doc.EditDelete.call_count, 0)
        register(SketchAudit, f"none_result_{method}", "A missing sketch entity is a failure, not a successful result", no_geometry)
        for coordinate in range(len(args)):
            for value in [float("nan"), float("inf"), float("-inf")]:
                def invalid_coordinate(self, method=method, args=args, coordinate=coordinate, value=value):
                    doc = FakeDocument()
                    changed = list(args)
                    changed[coordinate] = value
                    self.observe(input=changed, parameter_index=coordinate)
                    self.rejected_without_geometry(doc, lambda: getattr(sketch_manager(doc), method)(*changed))
                register(SketchAudit, f"nonfinite_{method}_parameter_{coordinate}_{value}", "Every sketch coordinate and size must be finite before any COM geometry call", invalid_coordinate)
    degenerate = {
        "draw_line": [[0, 0, 0, 0], [-5, 10, -5, 10]],
        "draw_centerline": [[0, 0, 0, 0], [-5, 10, -5, 10]],
        "draw_rectangle": [[0, 0, 0, 10], [0, 0, 10, 0], [-1, -1, -1, -1]],
        "draw_circle": [[0, 0, 0], [0, 0, -1], [0, 0, -1e-12]],
        "draw_arc": [
            [0, 0, 0, 0, 1, 1], [0, 0, 1, 1, 0, 0], [0, 0, 1, 1, 1, 1],
            [0, 0, 0, 0, 0, 0], [0, 0, 10, 0, 20, 0], [0, 0, 10, 10, 20, 20],
            [0, 0, 0, 10, 0, 20], [20, 20, 10, 10, 0, 0],
        ],
    }
    for method, variants in degenerate.items():
        for index, args in enumerate(variants):
            def degenerate_shape(self, method=method, args=args):
                doc = FakeDocument()
                self.observe(input=args)
                self.rejected_without_geometry(doc, lambda: getattr(sketch_manager(doc), method)(*args))
            register(SketchAudit, f"degenerate_{method}_{index}", "Zero-size, duplicate-point, or collinear geometry is rejected before COM mutation", degenerate_shape)
    def reverse_rectangle(self):
        doc = FakeDocument()
        result = sketch_manager(doc).draw_rectangle(10, 20, -10, -20)
        self.observe(result=result, document=doc.snapshot())
        self.assertEqual((result["width_mm"], result["height_mm"]), (20, 40))
    register(SketchAudit, "rectangle_reversed_corners", "Reversing rectangle corners preserves positive width and height", reverse_rectangle)
    for coordinate in range(3):
        for value in [float("nan"), float("inf"), float("-inf")]:
            def invalid_face_point(self, coordinate=coordinate, value=value):
                doc = FakeDocument(active_sketch=False)
                args = [0, 10, 20]
                args[coordinate] = value
                self.rejected_without_geometry(doc, lambda: sketch_manager(doc).create_sketch_on_face(*args))
            register(SketchAudit, f"face_point_nonfinite_{coordinate}_{value}", "A nonfinite face selection point is rejected before changing selection or sketch mode", invalid_face_point)
    for mode in ["planar", "curved", "not_selected", "no_active_sketch"]:
        def face_case(self, mode=mode):
            doc = FakeDocument(active_sketch=False)
            if mode == "curved":
                doc.SelectionManager.GetSelectedObject6.return_value.GetSurface.IsPlane = False
            if mode == "not_selected":
                doc.SelectByID.return_value = False
            if mode == "no_active_sketch":
                doc.SketchManager.InsertSketch.side_effect = None
            result, exc = captured(lambda: sketch_manager(doc).create_sketch_on_face(-10, 20, 30))
            self.observe(mode=mode, result=result, exception=exc, selection_calls=calls_of(doc.SelectByID), document=doc.snapshot())
            if mode == "planar":
                self.assertIsNone(exc)
                self.assertTrue(result["sketch_active"])
                doc.SelectByID.assert_called_once_with("", "FACE", -0.01, 0.02, 0.03)
            else:
                self.assertIsInstance(exc, exceptions.FeatureCreationError)
                if mode in ["curved", "not_selected"]:
                    doc.SketchManager.InsertSketch.assert_not_called()
            doc.EditDelete.assert_not_called()
        register(SketchAudit, f"sketch_on_face_{mode}", "Face sketches require successful selection and a planar surface", face_case)
    for plane in ["Front Plane", "Top Plane", "Right Plane"]:
        for mode in ["direct", "localized", "tree", "missing"]:
            def plane_case(self, plane=plane, mode=mode):
                doc = FakeDocument(active_sketch=False)
                if mode == "direct":
                    doc.SelectByID.return_value = True
                elif mode == "localized":
                    localized = {"Front Plane": "Ebene vorne", "Top Plane": "Ebene oben", "Right Plane": "Ebene rechts"}[plane]
                    doc.SelectByID.side_effect = lambda name, *rest: name == localized
                else:
                    doc.SelectByID.return_value = False
                    if mode == "missing":
                        doc.FirstFeature = None
                    else:
                        nodes = [FakeFeature("History", "HistoryFolder", doc=doc)] + [FakeFeature("Datum" + str(i), "RefPlane", doc=doc) for i in range(3)]
                        for left, right in zip(nodes, nodes[1:]):
                            left.GetNextFeature = right
                        doc.FirstFeature = nodes[0]
                result, exc = captured(lambda: sketch_manager(doc).create_sketch(plane))
                self.observe(plane=plane, mode=mode, result=result, exception=exc, selection_calls=calls_of(doc.SelectByID), document=doc.snapshot())
                if mode == "missing":
                    self.assertIsInstance(exc, exceptions.FeatureCreationError)
                    doc.SketchManager.InsertSketch.assert_not_called()
                else:
                    self.assertIsNone(exc)
                    self.assertEqual(result, {"sketch_active": True, "plane": plane})
                    if mode == "tree":
                        index = ["Front Plane", "Top Plane", "Right Plane"].index(plane)
                        self.assertEqual(doc.selection, ["Datum" + str(index)])
                doc.EditDelete.assert_not_called()
            register(SketchAudit, f"plane_{plane}_{mode}", "Plane selection supports direct/localized/tree fallback without deleting preexisting geometry", plane_case)
    for active in [False, True]:
        def close_sketch_case(self, active=active):
            doc = FakeDocument(active_sketch=active)
            mgr = sketch_manager(doc)
            first = mgr.close_sketch()
            second = mgr.close_sketch()
            self.observe(first=first, second=second, document=doc.snapshot())
            self.assertEqual(first, {"sketch_active": False})
            self.assertEqual(second, first)
            self.assertEqual(doc.SketchManager.InsertSketch.call_count, int(active))
        register(SketchAudit, f"close_sketch_active_{active}", "Closing a sketch is idempotent and never reopens a closed sketch", close_sketch_case)


class FeatureAudit(AuditCase):
    category = "feature_validation_rollback"


FEATURES = {
    "boss_extrude": ("FeatureExtrusion3", (12.5,), {}),
    "cut_extrude": ("FeatureCut4", (7.25,), {}),
    "fillet": ("FeatureFillet", (2.5,), {}),
    "chamfer": ("InsertFeatureChamfer", (1.25,), {"angle_deg": 30.0}),
    "revolve_boss": ("FeatureRevolve2", (180.0,), {}),
    "revolve_cut": ("FeatureRevolve2", (270.0,), {}),
    "circular_pattern": ("FeatureCircularPattern4", ("SeedBoss",), {"total_instances": 6, "axis_entity_name": "Axis1"}),
    "boss_sweep": ("CreateFeature", (), {"path_sketch_name": "PathSketch", "circular_profile_diameter_mm": 2.5}),
    "cut_sweep": ("CreateFeature", (), {"path_sketch_name": "PathSketch", "circular_profile_diameter_mm": 2.5}),
}
SKETCH_BOUND = {"boss_extrude", "cut_extrude", "revolve_boss", "revolve_cut"}


def invoke_feature(doc, name, *, args=None, kwargs=None):
    _, defaults, options = FEATURES[name]
    return getattr(feature_manager(doc), name)(*(defaults if args is None else args), **(options if kwargs is None else kwargs))


def build_feature_cases():
    for name, (com_name, args, kwargs) in FEATURES.items():
        def success(self, name=name, com_name=com_name):
            doc = FakeDocument()
            result = invoke_feature(doc, name)
            actual = getattr(doc.FeatureManager, com_name).call_args.args
            self.observe(result=result, com_args=actual, sweep_definition=vars(doc.sweep_data), document=doc.snapshot())
            self.assertTrue(result["created"])
            self.assertEqual(result["feature"], "NewFeature")
            self.assertEqual(doc.EditDelete.call_count, 0)
            if name in ["boss_extrude", "cut_extrude"]:
                self.assertAlmostEqual(actual[5], FEATURES[name][1][0] / 1000)
            elif name == "fillet":
                self.assertEqual(actual[:3], (3, 0.0025, 0))
            elif name == "chamfer":
                self.assertAlmostEqual(actual[2], 0.00125)
                self.assertAlmostEqual(actual[3], math.pi / 6)
            elif name in ["revolve_boss", "revolve_cut"]:
                self.assertEqual(actual[3], name == "revolve_cut")
                self.assertAlmostEqual(actual[8], FEATURES[name][1][0] * math.pi / 180)
            elif name == "circular_pattern":
                self.assertEqual(actual[0], 6)
                self.assertAlmostEqual(actual[1], 2 * math.pi)
            else:
                self.assertTrue(doc.sweep_data.CircularProfile)
                self.assertAlmostEqual(doc.sweep_data.CircularProfileDiameter, 0.0025)
                self.assertIs(doc.sweep_data.Path, doc.path_feature)
                doc.FeatureManager.CreateDefinition.assert_called_once_with(17 if name == "boss_sweep" else 18)
        register(FeatureAudit, f"valid_{name}", "Successful features retain existing geometry and pass correctly scaled dimensions to COM", success)
        for active in [False, True]:
            def none_result(self, name=name, com_name=com_name, active=active):
                doc = FakeDocument(active_sketch=active)
                getattr(doc.FeatureManager, com_name).side_effect = None
                getattr(doc.FeatureManager, com_name).return_value = None
                result, exc = captured(lambda: invoke_feature(doc, name))
                self.observe(result=result, exception=exc, initially_active=active, document=doc.snapshot())
                self.assertIsInstance(exc, exceptions.FeatureCreationError)
                self.assertEqual(doc.EditDelete.call_count, 0, "A failed creation must never delete a previously selected feature")
                if name in SKETCH_BOUND or name in {"boss_sweep", "cut_sweep"}:
                    self.assertIsNone(doc.SketchManager.ActiveSketch)
                    self.assertEqual(doc.SketchManager.InsertSketch.call_count, int(active))
            register(FeatureAudit, f"none_{name}_sketch_active_{active}", "A failed feature exits sketch mode where appropriate without deleting prior geometry", none_result)
        for error_code in [1, 7, -1]:
            def corrupt_feature(self, name=name, error_code=error_code):
                doc = FakeDocument()
                doc.created_feature.GetErrorCode = error_code
                result, exc = captured(lambda: invoke_feature(doc, name))
                self.observe(result=result, exception=exc, document=doc.snapshot())
                self.assertIsInstance(exc, exceptions.FeatureCreationError)
                self.assertEqual(doc.deleted, ["NewFeature"], "Rollback must only delete the newly created corrupt feature")
                self.assertNotIn("ExistingUserFeature", doc.deleted)
                doc.created_feature.Select2.assert_called_once_with(False, 0)
                self.assertEqual(doc.EditDelete.call_count, 1)
                self.assertIn("rolled back", str(exc))
            register(FeatureAudit, f"rollback_{name}_error_{error_code}", "Nonzero feature errors roll back exactly the new feature, not the user's existing selection", corrupt_feature)
        def selection_failure(self, name=name):
            doc = FakeDocument()
            doc.created_feature.GetErrorCode = 7
            doc.created_feature.select_ok = False
            result, exc = captured(lambda: invoke_feature(doc, name))
            self.observe(result=result, exception=exc, selection_succeeded=False, document=doc.snapshot())
            self.assertEqual(doc.EditDelete.call_count, 0, "Unsafe rollback: EditDelete ran even though selecting the corrupt feature failed")
            self.assertNotIn("ExistingUserFeature", doc.deleted)
            self.assertIsInstance(exc, exceptions.FeatureCreationError)
        register(FeatureAudit, f"rollback_selection_failure_{name}", "Rollback MUST NOT delete the current user selection if selecting the new feature fails", selection_failure)
        def delete_failure(self, name=name):
            doc = FakeDocument()
            doc.created_feature.GetErrorCode = 7
            doc.delete_ok = False
            result, exc = captured(lambda: invoke_feature(doc, name))
            self.observe(result=result, exception=exc, deletion_succeeded=False, document=doc.snapshot())
            self.assertIsInstance(exc, exceptions.FeatureCreationError)
            self.assertNotIn("rolled back", str(exc).lower(), "Rollback was reported as complete even though EditDelete returned False")
        register(FeatureAudit, f"rollback_delete_failure_{name}", "Failed deletion must not be reported as a completed rollback", delete_failure)
        def selection_exception(self, name=name):
            doc = FakeDocument()
            doc.created_feature.GetErrorCode = 7
            doc.created_feature.select_error = OfflineCOMError(message="selection failed")
            result, exc = captured(lambda: invoke_feature(doc, name))
            self.observe(result=result, exception=exc, document=doc.snapshot())
            self.assertIsNotNone(exc)
            self.assertEqual(doc.EditDelete.call_count, 0)
            self.assertNotIn("ExistingUserFeature", doc.deleted)
        register(FeatureAudit, f"rollback_select_exception_{name}", "A selection exception never falls through to deleting an unrelated feature", selection_exception)
        def creation_exception(self, name=name, com_name=com_name):
            doc = FakeDocument()
            error = OfflineCOMError(message="creation COM exception")
            getattr(doc.FeatureManager, com_name).side_effect = error
            result, exc = captured(lambda: invoke_feature(doc, name))
            self.observe(result=result, exception=exc, document=doc.snapshot())
            self.assertIsNotNone(exc)
            self.assertEqual(doc.EditDelete.call_count, 0)
            if name in SKETCH_BOUND or name in {"boss_sweep", "cut_sweep"}:
                self.assertIsNone(doc.SketchManager.ActiveSketch, "A throwing COM creation left the failed sketch operation active")
        register(FeatureAudit, f"creation_exception_cleanup_{name}", "Throwing COM feature creation does not delete existing geometry or leave the failed sketch open", creation_exception)
    for name in ["boss_extrude", "cut_extrude", "fillet", "chamfer", "revolve_boss", "revolve_cut"]:
        values = [0.0, -0.0, -1.0, -1e-12, float("nan"), float("inf"), float("-inf")]
        if name.startswith("revolve"):
            values += [360.0001]
        for index, value in enumerate(values):
            def invalid_dimension(self, name=name, value=value):
                doc = FakeDocument()
                self.observe(parameter=value)
                self.rejected_without_geometry(doc, lambda: invoke_feature(doc, name, args=(value,)))
            register(FeatureAudit, f"invalid_dimension_{name}_{index}_{value}", "Feature sizes/angles must be positive, finite, and within the operation's documented bounds", invalid_dimension)
    for value in [0, -1, 90, 90.00001, float("nan"), float("inf"), float("-inf")]:
        def bad_chamfer_angle(self, value=value):
            doc = FakeDocument()
            self.rejected_without_geometry(doc, lambda: feature_manager(doc).chamfer(1, angle_deg=value))
        register(FeatureAudit, f"invalid_chamfer_angle_{value}", "Chamfer angle must be finite and strictly between 0 and 90 degrees", bad_chamfer_angle)
    for name in ["fillet", "chamfer"]:
        for coordinate in range(3):
            for value in [float("nan"), float("inf"), float("-inf")]:
                def invalid_edge(self, name=name, coordinate=coordinate, value=value):
                    doc = FakeDocument()
                    coords = [1.0, 2.0, 3.0]
                    coords[coordinate] = value
                    options = dict(zip(["edge_x_mm", "edge_y_mm", "edge_z_mm"], coords))
                    self.observe(edge_coordinates=coords)
                    self.rejected_without_geometry(doc, lambda: getattr(feature_manager(doc), name)(1, **options))
                register(FeatureAudit, f"nonfinite_edge_{name}_{coordinate}_{value}", "Nonfinite edge coordinates must not change selection or create a feature", invalid_edge)
        for partial in [{"edge_x_mm": 1}, {"edge_x_mm": 1, "edge_y_mm": 2}, {"edge_y_mm": 2, "edge_z_mm": 3}]:
            def partial_edge(self, name=name, partial=partial):
                doc = FakeDocument()
                self.observe(edge_parameters=partial)
                self.rejected_without_geometry(doc, lambda: getattr(feature_manager(doc), name)(1, **partial))
            register(FeatureAudit, f"partial_edge_{name}_{'_'.join(partial)}", "Partial edge coordinates must not silently apply a feature to a stale user selection", partial_edge)
        for selected in [False, True]:
            def edge_selection(self, name=name, selected=selected):
                doc = FakeDocument()
                doc.SelectByID.return_value = selected
                result, exc = captured(lambda: getattr(feature_manager(doc), name)(1, edge_x_mm=-10, edge_y_mm=20, edge_z_mm=30))
                self.observe(selected=selected, result=result, exception=exc, selection_calls=calls_of(doc.SelectByID), document=doc.snapshot())
                doc.SelectByID.assert_called_once_with("", "EDGE", -0.01, 0.02, 0.03)
                if selected:
                    self.assertIsNone(exc)
                    self.assertTrue(result["created"])
                else:
                    self.assertIsInstance(exc, exceptions.FeatureCreationError)
                    self.assertEqual(doc.creation_calls(), [])
            register(FeatureAudit, f"edge_select_{name}_{selected}", "A failed edge selection prevents feature creation", edge_selection)
    for value in [-1, 0, 1, 1.5, 2.5, float("nan"), float("inf")]:
        def instances_case(self, value=value):
            doc = FakeDocument()
            self.rejected_without_geometry(doc, lambda: feature_manager(doc).circular_pattern("SeedBoss", total_instances=value, axis_entity_name="Axis1"))
        register(FeatureAudit, f"pattern_invalid_instances_{value}", "Circular pattern instance count must be a finite integer of at least two", instances_case)
    for value in [0, -1, float("nan"), float("inf"), float("-inf")]:
        def pattern_angle(self, value=value):
            doc = FakeDocument()
            self.rejected_without_geometry(doc, lambda: feature_manager(doc).circular_pattern("SeedBoss", total_angle_deg=value, axis_entity_name="Axis1"))
        register(FeatureAudit, f"pattern_invalid_angle_{value}", "Circular pattern angles must be finite and positive", pattern_angle)
    for coords in [[0], [0, 1], [0, 1, 2, 3], [float("nan"), 0, 0], [0, float("inf"), 0], [0, 0, float("-inf")]]:
        def pattern_axis(self, coords=coords):
            doc = FakeDocument()
            self.rejected_without_geometry(doc, lambda: feature_manager(doc).circular_pattern("SeedBoss", axis_coord_mm=coords))
        register(FeatureAudit, f"pattern_invalid_axis_{repr(coords)}", "An explicitly supplied invalid axis point must not silently use a fallback datum", pattern_axis)
    for equal in [False, True]:
        for flip in [False, True]:
            def pattern_spacing(self, equal=equal, flip=flip):
                doc = FakeDocument()
                result = feature_manager(doc).circular_pattern("SeedBoss", total_instances=4, total_angle_deg=180, equal_spacing=equal, axis_entity_name="Axis1", flip_dir=flip)
                args = doc.FeatureManager.FeatureCircularPattern4.call_args.args
                self.observe(result=result, com_args=args)
                self.assertEqual(args[0], 4)
                self.assertAlmostEqual(args[1], math.pi if equal else math.pi / 3)
                self.assertEqual(args[2], flip)
                self.assertEqual(args[5], equal)
            register(FeatureAudit, f"pattern_spacing_equal_{equal}_flip_{flip}", "Circular-pattern spacing and direction flags are preserved", pattern_spacing)
    for name in ["boss_extrude", "cut_extrude", "revolve_boss", "revolve_cut"]:
        def reverse_feature(self, name=name):
            doc = FakeDocument()
            options = {"reverse_dir": True} if name.startswith("revolve") else {"flip_dir": True}
            result = invoke_feature(doc, name, kwargs=options)
            args = getattr(doc.FeatureManager, FEATURES[name][0]).call_args.args
            self.observe(result=result, com_args=args)
            self.assertTrue(args[4] if name.startswith("revolve") else args[2])
        register(FeatureAudit, f"reverse_direction_{name}", "Feature direction parameters are forwarded to the correct COM argument", reverse_feature)
    for name in ["boss_sweep", "cut_sweep"]:
        for diameter in [0, -1, -1e-12, float("nan"), float("inf"), float("-inf")]:
            def sweep_diameter(self, name=name, diameter=diameter):
                doc = FakeDocument()
                self.rejected_without_geometry(doc, lambda: getattr(feature_manager(doc), name)(path_sketch_name="PathSketch", profile_sketch_name="ProfileSketch", circular_profile_diameter_mm=diameter))
            register(FeatureAudit, f"sweep_invalid_diameter_{name}_{diameter}", "An explicitly provided invalid sweep diameter cannot silently fall back to a profile sketch", sweep_diameter)
        for mode in ["profile", "case_insensitive", "feature_by_name", "missing_path", "missing_profile", "no_definition"]:
            def sweep_resolution(self, name=name, mode=mode):
                doc = FakeDocument()
                options = {"path_sketch_name": "PathSketch", "profile_sketch_name": "ProfileSketch"}
                if mode == "case_insensitive":
                    options = {"path_sketch_name": "pathsketch", "profile_sketch_name": "PROFILESKETCH"}
                elif mode == "feature_by_name":
                    doc.FirstFeature = None
                    doc.FeatureByName.side_effect = lambda n: {"PathSketch": doc.path_feature, "ProfileSketch": doc.profile_feature}.get(n)
                elif mode == "missing_path":
                    options["path_sketch_name"] = "DefinitelyMissing"
                elif mode == "missing_profile":
                    options["profile_sketch_name"] = "DefinitelyMissing"
                elif mode == "no_definition":
                    doc.FeatureManager.CreateDefinition.return_value = None
                result, exc = captured(lambda: getattr(feature_manager(doc), name)(**options))
                self.observe(mode=mode, result=result, exception=exc, definition=vars(doc.sweep_data), document=doc.snapshot())
                if mode in {"missing_path", "missing_profile", "no_definition"}:
                    self.assertIsInstance(exc, exceptions.FeatureCreationError)
                    doc.FeatureManager.CreateFeature.assert_not_called()
                else:
                    self.assertIsNone(exc)
                    self.assertFalse(doc.sweep_data.CircularProfile)
                    self.assertIs(doc.sweep_data.Profile, doc.profile_feature)
                doc.EditDelete.assert_not_called()
            register(FeatureAudit, f"sweep_resolution_{name}_{mode}", "Sweep path/profile resolution is bounded and missing inputs never create or delete a feature", sweep_resolution)
    for rebuilt in [False, True]:
        def rebuild_case(self, rebuilt=rebuilt):
            doc = FakeDocument()
            doc.EditRebuild3 = rebuilt
            result, exc = captured(feature_manager(doc).rebuild)
            self.observe(result=result, exception=exc, document=doc.snapshot())
            if rebuilt:
                self.assertIsNone(exc)
                self.assertEqual(result, {"rebuilt": True})
            else:
                self.assertIsInstance(exc, exceptions.CADRebuildError)
            doc.EditDelete.assert_not_called()
        register(FeatureAudit, f"rebuild_{rebuilt}", "A failing rebuild is not reported as successful", rebuild_case)


class STAAudit(AuditCase):
    category = "sta_worker"


async def until(predicate, timeout=0.65):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Offline synchronization deadline exceeded")
        await asyncio.sleep(0.002)


class WorkerRig:
    def __init__(self, case, *, autostart=True):
        self.case = case
        self.worker = sta.STAWorker(name="Offline-Core-Audit-STA")
        self.tasks = []
        self.threads = []
        self.releases = []
        self.loop_errors = []
        self.events_start = len(COM_EVENTS)
        loop = asyncio.get_running_loop()
        self.previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: self.loop_errors.append({"message": context.get("message"), "exception": safe_json(context.get("exception"))}))
        if autostart:
            self.start()

    def remember(self):
        thread = self.worker._thread
        if thread is not None and thread not in self.threads:
            self.threads.append(thread)
        return thread

    def start(self):
        self.worker.start()
        return self.remember()

    def submit(self, fn, **kwargs):
        task = asyncio.create_task(self.worker.run(fn, **kwargs))
        self.tasks.append(task)
        return task

    def blocker(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        def block():
            entered.set()
            if not release.wait(timeout=0.8):
                raise TimeoutError("Mock STA blocker deadline exceeded")
            return "blocker complete"
        return block, entered, release

    async def close(self):
        self.remember()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        for release in self.releases:
            release.set()
        self.worker.stop(timeout=JOIN_LIMIT)
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=JOIN_LIMIT)
        if self.tasks:
            await asyncio.wait_for(asyncio.gather(*self.tasks, return_exceptions=True), timeout=ASYNC_LIMIT)
        await asyncio.sleep(0)
        alive = [thread.name for thread in self.threads if thread.is_alive()]
        self.case.observe(cleanup_threads_alive=alive, loop_errors=self.loop_errors, com_lifecycle=COM_EVENTS[self.events_start:])
        asyncio.get_running_loop().set_exception_handler(self.previous_handler)
        self.case.assertEqual(alive, [], "Offline audit left a worker thread running")
        self.case.assertEqual(self.loop_errors, [], "Worker delivered an invalid event-loop callback")


@contextlib.asynccontextmanager
async def worker_rig(case, *, autostart=True):
    rig = WorkerRig(case, autostart=autostart)
    try:
        yield rig
    finally:
        await rig.close()


def async_case(fn):
    def run(self):
        async def bounded():
            return await asyncio.wait_for(fn(self), timeout=4.0)
        asyncio.run(bounded())
    return run


def no_sleep():
    delays = []
    def sleep(delay):
        delays.append({"seconds": delay, "thread_id": threading.get_ident()})
    return types.SimpleNamespace(sleep=sleep), delays


def build_sta_cases():
    busy_codes = [-2147418111, -2147417846, 0x80010001, 0x8001010A]
    for code in busy_codes:
        for mode in ["default_mutation", "explicit_mutation"]:
            async def no_mutation_retry(self, code=code, mode=mode):
                calls = []
                fake_time, delays = no_sleep()
                error = OfflineCOMError(code)
                async with worker_rig(self) as rig:
                    def mutate():
                        calls.append(threading.get_ident())
                        raise error
                    with mock.patch.object(sta, "time", fake_time):
                        task = rig.submit(mutate, **({} if mode == "default_mutation" else {"idempotent": False}))
                        try:
                            result, exc = await asyncio.wait_for(task, ASYNC_LIMIT), None
                        except Exception as caught:
                            result, exc = None, caught
                    self.observe(hresult=code, mode=mode, attempts=len(calls), mutation_threads=calls, delays=delays, result=result, exception=exc)
                    self.assertIs(exc, error)
                    self.assertEqual(len(calls), 1, "A non-idempotent operation was retried")
                    self.assertEqual(delays, [])
            register(STAAudit, f"busy_no_retry_{mode}_{code}", "Default and explicit non-idempotent mutations execute exactly once on COM busy", async_case(no_mutation_retry))
    for code in busy_codes:
        for failures in [1, 2, 4, 5]:
            async def read_retry(self, code=code, failures=failures):
                calls = []
                fake_time, delays = no_sleep()
                async with worker_rig(self) as rig:
                    def read():
                        calls.append(threading.get_ident())
                        if len(calls) <= failures:
                            raise OfflineCOMError(code)
                        return {"read": "ok", "attempt": len(calls)}
                    with mock.patch.object(sta, "time", fake_time):
                        task = rig.submit(read, idempotent=True)
                        try:
                            result, exc = await asyncio.wait_for(task, ASYNC_LIMIT), None
                        except Exception as caught:
                            result, exc = None, caught
                    expected_attempts = min(failures + 1, 5)
                    self.observe(hresult=code, busy_failures=failures, attempts=len(calls), threads=calls, delays=delays, result=result, exception=exc)
                    self.assertEqual(len(calls), expected_attempts)
                    self.assertEqual([d["seconds"] for d in delays], [0.2 * 2 ** i for i in range(expected_attempts - 1)])
                    self.assertTrue(all(d["thread_id"] == rig.threads[0].ident for d in delays))
                    if failures >= 5:
                        self.assertIsInstance(exc, OfflineCOMError)
                    else:
                        self.assertIsNone(exc)
                        self.assertEqual(result["attempt"], expected_attempts)
            register(STAAudit, f"idempotent_busy_{code}_failures_{failures}", "Idempotent reads retry signed/unsigned busy HRESULTs with bounded exponential backoff", async_case(read_retry))
    for code in [-2147467259, 0x80004005, -2147024891, -2147023174, 0, None]:
        async def nonbusy(self, code=code):
            calls = []
            fake_time, delays = no_sleep()
            error = OfflineCOMError(code)
            async with worker_rig(self) as rig:
                def read():
                    calls.append(threading.get_ident())
                    raise error
                with mock.patch.object(sta, "time", fake_time):
                    task = rig.submit(read, idempotent=True)
                    try:
                        await asyncio.wait_for(task, ASYNC_LIMIT)
                        exc = None
                    except Exception as caught:
                        exc = caught
                self.observe(hresult=code, attempts=len(calls), delays=delays, exception=exc)
                self.assertIs(exc, error)
                self.assertEqual(len(calls), 1)
                self.assertEqual(delays, [])
        register(STAAudit, f"idempotent_nonbusy_no_retry_{code}", "Nonbusy COM errors are never retried even for idempotent reads", async_case(nonbusy))
    for exception_type in [ValueError, RuntimeError, OSError]:
        async def noncom(self, exception_type=exception_type):
            calls = []
            error = exception_type("not a COM busy error")
            fake_time, delays = no_sleep()
            async with worker_rig(self) as rig:
                def read():
                    calls.append(1)
                    raise error
                with mock.patch.object(sta, "time", fake_time):
                    result = await asyncio.wait_for(asyncio.gather(rig.submit(read, idempotent=True), return_exceptions=True), ASYNC_LIMIT)
                self.observe(attempts=len(calls), exception=result[0], delays=delays)
                self.assertIs(result[0], error)
                self.assertEqual(len(calls), 1)
                self.assertEqual(delays, [])
        register(STAAudit, f"noncom_no_retry_{exception_type.__name__}", "Ordinary Python exceptions propagate unchanged and are not retried", async_case(noncom))
    for code in busy_codes:
        def missing_hresult(self, code=code):
            worker = sta.STAWorker()
            calls = []
            fake_time, delays = no_sleep()
            def fn():
                calls.append(1)
                if len(calls) == 1:
                    raise OfflineCOMError(code, expose=False)
                return "ok"
            with mock.patch.object(sta, "time", fake_time):
                result = worker._execute_with_retry(fn, max_retries=3, base_delay=0.01)
            self.observe(hresult_in_args=code, result=result, attempts=len(calls), delays=delays)
            self.assertEqual(result, "ok")
            self.assertEqual(len(calls), 2)
            self.assertEqual([d["seconds"] for d in delays], [0.01])
        register(STAAudit, f"busy_hresult_args_fallback_{code}", "Busy HRESULT detection also supports com_error instances exposing the code only in args", missing_hresult)
    for retry in [False, True]:
        def explicit_retry_limit(self, retry=retry):
            worker = sta.STAWorker()
            calls = []
            fake_time, delays = no_sleep()
            def fn():
                calls.append(1)
                raise OfflineCOMError(-2147418111)
            with mock.patch.object(sta, "time", fake_time):
                result, exc = captured(lambda: worker._execute_with_retry(fn, max_retries=3, base_delay=0.01, retry=retry))
            self.observe(retry=retry, result=result, exception=exc, attempts=len(calls), delays=delays)
            self.assertIsInstance(exc, OfflineCOMError)
            self.assertEqual(len(calls), 3 if retry else 1)
            self.assertEqual([d["seconds"] for d in delays], [0.01, 0.02] if retry else [])
        register(STAAudit, f"explicit_retry_limit_enabled_{retry}", "The retry limit bounds total attempts and disables all backoff when retry is false", explicit_retry_limit)
    async def fifo(self):
        main_thread = threading.get_ident()
        order, thread_ids = [], []
        async with worker_rig(self) as rig:
            def work(index):
                def run():
                    order.append(index)
                    thread_ids.append(threading.get_ident())
                    return {"index": index}
                return run
            tasks = [rig.submit(work(i)) for i in range(32)]
            results = await asyncio.wait_for(asyncio.gather(*tasks), ASYNC_LIMIT)
            self.observe(order=order, thread_ids=sorted(set(thread_ids)), main_thread=main_thread, results=results)
            self.assertEqual(order, list(range(32)))
            self.assertEqual(results, [{"index": i} for i in range(32)])
            self.assertEqual(set(thread_ids), {rig.threads[0].ident})
            self.assertNotEqual(thread_ids[0], main_thread)
    register(STAAudit, "single_correct_thread_fifo_32_tasks", "All submitted operations run FIFO on one dedicated STA thread, never the asyncio thread", async_case(fifo))
    async def continue_after_error(self):
        seen = []
        error = ValueError("middle task failed")
        async with worker_rig(self) as rig:
            def work(index):
                def run():
                    seen.append(index)
                    if index == 1:
                        raise error
                    return index
                return run
            results = await asyncio.wait_for(asyncio.gather(*(rig.submit(work(i)) for i in range(3)), return_exceptions=True), ASYNC_LIMIT)
            self.observe(order=seen, results=results)
            self.assertEqual(seen, [0, 1, 2])
            self.assertEqual(results[0], 0)
            self.assertIs(results[1], error)
            self.assertEqual(results[2], 2)
    register(STAAudit, "failure_does_not_poison_fifo_queue", "A task exception does not prevent later queued operations from completing", async_case(continue_after_error))
    for count, mode in [(1, "default"), (8, "default"), (1, "explicit_false"), (1, "wait_for_timeout")]:
        async def canceled_pending(self, count=count, mode=mode):
            mutations = []
            async with worker_rig(self) as rig:
                block, entered, release = rig.blocker()
                first = rig.submit(block)
                await until(entered.is_set)
                def mutate(index):
                    return lambda: mutations.append(index)
                tasks = [rig.submit(mutate(i), **({"idempotent": False} if mode == "explicit_false" else {})) for i in range(count)]
                await until(lambda: rig.worker._task_queue.qsize() >= count)
                if mode == "wait_for_timeout":
                    try:
                        await asyncio.wait_for(tasks[0], timeout=0.025)
                    except TimeoutError:
                        pass
                else:
                    for task in tasks:
                        task.cancel()
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), ASYNC_LIMIT)
                release.set()
                await asyncio.wait_for(first, ASYNC_LIMIT)
                barrier = await asyncio.wait_for(rig.submit(lambda: "barrier", idempotent=True), ASYNC_LIMIT)
                self.observe(cancellation_mode=mode, queued_mutations=count, canceled=[t.cancelled() for t in tasks], executed_mutations=mutations, barrier=barrier)
                self.assertTrue(all(t.cancelled() for t in tasks))
                self.assertEqual(mutations, [], "Canceled pending mutations were executed on the STA thread")
        register(STAAudit, f"cancel_pending_mutation_{mode}_count_{count}", "Cancellation before execution MUST prevent the queued mutation from running", async_case(canceled_pending))
    async def stop_drain(self):
        mutations = []
        async with worker_rig(self) as rig:
            block, entered, release = rig.blocker()
            first = rig.submit(block)
            await until(entered.is_set)
            pending = [rig.submit(lambda i=i: mutations.append(i)) for i in range(4)]
            await until(lambda: rig.worker._task_queue.qsize() >= 4)
            old_thread = rig.threads[0]
            started = time.monotonic()
            rig.worker.stop(timeout=0.02)
            stop_elapsed = time.monotonic() - started
            release.set()
            old_thread.join(timeout=JOIN_LIMIT)
            results = await asyncio.wait_for(asyncio.gather(first, *pending, return_exceptions=True), ASYNC_LIMIT)
            self.observe(stop_elapsed_seconds=stop_elapsed, pending_results=results[1:], first_result=results[0], mutations=mutations, queue_size=rig.worker._task_queue.qsize(), unfinished_tasks=rig.worker._task_queue.unfinished_tasks, old_thread_alive=old_thread.is_alive())
            self.assertLess(stop_elapsed, 0.3)
            self.assertFalse(old_thread.is_alive())
            self.assertEqual(results[0], "blocker complete")
            self.assertTrue(all(isinstance(x, RuntimeError) for x in results[1:]))
            self.assertEqual(mutations, [])
            self.assertEqual(rig.worker._task_queue.qsize(), 0)
    register(STAAudit, "stop_bounded_drains_pending_without_mutation", "A bounded stop rejects all pending futures and does not execute pending mutations", async_case(stop_drain))
    for pending_count in [0, 3]:
        async def queue_accounting(self, pending_count=pending_count):
            async with worker_rig(self) as rig:
                if pending_count:
                    block, entered, release = rig.blocker()
                    first = rig.submit(block)
                    await until(entered.is_set)
                    pending = [rig.submit(lambda: "must not run") for _ in range(pending_count)]
                    await until(lambda: rig.worker._task_queue.qsize() >= pending_count)
                    rig.worker.stop(timeout=0.01)
                    release.set()
                    rig.threads[0].join(timeout=JOIN_LIMIT)
                    await asyncio.wait_for(asyncio.gather(first, *pending, return_exceptions=True), ASYNC_LIMIT)
                else:
                    await asyncio.wait_for(rig.submit(lambda: "done"), ASYNC_LIMIT)
                    rig.worker.stop(timeout=JOIN_LIMIT)
                self.observe(pending_count=pending_count, queue_size=rig.worker._task_queue.qsize(), unfinished_tasks=rig.worker._task_queue.unfinished_tasks)
                self.assertEqual(rig.worker._task_queue.qsize(), 0)
                self.assertEqual(rig.worker._task_queue.unfinished_tasks, 0, "Shutdown drained items without balancing task_done; queue.join would hang")
        register(STAAudit, f"stop_queue_accounting_pending_{pending_count}", "Every removed item, including stop sentinels and drained tasks, must balance queue accounting", async_case(queue_accounting))
    async def start_stop_restart(self):
        async with worker_rig(self) as rig:
            first_thread = rig.threads[0]
            rig.start()
            self.assertIs(rig.worker._thread, first_thread)
            first = await asyncio.wait_for(rig.submit(lambda: "first"), ASYNC_LIMIT)
            rig.worker.stop(timeout=JOIN_LIMIT)
            first_thread.join(timeout=JOIN_LIMIT)
            rig.worker.stop(timeout=0.01)
            second_thread = rig.start()
            second = await asyncio.wait_for(rig.submit(lambda: "second"), ASYNC_LIMIT)
            self.observe(first=first, second=second, same_thread_object=first_thread is second_thread, first_thread_alive=first_thread.is_alive())
            self.assertFalse(first_thread.is_alive())
            self.assertIsNot(first_thread, second_thread)
            self.assertEqual((first, second), ("first", "second"))
    register(STAAudit, "start_idempotent_clean_stop_restart", "Repeated start/stop is bounded and a cleanly stopped worker can restart", async_case(start_stop_restart))
    async def timeout_preserves_handle(self):
        async with worker_rig(self) as rig:
            block, entered, release = rig.blocker()
            first = rig.submit(block)
            await until(entered.is_set)
            original = rig.threads[0]
            rig.worker.stop(timeout=0.01)
            self.observe(original_thread_alive=original.is_alive(), worker_retains_thread_handle=rig.worker._thread is original, running_flag=rig.worker._running)
            self.assertTrue(original.is_alive())
            self.assertIs(rig.worker._thread, original, "A timed-out stop discarded the handle to a still-running STA thread")
    register(STAAudit, "stop_timeout_does_not_forget_live_sta", "A timed-out stop must retain control of the still-running worker thread", async_case(timeout_preserves_handle))
    async def no_overlapping_restart(self):
        async with worker_rig(self) as rig:
            block, entered, release = rig.blocker()
            first = rig.submit(block)
            await until(entered.is_set)
            original = rig.threads[0]
            rig.worker.stop(timeout=0.01)
            result, error = captured(rig.start)
            replacement = rig.remember()
            self.observe(original_thread_alive=original.is_alive(), restart_exception=error, replacement_created=replacement is not None and replacement is not original, replacement_alive=replacement.is_alive() if replacement is not None else False)
            self.assertFalse(original.is_alive() and replacement is not None and replacement is not original, "Restart created a second STA while the timed-out worker was still executing")
    register(STAAudit, "restart_cannot_overlap_timed_out_sta", "Restart must refuse/defer while the previous STA is still executing", async_case(no_overlapping_restart))
    async def apartment_lifecycle(self):
        start = len(COM_EVENTS)
        async with worker_rig(self, autostart=False) as rig:
            result = await asyncio.wait_for(rig.submit(lambda: threading.get_ident()), ASYNC_LIMIT)
            thread = rig.remember()
            rig.worker.stop(timeout=JOIN_LIMIT)
            thread.join(timeout=JOIN_LIMIT)
            events = COM_EVENTS[start:]
            self.observe(result_thread=result, events=events)
            initialized = [event for event in events if event["action"] == "initialize"]
            uninitialized = [event for event in events if event["action"] == "uninitialize"]
            self.assertEqual(len(initialized), 1)
            self.assertEqual(len(uninitialized), 1)
            self.assertEqual(initialized[0]["args"], (2,))
            self.assertTrue(all(event["thread_id"] == result for event in events))
            self.assertTrue(any(event["action"] == "pump" for event in events))
            self.assertEqual(events[0]["action"], "initialize")
            self.assertEqual(events[-1]["action"], "uninitialize")
    register(STAAudit, "lazy_run_sta_apartment_lifecycle", "Lazy start initializes/pumps/uninitializes the mocked STA on the same dedicated thread", async_case(apartment_lifecycle))
    def never_started_stop(self):
        start = len(COM_EVENTS)
        worker = sta.STAWorker()
        worker.stop(timeout=0.01)
        worker.stop(timeout=0.01)
        self.observe(thread=worker._thread, running=worker._running, queue_size=worker._task_queue.qsize(), com_events=COM_EVENTS[start:])
        self.assertIsNone(worker._thread)
        self.assertFalse(worker._running)
        self.assertEqual(COM_EVENTS[start:], [])
    register(STAAudit, "stop_never_started_is_noop", "Stopping a never-started worker does not initialize COM or queue work", never_started_stop)


class ExceptionAudit(AuditCase):
    category = "exceptions"


def build_exception_cases():
    for name in ["COMConnectionError", "DocumentNotFoundError", "FeatureCreationError", "CADRebuildError", "ParameterNotFoundError", "InvalidSelectionError", "MateError", "DrawingError"]:
        def exception_case(self, name=name):
            cls = getattr(exceptions, name)
            error = cls("offline diagnostic")
            self.observe(exception_class=name, base_class=exceptions.SolidWorksError.__name__, message=str(error))
            self.assertIsInstance(error, exceptions.SolidWorksError)
            self.assertIsInstance(error, Exception)
            self.assertEqual(str(error), "offline diagnostic")
        register(ExceptionAudit, f"exception_hierarchy_{name}", "Public CAD exceptions preserve the SolidWorksError hierarchy and diagnostics", exception_case)


class JSONTestResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.started = {}

    def startTest(self, test):
        self.started[id(test)] = time.monotonic()
        super().startTest(test)

    def record(self, test, status, error=None, reason=None):
        method = getattr(test, test._testMethodName)
        item = {
            "id": test.id(), "category": test.category, "status": status,
            "expected": getattr(method, "audit_expected", method.__doc__),
            "duration_seconds": round(time.monotonic() - self.started.get(id(test), time.monotonic()), 6),
            "actual_summary": getattr(test, "actual_summary", {}),
            "traceback": self._exc_info_to_string(error, test) if error else None,
            "exception_type": error[0].__name__ if error else None,
            "exception_message": str(error[1]) if error else None,
            "skip_reason": reason,
        }
        self.cases.append(item)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "fail", err)

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", err)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skip", reason=reason)


MODULE_PATHS = [
    "core/units.py", "core/sta_worker.py", "core/exceptions.py",
    "cad/client.py", "cad/document.py", "cad/sketcher.py", "cad/features.py",
]


def source_hashes():
    return {"src/sw_mcp/" + relative: hashlib.sha256((PROJECT_ROOT / "src" / "sw_mcp" / relative).read_bytes()).hexdigest() for relative in MODULE_PATHS}


def main():
    global PROJECT_ROOT, OUTPUT_ROOT, units, sta, exceptions, client_mod, document_mod, sketcher_mod, features_mod
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    PROJECT_ROOT, OUTPUT_ROOT = args.project_root.resolve(), args.output_root.resolve()
    if not (PROJECT_ROOT / "src" / "sw_mcp").is_dir():
        parser.error("project root must contain src/sw_mcp")
    if not OUTPUT_ROOT.is_dir():
        parser.error("output root must already exist")
    script_copy = OUTPUT_ROOT / "core_offline.py"
    if Path(__file__).resolve() != script_copy:
        shutil.copyfile(Path(__file__).resolve(), script_copy)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    report_path, log_path = OUTPUT_ROOT / "core_report.json", OUTPUT_ROOT / "core_tests.log"
    cases, harness_error, result = [], None, None
    before_hashes = source_hashes()
    with log_path.open("w", encoding="utf-8", newline="\n") as log:
        import logging
        handler = logging.StreamHandler(log)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        production_logger = logging.getLogger("sw_mcp")
        production_logger.handlers = [handler]
        production_logger.setLevel(logging.DEBUG)
        production_logger.propagate = False
        try:
            install_com_mocks()
            sys.path.insert(0, str(PROJECT_ROOT / "src"))
            units = importlib.import_module("sw_mcp.core.units")
            sta = importlib.import_module("sw_mcp.core.sta_worker")
            exceptions = importlib.import_module("sw_mcp.core.exceptions")
            client_mod = importlib.import_module("sw_mcp.cad.client")
            document_mod = importlib.import_module("sw_mcp.cad.document")
            sketcher_mod = importlib.import_module("sw_mcp.cad.sketcher")
            features_mod = importlib.import_module("sw_mcp.cad.features")
            for build in [build_unit_cases, build_document_cases, build_client_cases, build_sketch_cases, build_feature_cases, build_sta_cases, build_exception_cases]:
                build()
            suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls) for cls in [UnitAudit, DocumentAudit, ClientAudit, SketchAudit, FeatureAudit, STAAudit, ExceptionAudit])
            result = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=JSONTestResult).run(suite)
            cases = result.cases
        except Exception:
            harness_error = traceback.format_exc()
            log.write("\nHARNESS ERROR\n" + harness_error)
        finally:
            handler.flush()
            production_logger.removeHandler(handler)
    counts = {status: sum(case["status"] == status for case in cases) for status in ["pass", "fail", "error", "skip"]}
    counts["total"] = len(cases)
    after_hashes = source_hashes()
    source_unchanged = before_hashes == after_hashes
    exit_code = 2 if harness_error or not source_unchanged else (0 if result is not None and result.wasSuccessful() and cases else 1)
    categories = {}
    for case in cases:
        bucket = categories.setdefault(case["category"], {"pass": 0, "fail": 0, "error": 0, "skip": 0, "total": 0})
        bucket[case["status"]] += 1
        bucket["total"] += 1
    elapsed = round(time.monotonic() - started, 3)
    report = {
        "audit": "SolidWorks MCP offline core behavioral regression", "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(), "elapsed_seconds": elapsed,
        "exit_code": exit_code, "counts": counts, "categories": categories,
        "failing_cases": [case["id"] for case in cases if case["status"] in {"fail", "error"}],
        "harness_error": harness_error, "source_unchanged": source_unchanged,
        "source_sha256_before": before_hashes, "source_sha256_after": after_hashes,
        "environment": {"python": sys.version, "executable": sys.executable, "platform": sys.platform, "project_root": str(PROJECT_ROOT), "output_root": str(OUTPUT_ROOT)},
        "safety": {"real_com_used": False, "com_modules": "in-memory mock pythoncom/win32com installed before production imports", "real_solidworks_launched": False, "production_source_modified": False, "network_or_install_used": False, "fixtures": "in-memory document/features/filesystem; no CAD fixture files written", "thread_wait_limits_seconds": {"async_result": ASYNC_LIMIT, "thread_join": JOIN_LIMIT, "blocker": 0.8, "async_case": 4.0}},
        "scope": {"included": MODULE_PATHS, "excluded": ["MCP schemas", "tool wrappers", "protocol_contract.py", "live_validation.py", "live COM"]},
        "artifacts": {"report": str(report_path), "log": str(log_path), "script_copy": str(script_copy), "workspace_script": str(PROJECT_ROOT / "tests" / "validation" / "offline_core.py")},
        "cases": cases,
    }
    report_path.write_text(json.dumps(safe_json(report), indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print("CORE_OFFLINE " + " ".join(f"{key}={counts[key]}" for key in ["total", "pass", "fail", "error", "skip"]) + f" elapsed={elapsed}s exit_code={exit_code}")
    for category, category_counts in categories.items():
        print(category + ": " + ", ".join(f"{key}={category_counts[key]}" for key in ["pass", "fail", "error", "skip"]))
    if harness_error:
        print("HARNESS_ERROR: " + harness_error.splitlines()[-1])
    failing = report["failing_cases"]
    if failing:
        print(f"FAILING_CASES={len(failing)}; full IDs, actual summaries and tracebacks are in core_report.json / core_tests.log")
        for identifier in failing[:5]:
            print("  " + identifier)
    print("PRODUCTION_SOURCE_UNCHANGED=" + str(source_unchanged))
    print("REPORT=" + str(report_path))
    print("LOG=" + str(log_path))
    print("SCRIPT_COPY=" + str(script_copy))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
