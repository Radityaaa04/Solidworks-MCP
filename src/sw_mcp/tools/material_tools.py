"""Physical Engineering & Material Assignment MCP Tools for SolidWorks.

Provides tools to assign standard materials, query assigned material properties,
and explore standard SolidWorks material catalogs (.sldmat).
"""

from typing import Any, Dict, Optional

try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_material_tools(mcp: FastMCP) -> None:
    """Register material assignment, query, and catalog discovery tools with FastMCP."""

    @mcp.tool()
    async def sw_set_material(
        material_name: str,
        database_name: str = "SolidWorks Materials",
        config_name: str = "",
    ) -> Dict[str, Any]:
        """
        Assign an engineering material to the active Part document.
        Automatically updates Parasolid density, mass in grams/kg, and moments of inertia.

        material_name: Name of the material (e.g. 'AISI 1020', '6061 Alloy', 'Brass', 'ABS').
                       Pass an empty string '' to remove/clear the assigned material.
        database_name: Material database file/name (default: 'SolidWorks Materials').
        config_name: Target configuration name, or empty string for active configuration.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().material.set_material(
                material_name=material_name,
                database_name=database_name,
                config_name=config_name,
            )
        )

    @mcp.tool()
    async def sw_get_material(config_name: str = "") -> Dict[str, Any]:
        """
        Query the material currently assigned to the active Part document,
        including its database, mass density, and standard mechanical properties
        (tensile strength, yield strength, elastic modulus, Poisson's ratio).

        config_name: Configuration name, or empty string for active configuration.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().material.get_material(config_name=config_name),
            idempotent=True,
        )

    @mcp.tool()
    async def sw_list_materials(
        classification: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Browse and discover engineering materials available in SolidWorks (.sldmat).

        classification: Filter by material class (e.g. 'Steel', 'Iron', 'Aluminium Alloys',
                        'Copper Alloys', 'Titanium Alloys', 'Plastics', 'Other Metals').
        search: Keyword substring to search (e.g. '1020', '6061', 'Bronze', 'Delrin').
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().material.list_materials(
                classification=classification, search=search
            ),
            idempotent=True,
        )
