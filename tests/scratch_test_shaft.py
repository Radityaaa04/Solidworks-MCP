"""Test creating Shaft in isolation."""
import asyncio
import json
import os

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

            p_res = await session.call_tool("sw_new_part", {})
            print("New Part:", parse_tool_result(p_res))

            # Main journal: Dia 40 mm x 120 mm
            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Front Plane"})
            await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 50.0, "radius_mm": 20.0})
            b1 = await session.call_tool("sw_boss_extrude", {"depth_mm": 120.0, "flip_dir": False})
            print("Journal Extruded:", parse_tool_result(b1))

            mass = await session.call_tool("sw_get_mass_properties", {})
            m_info = parse_tool_result(mass)
            print("Journal Mass:", m_info)
            cg = m_info.get("center_of_mass_mm", {})
            print("CG:", cg)

            # Test face selection at Z = 120 vs Z = -120 based on CG
            z_face = 120.0 if cg.get("z", 0) > 0 else -120.0
            print(f"Sketching on Face at (0, 50, {z_face})...")
            sk = await session.call_tool("sw_create_sketch_on_face", {"x_mm": 0.0, "y_mm": 50.0, "z_mm": z_face})
            print("Sketch on Face result:", parse_tool_result(sk))

            await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 30.0})
            b2 = await session.call_tool("sw_boss_extrude", {"depth_mm": 20.0, "flip_dir": False})
            print("Shoulder Extruded:", parse_tool_result(b2))

            print("Done Shaft Test!")


if __name__ == "__main__":
    asyncio.run(main())
