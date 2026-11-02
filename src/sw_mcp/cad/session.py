"""CAD Session Container for SolidWorks MCP Server.

Instantiates and holds the client and domain managers for document,
sketching, features, equations, and inspection.
"""

from sw_mcp.cad.assembly import AssemblyManager
from sw_mcp.cad.client import SolidWorksClient
from sw_mcp.cad.document import DocumentManager
from sw_mcp.cad.drawing import DrawingManager
from sw_mcp.cad.equations import EquationManager
from sw_mcp.cad.features import FeatureManager
from sw_mcp.cad.inspection import InspectionManager
from sw_mcp.cad.material import MaterialManager
from sw_mcp.cad.sketcher import SketchManager


class CADSession:
    """Encapsulates all SolidWorks managers in one cohesive session."""

    def __init__(self, visible: bool = True):
        self.client = SolidWorksClient(visible=visible)
        self.document = DocumentManager(self.client)
        self.sketcher = SketchManager(self.document)
        self.features = FeatureManager(self.document)
        self.equations = EquationManager(self.document)
        self.inspection = InspectionManager(self.document)
        self.material = MaterialManager(self.document)
        self.assembly = AssemblyManager(self.document)
        self.drawing = DrawingManager(self.document)


# Global instance accessed only through STA worker calls
_session: CADSession | None = None


def get_cad_session() -> CADSession:
    """Retrieve or create the global CADSession."""
    global _session
    if _session is None:
        _session = CADSession(visible=True)
    return _session
