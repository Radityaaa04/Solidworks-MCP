"""Integration tests for MCP Server tool registration and schemas."""

import pytest
from sw_mcp.server import mcp


@pytest.mark.asyncio
async def test_all_tools_registered():
    tools = await mcp.list_tools()
    assert len(tools) >= 20

    tool_names = {t.name for t in tools}

    # Verify critical tool names exist
    expected = [
        "sw_get_session_info",
        "sw_new_part",
        "sw_open_doc",
        "sw_save_doc",
        "sw_export_cad",
        "sw_create_sketch_on_plane",
        "sw_draw_rectangle",
        "sw_draw_circle",
        "sw_boss_extrude",
        "sw_cut_extrude",
        "sw_get_equations",
        "sw_set_global_variable",
        "sw_modify_dimension",
        "sw_get_mass_properties",
        "sw_capture_viewport",
        "sw_set_material",
        "sw_get_material",
        "sw_list_materials",
        "sw_new_assembly",
        "sw_insert_component",
        "sw_add_mate",
        "sw_list_components",
        "sw_check_interference",
        "sw_set_component_fixed",
        "sw_new_drawing",
        "sw_create_drawing_view",
        "sw_create_standard_views",
        "sw_list_drawing_views",
        "sw_auto_dimension",
        "sw_add_drawing_note",
        "sw_export_drawing",
        "sw_create_section_view",
        "sw_circular_pattern",
        "sw_boss_sweep",
        "sw_cut_sweep",
        "sw_create_reference_plane",
        "sw_mirror_feature",
        "sw_create_3d_sketch",
        "sw_draw_3d_line",
        "sw_add_sketch_constraint",
        "sw_linear_pattern",
        "sw_shell",
        "sw_hole_wizard",
        "sw_loft_boss",
        "sw_insert_bom_table",
    ]
    assert len(tools) == 58
    for name in expected:
        assert name in tool_names, f"Expected tool {name} not found in registered tools"


@pytest.mark.asyncio
async def test_tool_descriptions_and_parameters():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description, f"Tool {tool.name} must have a description"
        assert tool.name.startswith("sw_"), f"Tool {tool.name} should adhere to naming convention"


def test_industrial_cad_domain_methods():
    """Unit test the 6 new industrial CAD methods (sketch constraints, linear pattern, shell, hole wizard, loft, BOM)."""
    import types
    from sw_mcp.cad.sketcher import SketchManager
    from sw_mcp.cad.features import FeatureManager
    from sw_mcp.cad.drawing import DrawingManager

    class DummyFeat:
        Name = "Feat1"
        GetTypeName2 = "MockFeature"
        GetErrorCode = 0

    class DummyExt:
        NewSelectData = object()

        def SelectByID2(self, *args, **kwargs):
            return True

    class DummySketchMgr:
        ActiveSketch = None

        def InsertSketch(self, val):
            pass

    class DummyFeatMgr:
        def FeatureLinearPattern4(self, *args):
            return DummyFeat()

        def HoleWizard5(self, *args):
            return DummyFeat()

        def InsertProtrusionBlend2(self, *args):
            return DummyFeat()

    class DummyView:
        GetName2 = "Drawing View1"
        GetNextView = None

        def InsertBomTable4(self, *args):
            return types.SimpleNamespace(Name="Bill of Materials1")

    class DummyDoc:
        GetType = 3
        GetTitle = "Drawing1"
        Extension = DummyExt()
        SketchManager = DummySketchMgr()
        FeatureManager = DummyFeatMgr()
        GetFirstView = DummyView()

        def ClearSelection2(self, all_sel):
            pass

        def SelectByID(self, *args):
            return True

        def SketchAddConstraints(self, cid):
            self.last_constraint = cid

        def InsertFeatureShell(self, thick, outward):
            self.last_shell = (thick, outward)

    doc = DummyDoc()
    doc_mgr = types.SimpleNamespace(get_active_doc=lambda: doc)

    sk_mgr = SketchManager(doc_mgr)
    res_c = sk_mgr.add_sketch_constraint("tangent", x1_mm=10.0, y1_mm=20.0, x2_mm=15.0, y2_mm=25.0)
    assert res_c["applied"] is True
    assert res_c["sw_constant"] == "sgTANGENT"

    f_mgr = FeatureManager(doc_mgr)
    res_lp = f_mgr.linear_pattern("Cut-Extrude1", spacing1_mm=25.0, instances1=4)
    assert res_lp["created"] is True
    assert res_lp["instances1"] == 4

    res_sh = f_mgr.shell(thickness_mm=2.5, face_x_mm=0.0, face_y_mm=0.0, face_z_mm=10.0)
    assert res_sh["created"] is True
    assert res_sh["thickness_mm"] == 2.5

    res_hw = f_mgr.hole_wizard(hole_type="tapped", standard="ISO", fastener_size="M6", diameter_mm=6.0, depth_mm=12.0)
    assert res_hw["created"] is True
    assert res_hw["fastener_size"] == "M6"

    res_loft = f_mgr.loft_boss("Sketch1", "Sketch2")
    assert res_loft["created"] is True

    d_mgr = DrawingManager(doc_mgr)
    res_bom = d_mgr.insert_bom_table("Drawing View1", x_mm=180.0, y_mm=40.0, bom_type="parts_only")
    assert res_bom["status"] == "created"
    assert res_bom["bom_type"] == "parts_only"
