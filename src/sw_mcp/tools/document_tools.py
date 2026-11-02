"""Document lifecycle MCP tools."""

from typing import Any, Dict, List, Optional
try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_document_tools(mcp: FastMCP) -> None:
    """Register all document and export tools with the FastMCP server."""

    @mcp.tool()
    async def sw_get_session_info() -> Dict[str, Any]:
        """Check connection status and active document in SolidWorks 2026."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().client.get_session_info(), idempotent=True)

    @mcp.tool()
    async def sw_new_part(template_path: str = "") -> Dict[str, Any]:
        """
        Create a new blank Part document in SolidWorks.
        template_path: Optional custom .prtdot template path. If omitted, uses system default.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.new_part(template_path))

    @mcp.tool()
    async def sw_new_assembly(template_path: str = "") -> Dict[str, Any]:
        """
        Create a new blank Assembly document in SolidWorks.
        template_path: Optional custom .asmdot template path.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.new_assembly(template_path))

    @mcp.tool()
    async def sw_open_doc(file_path: str, doc_type: str = "auto") -> Dict[str, Any]:
        """
        Open an existing SolidWorks part (.sldprt), assembly (.sldasm), or drawing (.slddrw).
        file_path: Absolute path to the CAD file.
        doc_type: 'auto', 'part', 'assembly', or 'drawing'.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.open_doc(file_path, doc_type))

    @mcp.tool()
    async def sw_save_doc(
        output_path: Optional[str] = None,
        file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Save the active SolidWorks document.
        output_path / file_path: Optional new file path to Save-As. If omitted, saves in-place.
        """
        target_path = output_path or file_path
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.save_doc(target_path))

    @mcp.tool()
    async def sw_close_doc(save_changes: bool = False) -> Dict[str, Any]:
        """Close the currently active document with optional save."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.close_doc(save_changes))

    @mcp.tool()
    async def sw_list_open_documents() -> List[Dict[str, Any]]:
        """List all CAD documents currently open in the active SolidWorks session."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.list_open_documents(), idempotent=True)

    @mcp.tool()
    async def sw_export_cad(output_path: str) -> Dict[str, Any]:
        """
        Export the active model to STEP, STL, Parasolid (.x_t), DXF, or PDF.
        Format is determined by the output file extension.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().document.export_cad(output_path))
