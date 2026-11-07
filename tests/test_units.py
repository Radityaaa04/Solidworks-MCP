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
    select_brep_entity_by_point,
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


def test_select_brep_entity_by_point_occluded_edge_and_face():
    """Verify B-Rep closest-point selection succeeds even when viewport SelectByID would fail."""
    class DummyEntity:
        def __init__(self, pt):
            self._pt = pt
            self.selected_with = None

        def GetClosestPointOn(self, x, y, z):
            return self._pt

        def Select4(self, append, sel_data):
            self.selected_with = (append, getattr(sel_data, "Mark", 0))
            return True

    occluded_edge = DummyEntity((0.0, 0.0, 0.010))
    far_edge = DummyEntity((0.050, 0.030, 0.020))
    planar_face = DummyEntity((0.025, 0.015, 0.020))

    class DummyBody:
        def GetEdges(self):
            return [far_edge, occluded_edge]

        def GetFaces(self):
            return [planar_face]

    class DummySelectData:
        def __init__(self):
            self.Mark = 0

    class DummyExt:
        def CreateSelectData(self):
            return DummySelectData()

    class DummyDoc:
        Extension = DummyExt()

        def GetBodies2(self, body_type, visible_only):
            return [DummyBody()]

    doc = DummyDoc()
    assert select_brep_entity_by_point(doc, "EDGE", 0.0, 0.0, 0.010, append=False, mark=1) is True
    assert occluded_edge.selected_with == (False, 1)
    assert far_edge.selected_with is None

    assert select_brep_entity_by_point(doc, "FACE", 0.025, 0.015, 0.020, append=True, mark=2) is True
    assert planar_face.selected_with == (True, 2)

    # Out-of-tolerance point should be rejected
    assert select_brep_entity_by_point(doc, "EDGE", 0.5, 0.5, 0.5) is False
