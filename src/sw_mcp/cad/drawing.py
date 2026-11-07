"""Drawing Management and 2D Drafting Automation.

Supports 2D drafting document creation (Drawings), standard and model view
generation, orthogonal multi-view projections, automatic dimensioning,
engineering notes / title blocks, and silent export to PDF, DXF, DWG, and SLDDRW.
"""

import glob
import logging
import os
import re
from typing import Any, Dict, List, Optional

import pythoncom
import win32com.client
from sw_mcp.cad.document import DocumentManager, swDocDRAWING, swDocPART, swDocASSEMBLY, swOpenDocOptions_Silent
from sw_mcp.core.exceptions import DrawingError, DocumentNotFoundError, InvalidSelectionError, SolidWorksError
from sw_mcp.core.units import mm_to_meters

logger = logging.getLogger("sw_mcp.cad.drawing")

# SolidWorks Drawing View Types (swDrawingViewTypes_e)
VIEW_TYPES = {
    1: "Sheet",
    2: "Standard",
    3: "Section",
    4: "Detail",
    5: "Auxiliary",
    6: "Relative",
    7: "Named",
    8: "Projected",
    9: "Detached",
    10: "FlatPattern",
}

# AutoDimension Schemes (swAutodimScheme_e)
AUTODIM_SCHEMES = {
    "baseline": 0,  # swAutodimSchemeBaseline
    "chain": 1,     # swAutodimSchemeChain
}

# AutoDimension Placements (swAutodimPlacement_e)
AUTODIM_HORIZONTAL_PLACEMENTS = {
    "above": 1,     # swAutodimPlacementAbove
    "below": 2,     # swAutodimPlacementBelow
}

AUTODIM_VERTICAL_PLACEMENTS = {
    "left": 1,      # swAutodimPlacementLeft
    "right": 2,     # swAutodimPlacementRight
}


