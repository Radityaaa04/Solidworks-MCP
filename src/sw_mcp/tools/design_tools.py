"""2D Sketching and 3D Feature design MCP tools."""

from typing import Any, Dict, Optional
try:
    from mcp.server import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP
from sw_mcp.cad.session import get_cad_session
from sw_mcp.core.sta_worker import get_sta_worker


def register_design_tools(mcp: FastMCP) -> None:
    """Register all 2D sketch and 3D modeling tools with FastMCP."""

    @mcp.tool()
    async def sw_create_sketch_on_plane(plane_name: str = "Front Plane") -> Dict[str, Any]:
        """
        Open a new 2D sketch on a reference plane.
        plane_name: 'Front Plane', 'Top Plane', 'Right Plane' (multi-lingual supported).
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.create_sketch(plane_name))

    @mcp.tool()
    async def sw_create_sketch_on_face(x_mm: float, y_mm: float, z_mm: float) -> Dict[str, Any]:
        """
        Open a new 2D sketch on a planar face of an existing 3D body located at 3D coordinates (x, y, z).
        x_mm, y_mm, z_mm: Point coordinates in millimeters lying on the target planar face.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.create_sketch_on_face(x_mm, y_mm, z_mm))

    @mcp.tool()
    async def sw_close_sketch() -> Dict[str, Any]:
        """Exit/finish the currently active 2D sketch mode."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.close_sketch())

    @mcp.tool()
    async def sw_draw_line(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """Draw a 2D line segment between two points in millimeters."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.draw_line(x1_mm, y1_mm, x2_mm, y2_mm))

    @mcp.tool()
    async def sw_draw_centerline(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """
        Draw a 2D centerline / construction line between two points in millimeters.
        Essential for establishing revolution axes and symmetry lines.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.draw_centerline(x1_mm, y1_mm, x2_mm, y2_mm))

    @mcp.tool()
    async def sw_draw_rectangle(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> Dict[str, Any]:
        """Draw a 2D corner rectangle from corner1 (x1, y1) to corner2 (x2, y2) in millimeters."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.draw_rectangle(x1_mm, y1_mm, x2_mm, y2_mm))

    @mcp.tool()
    async def sw_draw_circle(center_x_mm: float, center_y_mm: float, radius_mm: float) -> Dict[str, Any]:
        """Draw a 2D circle with center and radius in millimeters."""
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.draw_circle(center_x_mm, center_y_mm, radius_mm))

    @mcp.tool()
    async def sw_draw_arc(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float, x3_mm: float, y3_mm: float) -> Dict[str, Any]:
        """
        Draw a 2D 3-point circular arc starting at (x1, y1), ending at (x2, y2), and passing through (x3, y3).
        All coordinates in millimeters.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.draw_arc(x1_mm, y1_mm, x2_mm, y2_mm, x3_mm, y3_mm))

    @mcp.tool()
    async def sw_create_3d_sketch() -> Dict[str, Any]:
        """
        Create and activate an unconstrained 3D Sketch in the active document.
        Essential for Phase 0 Master Kinematic Skeleton, layout wireframes, and 3D curve paths.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().sketcher.create_3d_sketch())

    @mcp.tool()
    async def sw_draw_3d_line(
        x1_mm: float,
        y1_mm: float,
        z1_mm: float,
        x2_mm: float,
        y2_mm: float,
        z2_mm: float,
    ) -> Dict[str, Any]:
        """
        Draw a 3D line segment between two spatial coordinates in millimeters within an active 3D sketch.
        Used for skeleton centerlines (crank-to-pin, conrod center-to-center, valve axes).
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().sketcher.draw_3d_line(
                x1_mm, y1_mm, z1_mm, x2_mm, y2_mm, z2_mm
            )
        )

    @mcp.tool()
    async def sw_boss_extrude(depth_mm: float, flip_dir: bool = False) -> Dict[str, Any]:
        """
        Extrude the active sketch profile into a 3D solid boss/base.
        depth_mm: Thickness of extrusion in millimeters.
        flip_dir: True to extrude in reverse direction.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.boss_extrude(depth_mm, flip_dir))

    @mcp.tool()
    async def sw_cut_extrude(depth_mm: float, flip_dir: bool = False) -> Dict[str, Any]:
        """
        Cut and remove material using the active sketch profile.
        depth_mm: Cut depth in millimeters.
        flip_dir: True to cut in reverse direction.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.cut_extrude(depth_mm, flip_dir))

    @mcp.tool()
    async def sw_revolve_boss(angle_deg: float = 360.0, reverse_dir: bool = False) -> Dict[str, Any]:
        """
        Revolve the active sketch profile around its centerline axis into a 3D solid body.
        angle_deg: Angle of revolution in degrees (default 360.0°).
        reverse_dir: True to reverse direction of rotation.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.revolve_boss(angle_deg, reverse_dir))

    @mcp.tool()
    async def sw_revolve_cut(angle_deg: float = 360.0, reverse_dir: bool = False) -> Dict[str, Any]:
        """
        Revolve the active sketch profile around its centerline axis to cut and remove material from the solid body.
        angle_deg: Angle of revolution in degrees (default 360.0°).
        reverse_dir: True to reverse direction of rotation.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.revolve_cut(angle_deg, reverse_dir))

    @mcp.tool()
    async def sw_fillet(
        radius_mm: float,
        edge_x_mm: Optional[float] = None,
        edge_y_mm: Optional[float] = None,
        edge_z_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Apply a constant-radius fillet to currently selected edges/faces, or to the edge at given 3D coordinates.
        radius_mm: Fillet radius in millimeters.
        edge_x_mm, edge_y_mm, edge_z_mm: Optional 3D point in millimeters to select the target edge.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.fillet(radius_mm, edge_x_mm, edge_y_mm, edge_z_mm))

    @mcp.tool()
    async def sw_chamfer(
        distance_mm: float,
        angle_deg: float = 45.0,
        edge_x_mm: Optional[float] = None,
        edge_y_mm: Optional[float] = None,
        edge_z_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Apply a chamfer to currently selected edges/faces, or to the edge at given 3D coordinates.
        distance_mm: Chamfer distance/width in millimeters.
        angle_deg: Chamfer angle in degrees (default 45.0°).
        edge_x_mm, edge_y_mm, edge_z_mm: Optional 3D point in millimeters to select the target edge.
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.chamfer(distance_mm, angle_deg, edge_x_mm, edge_y_mm, edge_z_mm))

    @mcp.tool()
    async def sw_rebuild(force: bool = True) -> Dict[str, Any]:
        """
        Force a full regeneration and rebuild of the active CAD model.
        force: Optional boolean flag (default True).
        """
        worker = get_sta_worker()
        return await worker.run(lambda: get_cad_session().features.rebuild())

    @mcp.tool()
    async def sw_circular_pattern(
        feature_name: str,
        total_instances: int = 6,
        total_angle_deg: float = 360.0,
        equal_spacing: bool = True,
        axis_x_mm: Optional[float] = None,
        axis_y_mm: Optional[float] = None,
        axis_z_mm: Optional[float] = None,
        axis_entity_name: str = "",
        flip_dir: bool = False,
        spacing_deg: Optional[float] = None,
        axis_name: str = "",
        reverse_dir: bool = False,
    ) -> Dict[str, Any]:
        """
        Pattern a 3D feature circularly around a rotation axis or cylindrical face.
        Essential for engine gears, bolt circles, clutch baskets, and impellers.

        feature_name: (Required) Name of feature to pattern (e.g. 'Cut-Extrude1').
        total_instances: Number of patterned instances (including original).
        total_angle_deg / spacing_deg: Total sweep angle in degrees (default 360.0°).
        equal_spacing: Distribute instances equally across total_angle_deg.
        axis_x_mm, axis_y_mm, axis_z_mm: Optional 3D coordinate on the cylindrical face to use as axis.
        axis_entity_name / axis_name: Optional name of axis entity (e.g. 'Axis1').
        flip_dir / reverse_dir: True to reverse rotation direction.
        """
        target_angle = spacing_deg if spacing_deg is not None else total_angle_deg
        target_axis_name = axis_name if axis_name else axis_entity_name
        target_flip = reverse_dir or flip_dir
        axis_coord = [axis_x_mm, axis_y_mm, axis_z_mm] if (axis_x_mm is not None and axis_y_mm is not None and axis_z_mm is not None) else None
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.circular_pattern(
                feature_name=feature_name,
                total_instances=total_instances,
                total_angle_deg=target_angle,
                equal_spacing=equal_spacing,
                axis_coord_mm=axis_coord,
                axis_entity_name=target_axis_name,
                flip_dir=target_flip,
            )
        )

    @mcp.tool()
    async def sw_boss_sweep(
        path_sketch_name: str = "",
        profile_sketch_name: str = "",
        circular_profile_diameter_mm: Optional[float] = None,
        diameter_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create a 3D Swept Boss feature along a trajectory path.
        Essential for engine intake/exhaust ports, springs, oil lines, and curved conduits.

        path_sketch_name: Name of trajectory path sketch (empty for most recent sketch).
        profile_sketch_name: Name of cross-section profile sketch.
        circular_profile_diameter_mm / diameter_mm: Diameter in mm for automatic circular sweep without profile sketch.
        """
        target_dia = circular_profile_diameter_mm if circular_profile_diameter_mm is not None else diameter_mm
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.boss_sweep(
                path_sketch_name=path_sketch_name,
                profile_sketch_name=profile_sketch_name,
                circular_profile_diameter_mm=target_dia,
            )
        )

    @mcp.tool()
    async def sw_cut_sweep(
        path_sketch_name: str = "",
        profile_sketch_name: str = "",
        circular_profile_diameter_mm: Optional[float] = None,
        diameter_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Create a 3D Swept Cut feature removing material along a trajectory path.
        Essential for internal oil galleries, curved porting tunnels, and grooves.

        path_sketch_name: Name of trajectory path sketch (empty for most recent sketch).
        profile_sketch_name: Name of cross-section profile sketch.
        circular_profile_diameter_mm / diameter_mm: Diameter in mm for automatic circular cut sweep without profile sketch.
        """
        target_dia = circular_profile_diameter_mm if circular_profile_diameter_mm is not None else diameter_mm
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.cut_sweep(
                path_sketch_name=path_sketch_name,
                profile_sketch_name=profile_sketch_name,
                circular_profile_diameter_mm=target_dia,
            )
        )

    @mcp.tool()
    async def sw_create_reference_plane(
        plane_name: str = "",
        first_reference: str = "Front Plane",
        constraint_type: str = "distance",
        distance_mm: float = 0.0,
        angle_deg: float = 0.0,
        second_reference: str = "",
        flip: bool = False,
    ) -> Dict[str, Any]:
        """
        Create a new datum Reference Plane in the active part or assembly.
        Essential for canted valves (e.g. 9.5 deg DOHC), offset deck planes, and angled spark plugs.

        plane_name: Custom name for the reference plane (empty for default auto-naming).
        first_reference: Name of reference plane or planar face (default 'Front Plane').
        constraint_type: 'distance' (default), 'angle', 'coincident', 'parallel', or 'perpendicular'.
        distance_mm: Offset distance in mm (when constraint_type='distance').
        angle_deg: Incline angle in degrees (when constraint_type='angle').
        second_reference: Optional rotation axis/edge or secondary plane.
        flip: Invert the offset/angle direction.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.create_reference_plane(
                plane_name=plane_name,
                first_reference=first_reference,
                constraint_type=constraint_type,
                distance_mm=distance_mm,
                angle_deg=angle_deg,
                second_reference=second_reference,
                flip=flip,
            )
        )

    @mcp.tool()
    async def sw_mirror_feature(
        plane_name: str,
        feature_name: str = "",
        mirror_body: bool = False,
        geometry_pattern: bool = False,
    ) -> Dict[str, Any]:
        """
        Mirror 3D features or solid bodies across a datum plane or planar face.
        Essential for symmetric crankshaft counterweights, conrod beams, paired intake/exhaust valves.

        plane_name: Reference plane or planar face name to mirror across (e.g. 'Front Plane', 'Right Plane').
        feature_name: Name of feature to mirror, or body name if mirror_body=True.
        mirror_body: True to mirror entire solid body; False to mirror specific feature (default False).
        geometry_pattern: True to pattern geometry directly without re-evaluating end conditions.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.mirror_feature(
                plane_name=plane_name,
                feature_name=feature_name,
                mirror_body=mirror_body,
                geometry_pattern=geometry_pattern,
            )
        )

    @mcp.tool()
    async def sw_add_sketch_constraint(
        constraint_type: str,
        x1_mm: Optional[float] = None,
        y1_mm: Optional[float] = None,
        x2_mm: Optional[float] = None,
        y2_mm: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Apply a geometric sketch constraint/relation to 2D sketch entities.
        constraint_type: 'horizontal', 'vertical', 'collinear', 'perpendicular', 'parallel',
                         'tangent', 'concentric', 'coincident', 'midpoint', 'equal', 'symmetric', or 'fix'.
        x1_mm, y1_mm: Optional 2D coordinates in mm to select first sketch segment/point.
        x2_mm, y2_mm: Optional 2D coordinates in mm to select second sketch segment/point.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().sketcher.add_sketch_constraint(
                constraint_type=constraint_type,
                x1_mm=x1_mm,
                y1_mm=y1_mm,
                x2_mm=x2_mm,
                y2_mm=y2_mm,
            )
        )

    @mcp.tool()
    async def sw_linear_pattern(
        feature_name: str,
        spacing1_mm: float,
        instances1: int = 2,
        dir1_entity: str = "Right Plane",
        spacing2_mm: float = 0.0,
        instances2: int = 1,
        dir2_entity: str = "",
        flip_dir1: bool = False,
        flip_dir2: bool = False,
    ) -> Dict[str, Any]:
        """
        Pattern a 3D feature linearly along one or two directional references.
        feature_name: Name of feature to pattern (e.g. 'Cut-Extrude1').
        spacing1_mm: Pitch spacing along Direction 1 in millimeters.
        instances1: Total instances along Direction 1 (>= 2).
        dir1_entity: Reference plane, edge, or axis for Direction 1.
        spacing2_mm: Pitch spacing along Direction 2 in millimeters.
        instances2: Total instances along Direction 2 (1 for single-direction).
        dir2_entity: Reference plane, edge, or axis for Direction 2.
        flip_dir1: Reverse Direction 1.
        flip_dir2: Reverse Direction 2.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.linear_pattern(
                feature_name=feature_name,
                spacing1_mm=spacing1_mm,
                instances1=instances1,
                dir1_entity=dir1_entity,
                spacing2_mm=spacing2_mm,
                instances2=instances2,
                dir2_entity=dir2_entity,
                flip_dir1=flip_dir1,
                flip_dir2=flip_dir2,
            )
        )

    @mcp.tool()
    async def sw_shell(
        thickness_mm: float,
        face_x_mm: Optional[float] = None,
        face_y_mm: Optional[float] = None,
        face_z_mm: Optional[float] = None,
        shell_outward: bool = False,
    ) -> Dict[str, Any]:
        """
        Hollow out a 3D solid body with constant wall thickness, removing the face at (face_x_mm, face_y_mm, face_z_mm).
        thickness_mm: Wall thickness in millimeters.
        face_x_mm, face_y_mm, face_z_mm: Optional 3D point on the planar/outer face to remove.
        shell_outward: True to grow wall thickness outward; False for inward.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.shell(
                thickness_mm=thickness_mm,
                face_x_mm=face_x_mm,
                face_y_mm=face_y_mm,
                face_z_mm=face_z_mm,
                shell_outward=shell_outward,
            )
        )

    @mcp.tool()
    async def sw_hole_wizard(
        hole_type: str = "tapped",
        standard: str = "ISO",
        fastener_size: str = "M6",
        diameter_mm: float = 6.0,
        depth_mm: float = 15.0,
        x_mm: float = 0.0,
        y_mm: float = 0.0,
        z_mm: float = 0.0,
        through_all: bool = False,
        counterbore_diameter_mm: float = 10.0,
        counterbore_depth_mm: float = 5.0,
        countersink_angle_deg: float = 90.0,
    ) -> Dict[str, Any]:
        """
        Create a standard manufacturing hole (Tapped, Counterbore, Countersink, or Simple) via HoleWizard5.
        hole_type: 'tapped', 'counterbore', 'countersink', or 'simple'.
        standard: Engineering standard ('ISO', 'ANSI Metric', 'ANSI Inch', 'DIN', 'JIS').
        fastener_size: Standard thread/fastener designation (e.g. 'M6', 'M8', 'M10').
        diameter_mm: Core hole diameter in millimeters.
        depth_mm: Hole depth in millimeters (when through_all=False).
        x_mm, y_mm, z_mm: 3D point on the target placement face in millimeters.
        through_all: True for Through-All end condition; False for Blind depth.
        counterbore_diameter_mm: Counterbore/countersink head diameter in mm.
        counterbore_depth_mm: Counterbore socket depth in mm.
        countersink_angle_deg: Countersink included angle in degrees (default 90.0°).
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.hole_wizard(
                hole_type=hole_type,
                standard=standard,
                fastener_size=fastener_size,
                diameter_mm=diameter_mm,
                depth_mm=depth_mm,
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=z_mm,
                through_all=through_all,
                counterbore_diameter_mm=counterbore_diameter_mm,
                counterbore_depth_mm=counterbore_depth_mm,
                countersink_angle_deg=countersink_angle_deg,
            )
        )

    @mcp.tool()
    async def sw_loft_boss(
        profile1_sketch: str,
        profile2_sketch: str,
        guide_curve_sketch: str = "",
        closed_loft: bool = False,
        thin_feature: bool = False,
        thin_thickness_mm: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Create a 3D Lofted Boss blending smoothly between two sketch profiles.
        profile1_sketch: Name of first profile sketch (e.g. 'Sketch1').
        profile2_sketch: Name of second profile sketch (e.g. 'Sketch2').
        guide_curve_sketch: Optional guide curve sketch name.
        closed_loft: True to close loft loop smoothly.
        thin_feature: True to create a thin-walled loft.
        thin_thickness_mm: Wall thickness in mm when thin_feature=True.
        """
        worker = get_sta_worker()
        return await worker.run(
            lambda: get_cad_session().features.loft_boss(
                profile1_sketch=profile1_sketch,
                profile2_sketch=profile2_sketch,
                guide_curve_sketch=guide_curve_sketch,
                closed_loft=closed_loft,
                thin_feature=thin_feature,
                thin_thickness_mm=thin_thickness_mm,
            )
        )
