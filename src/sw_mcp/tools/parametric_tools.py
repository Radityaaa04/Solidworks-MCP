"""Parametric modeling & equation table MCP tools."""

from typing import Any, Dict, List
try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_parametric_tools(mcp: FastMCP) -> None:
    """Register parametric and equation tools with FastMCP."""

    @mcp.tool()
    async def sw_get_equations() -> List[Dict[str, Any]]:
        """List all equations and global variables defined in the active CAD document."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().equations.get_equations(), idempotent=True)

    @mcp.tool()
    async def sw_set_global_variable(name: str, value: float, unit: str = "mm") -> Dict[str, Any]:
        """
        Add or update a Global Variable in the Equation Table with explicit unit safety.
        name: Variable name (e.g., 'TotalLength', 'WallThickness').
        value: Numeric value.
        unit: 'mm', 'deg', 'in', etc. Default is 'mm'.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().equations.set_global_variable(name, value, unit))

    @mcp.tool()
    async def sw_modify_dimension(dimension_name: str, value_mm: float) -> Dict[str, Any]:
        """
        Modify a specific dimension parameter directly and rebuild the model.
        dimension_name: Dimension address (e.g. 'D1@Sketch1', 'D1@Boss-Extrude1').
        value_mm: New dimension value in millimeters.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().equations.modify_dimension(dimension_name, value_mm))
