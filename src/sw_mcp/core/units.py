"""Unit conversion and normalisation middleware for SolidWorks API.

SolidWorks COM API handles dimensions internally in SI Base Units:
- Length: Meters (m)
- Angle: Radians (rad)
- Mass: Kilograms (kg)
- Time: Seconds (s)

This module handles transparent, bidirectional conversions between user-facing units
(typically millimeters, degrees, grams) and SolidWorks internal SI representations.
"""

import math
from typing import Dict, Any


def mm_to_meters(val_mm: float) -> float:
    """Convert millimeters to meters (SI base unit for length)."""
    return float(val_mm) / 1000.0


def meters_to_mm(val_m: float) -> float:
    """Convert meters to millimeters."""
    return float(val_m) * 1000.0


def deg_to_radians(val_deg: float) -> float:
    """Convert degrees to radians (SI base unit for angles)."""
    return math.radians(float(val_deg))


def radians_to_deg(val_rad: float) -> float:
    """Convert radians to degrees."""
    return math.degrees(float(val_rad))


def kg_to_grams(val_kg: float) -> float:
    """Convert kilograms to grams."""
    return float(val_kg) * 1000.0


def format_equation_string(name: str, value: float, unit: str = "mm") -> str:
    """
    Format a SolidWorks Equation Manager string with explicit unit safety.
    Example: name='Thickness', value=12.5, unit='mm' -> '"Thickness" = 12.5mm'
    """
    if not name or not str(name).strip():
        raise ValueError("Equation variable name cannot be empty or whitespace.")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"Equation value cannot be NaN or Infinite: {value}")
    clean_name = str(name).strip().replace('"', "")
    if not clean_name:
        raise ValueError("Equation variable name cannot be empty.")
    return f'"{clean_name}" = {value}{unit}'


def convert_mass_properties(raw_props: list[float]) -> Dict[str, Any]:
    """
    Parse the 12-element or 18-element raw array returned by IModelDocExtension::GetMassProperties2.
    
    Standard SolidWorks mass property array indices:
    [0] Center of mass X (meters)
    [1] Center of mass Y (meters)
    [2] Center of mass Z (meters)
    [3] Volume (meters^3)
    [4] Surface Area (meters^2)
    [5] Mass (kg)
    [6..14] Moments of inertia at center of mass
    """
    if not raw_props or len(raw_props) < 6:
        return {"error": "Invalid mass properties array"}

    for idx in range(6):
        val = raw_props[idx]
        if not isinstance(val, (int, float)) or not math.isfinite(val):
            return {"error": f"Invalid nonfinite mass property at index {idx}: {val}"}

    com_x_mm = meters_to_mm(raw_props[0])
    com_y_mm = meters_to_mm(raw_props[1])
    com_z_mm = meters_to_mm(raw_props[2])
    
    # 1 m^3 = 1,000,000,000 mm^3 = 1,000,000 cm^3
    volume_m3 = raw_props[3]
    volume_mm3 = volume_m3 * 1e9
    volume_cm3 = volume_m3 * 1e6
    
    # 1 m^2 = 1,000,000 mm^2
    surface_area_m2 = raw_props[4]
    surface_area_mm2 = surface_area_m2 * 1e6
    
    mass_kg = raw_props[5]
    mass_grams = kg_to_grams(mass_kg)

    return {
        "mass_kg": round(mass_kg, 6),
        "mass_g": round(mass_grams, 3),
        "volume_mm3": round(volume_mm3, 3),
        "volume_cm3": round(volume_cm3, 3),
        "surface_area_mm2": round(surface_area_mm2, 3),
        "center_of_mass_mm": {
            "x": round(com_x_mm, 4),
            "y": round(com_y_mm, 4),
            "z": round(com_z_mm, 4),
        },
    }


def _call_or_prop(obj: Any, attr_name: str, *args: Any) -> Any:
    """Safely read a COM attribute that may be exposed as either a property or a method."""
    attr = getattr(obj, attr_name, None)
    if attr is None:
        return None
    if callable(attr):
        return attr(*args)
    return attr


