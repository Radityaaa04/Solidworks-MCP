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
