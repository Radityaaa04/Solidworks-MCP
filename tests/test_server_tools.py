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
    ]
    for name in expected:
        assert name in tool_names, f"Expected tool {name} not found in registered tools"


@pytest.mark.asyncio
async def test_tool_descriptions_and_parameters():
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description, f"Tool {tool.name} must have a description"
        assert tool.name.startswith("sw_"), f"Tool {tool.name} should adhere to naming convention"
