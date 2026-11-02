"""Model Inspection & Viewport Capture MCP tools."""

from typing import Any, Dict, List
try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_inspection_tools(mcp: FastMCP) -> None:
    """Register inspection and multimodal vision tools with FastMCP."""

    @mcp.tool()
    async def sw_get_mass_properties() -> Dict[str, Any]:
        """
        Calculate and return mass (grams/kg), volume (mm^3/cm^3), surface area (mm^2),
        and center of mass coordinates in millimeters.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().inspection.get_mass_properties(), idempotent=True)

    @mcp.tool()
    async def sw_get_feature_tree() -> List[Dict[str, Any]]:
        """List all features and datum planes present in the active model's feature tree."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().inspection.list_feature_tree(), idempotent=True)

    @mcp.tool()
    async def sw_capture_viewport(output_path: str = "output/viewport_render.png") -> Dict[str, Any]:
        """
        Capture the active 3D model viewport into a high-resolution PNG image file.
        Use this tool to visually inspect the CAD model after creating or modifying features.
        output_path: Destination path for the PNG image.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().inspection.capture_viewport(output_path), idempotent=True)
