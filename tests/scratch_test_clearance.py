"""Check clearance with Z=40 for collar and Z=65 for shaft."""
import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")

def parse_tool_result(res):
    if res.is_error:
        return {"is_error": True, "error_message": res.content[0].text if res.content else "Unknown"}
    try:
        return json.loads(res.content[0].text)
    except Exception:
        return res.content[0].text

async def main():
    server_params = StdioServerParameters(
        command="uv", args=["run", "python", "-m", "sw_mcp.server"],
        cwd=PROJECT_ROOT, env={"PYTHONUNBUFFERED": "1"}
    )
    async with stdio_client(server_params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print("Connected.")

            housing_path = os.path.join(OUTPUT_DIR, "p3_pillow_housing.sldprt")
            shaft_path = os.path.join(OUTPUT_DIR, "p3_drive_shaft.sldprt")
            collar_path = os.path.join(OUTPUT_DIR, "p3_retaining_collar.sldprt")

            await s.call_tool("sw_new_assembly", {})
            await s.call_tool("sw_insert_component", {"component_path": housing_path, "x_mm": 0, "y_mm": 0, "z_mm": 0})
            await s.call_tool("sw_insert_component", {"component_path": shaft_path, "x_mm": 0, "y_mm": 150, "z_mm": 0})
            await s.call_tool("sw_insert_component", {"component_path": collar_path, "x_mm": 0, "y_mm": -150, "z_mm": 0})

            # Shaft Mates
            await s.call_tool("sw_add_mate", {"mate_type": "coincident", "entity1": "Top Plane@p3_pillow_housing-1", "entity2": "Top Plane@p3_drive_shaft-1"})
            await s.call_tool("sw_add_mate", {"mate_type": "coincident", "entity1": "Right Plane@p3_pillow_housing-1", "entity2": "Right Plane@p3_drive_shaft-1"})
            m3 = await s.call_tool("sw_add_mate", {"mate_type": "distance", "entity1": "Front Plane@p3_pillow_housing-1", "entity2": "Front Plane@p3_drive_shaft-1", "distance_mm": 65.0, "flip": False})
            print("Shaft dist mate:", parse_tool_result(m3))

            # Collar Mates
            await s.call_tool("sw_add_mate", {"mate_type": "coincident", "entity1": "Top Plane@p3_pillow_housing-1", "entity2": "Top Plane@p3_retaining_collar-1"})
            await s.call_tool("sw_add_mate", {"mate_type": "coincident", "entity1": "Right Plane@p3_pillow_housing-1", "entity2": "Right Plane@p3_retaining_collar-1"})
            m6 = await s.call_tool("sw_add_mate", {"mate_type": "distance", "entity1": "Front Plane@p3_pillow_housing-1", "entity2": "Front Plane@p3_retaining_collar-1", "distance_mm": 40.0, "flip": False})
            print("Collar dist mate:", parse_tool_result(m6))

            # Check Interference
            intf = await s.call_tool("sw_check_interference", {"treat_coincidence_as_interference": False})
            info = parse_tool_result(intf)
            print("Interference (flip=False):", info)

if __name__ == "__main__":
    asyncio.run(main())
