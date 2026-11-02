"""Assembly Modeling, Multi-Component Mating & Interference Checking MCP Tools.

Provides high-level tools to assemble components into 3D SolidWorks assemblies (.sldasm),
apply kinematic mates (Coincident, Concentric, Distance, Parallel, Perpendicular, Angle, Tangent, Lock),
inspect component trees, and run interference/collision detection.
"""

from typing import Any, Dict, List, Optional

try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_assembly_tools(mcp: FastMCP) -> None:
    """Register assembly modeling, component management, and mating tools with FastMCP."""

    @mcp.tool()
    async def sw_insert_component(
        component_path: str,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = 0.0,
        config_name: str = "",
    ) -> Dict[str, Any]:
        """
        Insert an external part (.sldprt) or sub-assembly (.sldasm) into the active assembly document.
        Pre-loads the file into memory silently if needed and positions it at the specified coordinates.

        component_path: Absolute or relative file path to the .sldprt or .sldasm file.
        x_mm, y_mm, z_mm: Initial rough placement coordinates in millimeters.
        config_name: Component configuration to instantiate, or empty string for default.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().assembly.insert_component(
                component_path=component_path,
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=z_mm,
                config_name=config_name,
            )
        )

    @mcp.tool()
    async def sw_add_mate(
        mate_type: str,
        entity1: str,
        entity2: str,
        alignment: str = "aligned",
        flip: bool = False,
        distance_mm: float = 0.0,
        angle_deg: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Create a physical assembly constraint (mate) between two entities in the active assembly.

        mate_type: Type of mate: 'coincident', 'concentric', 'perpendicular',
                   'parallel', 'tangent', 'distance', 'angle', or 'lock'.
        entity1: First entity: named plane/feature (e.g. 'Top Plane@part1-1', 'Top Plane')
                 or 3D spatial coordinate ('FACE:x,y,z', 'EDGE:x,y,z').
        entity2: Second entity: named plane/feature (e.g. 'Top Plane@part2-1')
                 or 3D spatial coordinate ('FACE:x,y,z', 'EDGE:x,y,z').
        alignment: 'aligned' (normal vectors same direction),
                   'anti_aligned' (opposite directions), or 'closest'.
        flip: True to invert mate direction.
        distance_mm: Offset distance in millimeters (for 'distance' mate).
        angle_deg: Angular offset in degrees (for 'angle' mate).
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().assembly.add_mate(
                mate_type=mate_type,
                entity1=entity1,
                entity2=entity2,
                alignment=alignment,
                flip=flip,
                distance_mm=distance_mm,
                angle_deg=angle_deg,
            )
        )

    @mcp.tool()
    async def sw_list_components(top_level_only: bool = True) -> List[Dict[str, Any]]:
        """
        List all components in the active assembly with their file paths,
        suppression state, grounding (fixed/floating) status, and 3D bounding boxes.

        top_level_only: True to list top-level components only, False to include sub-assembly parts.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().assembly.list_components(top_level_only=top_level_only),
            idempotent=True,
        )

    @mcp.tool()
    async def sw_check_interference(
        treat_coincidence_as_interference: bool = False,
    ) -> Dict[str, Any]:
        """
        Run Parasolid interference detection on the active assembly to verify mechanical clearances
        and detect physical collisions between components.

        treat_coincidence_as_interference: True to treat contacting coincident surfaces as collisions.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().assembly.check_interference(
                treat_coincidence_as_interference=treat_coincidence_as_interference
            ),
            idempotent=True,
        )

    @mcp.tool()
    async def sw_set_component_fixed(
        component_name: str,
        fixed: bool = True,
        is_fixed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Ground (fix) or un-ground (float) a component in assembly 3D space.

        component_name: Name of the component instance (e.g. 'base_plate-1').
        fixed / is_fixed: True to lock in place, False to allow motion via mates.
        """
        target_fixed = is_fixed if is_fixed is not None else fixed
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().assembly.set_component_fixed(
                component_name=component_name, fixed=target_fixed
            )
        )
