"""Scratch script to verify SolidWorks COM behavior with AssemblyManager."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "tests", "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)


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
            print("Connected to MCP server.")

            # 1. Create Part A (Cube 50x50x50 at origin)
            print("\nCreating Part A...")
            res = await session.call_tool("sw_new_part", {})
            print("sw_new_part:", parse_tool_result(res))

            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
            await session.call_tool("sw_draw_rectangle", {"x1_mm": -25.0, "y1_mm": -25.0, "x2_mm": 25.0, "y2_mm": 25.0})
            await session.call_tool("sw_boss_extrude", {"depth_mm": 50.0})
            
            part_a_path = os.path.join(OUTPUT_DIR, "part_a.sldprt")
            save_res = await session.call_tool("sw_save_doc", {"file_path": part_a_path})
            print("Saved Part A:", parse_tool_result(save_res))

            # 2. Create Part B (Cylinder dia 30, length 80)
            print("\nCreating Part B...")
            res = await session.call_tool("sw_new_part", {})
            print("sw_new_part:", parse_tool_result(res))

            await session.call_tool("sw_create_sketch_on_plane", {"plane_name": "Top Plane"})
            await session.call_tool("sw_draw_circle", {"center_x_mm": 0.0, "center_y_mm": 0.0, "radius_mm": 15.0})
            await session.call_tool("sw_boss_extrude", {"depth_mm": 80.0})

            part_b_path = os.path.join(OUTPUT_DIR, "part_b.sldprt")
            save_res = await session.call_tool("sw_save_doc", {"file_path": part_b_path})
            print("Saved Part B:", parse_tool_result(save_res))

            # 3. Create Assembly
            print("\nCreating Assembly...")
            assy_res = await session.call_tool("sw_new_assembly", {})
            print("sw_new_assembly:", parse_tool_result(assy_res))

            # 4. Insert Part A
            print("\nInserting Part A...")
            ins_a = await session.call_tool("sw_insert_component", {
                "component_path": part_a_path,
                "x_mm": 0, "y_mm": 0, "z_mm": 0
            })
            print("Inserted Part A:", parse_tool_result(ins_a))

            # 5. Insert Part B
            print("\nInserting Part B (offset in X)...")
            ins_b = await session.call_tool("sw_insert_component", {
                "component_path": part_b_path,
                "x_mm": 100, "y_mm": 0, "z_mm": 0
            })
            print("Inserted Part B:", parse_tool_result(ins_b))

            # 6. List components
            print("\nListing components...")
            list_res = await session.call_tool("sw_list_components", {})
            print("List components:", parse_tool_result(list_res))

            # 7. Test Mating
            # Mate Front Plane of Part A to Front Plane of Part B
            print("\nAdding Coincident Mate between Front Planes...")
            mate_res = await session.call_tool("sw_add_mate", {
                "mate_type": "coincident",
                "entity1": "Front Plane@part_a-1",
                "entity2": "Front Plane@part_b-1"
            })
            print("Mate Front Plane:", parse_tool_result(mate_res))

            # Mate Distance between Right Planes: 60mm
            print("\nAdding Distance Mate between Right Planes (60mm)...")
            dist_res = await session.call_tool("sw_add_mate", {
                "mate_type": "distance",
                "entity1": "Right Plane@part_a-1",
                "entity2": "Right Plane@part_b-1",
                "distance_mm": 60.0
            })
            print("Mate Right Plane (Distance 60mm):", parse_tool_result(dist_res))

            # Mate Coincident between Top Planes
            print("\nAdding Coincident Mate between Top Planes...")
            top_res = await session.call_tool("sw_add_mate", {
                "mate_type": "coincident",
                "entity1": "Top Plane@part_a-1",
                "entity2": "Top Plane@part_b-1"
            })
            print("Mate Top Plane:", parse_tool_result(top_res))

            # 8. Check Interference (Non-colliding: center distance is 60mm, Part A half width = 25mm, Part B radius = 15mm, gap = 20mm)
            print("\nChecking interference (should be 0)...")
            intf1 = await session.call_tool("sw_check_interference", {})
            print("Interference 1:", parse_tool_result(intf1))

            # 9. Mate Over-defining test (Adversarial)
            print("\nTesting adversarial over-defining mate...")
            adv_res = await session.call_tool("sw_add_mate", {
                "mate_type": "perpendicular",
                "entity1": "Front Plane@part_a-1",
                "entity2": "Front Plane@part_b-1"
            })
            print("Adversarial Mate (is_error?):", adv_res.is_error, parse_tool_result(adv_res))

            print("\nDone scratch verification successfully!")


if __name__ == "__main__":
    asyncio.run(main())
