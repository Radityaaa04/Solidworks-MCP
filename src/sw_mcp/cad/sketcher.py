"""2D Sketching operations for SolidWorks.

Handles reference plane selection, 2D geometry generation (lines, rectangles, circles, arcs),
and unit normalization from millimeters to internal SI meters.
"""

import logging
import math
from typing import Any, Dict, Optional

from sw_mcp.cad.document import DocumentManager
from sw_mcp.core.exceptions import FeatureCreationError
from sw_mcp.core.units import deg_to_radians, mm_to_meters

logger = logging.getLogger("sw_mcp.cad.sketcher")


class SketchManager:
    """Manages 2D sketching workflows on planes and planar faces."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def select_plane(self, plane_name: str = "Front Plane") -> bool:
        """
        Select a reference plane by name with multi-language and tree-index fallback.
        Standard names: 'Front Plane', 'Top Plane', 'Right Plane'.
        Rejects unknown plane names instead of silently falling back to Front Plane.
        """
        doc = self.doc_mgr.get_active_doc()
        doc.ClearSelection2(True)

        # 1. Try direct selection by requested name via SelectByID
        try:
            if doc.SelectByID(plane_name, "PLANE", 0.0, 0.0, 0.0):
                return True
        except Exception:
            pass

        # 2. Multi-lingual dictionary lookup only for recognized plane families
        standard_planes = {
            "front": ["Front Plane", "Ebene vorne", "Plan de face", "Plano alzado", "Plano Frontal", "前视基准面"],
            "top": ["Top Plane", "Ebene oben", "Plan de dessus", "Plano de planta", "Plano Superior", "上视基准面"],
            "right": ["Right Plane", "Ebene rechts", "Plan de droite", "Plano de vista lateral", "Plano Direito", "右视基准面"],
        }

        low = plane_name.lower().strip()
        key = None
        if any(x in low for x in ["front", "vorne", "face", "alzado", "frontal", "前视"]):
            key = "front"
        elif any(x in low for x in ["top", "oben", "dessus", "planta", "superior", "上视"]):
            key = "top"
        elif any(x in low for x in ["right", "rechts", "droite", "lateral", "direito", "右视"]):
            key = "right"

        if key is None:
            # Not a recognized standard plane; do not silently fall back to Front Plane
            return False

        for alt_name in standard_planes[key]:
            try:
                if doc.SelectByID(alt_name, "PLANE", 0.0, 0.0, 0.0):
                    return True
            except Exception:
                pass

        # 3. Fallback: Iterate feature tree to find first 3 RefPlane features
        feat = doc.FirstFeature
        plane_count = 0
        target_index = {"front": 0, "top": 1, "right": 2}[key]

        while feat is not None:
            if feat.GetTypeName2 == "RefPlane":
                if plane_count == target_index:
                    return feat.Select2(False, 0)
                plane_count += 1
            feat = feat.GetNextFeature

        return False

    def create_sketch(self, plane_name: str = "Front Plane") -> Dict[str, Any]:
        """Select plane and enter sketch creation mode."""
        doc = self.doc_mgr.get_active_doc()
        if not self.select_plane(plane_name):
            raise FeatureCreationError(f"Could not locate or select plane: {plane_name}")

        # InsertSketch(True) enters sketch mode
        doc.SketchManager.InsertSketch(True)
        active_sketch = doc.SketchManager.ActiveSketch
        if active_sketch is None:
            raise FeatureCreationError(f"Failed to activate sketch on plane: {plane_name}")

        return {
            "sketch_active": True,
            "plane": plane_name,
        }

    def create_sketch_on_face(self, x_mm: float, y_mm: float, z_mm: float) -> Dict[str, Any]:
        """
        Select a planar face on an existing solid body by a 3D coordinate point and activate sketch mode.
        x_mm, y_mm, z_mm: Coordinates in millimeters of a point lying on the target face.
        """
        for c, name in [(x_mm, "x_mm"), (y_mm, "y_mm"), (z_mm, "z_mm")]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Face coordinate {name} must be finite, got {c}")

        doc = self.doc_mgr.get_active_doc()
        doc.ClearSelection2(True)

        xm = mm_to_meters(x_mm)
        ym = mm_to_meters(y_mm)
        zm = mm_to_meters(z_mm)

        selected = doc.SelectByID("", "FACE", xm, ym, zm)
        if not selected:
            raise FeatureCreationError(f"Could not locate or select a planar face at coordinates ({x_mm}, {y_mm}, {z_mm}) mm.")

        # Validate that the selected face is planar
        try:
            sel_mgr = doc.SelectionManager
            face = sel_mgr.GetSelectedObject6(1, -1)
            if face is not None:
                surf = face.GetSurface
                if surf is not None and not surf.IsPlane:
                    doc.ClearSelection2(True)
                    raise FeatureCreationError(
                        f"Selected face at ({x_mm}, {y_mm}, {z_mm}) mm is non-planar (curved/cylindrical). "
                        "2D sketches require a strictly planar face."
                    )
        except FeatureCreationError:
            raise
        except Exception as e:
            logger.debug("Could not verify face planarity via SelectionManager: %s", e)

        doc.SketchManager.InsertSketch(True)
        active_sketch = doc.SketchManager.ActiveSketch
        if active_sketch is None:
            raise FeatureCreationError(f"Failed to activate sketch on face at ({x_mm}, {y_mm}, {z_mm}) mm.")

        return {
            "sketch_active": True,
            "target_face_point_mm": [x_mm, y_mm, z_mm],
        }

    def close_sketch(self) -> Dict[str, Any]:
        """Exit the current sketch mode."""
        doc = self.doc_mgr.get_active_doc()
        if doc.SketchManager.ActiveSketch is not None:
            doc.SketchManager.InsertSketch(True)
        return {"sketch_active": False}

    def create_3d_sketch(self) -> Dict[str, Any]:
        """
        Create and activate an unconstrained 3D Sketch in the active document.
        Used for Phase 0 Master Kinematic Skeletons, layout wireframes, and 3D curve paths.
        """
        doc = self.doc_mgr.get_active_doc()
        doc.ClearSelection2(True)
        doc.SketchManager.Insert3DSketch(True)
        self._active_sketch = True
        return {"sketch_active": True, "sketch_type": "3D"}

    def draw_line(self, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """Draw a 2D line segment between two points (in millimeters)."""
        for c in [x1_mm, y1_mm, x2_mm, y2_mm]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Coordinate must be finite, got {c}")
        if x1_mm == x2_mm and y1_mm == y2_mm:
            raise ValueError(f"Line segment must have distinct start and end points: ({x1_mm}, {y1_mm}).")

        doc = self.doc_mgr.get_active_doc()
        x1 = mm_to_meters(x1_mm)
        y1 = mm_to_meters(y1_mm)
        x2 = mm_to_meters(x2_mm)
        y2 = mm_to_meters(y2_mm)

        line = doc.SketchManager.CreateLine(x1, y1, 0.0, x2, y2, 0.0)
        if line is None:
            raise FeatureCreationError("Failed to draw line segment")

        return {
            "entity": "line",
            "start_mm": [x1_mm, y1_mm],
            "end_mm": [x2_mm, y2_mm],
        }

    def draw_rectangle(self, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """Draw a 2D corner-to-corner rectangle (in millimeters)."""
        for c in [x1_mm, y1_mm, x2_mm, y2_mm]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Coordinate must be finite, got {c}")
        if x1_mm == x2_mm or y1_mm == y2_mm:
            raise ValueError(f"Corner rectangle cannot have zero width or height: ({x1_mm}, {y1_mm}) to ({x2_mm}, {y2_mm}).")

        doc = self.doc_mgr.get_active_doc()
        x1 = mm_to_meters(x1_mm)
        y1 = mm_to_meters(y1_mm)
        x2 = mm_to_meters(x2_mm)
        y2 = mm_to_meters(y2_mm)

        # CreateCornerRectangle parameters: X1, Y1, Z1, X2, Y2, Z2
        rect = doc.SketchManager.CreateCornerRectangle(x1, y1, 0.0, x2, y2, 0.0)
        if rect is None:
            raise FeatureCreationError("Failed to create corner rectangle")

        width_mm = abs(x2_mm - x1_mm)
        height_mm = abs(y2_mm - y1_mm)
        return {
            "entity": "rectangle",
            "corner1_mm": [x1_mm, y1_mm],
            "corner2_mm": [x2_mm, y2_mm],
            "width_mm": width_mm,
            "height_mm": height_mm,
        }

    def draw_circle(self, center_x_mm: float, center_y_mm: float, radius_mm: float) -> Dict[str, Any]:
        """Draw a 2D circle with given center point and radius (in millimeters)."""
        for c in [center_x_mm, center_y_mm]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Center coordinate must be finite, got {c}")
        if not (isinstance(radius_mm, (int, float)) and math.isfinite(radius_mm) and radius_mm > 0):
            raise ValueError(f"Circle radius must be strictly positive and finite (> 0 mm), got {radius_mm} mm.")

        doc = self.doc_mgr.get_active_doc()
        cx = mm_to_meters(center_x_mm)
        cy = mm_to_meters(center_y_mm)
        r = mm_to_meters(radius_mm)

        # CreateCircleByRadius parameters: CenterX, CenterY, CenterZ, Radius
        circle = doc.SketchManager.CreateCircleByRadius(cx, cy, 0.0, r)
        if circle is None:
            raise FeatureCreationError("Failed to draw circle")

        return {
            "entity": "circle",
            "center_mm": [center_x_mm, center_y_mm],
            "radius_mm": radius_mm,
            "diameter_mm": radius_mm * 2,
        }

    def draw_centerline(self, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """Draw a 2D centerline / construction line between two points in millimeters."""
        for c in [x1_mm, y1_mm, x2_mm, y2_mm]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Coordinate must be finite, got {c}")
        if x1_mm == x2_mm and y1_mm == y2_mm:
            raise ValueError(f"Centerline must have distinct start and end points: ({x1_mm}, {y1_mm}).")

        doc = self.doc_mgr.get_active_doc()
        x1 = mm_to_meters(x1_mm)
        y1 = mm_to_meters(y1_mm)
        x2 = mm_to_meters(x2_mm)
        y2 = mm_to_meters(y2_mm)

        cl = doc.SketchManager.CreateCenterLine(x1, y1, 0.0, x2, y2, 0.0)
        if cl is None:
            raise FeatureCreationError("Failed to draw centerline segment")

        return {
            "entity": "centerline",
            "start_mm": [x1_mm, y1_mm],
            "end_mm": [x2_mm, y2_mm],
        }

    def draw_arc(self, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float, x3_mm: float, y3_mm: float) -> Dict[str, Any]:
        """
        Draw a 2D 3-point arc from start point (x1, y1) to end point (x2, y2) passing through (x3, y3).
        All coordinates in millimeters.
        """
        for c in [x1_mm, y1_mm, x2_mm, y2_mm, x3_mm, y3_mm]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Coordinate must be finite, got {c}")

        p1 = (x1_mm, y1_mm)
        p2 = (x2_mm, y2_mm)
        p3 = (x3_mm, y3_mm)
        if p1 == p2 or p1 == p3 or p2 == p3:
            raise ValueError(f"3-point arc must have distinct points: ({x1_mm}, {y1_mm}), ({x2_mm}, {y2_mm}), ({x3_mm}, {y3_mm}).")

        cross = (x2_mm - x1_mm) * (y3_mm - y1_mm) - (y2_mm - y1_mm) * (x3_mm - x1_mm)
        if abs(cross) < 1e-9:
            raise ValueError(f"3-point arc points cannot be collinear: ({x1_mm}, {y1_mm}), ({x2_mm}, {y2_mm}), ({x3_mm}, {y3_mm}).")

        doc = self.doc_mgr.get_active_doc()
        x1 = mm_to_meters(x1_mm)
        y1 = mm_to_meters(y1_mm)
        x2 = mm_to_meters(x2_mm)
        y2 = mm_to_meters(y2_mm)
        x3 = mm_to_meters(x3_mm)
        y3 = mm_to_meters(y3_mm)

        arc = doc.SketchManager.Create3PointArc(x1, y1, 0.0, x2, y2, 0.0, x3, y3, 0.0)
        if arc is None:
            raise FeatureCreationError("Failed to draw 3-point arc")

        return {
            "entity": "arc",
            "start_mm": [x1_mm, y1_mm],
            "end_mm": [x2_mm, y2_mm],
            "through_mm": [x3_mm, y3_mm],
        }

    def draw_3d_line(
        self,
        x1_mm: float,
        y1_mm: float,
        z1_mm: float,
        x2_mm: float,
        y2_mm: float,
        z2_mm: float,
    ) -> Dict[str, Any]:
        """
        Draw a 3D line segment between two spatial coordinates in millimeters within an active 3D sketch.
        """
        for c, name in [
            (x1_mm, "x1_mm"), (y1_mm, "y1_mm"), (z1_mm, "z1_mm"),
            (x2_mm, "x2_mm"), (y2_mm, "y2_mm"), (z2_mm, "z2_mm"),
        ]:
            if not (isinstance(c, (int, float)) and math.isfinite(c)):
                raise ValueError(f"Coordinate {name} must be finite, got {c}")

        length_sq = (x2_mm - x1_mm) ** 2 + (y2_mm - y1_mm) ** 2 + (z2_mm - z1_mm) ** 2
        if length_sq < 1e-12:
            raise ValueError(
                f"3D line segment must have distinct start and end points: "
                f"({x1_mm}, {y1_mm}, {z1_mm}) to ({x2_mm}, {y2_mm}, {z2_mm})."
            )

        doc = self.doc_mgr.get_active_doc()
        x1m, y1m, z1m = mm_to_meters(x1_mm), mm_to_meters(y1_mm), mm_to_meters(z1_mm)
        x2m, y2m, z2m = mm_to_meters(x2_mm), mm_to_meters(y2_mm), mm_to_meters(z2_mm)

        seg = doc.SketchManager.CreateLine(x1m, y1m, z1m, x2m, y2m, z2m)
        if not seg:
            raise FeatureCreationError("Failed to create 3D line segment. Ensure a 3D sketch is active.")

        length_mm = math.sqrt(length_sq)
        return {
            "type": "Line3D",
            "start_mm": [x1_mm, y1_mm, z1_mm],
            "end_mm": [x2_mm, y2_mm, z2_mm],
            "length_mm": round(length_mm, 4),
        }
