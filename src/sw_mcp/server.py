"""FastMCP Server Entrypoint for SolidWorks 2026.

Initializes tool suites and sets up clean logging routed exclusively to sys.stderr
to avoid stdio JSON-RPC protocol corruption.
"""

import logging
import sys
try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from sw_mcp.tools.assembly_tools import register_assembly_tools
from sw_mcp.tools.design_tools import register_design_tools
from sw_mcp.tools.document_tools import register_document_tools
from sw_mcp.tools.drawing_tools import register_drawing_tools
from sw_mcp.tools.inspection_tools import register_inspection_tools
from sw_mcp.tools.material_tools import register_material_tools
from sw_mcp.tools.parametric_tools import register_parametric_tools

# Configure logging strictly to sys.stderr for stdio transport safety
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("sw_mcp.server")

# Instantiate FastMCP server
mcp = FastMCP(
    "SolidWorks-2026-Assistant"
)

# Register all modular tools
register_document_tools(mcp)
register_design_tools(mcp)
register_parametric_tools(mcp)
register_inspection_tools(mcp)
register_material_tools(mcp)
register_assembly_tools(mcp)
register_drawing_tools(mcp)


def main() -> None:
    """Launch the SolidWorks MCP server in stdio mode."""
    logger.info("Starting SolidWorks 2026 MCP Server (stdio transport)...")
    mcp.run()


if __name__ == "__main__":
    main()
