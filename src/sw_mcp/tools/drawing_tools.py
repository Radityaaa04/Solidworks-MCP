"""2D Drafting & Engineering Drawing MCP Tools for SolidWorks.

Enables automated creation of 2D engineering drawings, multi-view projections
(Front, Top, Right, Isometric), view inspection, automated drafting dimensioning,
engineering notes / title blocks, and silent export to PDF, DXF, DWG, and SLDDRW.
"""

from typing import Any, Dict, List, Optional

try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_drawing_tools(mcp: FastMCP) -> None:
    """Register 2D drawing and drafting automation tools with FastMCP."""

    @mcp.tool()
    async def sw_new_drawing(template_path: str = "") -> Dict[str, Any]:
        """
        Create a new 2D Engineering Drawing document (.slddrw).
        Automatically locates standard drawing templates (Drawing.drwdot) if omitted.

        template_path: Path to custom .drwdot drawing template, or empty for default.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.new_drawing(template_path=template_path)
        )

    @mcp.tool()
    async def sw_create_drawing_view(
        model_path: str,
        orientation: str = "*Front",
        x_mm: float = 100.0,
        y_mm: float = 100.0,
        scale: str = "1:1",
    ) -> Dict[str, Any]:
        """
        Create a 2D model view of a 3D Part or Assembly in the active Drawing.

        model_path: Absolute or relative path to .sldprt or .sldasm model.
        orientation: View orientation ('*Front', '*Top', '*Right', '*Isometric', '*Left', '*Bottom', '*Back').
        x_mm: Horizontal position on the sheet in millimeters from bottom-left origin.
        y_mm: Vertical position on the sheet in millimeters from bottom-left origin.
        scale: View scale ratio (e.g. '1:1', '1:2', '2:1').
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.create_drawing_view(
                model_path=model_path,
                orientation=orientation,
                x_mm=x_mm,
                y_mm=y_mm,
                scale=scale,
            )
        )

    @mcp.tool()
    async def sw_create_standard_views(
        model_path: str,
        center_x_mm: float = 150.0,
        center_y_mm: float = 120.0,
        spacing_mm: float = 90.0,
        include_isometric: bool = True,
        scale: str = "1:1",
    ) -> List[Dict[str, Any]]:
        """
        Generate standard engineering multi-view projection (Front, Top, Right, Isometric)
        for a model on the active Drawing sheet.

        model_path: Path to .sldprt or .sldasm file.
        center_x_mm: Center X coordinate for Front view in mm.
        center_y_mm: Center Y coordinate for Front view in mm.
        spacing_mm: Distance between adjacent orthogonal views in mm.
        include_isometric: Whether to also create an Isometric view.
        scale: View scale ratio string (e.g. '1:1', '1:2').
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.create_standard_views(
                model_path=model_path,
                center_x_mm=center_x_mm,
                center_y_mm=center_y_mm,
                spacing_mm=spacing_mm,
                include_isometric=include_isometric,
                scale=scale,
            )
        )

    @mcp.tool()
    async def sw_list_drawing_views() -> List[Dict[str, Any]]:
        """
        Enumerate all drawing views on the active drawing sheet, including names,
        types, positions (in mm), view scales, and referenced model paths.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.list_drawing_views(),
            idempotent=True,
        )

    @mcp.tool()
    async def sw_auto_dimension(
        view_name: str,
        scheme: str = "baseline",
        horizontal_placement: str = "above",
        vertical_placement: str = "right",
    ) -> Dict[str, Any]:
        """
        Automatically place drafting dimensions on a specified drawing view.

        view_name: Name of drawing view (e.g. 'Drawing View1').
        scheme: Dimensioning scheme ('baseline' or 'chain').
        horizontal_placement: Placement for horizontal dimensions ('above' or 'below').
        vertical_placement: Placement for vertical dimensions ('left' or 'right').
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.auto_dimension(
                view_name=view_name,
                scheme=scheme,
                horizontal_placement=horizontal_placement,
                vertical_placement=vertical_placement,
            )
        )

    @mcp.tool()
    async def sw_add_drawing_note(
        text: str,
        x_mm: float = 20.0,
        y_mm: float = 20.0,
    ) -> Dict[str, Any]:
        """
        Insert an engineering annotation note or title block label onto the drawing sheet.

        text: Annotation text (supports multi-line string).
        x_mm: Horizontal position on sheet in mm from bottom-left origin.
        y_mm: Vertical position on sheet in mm from bottom-left origin.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.add_drawing_note(
                text=text,
                x_mm=x_mm,
                y_mm=y_mm,
            )
        )

    @mcp.tool()
    async def sw_export_drawing(
        output_path: str,
        format_type: str = "auto",
    ) -> Dict[str, Any]:
        """
        Silently export the active drawing to PDF, DXF, DWG, or native SLDDRW format.

        output_path: Destination path on disk (e.g. 'drawings/bracket.pdf').
        format_type: Export format ('auto', 'pdf', 'dxf', 'dwg', 'slddrw').
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.export_drawing(
                output_path=output_path,
                format_type=format_type,
            )
        )

    @mcp.tool()
    async def sw_create_section_view(
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
        Create a 2D Section View (Potongan Penampang Melintang A-A) on the drawing sheet.
        Essential for manufacturing blueprints of hollow/internal features (pistons, cylinder head, wet-sleeve).

        parent_view_name: Source drawing view to slice (e.g. 'Drawing View1').
        cut_start_x_mm: Start X position of section cut line in sheet mm.
        cut_start_y_mm: Start Y position of section cut line in sheet mm.
        cut_end_x_mm: End X position of section cut line in sheet mm.
        cut_end_y_mm: End Y position of section cut line in sheet mm.
        placement_x_mm: Target horizontal placement for the section view in sheet mm.
        placement_y_mm: Target vertical placement for the section view in sheet mm.
        section_label: Section letter identifier (e.g. 'A' generates 'SECTION A-A').
        reverse_direction: True to flip viewing arrow direction.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.create_section_view(
                parent_view_name=parent_view_name,
                cut_start_x_mm=cut_start_x_mm,
                cut_start_y_mm=cut_start_y_mm,
                cut_end_x_mm=cut_end_x_mm,
                cut_end_y_mm=cut_end_y_mm,
                placement_x_mm=placement_x_mm,
                placement_y_mm=placement_y_mm,
                section_label=section_label,
                reverse_direction=reverse_direction,
            )
        )

    @mcp.tool()
    async def sw_insert_bom_table(
        view_name: str,
        x_mm: float = 200.0,
        y_mm: float = 50.0,
        bom_type: str = "top_level",
        configuration: str = "Default",
        table_template: str = "",
    ) -> Dict[str, Any]:
        """
        Insert a manufacturing Bill of Materials (BOM) table on the active 2D drawing sheet.
        view_name: Name of the drawing view to reference (e.g. 'Drawing View1').
        x_mm: Horizontal anchor placement on sheet in millimeters.
        y_mm: Vertical anchor placement on sheet in millimeters.
        bom_type: 'top_level', 'parts_only', or 'indented'.
        configuration: Model configuration name (default 'Default').
        table_template: Optional path to custom .sldbomtbt template.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().drawing.insert_bom_table(
                view_name=view_name,
                x_mm=x_mm,
                y_mm=y_mm,
                bom_type=bom_type,
                configuration=configuration,
                table_template=table_template,
            )
        )
