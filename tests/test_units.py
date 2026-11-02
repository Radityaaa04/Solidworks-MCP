"""Unit tests for units.py conversion module."""

import pytest
from sw_mcp.core.units import (
    mm_to_meters,
    meters_to_mm,
    deg_to_radians,
    radians_to_deg,
    kg_to_grams,
    format_equation_string,
    convert_mass_properties,
)


def test_length_conversions():
    assert mm_to_meters(100.0) == pytest.approx(0.1)
    assert mm_to_meters(25.4) == pytest.approx(0.0254)
    assert meters_to_mm(0.05) == pytest.approx(50.0)


def test_angle_conversions():
    assert deg_to_radians(90.0) == pytest.approx(1.57079632679)
    assert radians_to_deg(3.14159265359) == pytest.approx(180.0)


def test_mass_conversions():
    assert kg_to_grams(2.5) == pytest.approx(2500.0)


def test_equation_string_formatting():
    eq1 = format_equation_string("D1@Sketch1", 50.0, "mm")
    assert eq1 == '"D1@Sketch1" = 50.0mm'

    eq2 = format_equation_string('"Thickness"', 12.0, "mm")
    assert eq2 == '"Thickness" = 12.0mm'


def test_convert_mass_properties():
    # Mock SolidWorks raw mass array:
    # [CoM_X, CoM_Y, CoM_Z, Volume_m3, SurfaceArea_m2, Mass_kg, ...]
    raw = [0.025, 0.015, 0.010, 0.00003, 0.0062, 0.234] + [0.0] * 12
    result = convert_mass_properties(raw)

    assert result["mass_kg"] == pytest.approx(0.234)
    assert result["mass_g"] == pytest.approx(234.0)
    assert result["volume_mm3"] == pytest.approx(30000.0)
    assert result["surface_area_mm2"] == pytest.approx(6200.0)
    assert result["center_of_mass_mm"]["x"] == pytest.approx(25.0)
    assert result["center_of_mass_mm"]["y"] == pytest.approx(15.0)
    assert result["center_of_mass_mm"]["z"] == pytest.approx(10.0)
