"""SolidWorks COM Client Lifecycle & Connection Manager.

Manages connection to SldWorks.Application, silent error preferences,
default template detection, and garbage collection.
"""

import gc
import logging
import os
from typing import Any, Dict, Optional

import win32com.client
from sw_mcp.core.exceptions import COMConnectionError

logger = logging.getLogger("sw_mcp.cad.client")

# SolidWorks User Preference Toggle Enums (from swUserPreferenceToggle_e)
swShowErrorsEveryRebuild = 31
swDontShowAgainPromptResponses = 320

# SolidWorks User Preference String Enums (from swUserPreferenceStringValue_e)
swDefaultTemplatePart = 8
swDefaultTemplateAssembly = 9
swDefaultTemplateDrawing = 10


class SolidWorksClient:
    """Manages connection and global session settings for SolidWorks 2026."""

    def __init__(self, visible: bool = True):
        self.visible = visible
        self._app: Optional[Any] = None

    @property
    def app(self) -> Any:
        """Get the active SldWorks.Application instance, connecting if necessary."""
        if self._app is None:
            self.connect()
        return self._app

    def is_connected(self) -> bool:
        """Check if connection to SolidWorks is active and responsive."""
        if self._app is None:
            return False
        try:
            # Query revision number property to test responsiveness
            _ = self._app.RevisionNumber
            return True
        except Exception:
            return False

    def connect(self) -> Any:
        """
        Connect to an active SolidWorks session, or launch a new one if not running.
        Configures silent error suppression and template detection.
        Never forcibly kills running user sessions.
        """
        logger.info("Attempting connection to SolidWorks COM application...")
        # 1. Try attaching to existing running session via ROT (Running Object Table)
        try:
            self._app = win32com.client.GetActiveObject("SldWorks.Application")
            logger.info("Successfully attached to running SolidWorks session via ROT.")
        except Exception as e_rot:
            logger.info("GetActiveObject not available (%s); connecting via COM Dispatch...", e_rot)
            # 2. Fallback to COM Dispatch (safely connects to running class or launches cleanly)
            try:
                self._app = win32com.client.Dispatch("SldWorks.Application")
                logger.info("SolidWorks COM connection established via Dispatch.")
            except Exception as e_dispatch:
                raise COMConnectionError(
                    f"Failed to connect to or launch SolidWorks: {e_dispatch}"
                ) from e_dispatch

        try:
            self._app.Visible = self.visible
            self._app.UserControl = True
            # Configure silent error preferences to avoid modal pop-ups
            self._app.SetUserPreferenceToggle(swShowErrorsEveryRebuild, False)
            self._app.SetUserPreferenceToggle(swDontShowAgainPromptResponses, True)
        except Exception as e:
            logger.warning("Could not set full user preference toggles: %s", e)

        return self._app

    def get_default_template(self, doc_type: str = "part") -> str:
        """
        Get the default template path configured in SolidWorks system options.
        doc_type can be 'part', 'assembly', or 'drawing'.
        """
        app = self.app
        enum_map = {
            "part": swDefaultTemplatePart,
            "assembly": swDefaultTemplateAssembly,
            "drawing": swDefaultTemplateDrawing,
        }
        pref_id = enum_map.get(doc_type.lower(), swDefaultTemplatePart)
        try:
            template_path = app.GetUserPreferenceStringValue(pref_id)
            if template_path and os.path.exists(template_path):
                return template_path
        except Exception as e:
            logger.warning("Could not read default template for %s: %s", doc_type, e)

        # Fallback to SolidWorks standard installation folder if available
        # SolidWorks creates default templates in C:\ProgramData\SolidWorks\...\templates
        return ""

    def get_session_info(self) -> Dict[str, Any]:
        """Return information about the active SolidWorks session and version."""
        app = self.app
        rev = app.RevisionNumber
        active_doc = app.ActiveDoc
        doc_title = active_doc.GetTitle if active_doc else None
        doc_type = active_doc.GetType if active_doc else None

        type_names = {1: "Part", 2: "Assembly", 3: "Drawing"}
        return {
            "connected": True,
            "revision": rev,
            "visible": bool(app.Visible),
            "active_document": doc_title,
            "active_document_type": type_names.get(doc_type, "None"),
        }

    def disconnect(self) -> None:
        """Cleanly release COM object reference and trigger garbage collection."""
        self._app = None
        gc.collect()
        logger.info("SolidWorks COM reference cleared.")
