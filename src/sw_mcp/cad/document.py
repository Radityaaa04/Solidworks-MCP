"""Document lifecycle and file export operations for SolidWorks.

Supports opening, creating, saving, closing, and exporting parts,
assemblies, and drawings silently without dialog popups.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import pythoncom
import win32com.client

from sw_mcp.cad.client import SolidWorksClient
from sw_mcp.core.exceptions import DocumentNotFoundError, SolidWorksError

logger = logging.getLogger("sw_mcp.cad.document")

# SolidWorks Document Type Enums (swDocumentTypes_e)
swDocNONE = 0
swDocPART = 1
swDocASSEMBLY = 2
swDocDRAWING = 3

# SolidWorks OpenDoc Options (swOpenDocOptions_e)
swOpenDocOptions_Silent = 1

# SolidWorks Save Options (swSaveAsOptions_e)
swSaveAsOptions_Silent = 1


class DocumentManager:
    """Manages document creation, opening, saving, and format exporting."""

    def __init__(self, client: SolidWorksClient):
        self.client = client

    def get_active_doc(self) -> Any:
        """Retrieve the active ModelDoc2 instance or raise DocumentNotFoundError."""
        doc = self.client.app.ActiveDoc
        if doc is None:
            raise DocumentNotFoundError("No active document currently open in SolidWorks.")
        return doc

    def new_part(self, template_path: str = "") -> Dict[str, Any]:
        """Create a new Part document from default or specified template."""
        app = self.client.app
        if not template_path:
            template_path = self.client.get_default_template("part")

        # NewDocument parameters: TemplateName, PaperSize, Width, Height
        doc = app.NewDocument(template_path, 0, 0.0, 0.0)
        if doc is None:
            raise SolidWorksError(f"Failed to create new part document using template: {template_path}")

        return {
            "title": doc.GetTitle,
            "type": "Part",
            "template_used": template_path,
        }

    def new_assembly(self, template_path: str = "") -> Dict[str, Any]:
        """Create a new Assembly document from default or specified template."""
        app = self.client.app
        if not template_path:
            template_path = self.client.get_default_template("assembly")

        doc = app.NewDocument(template_path, 0, 0.0, 0.0)
        if doc is None:
            raise SolidWorksError(f"Failed to create new assembly document using template: {template_path}")

        return {
            "title": doc.GetTitle,
            "type": "Assembly",
            "template_used": template_path,
        }

    def open_doc(self, file_path: str, doc_type: str = "auto") -> Dict[str, Any]:
        """
        Open an existing SolidWorks file using silent options.
        doc_type can be 'auto', 'part', 'assembly', or 'drawing'.
        """
        if not os.path.exists(file_path):
            raise DocumentNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()
        type_mapping = {
            ".sldprt": swDocPART,
            ".sldasm": swDocASSEMBLY,
            ".slddrw": swDocDRAWING,
        }
        if doc_type == "auto":
            sw_type = type_mapping.get(ext, swDocPART)
        else:
            sw_type = {"part": swDocPART, "assembly": swDocASSEMBLY, "drawing": swDocDRAWING}.get(doc_type.lower(), swDocPART)

        app = self.client.app
        # OpenDoc6 parameters: FileName, Type, Options, Configuration, Errors (ByRef), Warnings (ByRef)
        import pythoncom
        import win32com.client

        v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        doc = app.OpenDoc6(os.path.abspath(file_path), sw_type, swOpenDocOptions_Silent, "", v_err, v_warn)
        if doc is None:
            raise SolidWorksError(f"Could not open document: {file_path}")

        type_names = {swDocPART: "Part", swDocASSEMBLY: "Assembly", swDocDRAWING: "Drawing"}
        return {
            "title": doc.GetTitle,
            "path": doc.GetPathName,
            "type": type_names.get(sw_type, "Unknown"),
        }

    @staticmethod
    def _decode_save_error(err_code: int) -> str:
        """Decode bitmask error codes from swFileSaveError_e."""
        if err_code == 0:
            return "No error"
        errors = []
        flags = {
            1: "Generic save error (swGenericSaveError)",
            2: "File is read-only (swReadOnlySaveError)",
            4: "File name is empty (swFileNameEmpty)",
            8: "File name contains @ symbol (swFileNameContainsAtSymbol)",
            16: "File lock error (swFileLockError)",
            32: "Save format not available (swFileSaveFormatNotAvailable)",
            64: "Do not overwrite existing file (swFileSaveAsDoNotOverwrite)",
            128: "Invalid file extension (swFileSaveAsInvalidFileExtension)",
        }
        for bit, msg in flags.items():
            if err_code & bit:
                errors.append(msg)
        return ", ".join(errors) if errors else f"Unknown error flag ({err_code})"

    def save_doc(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Save the active document, either in-place or to a specified target path (SaveAs).
        Strictly validates return status and SolidWorks error codes to prevent silent save failure.
        """
        doc = self.get_active_doc()
        v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)

        if output_path:
            abs_path = os.path.abspath(output_path)
            drive, path_no_drive = os.path.splitdrive(abs_path)
            if ":" in path_no_drive or any(c in path_no_drive for c in '<>"|?*'):
                raise ValueError(
                    f"Invalid characters or NTFS Alternate Data Stream (ADS) detected in output path: '{output_path}'"
                )
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)

            pre_title = getattr(doc, "GetTitle", "")
            pre_path = getattr(doc, "GetPathName", "")

            v_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            v_opts = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
            res = doc.Extension.SaveAs3(
                abs_path,
                0,  # swSaveAsCurrentVersion
                swSaveAsOptions_Silent,
                v_data,
                v_opts,
                v_err,
                v_warn,
            )
            err_code = int(v_err.value)
            if not res or err_code != 0:
                post_title = getattr(doc, "GetTitle", "")
                post_path = getattr(doc, "GetPathName", "")
                err_msg = self._decode_save_error(err_code)
                partial_note = ""
                if (post_title and post_title != pre_title) or (post_path and post_path != pre_path):
                    partial_note = f"; partial in-memory state changed (title mutated from '{pre_title}' to '{post_title}', path from '{pre_path}' to '{post_path}')"
                raise SolidWorksError(
                    f"SaveAs failed for path '{abs_path}' (status={res}, error_code={err_code}: {err_msg}){partial_note}"
                )

            if not os.path.exists(abs_path):
                raise SolidWorksError(
                    f"SaveAs reported success but file was not found on disk: '{abs_path}'"
                )

            return {
                "saved": True,
                "path": abs_path,
                "warnings": int(v_warn.value),
            }
        else:
            # In-place save
            res = doc.Save3(swSaveAsOptions_Silent, v_err, v_warn)
            err_code = int(v_err.value)

            if not res or err_code != 0:
                err_msg = self._decode_save_error(err_code)
                raise SolidWorksError(
                    f"In-place Save failed for document '{doc.GetTitle}' (status={res}, error_code={err_code}: {err_msg})"
                )

            current_path = doc.GetPathName
            if not current_path:
                raise SolidWorksError(
                    f"Document '{doc.GetTitle}' has never been saved to disk. Please specify an output_path."
                )

            return {
                "saved": True,
                "path": current_path,
                "warnings": int(v_warn.value),
            }

    def close_doc(self, save_changes: bool = False) -> Dict[str, Any]:
        """Close the active document with optional save."""
        doc = self.get_active_doc()
        title = doc.GetTitle
        if save_changes:
            self.save_doc()

        app = self.client.app
        app.CloseDoc(title)
        return {"closed": True, "title": title}

    def list_open_documents(self) -> List[Dict[str, Any]]:
        """List all documents currently open in the active session."""
        app = self.client.app
        docs: List[Dict[str, Any]] = []
        doc = app.GetFirstDocument
        type_names = {swDocPART: "Part", swDocASSEMBLY: "Assembly", swDocDRAWING: "Drawing"}

        while doc is not None:
            docs.append({
                "title": doc.GetTitle,
                "path": doc.GetPathName,
                "type": type_names.get(doc.GetType, "Unknown"),
            })
            doc = doc.GetNext

        return docs

    def export_cad(self, output_path: str) -> Dict[str, Any]:
        """
        Export the active document to STEP, STL, Parasolid, DXF, IGES, or PDF.
        Format is determined by file extension.
        """
        doc = self.get_active_doc()
        abs_path = os.path.abspath(output_path)
        base, ext = os.path.splitext(abs_path)
        if ext.lower() == ".iges":
            abs_path = base + ".igs"
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        res = doc.SaveAs(abs_path)
        if not res:
            raise SolidWorksError(f"Export failed for target path: {abs_path}")

        return {
            "exported": True,
            "path": abs_path,
            "format": os.path.splitext(abs_path)[1].upper().replace(".", ""),
        }
