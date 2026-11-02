"""Test creating Housing part in isolation."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")


def parse_tool_result(res):
    if res.is_error:
        err_msg = res.content[0].text if res.content else "Unknown error"
        return {"is_error": True, "error_message": err_msg}
    if not res.content:
        return {}
    try:
        return json.loads(res.content[0].text)
    except Exception:
        return res.content[0].text


async def main():
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT,
        env={"PYTHONUNBUFFERED": "1"},
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Connected.")

            # New Part
            p_res = await session.call_tool("sw_new_part", {})
            print("New Part:", parse_tool_result(p_res))

            # Base flange (160 x 80 x 20 mm)
            print("Creating Base Flange...")
            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
            await session.call_tool("sw_draw_rectangle", {"x1_mm": -80.0, "y1_mm": 0.0, "x2_mm": 80.0, "y2_mm": 80.0})
            b1 = await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0})
            print("Base Flange Extruded:", parse_tool_result(b1))

            # Pedestal
            print("Creating Pedestal...")
            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
            await session.call_tool("sw_draw_rectangle", {"x1_mm": -40.0, "y1_mm": 0.0, "x2_mm": 40.0, "y2_mm": 80.0})
            b2 = await session.call_tool("sw_boss_extrude", {"depth_mm": 80.0})
            print("Pedestal Extruded:", parse_tool_result(b2))

            # Bearing Bore
            print("Cutting Bearing Bore...")
            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 20.0})
            c1 = await session.call_tool("sw_cut_extrude", {"depth_mm": 80.0, "flip_dir": False})
            print("Bore Cut:", parse_tool_result(c1))

            # Material
            print("Assigning Material...")
            m_res = await session.call_tool("sw_set_material", {
                "material_name": "Cast Alloy Steel",
                "database_name": "SolidWorks Materials"
            })
            print("Material:", parse_tool_result(m_res))

            # Save
            path = os.path.join(OUTPUT_DIR, "p3_pillow_housing.sldprt")
            s_res = await session.call_tool("sw_save_doc", {"output_path": path})
            print("Saved:", parse_tool_result(s_res))

            # Mass properties
            mass_res = await session.call_tool("sw_get_mass_properties", {})
            print("Mass properties:", parse_tool_result(mass_res))
            print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