def _closest_point_on_segment(
    px: float, py: float, pz: float,
    x1: float, y1: float, z1: float,
    x2: float, y2: float, z2: float,
) -> tuple[float, float, float]:
    """Compute the closest point on 3D segment (x1,y1,z1)-(x2,y2,z2) to (px,py,pz)."""
    dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
    seg_len_sq = dx * dx + dy * dy + dz * dz
    if seg_len_sq <= 1e-18:
        return (x1, y1, z1)
    t = ((px - x1) * dx + (py - y1) * dy + (pz - z1) * dz) / seg_len_sq
    t = max(0.0, min(1.0, t))
    return (x1 + t * dx, y1 + t * dy, z1 + t * dz)


def select_brep_entity_by_point(
    doc: Any,
    entity_type: str,
    x_m: float,
    y_m: float,
    z_m: float,
    append: bool = False,
    mark: int = 0,
    tol_m: float = 0.002,
) -> bool:
    """
    Camera/viewport-independent B-Rep topological selector.
    Traverses solid bodies (IBody2) to find the closest EDGE, FACE, or VERTEX
    to (x_m, y_m, z_m) in meters within tolerance tol_m, then selects it directly
    via IEntity.Select4 / Select2.
    """
    ent_kind = entity_type.strip().upper()
    if ent_kind not in ("EDGE", "FACE", "VERTEX"):
        return False

    body_pairs: list[tuple[Any, tuple[float, float, float]]] = []
    try:
        get_bodies = getattr(doc, "GetBodies2", None)
        if callable(get_bodies):
            bodies = get_bodies(0, False) or []
            for b in bodies:
                if b is not None:
                    body_pairs.append((b, (x_m, y_m, z_m)))
    except Exception:
        pass

    if not body_pairs:
        try:
            get_comps = getattr(doc, "GetComponents", None)
            if callable(get_comps):
                comps = get_comps(False) or []
                for comp in comps:
                    if comp is None or getattr(comp, "IsSuppressed", False):
                        continue
                    lx, ly, lz = x_m, y_m, z_m
                    try:
                        xf = _call_or_prop(comp, "Transform2")
                        arr = _call_or_prop(xf, "ArrayData") if xf is not None else None
                        if arr and len(arr) >= 12:
                            tx, ty, tz = float(arr[9]), float(arr[10]), float(arr[11])
                            dx, dy, dz = x_m - tx, y_m - ty, z_m - tz
                            # Inverse rotation R^T * (p - T)
                            lx = float(arr[0]) * dx + float(arr[3]) * dy + float(arr[6]) * dz
                            ly = float(arr[1]) * dx + float(arr[4]) * dy + float(arr[7]) * dz
                            lz = float(arr[2]) * dx + float(arr[5]) * dy + float(arr[8]) * dz
                    except Exception:
                        pass
                    cbodies = []
                    try:
                        gb3 = getattr(comp, "GetBodies3", None)
                        if callable(gb3):
                            cbodies = gb3(0, None) or []
                    except Exception:
                        pass
                    if not cbodies:
                        try:
                            b_single = _call_or_prop(comp, "GetBody")
                            if b_single is not None:
                                cbodies = [b_single]
                        except Exception:
                            pass
                    for cb in cbodies:
                        if cb is not None:
                            body_pairs.append((cb, (lx, ly, lz)))
        except Exception:
            pass

    if not body_pairs:
        return False

    best_entity: Any = None
    best_dist: float = float("inf")

    for body, (lx, ly, lz) in body_pairs:
        if ent_kind == "EDGE":
            try:
                edges = _call_or_prop(body, "GetEdges") or []
            except Exception:
                edges = []
            for edge in edges:
                if edge is None:
                    continue
                pt = None
                try:
                    cpo = getattr(edge, "GetClosestPointOn", None)
                    if callable(cpo):
                        pt = cpo(lx, ly, lz)
                except Exception:
                    pt = None
                if not pt or len(pt) < 3:
                    try:
                        curve = _call_or_prop(edge, "GetCurve")
                        if curve is not None:
                            cpo_c = getattr(curve, "GetClosestPointOn", None)
                            if callable(cpo_c):
                                pt = cpo_c(lx, ly, lz)
                    except Exception:
                        pt = None
                if not pt or len(pt) < 3:
                    try:
                        verts = _call_or_prop(edge, "GetTwoEndVertices")
                        if verts and len(verts) >= 2 and verts[0] is not None and verts[1] is not None:
                            p0 = _call_or_prop(verts[0], "GetPoint")
                            p1 = _call_or_prop(verts[1], "GetPoint")
                            if p0 and p1 and len(p0) >= 3 and len(p1) >= 3:
                                pt = _closest_point_on_segment(
                                    lx, ly, lz,
                                    float(p0[0]), float(p0[1]), float(p0[2]),
                                    float(p1[0]), float(p1[1]), float(p1[2]),
                                )
                    except Exception:
                        pt = None
                if pt and len(pt) >= 3:
                    dist = math.hypot(float(pt[0]) - lx, float(pt[1]) - ly, float(pt[2]) - lz)
                    if dist < best_dist:
                        best_dist = dist
                        best_entity = edge

        elif ent_kind == "FACE":
            try:
                faces = _call_or_prop(body, "GetFaces") or []
            except Exception:
                faces = []
            for face in faces:
                if face is None:
                    continue
                pt = None
                try:
                    cpo = getattr(face, "GetClosestPointOn", None)
                    if callable(cpo):
                        pt = cpo(lx, ly, lz)
                except Exception:
                    pt = None
                if not pt or len(pt) < 3:
                    try:
                        surf = _call_or_prop(face, "GetSurface")
                        if surf is not None:
                            cpo_s = getattr(surf, "GetClosestPointOn", None)
                            if callable(cpo_s):
                                pt = cpo_s(lx, ly, lz)
                    except Exception:
                        pt = None
                if pt and len(pt) >= 3:
                    dist = math.hypot(float(pt[0]) - lx, float(pt[1]) - ly, float(pt[2]) - lz)
                    if dist < best_dist:
                        best_dist = dist
                        best_entity = face

        elif ent_kind == "VERTEX":
            try:
                edges = _call_or_prop(body, "GetEdges") or []
            except Exception:
                edges = []
            for edge in edges:
                if edge is None:
                    continue
                try:
                    verts = _call_or_prop(edge, "GetTwoEndVertices") or []
                except Exception:
                    verts = []
                for v in verts:
                    if v is None:
                        continue
                    try:
                        pt = _call_or_prop(v, "GetPoint")
                        if pt and len(pt) >= 3:
                            dist = math.hypot(float(pt[0]) - lx, float(pt[1]) - ly, float(pt[2]) - lz)
                            if dist < best_dist:
                                best_dist = dist
                                best_entity = v
                    except Exception:
                        pass

    if best_entity is None or best_dist > tol_m:
        return False

    # Select the discovered B-Rep entity directly without camera raycasting
    ext = getattr(doc, "Extension", None)
    sel_data = None
    if ext is not None:
        try:
            csd = getattr(ext, "CreateSelectData", None)
            if callable(csd):
                sel_data = csd()
            else:
                sel_data = getattr(ext, "NewSelectData", None)
                if callable(sel_data):
                    sel_data = sel_data()
            if sel_data is not None and mark:
                try:
                    sel_data.Mark = int(mark)
                except Exception:
                    pass
        except Exception:
            sel_data = None

    try:
        sel4 = getattr(best_entity, "Select4", None)
        if callable(sel4):
            if sel4(bool(append), sel_data):
                return True
    except Exception:
        pass

    try:
        sel2 = getattr(best_entity, "Select2", None)
        if callable(sel2):
            if sel2(bool(append), int(mark)):
                return True
    except Exception:
        pass

    return False
