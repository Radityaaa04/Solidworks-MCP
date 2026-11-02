"""3D Feature operations for SolidWorks.

Supports Boss-Extrude, Cut-Extrude, Fillets, Chamfers, and Rebuild
with transaction safeguards (active sketch exit & corrupt feature deletion).
"""

import logging
import math
from typing import Any, Dict, List, Optional

import pythoncom
import win32com.client
from sw_mcp.cad.document import DocumentManager
from sw_mcp.core.exceptions import CADRebuildError, FeatureCreationError
from sw_mcp.core.units import deg_to_radians, mm_to_meters

logger = logging.getLogger("sw_mcp.cad.features")


class FeatureManager:
    """Manages 3D CAD features (extrude, cut, fillet, chamfer) on the active part."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def _rollback_feature(self, doc: Any, feat: Any, feat_name: str, err_code: int) -> None:
        """
        Safely roll back a newly created feature that reported an error code.
        Ensures doc.EditDelete is ONLY called if the feature is successfully selected.
        Verifies that EditDelete returns True before claiming the feature was rolled back.
        """
        try:
            if doc.SketchManager.ActiveSketch is not None:
                doc.SketchManager.InsertSketch(True)
        except Exception:
            pass

        selected = False
        try:
            sel_res = feat.Select2(False, 0)
            selected = bool(sel_res) if sel_res is not None else False
        except Exception as sel_err:
            logger.warning("Failed to select corrupt feature %s for deletion: %s", feat_name, sel_err)
            selected = False

        if not selected:
            raise FeatureCreationError(
                f"{feat_name} generated with error code {err_code}; selection failed so deletion was aborted to prevent deleting unrelated geometry."
            )

        deleted = False
        try:
            del_res = doc.EditDelete()
            deleted = bool(del_res) if del_res is not None else False
        except Exception as del_err:
            logger.warning("EditDelete failed for corrupt feature %s: %s", feat_name, del_err)
            deleted = False

        if not deleted:
            raise FeatureCreationError(
                f"{feat_name} generated with error code {err_code}; deletion returned False (deletion failed)."
            )

        raise FeatureCreationError(
            f"{feat_name} generated with error code {err_code}; rolled back."
        )

    def boss_extrude(self, depth_mm: float, flip_dir: bool = False) -> Dict[str, Any]:
        """
        Extrude the active sketch into a 3D solid boss/base.
        depth_mm: Extrusion thickness in millimeters.
        flip_dir: True to extrude in reverse direction.
        """
        if not (isinstance(depth_mm, (int, float)) and math.isfinite(depth_mm) and depth_mm > 0):
            raise ValueError(f"Extrusion depth must be strictly positive and finite (> 0 mm), got {depth_mm}.")
        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        depth_m = mm_to_meters(depth_mm)

        # FeatureExtrusion3 expects 23 positional arguments:
        # Sd, Flip, Dir, T1, T2, D1, D2, Dchk1, Dchk2, Ddir1, Ddir2, Dang1, Dang2,
        # OffsetRev1, OffsetRev2, TranslateSurf1, TranslateSurf2, Merge, UseFeatScope,
        # UseAutoSelect, T0, StartOffset, FlipStartOffset
        try:
            feat = feat_mgr.FeatureExtrusion3(
                True,       # Sd: Single-ended
                False,      # Flip
                flip_dir,   # Dir: Flip direction
                0,          # T1: swEndCondBlind = 0
                0,          # T2
                depth_m,    # D1: Depth in meters
                0.0,        # D2
                False,      # Dchk1: Draft outward
                False,      # Dchk2
                False,      # Ddir1: Draft direction
                False,      # Ddir2
                0.0,        # Dang1: Draft angle
                0.0,        # Dang2
                False,      # OffsetRev1
                False,      # OffsetRev2
                False,      # TranslateSurface1
                False,      # TranslateSurface2
                True,       # Merge results
                True,       # UseFeatScope
                True,       # UseAutoSelect
                0,          # T0: swStartSketchPlane = 0
                0.0,        # StartOffset
                False       # FlipStartOffset
            )
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if feat is None:
            # Safe rollback: Exit sketch mode if still active, without deleting prior sketches
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Boss-Extrude of {depth_mm}mm failed. Check sketch continuity and profile closure.")

        # Check for corrupt feature error codes (0 = no error)
        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Boss-Extrude", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "depth_mm": depth_mm,
            "created": True,
        }

    def cut_extrude(self, depth_mm: float, flip_dir: bool = False) -> Dict[str, Any]:
        """
        Perform a blind cut-extrude removing material using the active sketch.
        depth_mm: Cut depth in millimeters.
        """
        if not (isinstance(depth_mm, (int, float)) and math.isfinite(depth_mm) and depth_mm > 0):
            raise ValueError(f"Cut extrusion depth must be strictly positive and finite (> 0 mm), got {depth_mm}.")
        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        depth_m = mm_to_meters(depth_mm)

        try:
            feat = feat_mgr.FeatureCut4(
                True,       # Sd: Single-ended
                False,      # Flip
                flip_dir,   # Dir
                0,          # T1: Blind (0 or 1 depending on version, 0 = swEndCondBlind)
                0,          # T2
                depth_m,    # D1: Depth in meters
                0.0,        # D2
                False, False, False, False, 0.0, 0.0, # Draft options
                False, False, False, False,           # Offset options
                False,      # NormalCut
                True,       # UseFeatScope
                True,       # UseAutoSelect
                False,      # AssemblyFeatureScope
                True,       # AutoSelectComponents
                False,      # PropagateFeatureToParts
                0,          # T0: Start condition
                0.0,        # StartOffset
                False,      # FlipStartOffset
                False       # OptimizeGeometry
            )
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if feat is None:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Cut-Extrude of {depth_mm}mm failed.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Cut-Extrude", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "depth_mm": depth_mm,
            "created": True,
        }

    def fillet(
        self,
        radius_mm: float,
        edge_x_mm: Optional[float] = None,
        edge_y_mm: Optional[float] = None,
        edge_z_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Add a constant-radius fillet to currently selected edges/faces, or to the edge at given 3D coordinates.
        radius_mm: Fillet radius in millimeters.
        edge_x_mm, edge_y_mm, edge_z_mm: Optional 3D point in millimeters to select target edge.
        """
        if not (isinstance(radius_mm, (int, float)) and math.isfinite(radius_mm) and radius_mm > 0):
            raise ValueError(f"Fillet radius must be strictly positive and finite (> 0 mm), got {radius_mm}.")

        has_x = edge_x_mm is not None
        has_y = edge_y_mm is not None
        has_z = edge_z_mm is not None
        if (has_x or has_y or has_z) and not (has_x and has_y and has_z):
            raise ValueError("All three edge coordinates (edge_x_mm, edge_y_mm, edge_z_mm) must be provided together.")
        if has_x and has_y and has_z:
            for coord_val, coord_name in [(edge_x_mm, "edge_x_mm"), (edge_y_mm, "edge_y_mm"), (edge_z_mm, "edge_z_mm")]:
                if not (isinstance(coord_val, (int, float)) and math.isfinite(coord_val)):
                    raise ValueError(f"{coord_name} must be finite, got {coord_val}")

        doc = self.doc_mgr.get_active_doc()

        if edge_x_mm is not None and edge_y_mm is not None and edge_z_mm is not None:
            doc.ClearSelection2(True)
            ex = mm_to_meters(edge_x_mm)
            ey = mm_to_meters(edge_y_mm)
            ez = mm_to_meters(edge_z_mm)
            sel_ok = doc.SelectByID("", "EDGE", ex, ey, ez)
            if not sel_ok:
                raise FeatureCreationError(f"Could not select edge at ({edge_x_mm}, {edge_y_mm}, {edge_z_mm}) mm for fillet.")

        feat_mgr = doc.FeatureManager
        radius_m = mm_to_meters(radius_mm)

        # Options: 1 = swFeatureFilletPropagate, 2 = swFeatureFilletAttachEdges
        fillet_options = 1 | 2

        try:
            feat = feat_mgr.FeatureFillet(
                fillet_options,
                radius_m,
                0,  # Constant radius (swFeatureFilletType_Simple)
                0,  # Overflow type default
                None,
                None,
                None,
            )
        except Exception:
            raise

        if feat is None:
            raise FeatureCreationError(f"Fillet of radius {radius_mm}mm failed. Ensure edges or faces are selected.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Fillet", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "radius_mm": radius_mm,
            "created": True,
        }

    def chamfer(
        self,
        distance_mm: float,
        angle_deg: float = 45.0,
        edge_x_mm: Optional[float] = None,
        edge_y_mm: Optional[float] = None,
        edge_z_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Add a chamfer to currently selected edges/faces, or to the edge at given 3D coordinates.
        distance_mm: Chamfer distance/width in millimeters.
        angle_deg: Chamfer angle in degrees (default 45.0°).
        edge_x_mm, edge_y_mm, edge_z_mm: Optional 3D point in millimeters to select target edge.
        """
        if not (isinstance(distance_mm, (int, float)) and math.isfinite(distance_mm) and distance_mm > 0):
            raise ValueError(f"Chamfer distance must be strictly positive and finite (> 0 mm), got {distance_mm}.")
        if not (isinstance(angle_deg, (int, float)) and math.isfinite(angle_deg) and 0 < angle_deg < 90):
            raise ValueError(f"Chamfer angle must be finite between 0 and 90 degrees, got {angle_deg}.")

        has_x = edge_x_mm is not None
        has_y = edge_y_mm is not None
        has_z = edge_z_mm is not None
        if (has_x or has_y or has_z) and not (has_x and has_y and has_z):
            raise ValueError("All three edge coordinates (edge_x_mm, edge_y_mm, edge_z_mm) must be provided together.")
        if has_x and has_y and has_z:
            for coord_val, coord_name in [(edge_x_mm, "edge_x_mm"), (edge_y_mm, "edge_y_mm"), (edge_z_mm, "edge_z_mm")]:
                if not (isinstance(coord_val, (int, float)) and math.isfinite(coord_val)):
                    raise ValueError(f"{coord_name} must be finite, got {coord_val}")

        doc = self.doc_mgr.get_active_doc()

        if edge_x_mm is not None and edge_y_mm is not None and edge_z_mm is not None:
            doc.ClearSelection2(True)
            ex = mm_to_meters(edge_x_mm)
            ey = mm_to_meters(edge_y_mm)
            ez = mm_to_meters(edge_z_mm)
            sel_ok = doc.SelectByID("", "EDGE", ex, ey, ez)
            if not sel_ok:
                raise FeatureCreationError(f"Could not select edge at ({edge_x_mm}, {edge_y_mm}, {edge_z_mm}) mm for chamfer.")

        feat_mgr = doc.FeatureManager
        dist_m = mm_to_meters(distance_mm)
        angle_rad = deg_to_radians(angle_deg)

        try:
            feat = feat_mgr.InsertFeatureChamfer(
                4,          # swFeatureChamferEqualDistance or angle-distance (4 = angle/distance)
                1,          # Edge/face option
                dist_m,     # Distance in meters
                angle_rad,  # Angle in radians
                0, 0, 0, 0, 0, 0, 0, 0, 0, 0
            )
        except Exception:
            raise

        if feat is None:
            raise FeatureCreationError(f"Chamfer of {distance_mm}mm @ {angle_deg}° failed. Ensure edges or faces are selected.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Chamfer", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "distance_mm": distance_mm,
            "angle_deg": angle_deg,
            "created": True,
        }

    def revolve_boss(self, angle_deg: float = 360.0, reverse_dir: bool = False) -> Dict[str, Any]:
        """
        Revolve the active sketch profile around its centerline into a 3D solid boss.
        angle_deg: Angle of revolution in degrees (default 360.0° for full rotation).
        reverse_dir: True to reverse rotation direction.
        """
        if not (isinstance(angle_deg, (int, float)) and math.isfinite(angle_deg) and 0 < angle_deg <= 360.0):
            raise ValueError(f"Revolve angle must be in range (0, 360] degrees, got {angle_deg}°.")

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        angle_rad = deg_to_radians(angle_deg)

        # FeatureRevolve2:
        # SingleDir, IsSolid, IsThin, IsCut, ReverseDir, BothDirectionUpToSameEntity,
        # Dir1Type, Dir2Type, Dir1Angle, Dir2Angle, OffsetReverse1, OffsetReverse2,
        # OffsetDistance1, OffsetDistance2, ThinType, ThinThickness1, ThinThickness2,
        # Merge, UseFeatScope, UseAutoSelect
        try:
            feat = feat_mgr.FeatureRevolve2(
                True,        # SingleDir
                True,        # IsSolid
                False,       # IsThin
                False,       # IsCut: False (Boss)
                reverse_dir, # ReverseDir
                False,       # BothDirectionUpToSameEntity
                0,           # Dir1Type: swEndCondBlind = 0
                0,           # Dir2Type
                angle_rad,   # Dir1Angle
                0.0,         # Dir2Angle
                False,       # OffsetReverse1
                False,       # OffsetReverse2
                0.0,         # OffsetDistance1
                0.0,         # OffsetDistance2
                0,           # ThinType
                0.0,         # ThinThickness1
                0.0,         # ThinThickness2
                True,        # Merge
                True,        # UseFeatScope
                True         # UseAutoSelect
            )
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if feat is None:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Revolve-Boss of {angle_deg}° failed. Ensure the sketch has a closed profile and a valid centerline axis.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Revolve-Boss", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "angle_deg": angle_deg,
            "created": True,
        }

    def revolve_cut(self, angle_deg: float = 360.0, reverse_dir: bool = False) -> Dict[str, Any]:
        """
        Revolve the active sketch profile around its centerline to cut and remove material from the solid body.
        angle_deg: Angle of revolution in degrees (default 360.0°).
        reverse_dir: True to reverse direction.
        """
        if not (isinstance(angle_deg, (int, float)) and math.isfinite(angle_deg) and 0 < angle_deg <= 360.0):
            raise ValueError(f"Revolve-Cut angle must be in range (0, 360] degrees, got {angle_deg}°.")

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        angle_rad = deg_to_radians(angle_deg)

        try:
            feat = feat_mgr.FeatureRevolve2(
                True,        # SingleDir
                True,        # IsSolid
                False,       # IsThin
                True,        # IsCut: True (Cut)
                reverse_dir, # ReverseDir
                False,       # BothDirectionUpToSameEntity
                0,           # Dir1Type: swEndCondBlind = 0
                0,           # Dir2Type
                angle_rad,   # Dir1Angle
                0.0,         # Dir2Angle
                False,       # OffsetReverse1
                False,       # OffsetReverse2
                0.0,         # OffsetDistance1
                0.0,         # OffsetDistance2
                0,           # ThinType
                0.0,         # ThinThickness1
                0.0,         # ThinThickness2
                True,        # Merge
                True,        # UseFeatScope
                True         # UseAutoSelect
            )
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if feat is None:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Revolve-Cut of {angle_deg}° failed. Ensure the sketch has a closed profile and a valid centerline axis.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Revolve-Cut", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "angle_deg": angle_deg,
            "created": True,
        }

    def rebuild(self) -> Dict[str, Any]:
        """Force a full rebuild of the active model and check for errors."""
        doc = self.doc_mgr.get_active_doc()
        res = doc.EditRebuild3
        if not res:
            raise CADRebuildError("Rebuild reported errors in the model geometry.")
        return {"rebuilt": True}

    def circular_pattern(
        self,
        feature_name: str,
        total_instances: int = 6,
        total_angle_deg: float = 360.0,
        equal_spacing: bool = True,
        axis_coord_mm: Optional[List[float]] = None,
        axis_entity_name: str = "",
        flip_dir: bool = False,
    ) -> Dict[str, Any]:
        """
        Pattern a 3D feature circularly around a rotation axis or cylindrical face.

        feature_name: Name of the feature to pattern (e.g. 'Cut-Extrude1', 'Boss-Extrude2').
        total_instances: Number of patterned instances (including original).
        total_angle_deg: Total sweep angle in degrees (default 360.0°).
        equal_spacing: If True, distributes instances equally across total_angle_deg.
        axis_coord_mm: Optional [X, Y, Z] coordinate on the cylindrical face or axis to select.
        axis_entity_name: Optional name of axis entity (e.g. 'Axis1', or empty for coordinate/auto).
        flip_dir: True to reverse rotation direction.
        """
        if not feature_name or not str(feature_name).strip():
            raise ValueError("feature_name is required for circular pattern.")
        if not (isinstance(total_instances, int) and not isinstance(total_instances, bool) and total_instances >= 2):
            raise ValueError(f"total_instances must be an integer >= 2, got {total_instances}")
        if not (isinstance(total_angle_deg, (int, float)) and math.isfinite(total_angle_deg) and total_angle_deg > 0):
            raise ValueError(f"total_angle_deg must be positive and finite, got {total_angle_deg}")
        if axis_coord_mm is not None:
            if not (isinstance(axis_coord_mm, (list, tuple)) and len(axis_coord_mm) == 3 and all(isinstance(c, (int, float)) and math.isfinite(c) for c in axis_coord_mm)):
                raise ValueError(f"axis_coord_mm must be a list/tuple of 3 finite numbers, got {axis_coord_mm}")

        doc = self.doc_mgr.get_active_doc()
        ext = doc.Extension
        feat_mgr = doc.FeatureManager
        v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

        doc.ClearSelection2(True)

        # 1. Select rotation axis / cylindrical reference (Mark 1)
        axis_selected = False
        if axis_entity_name:
            axis_selected = ext.SelectByID2(axis_entity_name, "AXIS", 0.0, 0.0, 0.0, False, 1, v_call, 0)
        elif axis_coord_mm and len(axis_coord_mm) == 3:
            xm = mm_to_meters(axis_coord_mm[0])
            ym = mm_to_meters(axis_coord_mm[1])
            zm = mm_to_meters(axis_coord_mm[2])
            axis_selected = ext.SelectByID2("", "FACE", xm, ym, zm, False, 1, v_call, 0)

        # Fallback: find cylindrical face on the model
        if not axis_selected:
            part = doc
            try:
                bodies = part.GetBodies2(0, False)
                if bodies:
                    for b in bodies:
                        faces = b.GetFaces
                        if faces:
                            for f in faces:
                                surf = f.GetSurface
                                if getattr(surf, "IsCylinder", False):
                                    axis_selected = f.Select4(False, ext.NewSelectData)
                                    # Update mark to 1
                                    ext.SelectByID2("", "FACE", 0.0, 0.0, 0.0, False, 1, v_call, 0)
                                    break
                                if axis_selected:
                                    break
                        if axis_selected:
                            break
            except Exception as e:
                logger.debug("Automatic axis discovery fallback: %s", e)

        if not axis_selected:
            # Try selecting Top Plane or Front Plane as datum axis fallback
            axis_selected = ext.SelectByID2("Top Plane", "PLANE", 0.0, 0.0, 0.0, False, 1, v_call, 0)

        # 2. Select feature to pattern (Mark 4)
        feat_selected = ext.SelectByID2(feature_name, "BODYFEATURE", 0.0, 0.0, 0.0, True, 4, v_call, 0)
        if not feat_selected:
            raise FeatureCreationError(f"Could not select feature '{feature_name}' for circular pattern.")

        angle_rad = deg_to_radians(total_angle_deg)
        spacing_rad = angle_rad if equal_spacing else angle_rad / max(1, total_instances - 1)

        try:
            pat_feat = feat_mgr.FeatureCircularPattern4(
                total_instances,
                spacing_rad,
                flip_dir,
                "",
                False,
                equal_spacing,
                False,
            )
        except Exception:
            raise

        if not pat_feat:
            raise FeatureCreationError(
                f"Failed to create circular pattern for feature '{feature_name}'. "
                "Ensure a valid rotational axis or cylindrical face was provided."
            )

        err_code = pat_feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, pat_feat, "Circular pattern", err_code)

        return {
            "feature": pat_feat.Name,
            "type": pat_feat.GetTypeName2,
            "total_instances": total_instances,
            "total_angle_deg": total_angle_deg,
            "source_feature": feature_name,
            "created": True,
        }

    def boss_sweep(
        self,
        path_sketch_name: str = "",
        profile_sketch_name: str = "",
        circular_profile_diameter_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create a 3D Swept Boss feature along a trajectory path.

        path_sketch_name: Name of the 2D/3D sketch defining the sweep trajectory.
        profile_sketch_name: Name of the sketch defining the cross-section profile.
        circular_profile_diameter_mm: Diameter in mm for automatic circular profile sweep.
        """
        if circular_profile_diameter_mm is not None:
            if not (isinstance(circular_profile_diameter_mm, (int, float)) and math.isfinite(circular_profile_diameter_mm) and circular_profile_diameter_mm > 0):
                raise ValueError(f"circular_profile_diameter_mm must be strictly positive and finite (> 0 mm), got {circular_profile_diameter_mm}")

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager

        # Ensure active sketch is closed if currently in sketch mode
        if doc.SketchManager.ActiveSketch is not None:
            doc.SketchManager.InsertSketch(True)

        # swFmSweep = 17
        sweep_data = feat_mgr.CreateDefinition(17)
        if not sweep_data:
            raise FeatureCreationError("Failed to initialize ISweepFeatureData (swFmSweep = 17).")

        # Resolve path feature
        def _find_sketch_feature(target_name: str = ""):
            feat = doc.FirstFeature
            found = None
            while feat:
                t = feat.GetTypeName2.lower()
                n = feat.Name
                if target_name:
                    if n.lower() == target_name.lower():
                        return feat
                    # Match Sketch suffix if prefixed
                    if target_name.lower() in n.lower():
                        found = feat
                else:
                    if "profilefeature" in t or "sketch" in t or "sketch" in n.lower():
                        found = feat
                feat = feat.GetNextFeature
            return found

        path_feat = _find_sketch_feature(path_sketch_name) if path_sketch_name else _find_sketch_feature()
        if not path_feat:
            # Fallback: try doc.FeatureByName
            if path_sketch_name:
                path_feat = doc.FeatureByName(path_sketch_name)
        if not path_feat:
            raise FeatureCreationError(f"Could not locate trajectory path sketch '{path_sketch_name}'.")

        sweep_data.Path = path_feat

        if circular_profile_diameter_mm is not None:
            if not (isinstance(circular_profile_diameter_mm, (int, float)) and math.isfinite(circular_profile_diameter_mm) and circular_profile_diameter_mm > 0):
                raise ValueError(f"circular_profile_diameter_mm must be positive and finite, got {circular_profile_diameter_mm}")
            sweep_data.CircularProfile = True
            sweep_data.CircularProfileDiameter = mm_to_meters(circular_profile_diameter_mm)
        else:
            if not profile_sketch_name:
                raise ValueError("Either profile_sketch_name or circular_profile_diameter_mm must be specified.")
            prof_feat = _find_sketch_feature(profile_sketch_name)
            if not prof_feat:
                prof_feat = doc.FeatureByName(profile_sketch_name)
            if not prof_feat:
                raise FeatureCreationError(f"Could not locate profile sketch '{profile_sketch_name}'.")
            sweep_data.CircularProfile = False
            sweep_data.Profile = prof_feat

        try:
            feat = feat_mgr.CreateFeature(sweep_data)
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if not feat:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Swept Boss creation failed along path '{path_sketch_name}'.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Swept Boss", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "path_sketch": path_sketch_name,
            "created": True,
        }

    def cut_sweep(
        self,
        path_sketch_name: str = "",
        profile_sketch_name: str = "",
        circular_profile_diameter_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create a 3D Swept Cut feature removing material along a trajectory path.

        path_sketch_name: Name of the 2D/3D sketch defining the sweep trajectory.
        profile_sketch_name: Name of the sketch defining the cross-section profile.
        circular_profile_diameter_mm: Diameter in mm for automatic circular profile cut sweep.
        """
        if circular_profile_diameter_mm is not None:
            if not (isinstance(circular_profile_diameter_mm, (int, float)) and math.isfinite(circular_profile_diameter_mm) and circular_profile_diameter_mm > 0):
                raise ValueError(f"circular_profile_diameter_mm must be strictly positive and finite (> 0 mm), got {circular_profile_diameter_mm}")

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager

        if doc.SketchManager.ActiveSketch is not None:
            doc.SketchManager.InsertSketch(True)

        # swFmSweepCut = 18
        sweep_data = feat_mgr.CreateDefinition(18)
        if not sweep_data:
            raise FeatureCreationError("Failed to initialize ISweepFeatureData (swFmSweepCut = 18).")

        # Resolve path feature
        def _find_sketch_feature(target_name: str = ""):
            feat = doc.FirstFeature
            found = None
            while feat:
                t = feat.GetTypeName2.lower()
                n = feat.Name
                if target_name:
                    if n.lower() == target_name.lower():
                        return feat
                    if target_name.lower() in n.lower():
                        found = feat
                else:
                    if "profilefeature" in t or "sketch" in t or "sketch" in n.lower():
                        found = feat
                feat = feat.GetNextFeature
            return found

        path_feat = _find_sketch_feature(path_sketch_name) if path_sketch_name else _find_sketch_feature()
        if not path_feat:
            if path_sketch_name:
                path_feat = doc.FeatureByName(path_sketch_name)
        if not path_feat:
            raise FeatureCreationError(f"Could not locate trajectory path sketch '{path_sketch_name}'.")

        sweep_data.Path = path_feat

        if circular_profile_diameter_mm is not None:
            if not (isinstance(circular_profile_diameter_mm, (int, float)) and math.isfinite(circular_profile_diameter_mm) and circular_profile_diameter_mm > 0):
                raise ValueError(f"circular_profile_diameter_mm must be positive and finite, got {circular_profile_diameter_mm}")
            sweep_data.CircularProfile = True
            sweep_data.CircularProfileDiameter = mm_to_meters(circular_profile_diameter_mm)
        else:
            if not profile_sketch_name:
                raise ValueError("Either profile_sketch_name or circular_profile_diameter_mm must be specified.")
            prof_feat = _find_sketch_feature(profile_sketch_name)
            if not prof_feat:
                prof_feat = doc.FeatureByName(profile_sketch_name)
            if not prof_feat:
                raise FeatureCreationError(f"Could not locate profile sketch '{profile_sketch_name}'.")
            sweep_data.CircularProfile = False
            sweep_data.Profile = prof_feat

        try:
            feat = feat_mgr.CreateFeature(sweep_data)
        except Exception:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise

        if not feat:
            if doc.SketchManager.ActiveSketch is not None:
                try:
                    doc.SketchManager.InsertSketch(True)
                except Exception:
                    pass
            raise FeatureCreationError(f"Swept Cut creation failed along path '{path_sketch_name}'.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Swept Cut", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "path_sketch": path_sketch_name,
            "created": True,
        }

    def create_reference_plane(
        self,
        plane_name: str = "",
        first_reference: str = "Front Plane",
        constraint_type: str = "distance",
        distance_mm: float = 0.0,
        angle_deg: float = 0.0,
        second_reference: str = "",
        flip: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new datum Reference Plane in the active part or assembly.

        plane_name: Optional custom name for the new reference plane.
        first_reference: Name of the first reference plane, planar face, or axis.
        constraint_type: 'distance', 'angle', 'coincident', 'parallel', or 'perpendicular'.
        distance_mm: Offset distance in millimeters (used when constraint_type='distance').
        angle_deg: Angle in degrees (used when constraint_type='angle').
        second_reference: Optional secondary reference (e.g. axis of rotation or second plane).
        flip: Whether to invert the direction/offset of the plane.
        """
        for val, name in [(distance_mm, "distance_mm"), (angle_deg, "angle_deg")]:
            if not (isinstance(val, (int, float)) and math.isfinite(val)):
                raise ValueError(f"{name} must be finite, got {val}")

        constraint_map = {
            "perpendicular": 1,
            "parallel": 2,
            "coincident": 4,
            "distance": 8,
            "angle": 16,
        }
        ctype = constraint_type.lower().strip()
        if ctype not in constraint_map:
            raise ValueError(f"Invalid constraint_type '{constraint_type}'. Must be one of {list(constraint_map.keys())}")

        c1 = constraint_map[ctype]
        if ctype == "distance":
            dist_m = mm_to_meters(distance_mm)
            val1 = -dist_m if flip else dist_m
        elif ctype == "angle":
            ang_rad = deg_to_radians(angle_deg)
            val1 = -ang_rad if flip else ang_rad
        else:
            val1 = 0.0

        c2 = 0
        val2 = 0.0

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        ext = doc.Extension
        v_call = ext.NewSelectData

        doc.ClearSelection2(True)

        # Select first reference with mark 1
        sel1 = ext.SelectByID2(first_reference, "PLANE", 0.0, 0.0, 0.0, False, 1, v_call, 0)
        if not sel1:
            sel1 = ext.SelectByID2(first_reference, "FACE", 0.0, 0.0, 0.0, False, 1, v_call, 0)
        if not sel1:
            sel1 = ext.SelectByID2(first_reference, "", 0.0, 0.0, 0.0, False, 1, v_call, 0)

        if not sel1:
            raise FeatureCreationError(f"Could not select first reference '{first_reference}' for reference plane.")

        if second_reference:
            sel2 = ext.SelectByID2(second_reference, "AXIS", 0.0, 0.0, 0.0, True, 2, v_call, 0)
            if not sel2:
                sel2 = ext.SelectByID2(second_reference, "EDGE", 0.0, 0.0, 0.0, True, 2, v_call, 0)
            if not sel2:
                sel2 = ext.SelectByID2(second_reference, "PLANE", 0.0, 0.0, 0.0, True, 2, v_call, 0)
            if not sel2:
                sel2 = ext.SelectByID2(second_reference, "", 0.0, 0.0, 0.0, True, 2, v_call, 0)
            if not sel2:
                raise FeatureCreationError(f"Could not select second reference '{second_reference}' for reference plane.")
            c2 = 4 if ctype == "angle" else 0

        try:
            feat = feat_mgr.InsertRefPlane(c1, val1, c2, val2, 0, 0.0)
        except Exception:
            raise

        if not feat:
            raise FeatureCreationError(f"Failed to create reference plane from '{first_reference}'.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Reference Plane", err_code)

        if plane_name:
            try:
                feat.Name = plane_name
            except Exception as e:
                logger.debug("Renaming reference plane: %s", e)

        return {
            "created": True,
            "name": feat.Name,
            "constraint_type": ctype,
            "first_reference": first_reference,
        }

    def mirror_feature(
        self,
        plane_name: str,
        feature_name: str = "",
        mirror_body: bool = False,
        geometry_pattern: bool = False,
    ) -> Dict[str, Any]:
        """
        Mirror 3D features or solid bodies across a datum plane or planar face.

        plane_name: Name of the mirror plane or planar face (e.g. 'Front Plane', 'RefPlane1').
        feature_name: Name of the feature or solid body to mirror.
        mirror_body: If True, mirrors entire solid body; if False, mirrors specific feature.
        geometry_pattern: If True, creates geometry pattern only without re-solving end conditions.
        """
        if not plane_name or not plane_name.strip():
            raise ValueError("plane_name is required for mirror operation.")

        doc = self.doc_mgr.get_active_doc()
        feat_mgr = doc.FeatureManager
        ext = doc.Extension
        v_call = ext.NewSelectData

        doc.ClearSelection2(True)

        # 1. Select mirror plane with Mark = 2
        sel_plane = ext.SelectByID2(plane_name, "PLANE", 0.0, 0.0, 0.0, False, 2, v_call, 0)
        if not sel_plane:
            sel_plane = ext.SelectByID2(plane_name, "FACE", 0.0, 0.0, 0.0, False, 2, v_call, 0)
        if not sel_plane:
            raise FeatureCreationError(f"Could not select mirror plane '{plane_name}'.")

        # 2. Select feature (Mark = 1) or body (Mark = 256)
        if mirror_body:
            sel_body = ext.SelectByID2(feature_name or "", "SOLIDBODY", 0.0, 0.0, 0.0, True, 256, v_call, 0)
            if not sel_body and not feature_name:
                try:
                    bodies = doc.GetBodies2(0, False)
                    if bodies and len(bodies) > 0:
                        sel_body = bodies[0].Select4(True, v_call)
                except Exception:
                    pass
            if not sel_body:
                raise FeatureCreationError(f"Could not select solid body '{feature_name}' to mirror.")
        else:
            if not feature_name or not feature_name.strip():
                raise ValueError("feature_name is required when mirror_body is False.")
            sel_feat = ext.SelectByID2(feature_name, "BODYFEATURE", 0.0, 0.0, 0.0, True, 1, v_call, 0)
            if not sel_feat:
                sel_feat = ext.SelectByID2(feature_name, "FEATURE", 0.0, 0.0, 0.0, True, 1, v_call, 0)
            if not sel_feat:
                sel_feat = ext.SelectByID2(feature_name, "", 0.0, 0.0, 0.0, True, 1, v_call, 0)
            if not sel_feat:
                raise FeatureCreationError(f"Could not select feature '{feature_name}' to mirror.")

        try:
            feat = feat_mgr.InsertMirrorFeature2(mirror_body, geometry_pattern, False, False, 0)
        except Exception:
            raise

        if not feat:
            raise FeatureCreationError(f"Failed to create mirror feature for '{feature_name}' across '{plane_name}'.")

        err_code = feat.GetErrorCode
        if err_code != 0:
            self._rollback_feature(doc, feat, "Mirror", err_code)

        return {
            "feature": feat.Name,
            "type": feat.GetTypeName2,
            "plane": plane_name,
            "mirrored_feature": feature_name,
            "mirror_body": mirror_body,
            "created": True,
        }