class DrawingManager:
    """Manages 2D drafting documents, orthogonal views, dimensioning, notes, and exports."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def get_active_drawing(self) -> Any:
        """Retrieve the active DrawingDoc instance or raise DrawingError."""
        doc = self.doc_mgr.get_active_doc()
        if doc.GetType != swDocDRAWING:
            raise DrawingError(
                f"Active document '{doc.GetTitle}' is not a 2D Drawing (Type: {doc.GetType}). "
                "Open or create a Drawing document first."
            )
        return doc

    def _find_drawing_template(self, requested_template: str = "") -> str:
        """Locate a valid Drawing template (.drwdot) on the system."""
        if requested_template and os.path.exists(requested_template):
            return os.path.abspath(requested_template)

        # 1. Check SolidWorks user preference
        app = self.doc_mgr.client.app
        try:
            pref_template = app.GetUserPreferenceStringValue(15)  # swDefaultTemplateDrawing = 15
            if pref_template and os.path.exists(pref_template):
                return pref_template
        except Exception as e:
            logger.debug("Failed reading UserPreferenceStringValue(15): %s", e)

        # 2. Check standard ProgramData SolidWorks installation paths
        search_patterns = [
            r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates\Drawing.drwdot",
            r"C:\ProgramData\SolidWorks\SOLIDWORKS *\templates\*.drwdot",
            r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\data\templates\Drawing.drwdot",
            r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\data\templates\*.drwdot",
        ]
        for pattern in search_patterns:
            matches = glob.glob(pattern)
            if matches:
                return matches[0]

        raise DrawingError(
            "Could not locate a standard SolidWorks drawing template (.drwdot). "
            "Please provide a valid template_path."
        )

    def new_drawing(self, template_path: str = "") -> Dict[str, Any]:
        """Create a new 2D Drawing document from a template."""
        app = self.doc_mgr.client.app
        tmpl = self._find_drawing_template(template_path)
        logger.info("Creating new drawing with template: %s", tmpl)

        # Paper size 0 = custom / defined by template
        draw_doc = app.NewDocument(tmpl, 0, 0.0, 0.0)
        if draw_doc is None:
            raise DrawingError(f"Failed to create new drawing document using template '{tmpl}'.")

        sheet_name = "Sheet1"
        width_mm = 0.0
        height_mm = 0.0
        try:
            sheet = getattr(draw_doc, "GetCurrentSheet", None)
            if sheet is not None:
                sheet_name = sheet.GetName() if callable(getattr(sheet, "GetName", None)) else str(getattr(sheet, "GetName", "Sheet1"))
                props = sheet.GetProperties() if callable(getattr(sheet, "GetProperties", None)) else getattr(sheet, "GetProperties", None)
                if props and len(props) > 6:
                    width_mm = round(props[5] * 1000.0, 2)
                    height_mm = round(props[6] * 1000.0, 2)
        except Exception as e:
            logger.debug("Could not read sheet properties: %s", e)

        return {
            "title": draw_doc.GetTitle,
            "sheet_name": sheet_name,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "template_used": tmpl,
            "status": "created",
        }

    def _ensure_model_loaded(self, model_path: str) -> None:
        """Pre-load model silently into SolidWorks memory if not already open."""
        if not os.path.exists(model_path):
            raise DrawingError(f"Model file does not exist: {model_path}")

        app = self.doc_mgr.client.app
        norm_path = os.path.abspath(model_path)
        doc_type = swDocPART if norm_path.lower().endswith(".sldprt") else swDocASSEMBLY

        v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        
        # OpenDoc6 in silent mode pre-loads the model document
        loaded_doc = app.OpenDoc6(norm_path, doc_type, swOpenDocOptions_Silent, "", v_err, v_warn)
        if not loaded_doc and v_err.value != 0:
            logger.warning("OpenDoc6 warning/error for %s: err=%s, warn=%s", norm_path, v_err.value, v_warn.value)

    def create_drawing_view(
        self,
        model_path: str,
        orientation: str = "*Front",
        x_mm: float = 100.0,
        y_mm: float = 100.0,
        scale: str = "1:1",
    ) -> Dict[str, Any]:
        """Create a named model view in the active drawing document.
        
        Args:
            model_path: Absolute or relative path to the 3D part or assembly.
            orientation: Standard view name (e.g. "*Front", "*Top", "*Right", "*Isometric", "*Dimetric").
            x_mm: Horizontal position on sheet in mm from bottom-left origin.
            y_mm: Vertical position on sheet in mm from bottom-left origin.
            scale: View scale string e.g. "1:1", "1:2", "2:1".
        """
        draw_doc = self.get_active_drawing()
        draw_title = draw_doc.GetTitle
        app = self.doc_mgr.client.app

        abs_model_path = os.path.abspath(model_path)
        self._ensure_model_loaded(abs_model_path)

        # Reactivate drawing document in case OpenDoc shifted active doc
        v_act_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        app.ActivateDoc3(draw_title, False, 2, v_act_err)

        # Format orientation with leading asterisk if omitted
        norm_orient = orientation.strip()
        standard_names = ["front", "top", "right", "left", "bottom", "back", "isometric", "dimetric", "trimetric"]
        if norm_orient.lstrip("*").lower() in standard_names and not norm_orient.startswith("*"):
            norm_orient = f"*{norm_orient.capitalize()}"

        x_m = mm_to_meters(x_mm)
        y_m = mm_to_meters(y_mm)

        logger.info(
            "Creating drawing view: model='%s', orient='%s', pos=(%.3f, %.3f)m",
            abs_model_path, norm_orient, x_m, y_m
        )

        view = draw_doc.CreateDrawViewFromModelView3(abs_model_path, norm_orient, x_m, y_m, 0.0)
        if not view:
            raise DrawingError(
                f"Failed to create drawing view '{norm_orient}' from model '{abs_model_path}'. "
                "Verify orientation name and model validity."
            )

        # Apply view scale if requested
        if scale and ":" in scale:
            try:
                parts = scale.split(":")
                num = float(parts[0])
                den = float(parts[1])
                try:
                    view.UseSheetScale = False
                except Exception:
                    pass
                try:
                    view.SetScale2(int(num), int(den), False, False)
                except Exception:
                    view.ScaleDecimal = num / den
            except Exception as e:
                logger.warning("Could not set view scale '%s': %s", scale, e)

        pos = view.Position
        pos_mm = [round(pos[0] * 1000.0, 2), round(pos[1] * 1000.0, 2)]

        return {
            "name": view.GetName2,
            "type": VIEW_TYPES.get(view.Type, f"Unknown ({view.Type})"),
            "orientation": norm_orient,
            "model_path": abs_model_path,
            "position_mm": pos_mm,
            "scale_decimal": round(view.ScaleDecimal, 4),
            "status": "created",
        }

    def create_standard_views(
        self,
        model_path: str,
        center_x_mm: float = 150.0,
        center_y_mm: float = 120.0,
        spacing_mm: float = 90.0,
        include_isometric: bool = True,
        scale: str = "1:1",
    ) -> List[Dict[str, Any]]:
        """Convenience method to generate standard multi-view projection (Front, Top, Right, Isometric)."""
        views_created = []

        # Determine projection standard from sheet properties (props[4] is FirstAngle)
        is_first_angle = False
        try:
            draw_doc = self.get_active_drawing()
            sheet = getattr(draw_doc, "GetCurrentSheet", None)
            if sheet is not None:
                props = getattr(sheet, "GetProperties", None)
                if callable(props):
                    props = props()
                if props and len(props) > 4:
                    is_first_angle = bool(props[4])
        except Exception as e:
            logger.debug("Could not determine sheet projection standard: %s", e)

        top_y_mm = center_y_mm - spacing_mm if is_first_angle else center_y_mm + spacing_mm
        right_x_mm = center_x_mm - spacing_mm if is_first_angle else center_x_mm + spacing_mm

        # 1. Front View (Center / Reference)
        front = self.create_drawing_view(
            model_path=model_path,
            orientation="*Front",
            x_mm=center_x_mm,
            y_mm=center_y_mm,
            scale=scale,
        )
        views_created.append(front)

        # 2. Top View (Below Front in First-Angle, Above Front in Third-Angle)
        top = self.create_drawing_view(
            model_path=model_path,
            orientation="*Top",
            x_mm=center_x_mm,
            y_mm=top_y_mm,
            scale=scale,
        )
        views_created.append(top)

        # 3. Right View (Left of Front in First-Angle, Right of Front in Third-Angle)
        right = self.create_drawing_view(
            model_path=model_path,
            orientation="*Right",
            x_mm=right_x_mm,
            y_mm=center_y_mm,
            scale=scale,
        )
        views_created.append(right)

        # 4. Isometric View (Upper Right Quadrant)
        if include_isometric:
            iso = self.create_drawing_view(
                model_path=model_path,
                orientation="*Isometric",
                x_mm=center_x_mm + spacing_mm,
                y_mm=center_y_mm + spacing_mm,
                scale=scale,
            )
            views_created.append(iso)

        return views_created

    def list_drawing_views(self) -> List[Dict[str, Any]]:
        """Enumerate all views in the active drawing document."""
        draw_doc = self.get_active_drawing()
        views: List[Dict[str, Any]] = []

        view = draw_doc.GetFirstView  # Sheet level view
        while view:
            name = view.GetName2
            v_type = view.Type
            type_str = VIEW_TYPES.get(v_type, f"Custom ({v_type})")
            pos = view.Position
            pos_mm = [round(pos[0] * 1000.0, 2), round(pos[1] * 1000.0, 2)] if pos else [0.0, 0.0]
            ref_model = view.GetReferencedModelName or ""

            scale_dec = 1.0
            try:
                scale_dec = round(view.ScaleDecimal, 4)
            except Exception:
                pass

            views.append({
                "name": name,
                "type": type_str,
                "type_id": v_type,
                "position_mm": pos_mm,
                "scale_decimal": scale_dec,
                "referenced_model": ref_model,
            })
            view = view.GetNextView

        return views

    def auto_dimension(
        self,
        view_name: str,
        scheme: str = "baseline",
        horizontal_placement: str = "above",
        vertical_placement: str = "right",
    ) -> Dict[str, Any]:
        """Automatically generate drafting dimensions on a drawing view.
        
        Args:
            view_name: Name of the drawing view (e.g. "Drawing View1").
            scheme: Dimensioning scheme: "baseline" or "chain".
            horizontal_placement: Placement for horizontal dimensions: "above" or "below".
            vertical_placement: Placement for vertical dimensions: "left" or "right".
        """
        draw_doc = self.get_active_drawing()

        # Activate the view
        activated = draw_doc.ActivateView(view_name)
        if not activated:
            raise DrawingError(f"Could not activate view '{view_name}'. Check view name.")

        # Clear previous selection and select the drawing view
        draw_doc.ClearSelection2(True)
        v_call = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)
        selected = draw_doc.Extension.SelectByID2(
            view_name, "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, v_call, 0
        )
        if not selected:
            raise InvalidSelectionError(f"Could not select DRAWINGVIEW '{view_name}' for dimensioning.")

        h_scheme = AUTODIM_SCHEMES.get(scheme.lower(), 0)
        v_scheme = h_scheme
        h_place = AUTODIM_HORIZONTAL_PLACEMENTS.get(horizontal_placement.lower(), 1)
        v_place = AUTODIM_VERTICAL_PLACEMENTS.get(vertical_placement.lower(), 2)

        # Call AutoDimension:
        # EntitiesToDimension: 1 = swAutodimEntitiesAll
        # HorizontalScheme, HorizontalPlacement, VerticalScheme, VerticalPlacement
        status = draw_doc.AutoDimension(1, h_scheme, h_place, v_scheme, v_place)
        draw_doc.ClearSelection2(True)

        return {
            "view_name": view_name,
            "status": "success" if status == 1 else f"code_{status}",
            "scheme": scheme,
            "horizontal_placement": horizontal_placement,
            "vertical_placement": vertical_placement,
        }

    def add_drawing_note(
        self,
        text: str,
        x_mm: float = 20.0,
        y_mm: float = 20.0,
    ) -> Dict[str, Any]:
        """Insert an engineering text note or title block annotation onto the sheet."""
        draw_doc = self.get_active_drawing()

        note = draw_doc.InsertNote(text)
        if not note:
            raise DrawingError("InsertNote returned None. Failed to place annotation.")

        x_m = mm_to_meters(x_mm)
        y_m = mm_to_meters(y_mm)

        try:
            note.SetTextPoint(x_m, y_m, 0.0)
        except Exception as e:
            logger.debug("SetTextPoint failed, trying Annotation.SetPosition2: %s", e)
            try:
                ann = note.GetAnnotation()
                if ann:
                    ann.SetPosition2(x_m, y_m, 0.0)
            except Exception as e2:
                logger.warning("Could not set note coordinates: %s", e2)

        # note.GetText is a property in pywin32
        note_text = ""
        try:
            note_text = note.GetText
        except Exception:
            note_text = text

        return {
            "text": note_text,
            "position_mm": [x_mm, y_mm],
            "status": "created",
        }

    def export_drawing(
        self,
        output_path: str,
        format_type: str = "auto",
    ) -> Dict[str, Any]:
        """Silently export the active drawing to PDF, DXF, DWG, or native SLDDRW.
        
        Args:
            output_path: Destination file path.
            format_type: 'auto', 'pdf', 'dxf', 'dwg', or 'slddrw'.
        """
        draw_doc = self.get_active_drawing()
        app = self.doc_mgr.client.app

        abs_out = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_out), exist_ok=True)

        if format_type.lower() == "auto":
            ext = os.path.splitext(abs_out)[1].lower().lstrip(".")
            format_type = ext if ext else "pdf"
        else:
            format_type = format_type.lower().lstrip(".")

        v_err = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_warn = win32com.client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        v_opts = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

        if format_type == "pdf":
            export_data = app.GetExportFileData(1)  # swExportPDFData = 1
        else:
            export_data = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

        success = draw_doc.Extension.SaveAs3(abs_out, 0, 1, export_data, v_opts, v_err, v_warn)

        if not success or not os.path.exists(abs_out):
            raise DrawingError(
                f"Export failed for format '{format_type}' to '{abs_out}'. "
                f"Error code: {v_err.value}, Warning code: {v_warn.value}"
            )

        file_size = os.path.getsize(abs_out)
        return {
            "output_path": abs_out,
            "format": format_type,
            "size_bytes": file_size,
            "status": "exported",
        }

    def create_section_view(
        self,
        parent_view_name: str,
        cut_start_x_mm: float,
        cut_start_y_mm: float,
        cut_end_x_mm: float,
        cut_end_y_mm: float,
        placement_x_mm: float,
        placement_y_mm: float,
        section_label: str = "A",
        reverse_direction: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a 2D Section View (Potongan A-A) across a parent drawing view.

        parent_view_name: Name of the parent view (e.g. 'Drawing View1').
        cut_start_x_mm: Start X coordinate of cutting line in sheet mm.
        cut_start_y_mm: Start Y coordinate of cutting line in sheet mm.
        cut_end_x_mm: End X coordinate of cutting line in sheet mm.
        cut_end_y_mm: End Y coordinate of cutting line in sheet mm.
        placement_x_mm: Placement X coordinate of the section view on the sheet in mm.
        placement_y_mm: Placement Y coordinate of the section view on the sheet in mm.
        section_label: Section letter label (default 'A').
        reverse_direction: True to flip section view cut arrow direction.
        """
        draw_doc = self.get_active_drawing()

        # 1. Activate parent view
        if not draw_doc.ActivateView(parent_view_name):
            raise DrawingError(f"Could not activate parent view '{parent_view_name}'. Check view name.")

        # 2. Draw section cutting line across the view
        x1_m = mm_to_meters(cut_start_x_mm)
        y1_m = mm_to_meters(cut_start_y_mm)
        x2_m = mm_to_meters(cut_end_x_mm)
        y2_m = mm_to_meters(cut_end_y_mm)

        line = draw_doc.CreateLine2(x1_m, y1_m, 0.0, x2_m, y2_m, 0.0)
        if not line:
            raise DrawingError(
                f"Failed to create cutting line from ({cut_start_x_mm}, {cut_start_y_mm}) "
                f"to ({cut_end_x_mm}, {cut_end_y_mm}) on view '{parent_view_name}'."
            )

        # 3. Create section view
        px_m = mm_to_meters(placement_x_mm)
        py_m = mm_to_meters(placement_y_mm)
        v_disp_none = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)

        sec_view = None
        options = 1 if reverse_direction else 0
        try:
            sec_view = draw_doc.CreateSectionViewAt5(px_m, py_m, 0.0, section_label, options, v_disp_none, 0.0)
        except Exception:
            try:
                sec_view = draw_doc.CreateSectionViewAt2(
                    px_m, py_m, 0.0, False, False, section_label, reverse_direction, True, False, False
                )
            except Exception as e:
                raise DrawingError(f"CreateSectionView failed at ({placement_x_mm}, {placement_y_mm}) mm: {e}")

        if not sec_view:
            raise DrawingError(f"CreateSectionView returned None at ({placement_x_mm}, {placement_y_mm}) mm.")

        pos = sec_view.Position
        pos_mm = [round(pos[0] * 1000.0, 2), round(pos[1] * 1000.0, 2)] if pos else [placement_x_mm, placement_y_mm]

        return {
            "name": sec_view.GetName2,
            "type": "Section",
            "section_label": section_label,
            "parent_view": parent_view_name,
            "position_mm": pos_mm,
            "scale_decimal": round(sec_view.ScaleDecimal, 4) if hasattr(sec_view, "ScaleDecimal") else 1.0,
            "status": "created",
        }

    def insert_bom_table(
        self,
        view_name: str,
        x_mm: float = 200.0,
        y_mm: float = 50.0,
        bom_type: str = "top_level",
        configuration: str = "Default",
        table_template: str = "",
    ) -> Dict[str, Any]:
        """
        Insert a manufacturing Bill of Materials (BOM) table associated with a drawing view.
        """
        if not view_name or not str(view_name).strip():
            raise ValueError("view_name is required to insert a BOM table.")
        for c, cname in [(x_mm, "x_mm"), (y_mm, "y_mm")]:
            if not isinstance(c, (int, float)):
                raise ValueError(f"{cname} must be numeric, got {c}")

        bom_type_map = {
            "top_level": 1,     # swBomType_TopLevelOnly
            "parts_only": 2,    # swBomType_PartsOnly
            "indented": 3,      # swBomType_Indented
        }
        bt_key = bom_type.strip().lower() if isinstance(bom_type, str) else ""
        if bt_key not in bom_type_map:
            raise ValueError(f"Unsupported bom_type '{bom_type}'. Valid options: {list(bom_type_map.keys())}")

        draw_doc = self.get_active_drawing()

        # Locate view by name
        target_view = None
        v = draw_doc.GetFirstView
        while v is not None:
            v_name = v.GetName2 if not callable(getattr(v, "GetName2", None)) else v.GetName2()
            if str(v_name).strip().lower() == view_name.strip().lower():
                target_view = v
                break
            v = v.GetNextView

        if target_view is None:
            raise DrawingError(f"Drawing view '{view_name}' not found on the active drawing sheet.")

        tmpl = table_template.strip() if table_template else ""
        if not tmpl or not os.path.exists(tmpl):
            patterns = [
                r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english\bom-standard.sldbomtbt",
                r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\*\bom-standard.sldbomtbt",
            ]
            for pat in patterns:
                matches = glob.glob(pat)
                if matches:
                    tmpl = matches[0]
                    break

        bom_feat = None
        if hasattr(target_view, "InsertBomTable4"):
            bom_feat = target_view.InsertBomTable4(
                False,
                mm_to_meters(x_mm),
                mm_to_meters(y_mm),
                1,  # swBOMConfigurationAnchor_TopLeft
                bom_type_map[bt_key],
                configuration,
                tmpl,
                False,
                0,  # swNumberingType_Detailed
                False,
            )
        elif hasattr(target_view, "InsertBomTable3"):
            bom_feat = target_view.InsertBomTable3(
                False,
                mm_to_meters(x_mm),
                mm_to_meters(y_mm),
                1,
                bom_type_map[bt_key],
                configuration,
                tmpl,
                False,
            )

        if not bom_feat:
            raise DrawingError(f"Failed to insert BOM table for view '{view_name}'.")

        feat_name = getattr(bom_feat, "Name", "BomTable1")
        try:
            get_feat = getattr(bom_feat, "GetFeature", None)
            if callable(get_feat):
                f_obj = get_feat()
                if f_obj and hasattr(f_obj, "Name"):
                    feat_name = f_obj.Name
            elif get_feat and hasattr(get_feat, "Name"):
                feat_name = get_feat.Name
        except Exception:
            pass

        return {
            "bom_table": str(feat_name),
            "view_name": view_name,
            "bom_type": bt_key,
            "configuration": configuration,
            "position_mm": [x_mm, y_mm],
            "status": "created",
        }
