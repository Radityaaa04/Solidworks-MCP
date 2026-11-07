"""Assembly Management, Multi-Component Insertion, Mates & Interference Detection.

Enables assembling multi-body parts, inserting sub-assemblies/components,
constraining components with standard engineering mates (Coincident, Concentric,
Distance, Parallel, Perpendicular, Angle, Tangent, Lock), listing components,
and running Parasolid interference detection.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

import pythoncom
import win32com.client
from sw_mcp.cad.document import DocumentManager, swDocASSEMBLY, swDocPART, swOpenDocOptions_Silent
from sw_mcp.core.exceptions import FeatureCreationError, InvalidSelectionError, SolidWorksError
from sw_mcp.core.units import deg_to_radians, mm_to_meters, select_brep_entity_by_point

logger = logging.getLogger("sw_mcp.cad.assembly")

# SolidWorks Mate Types Enum (swMateType_e)
MATE_TYPES = {
    "coincident": 0,       # swMateCOINCIDENT
    "concentric": 1,       # swMateCONCENTRIC
    "perpendicular": 2,    # swMatePERPENDICULAR
    "parallel": 3,         # swMatePARALLEL
    "tangent": 4,          # swMateTANGENT
    "distance": 5,         # swMateDISTANCE
    "angle": 6,            # swMateANGLE
    "lock": 16,            # swMateLOCK
}

# SolidWorks Mate Alignment Enum (swMateAlign_e)
ALIGN_TYPES = {
    "aligned": 0,          # swMateAlignALIGNED
    "anti_aligned": 1,     # swMateAlignANTI_ALIGNED
    "closest": 2,          # swMateAlignCLOSEST
}

# SolidWorks AddMate Error Enum (swAddMateError_e)
ADD_MATE_ERRORS = {
    0: "ErrorUnknown: Unspecified failure creating mate.",
    1: "NoError: Mate created successfully.",
    2: "IncorrectMateType: Unsupported or invalid mate type.",
    3: "IncorrectAlignment: Unsupported alignment option.",
    4: "IncorrectSelections: Selected entities are invalid for this mate type.",
    5: "OverDefinedAssembly: Mate over-defines the assembly kinematics.",
    6: "IncorrectGearRatios: Invalid gear ratio parameters.",
}


class AssemblyManager:
    """Manages multi-component assemblies, mating relationships, and interference checks."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def get_active_assembly(self) -> Any:
        """Retrieve the active AssemblyDoc instance or raise error if not an Assembly."""
        doc = self.doc_mgr.get_active_doc()
        # In SolidWorks: swDocASSEMBLY = 2
        if doc.GetType != swDocASSEMBLY:
            raise SolidWorksError(
                f"Assembly operation requires an active Assembly document (.sldasm). "
                f"Current document type is {doc.GetType}."
            )
        return doc

    def _safe_select(
        self,
        ext: Any,
        name: str,
        obj_type: str,
        x_m: float = 0.0,
        y_m: float = 0.0,
        z_m: float = 0.0,
        append: bool = True,
        mark: int = 1,
    ) -> bool:
        """Call SelectByID2 with explicit VARIANT wrapping to prevent late-binding type mismatch."""
        v_name = win32com.client.VARIANT(pythoncom.VT_BSTR, name)
        v_type = win32com.client.VARIANT(pythoncom.VT_BSTR, obj_type)
        v_x = win32com.client.VARIANT(pythoncom.VT_R8, float(x_m))
        v_y = win32com.client.VARIANT(pythoncom.VT_R8, float(y_m))
        v_z = win32com.client.VARIANT(pythoncom.VT_R8, float(z_m))
        v_app = win32com.client.VARIANT(pythoncom.VT_BOOL, bool(append))
        v_mark = win32com.client.VARIANT(pythoncom.VT_I4, int(mark))
        v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        v_opt = win32com.client.VARIANT(pythoncom.VT_I4, 0)
        return bool(ext.SelectByID2(v_name, v_type, v_x, v_y, v_z, v_app, v_mark, v_call, v_opt))

    def _resolve_and_select_entity(self, assy_doc: Any, entity_str: str, mark: int = 1) -> bool:
        """
        Parse and select an assembly entity by name or 3D coordinate point.
        Formats supported:
          1. 'FACE:x,y,z' or 'EDGE:x,y,z' or 'VERTEX:x,y,z' (coordinates in millimeters)
          2. Plain coordinates 'x,y,z' (defaults to FACE)
          3. Named entities e.g. 'Top Plane@part1-1' or 'Front Plane'
        """
        ext = assy_doc.Extension
        assy_title = assy_doc.GetTitle
        raw = entity_str.strip()

        # Check for coordinate pattern: TYPE:x,y,z or x,y,z
        coord_match = re.match(r"^(?:(FACE|EDGE|VERTEX):)?\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$", raw, re.IGNORECASE)
        if coord_match:
            ent_type = (coord_match.group(1) or "FACE").upper()
            x_mm = float(coord_match.group(2))
            y_mm = float(coord_match.group(3))
            z_mm = float(coord_match.group(4))
            xm, ym, zm = mm_to_meters(x_mm), mm_to_meters(y_mm), mm_to_meters(z_mm)
            sel_ok = self._safe_select(ext, "", ent_type, xm, ym, zm, append=True, mark=mark)
            if not sel_ok:
                sel_ok = select_brep_entity_by_point(assy_doc, ent_type, xm, ym, zm, append=True, mark=mark)
            return sel_ok

        # Named entity (e.g. plane, axis, or feature)
        ent_name = raw
        ent_type = "PLANE"
        if "@" in ent_name:
            # Check if assembly title suffix is already present
            if not ent_name.endswith(f"@{assy_title}"):
                ent_name = f"{ent_name}@{assy_title}"
        elif ent_name.lower() in ["front plane", "top plane", "right plane", "front", "top", "right"]:
            # Assembly-level standard plane
            plane_aliases = {
                "front": "Front Plane", "top": "Top Plane", "right": "Right Plane",
                "front plane": "Front Plane", "top plane": "Top Plane", "right plane": "Right Plane"
            }
            ent_name = plane_aliases.get(ent_name.lower(), ent_name)
            ent_type = "PLANE"

        return self._safe_select(ext, ent_name, ent_type, 0.0, 0.0, 0.0, append=True, mark=mark)

    def insert_component(
        self,
        component_path: str,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = 0.0,
        config_name: str = "",
    ) -> Dict[str, Any]:
        """
        Insert a part or sub-assembly component into the active assembly document.
        Pre-loads the file into memory silently if not already loaded.
        """
        assy_doc = self.get_active_assembly()
        assy_title = assy_doc.GetTitle
        abs_path = os.path.abspath(component_path)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Component file not found on disk: {abs_path}")

        app = self.doc_mgr.client.app
        ext = os.path.splitext(abs_path)[1].lower()
        sw_type = swDocASSEMBLY if ext == ".sldasm" else swDocPART

        # Pre-load document into memory silently to satisfy AddComponent5 prerequisite
        v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        comp_doc = app.OpenDoc6(abs_path, sw_type, swOpenDocOptions_Silent, "", v_err, v_warn)
        if comp_doc is None:
            raise SolidWorksError(f"Failed loading component into memory: {abs_path} (Error code: {v_err.value})")

        # Re-activate assembly in case OpenDoc6 stole foreground focus
        v_act_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        app.ActivateDoc3(assy_title, False, 0, v_act_err)
        if app.ActiveDoc is None or app.ActiveDoc.GetType != swDocASSEMBLY:
            assy_path = assy_doc.GetPathName
            if assy_path:
                app.ActivateDoc3(os.path.basename(assy_path), False, 0, v_act_err)

        # Convert initial rough coordinates to meters
        x_m = mm_to_meters(x_mm)
        y_m = mm_to_meters(y_mm)
        z_m = mm_to_meters(z_mm)

        # Execute AddComponent5
        # ConfigOption: 0 = swAddComponentConfigOptions_CurrentSelectedConfig, 2 = swAddComponentConfigOptions_SpecifiedConfig
        config_option = 2 if config_name else 0
        use_config_for_part_ref = True if config_name else False
        comp = assy_doc.AddComponent5(abs_path, config_option, "", use_config_for_part_ref, config_name, x_m, y_m, z_m)
        if comp is None:
            raise SolidWorksError(f"AddComponent5 failed for component: {abs_path}")

        # Verify referenced configuration
        ref_config = getattr(comp, "ReferencedConfiguration", "")
        if config_name and ref_config and ref_config.lower() != config_name.lower():
            try:
                comp.ReferencedConfiguration = config_name
                ref_config = getattr(comp, "ReferencedConfiguration", "")
            except Exception:
                pass
            if ref_config and ref_config.lower() != config_name.lower():
                raise SolidWorksError(
                    f"Component insertion requested configuration '{config_name}', but active reference is '{ref_config}'."
                )

        # Query bounding box
        box = comp.GetBox(False, False)
        bbox_dict = None
        if box and len(box) >= 6:
            bbox_dict = {
                "min_x_mm": round(box[0] * 1000.0, 3),
                "min_y_mm": round(box[1] * 1000.0, 3),
                "min_z_mm": round(box[2] * 1000.0, 3),
                "max_x_mm": round(box[3] * 1000.0, 3),
                "max_y_mm": round(box[4] * 1000.0, 3),
                "max_z_mm": round(box[5] * 1000.0, 3),
            }

        logger.info("Successfully inserted component '%s' into assembly.", comp.Name2)

        return {
            "name": comp.Name2,
            "path": comp.GetPathName,
            "configuration": ref_config or config_name,
            "is_fixed": bool(comp.IsFixed),
            "is_suppressed": bool(comp.IsSuppressed),
            "initial_position_mm": {"x": x_mm, "y": y_mm, "z": z_mm},
            "bounding_box_mm": bbox_dict,
        }

    def list_components(self, top_level_only: bool = True) -> List[Dict[str, Any]]:
        """List all components currently assembled in the active document."""
        assy_doc = self.get_active_assembly()
        comps = assy_doc.GetComponents(top_level_only)
        results: List[Dict[str, Any]] = []

        for c in comps or []:
            box = c.GetBox(False, False)
            bbox = None
            if box and len(box) >= 6:
                bbox = {
                    "min_x_mm": round(box[0] * 1000.0, 3),
                    "min_y_mm": round(box[1] * 1000.0, 3),
                    "min_z_mm": round(box[2] * 1000.0, 3),
                    "max_x_mm": round(box[3] * 1000.0, 3),
                    "max_y_mm": round(box[4] * 1000.0, 3),
                    "max_z_mm": round(box[5] * 1000.0, 3),
                }
            results.append({
                "name": c.Name2,
                "path": c.GetPathName,
                "is_fixed": bool(c.IsFixed),
                "is_suppressed": bool(c.IsSuppressed),
                "bounding_box_mm": bbox,
            })

        return results

    def add_mate(
        self,
        mate_type: str,
        entity1: str,
        entity2: str,
        alignment: str = "aligned",
        flip: bool = False,
        distance_mm: float = 0.0,
        angle_deg: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Constrain two assembly entities with a physical mate.

        mate_type: 'coincident', 'concentric', 'perpendicular', 'parallel',
                   'tangent', 'distance', 'angle', or 'lock'.
        entity1: Named entity (e.g. 'Top Plane@part1-1') or coordinates ('FACE:0,20,0').
        entity2: Named entity (e.g. 'Top Plane@part2-1') or coordinates ('FACE:50,0,0').
        alignment: 'aligned' (0), 'anti_aligned' (1), or 'closest' (2).
        flip: True to reverse mate orientation.
        distance_mm: Distance offset in millimeters (for 'distance' mate).
        angle_deg: Angular offset in degrees (for 'angle' mate).
        """
        assy_doc = self.get_active_assembly()
        m_type_key = mate_type.strip().lower()
        if m_type_key not in MATE_TYPES:
            raise ValueError(
                f"Unsupported mate type '{mate_type}'. Valid options: {list(MATE_TYPES.keys())}"
            )

        align_key = alignment.strip().lower()
        if align_key not in ALIGN_TYPES:
            raise ValueError(
                f"Unsupported alignment '{alignment}'. Valid options: {list(ALIGN_TYPES.keys())}"
            )

        type_int = MATE_TYPES[m_type_key]
        align_int = ALIGN_TYPES[align_key]

        # Clear existing selections
        assy_doc.ClearSelection2(True)

        # Select Entity 1
        s1 = self._resolve_and_select_entity(assy_doc, entity1, mark=1)
        if not s1:
            raise InvalidSelectionError(f"Failed to find or select entity 1: '{entity1}'")

        # Select Entity 2
        s2 = self._resolve_and_select_entity(assy_doc, entity2, mark=1)
        if not s2:
            assy_doc.ClearSelection2(True)
            raise InvalidSelectionError(f"Failed to find or select entity 2: '{entity2}'")

        # Prepare AddMate5 parameters
        if type_int == 5 and distance_mm < 0:
            flip = not flip
        dist_m = mm_to_meters(abs(distance_mm)) if type_int == 5 else 0.0
        ang_rad = deg_to_radians(angle_deg) if type_int == 6 else 0.0
        dist_limit = dist_m if type_int == 5 else 0.0
        ang_limit = ang_rad if type_int == 6 else 0.0
        v_mate_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        # Execute AddMate5
        mate_feature = assy_doc.AddMate5(
            type_int,
            align_int,
            flip,
            dist_m,
            dist_limit, dist_limit,  # Distance limits (upper, lower)
            0.0, 0.0,                # Gear ratios
            ang_rad,
            ang_limit, ang_limit,    # Angle limits (upper, lower)
            False,                   # ForPositioningOnly
            False,                   # UseLimits
            0,                       # LockRotation
            v_mate_err
        )

        err_code = v_mate_err.value
        # In swAddMateError_e: 1 = swAddMateError_NoError
        if err_code != 1 or mate_feature is None:
            err_desc = ADD_MATE_ERRORS.get(err_code, f"Unknown error code {err_code}")
            assy_doc.ClearSelection2(True)
            raise FeatureCreationError(
                f"Failed creating {m_type_key.upper()} mate between '{entity1}' and '{entity2}': {err_desc}"
            )

        # Rebuild assembly to update kinematics and transform matrices
        assy_doc.ForceRebuild3(True)
        assy_doc.ClearSelection2(True)

        logger.info("Successfully added mate '%s' (%s).", mate_feature.Name, m_type_key)

        return {
            "mate_name": mate_feature.Name,
            "mate_type": m_type_key,
            "alignment": align_key,
            "distance_mm": distance_mm if type_int == 5 else 0.0,
            "angle_deg": angle_deg if type_int == 6 else 0.0,
            "status": "Created",
        }

    def check_interference(self, treat_coincidence_as_interference: bool = False) -> Dict[str, Any]:
        """
        Run Parasolid interference detection on the active assembly to verify kinematic clearance.
        treat_coincidence_as_interference: True to report coincident contacting faces as collisions.
        """
        assy_doc = self.get_active_assembly()
        id_mgr = assy_doc.InterferenceDetectionManager
        if id_mgr is None:
            raise SolidWorksError("Unable to initialize InterferenceDetectionManager for active assembly.")

        id_mgr.TreatCoincidenceAsInterference = bool(treat_coincidence_as_interference)
        interfs = id_mgr.GetInterferences

        results: List[Dict[str, Any]] = []
        total_vol_mm3 = 0.0

        for idx, item in enumerate(interfs or []):
            vol_m3 = float(getattr(item, "Volume", 0.0))
            vol_mm3 = round(vol_m3 * 1e9, 4)
            total_vol_mm3 += vol_mm3

            comps = getattr(item, "Components", None)
            comp_names = [c.Name2 for c in comps] if comps else []

            results.append({
                "interference_id": idx + 1,
                "volume_mm3": vol_mm3,
                "volume_cm3": round(vol_mm3 / 1000.0, 4),
                "components": comp_names,
            })

        id_mgr.Done()

        return {
            "has_interference": len(results) > 0,
            "interference_count": len(results),
            "total_interference_volume_mm3": round(total_vol_mm3, 4),
            "treat_coincidence_as_interference": treat_coincidence_as_interference,
            "interferences": results,
        }

    def set_component_fixed(self, component_name: str, fixed: bool = True) -> Dict[str, Any]:
        """Fix (ground) or float (unfix) a component in assembly space."""
        assy_doc = self.get_active_assembly()
        ext = assy_doc.Extension
        assy_title = assy_doc.GetTitle

        full_name = component_name
        if not full_name.endswith(f"@{assy_title}"):
            full_name = f"{full_name}@{assy_title}"

        assy_doc.ClearSelection2(True)
        sel_ok = self._safe_select(ext, full_name, "COMPONENT", append=False, mark=0)
        if not sel_ok:
            raise InvalidSelectionError(f"Could not select component: '{component_name}'")

        if fixed:
            assy_doc.FixComponent()
        else:
            assy_doc.UnfixComponent()

        assy_doc.ClearSelection2(True)
        return {
            "component": component_name,
            "name": component_name,
            "fixed": fixed,
            "is_fixed": fixed,
        }
