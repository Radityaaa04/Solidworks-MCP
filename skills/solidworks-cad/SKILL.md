---
name: solidworks-cad
description: Autonomous CAD engineering, 3D parametric modeling, kinematic assembly, mass properties analysis, and 2D drafting automation for SolidWorks 2026 SP4.1 using 58 dedicated tools. Use when creating 3D CAD parts, running assemblies, applying materials, generating engineering drawings, and rendering photorealistic views.
---

# SolidWorks 2026 CAD Automation Skill

This skill guides agents in driving **SolidWorks 2026 SP4.1** autonomously via the 58 tools exposed by the `solidworks_cad` MCP server.

## 1. Tool Catalog & Exact Schemas (58 Tools)

### A. Document Lifecycle & Session (8 Tools)
- `sw_get_session_info()`: Checks connection status and active document in SolidWorks.
- `sw_new_part(template_path: str = "")`: Creates a new blank Part document.
- `sw_new_assembly(template_path: str = "")`: Creates a new blank Assembly document.
- `sw_new_drawing(template_path: str = "")`: Creates a new 2D Engineering Drawing document.
- `sw_open_doc(file_path: str, doc_type: str = "auto")`: Opens an existing CAD file (`doc_type`: "auto", "part", "assembly", "drawing").
- `sw_save_doc(output_path: Optional[str] = None, file_path: Optional[str] = None)`: Saves the active document. Provide `output_path` to Save-As, or omit to save in-place.
- `sw_close_doc(save_changes: bool = False)`: Closes the active document safely.
- `sw_list_open_documents()`: Lists all CAD documents currently open in the session.

### B. 2D Sketching & Wireframe (11 Tools)
- `sw_create_sketch_on_plane(plane_name: str = "Front Plane")`: Opens a sketch on a standard plane ("Front Plane", "Top Plane", "Right Plane").
- `sw_create_sketch_on_face(x_mm: float, y_mm: float, z_mm: float)`: Opens a sketch on a planar face at given 3D coordinates.
- `sw_close_sketch()`: Closes and exits the active sketch.
- `sw_draw_line(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float)`: Draws a 2D line segment between two points.
- `sw_draw_centerline(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float)`: Draws a construction centerline for revolution axes and symmetry.
- `sw_draw_rectangle(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float)`: Draws a corner rectangle between corner1 (x1, y1) and corner2 (x2, y2).
- `sw_draw_circle(center_x_mm: float, center_y_mm: float, radius_mm: float)`: Draws a 2D circle.
- `sw_draw_arc(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float, x3_mm: float, y3_mm: float)`: Draws a 3-point circular arc from (x1,y1) to (x2,y2) passing through (x3,y3).
- `sw_create_3d_sketch()`: Creates and activates an unconstrained 3D Sketch for Phase 0 master kinematic skeletons and layout wireframes.
- `sw_draw_3d_line(x1_mm: float, y1_mm: float, z1_mm: float, x2_mm: float, y2_mm: float, z2_mm: float)`: Draws a 3D line segment between two spatial coordinates in millimeters within an active 3D sketch.
- `sw_add_sketch_constraint(constraint_type: str, x1_mm: Optional[float] = None, y1_mm: Optional[float] = None, x2_mm: Optional[float] = None, y2_mm: Optional[float] = None)`: Applies a geometric sketch relation ('horizontal', 'vertical', 'collinear', 'perpendicular', 'parallel', 'tangent', 'concentric', 'coincident', 'midpoint', 'equal', 'symmetric', 'fix').

### C. 3D Feature Modeling (16 Tools)
- `sw_boss_extrude(depth_mm: float, flip_dir: bool = False)`: Extrudes the active closed sketch into a solid boss.
- `sw_cut_extrude(depth_mm: float, flip_dir: bool = False)`: Cuts material into a solid body using the active sketch.
- `sw_revolve_boss(angle_deg: float = 360.0, reverse_dir: bool = False)`: Revolves active sketch profile around its centerline axis.
- `sw_revolve_cut(angle_deg: float = 360.0, reverse_dir: bool = False)`: Cuts a revolved groove or cavity from a solid body.
- `sw_boss_sweep(path_sketch_name: str = "", profile_sketch_name: str = "", circular_profile_diameter_mm: Optional[float] = None, diameter_mm: Optional[float] = None)`: Creates a swept solid boss along a 3D path curve with circular profile.
- `sw_cut_sweep(path_sketch_name: str = "", profile_sketch_name: str = "", circular_profile_diameter_mm: Optional[float] = None, diameter_mm: Optional[float] = None)`: Cuts a swept hollow channel or fluid port along a 3D path curve.
- `sw_fillet(radius_mm: float, edge_x_mm: Optional[float] = None, edge_y_mm: Optional[float] = None, edge_z_mm: Optional[float] = None)`: Rounds selected edges, or edge at given 3D coordinates.
- `sw_chamfer(distance_mm: float, angle_deg: float = 45.0, edge_x_mm: Optional[float] = None, edge_y_mm: Optional[float] = None, edge_z_mm: Optional[float] = None)`: Bevels selected edges, or edge at given 3D coordinates.
- `sw_circular_pattern(feature_name: str, total_instances: int = 6, total_angle_deg: float = 360.0, equal_spacing: bool = True, axis_x_mm: Optional[float] = None, axis_y_mm: Optional[float] = None, axis_z_mm: Optional[float] = None, axis_entity_name: str = "", flip_dir: bool = False, spacing_deg: Optional[float] = None, axis_name: str = "", reverse_dir: bool = False)`: Patterns features radially around an axis or cylindrical face coordinate. Note: `feature_name` is required.
- `sw_linear_pattern(feature_name: str, spacing1_mm: float, instances1: int = 2, dir1_entity: str = "Right Plane", spacing2_mm: float = 0.0, instances2: int = 1, dir2_entity: str = "", flip_dir1: bool = False, flip_dir2: bool = False)`: Patterns a 3D feature linearly along one or two directional references.
- `sw_shell(thickness_mm: float, face_x_mm: Optional[float] = None, face_y_mm: Optional[float] = None, face_z_mm: Optional[float] = None, shell_outward: bool = False)`: Hollows out a solid body with constant wall thickness, removing the specified face.
- `sw_hole_wizard(hole_type: str = "tapped", standard: str = "ISO", fastener_size: str = "M6", diameter_mm: float = 6.0, depth_mm: float = 15.0, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0, through_all: bool = False, counterbore_diameter_mm: float = 10.0, counterbore_depth_mm: float = 5.0, countersink_angle_deg: float = 90.0)`: Creates standardized ISO/ANSI tapped, counterbore, countersink, or simple holes via HoleWizard5.
- `sw_loft_boss(profile1_sketch: str, profile2_sketch: str, guide_curve_sketch: str = "", closed_loft: bool = False, thin_feature: bool = False, thin_thickness_mm: float = 1.0)`: Creates a 3D Lofted Boss blending between two sketch profiles.
- `sw_rebuild(force: bool = True)`: Forces full model regeneration and updates FeatureManager dependencies.
- `sw_create_reference_plane(plane_name: str = "", first_reference: str = "Front Plane", constraint_type: str = "distance", distance_mm: float = 0.0, angle_deg: float = 0.0, second_reference: str = "", flip: bool = False)`: Creates a new datum Reference Plane with distance offset, angle incline, or coincident constraints.
- `sw_mirror_feature(plane_name: str, feature_name: str = "", mirror_body: bool = False, geometry_pattern: bool = False)`: Mirrors features or solid bodies across a datum reference plane or planar face.

### D. Parametric Equations & Variables (3 Tools)
- `sw_get_equations()`: Lists all global variables and equations defined in the model.
- `sw_set_global_variable(name: str, value: float, unit: str = "mm")`: Adds or updates a Global Variable with unit safety.
- `sw_modify_dimension(dimension_name: str, value_mm: float)`: Updates a specific dimension directly (e.g. `D1@Sketch1`) and rebuilds.

### E. Physical Inspection & Multimodal Vision (4 Tools)
- `sw_get_mass_properties()`: Computes mass ($g$), volume ($mm^3$), surface area ($mm^2$), center of mass, and moments of inertia.
- `sw_get_feature_tree()`: Lists all features and datum planes in the FeatureManager design tree.
- `sw_capture_viewport(output_path: str = "output/viewport_render.png")`: Captures the active 3D model viewport into a high-res PNG image.
- `sw_export_cad(output_path: str)`: Exports 3D models to STEP, STL, Parasolid (.x_t), DXF, or PDF determined by file extension.

### F. Material Engineering (3 Tools)
- `sw_set_material(material_name: str, database_name: str = "SolidWorks Materials", config_name: str = "")`: Assigns standard materials (e.g. 'AISI 1020', '6061 Alloy', 'Cast Alloy Steel'). Pass `''` to clear material.
- `sw_get_material(config_name: str = "")`: Queries the assigned material, density, and mechanical properties.
- `sw_list_materials(classification: Optional[str] = None, search: Optional[str] = None)`: Browses and searches available engineering materials in SolidWorks.

### G. Kinematic Assembly & Mating (6 Tools)
- `sw_new_assembly(template_path: str = "")`: Creates a new blank assembly document.
- `sw_insert_component(component_path: str, x_mm: float = 0.0, y_mm: float = 0.0, z_mm: float = 0.0, config_name: str = "")`: Inserts a part or sub-assembly into the active assembly.
- `sw_set_component_fixed(component_name: str, fixed: bool = True, is_fixed: Optional[bool] = None)`: Grounds (fixes) or un-grounds (floats) a component.
- `sw_add_mate(mate_type: str, entity1: str, entity2: str, alignment: str = "aligned", flip: bool = False, distance_mm: float = 0.0, angle_deg: float = 0.0)`: Applies kinematic mates ('coincident', 'concentric', 'perpendicular', 'parallel', 'tangent', 'distance', 'angle', 'lock'). `entity1`/`entity2` are plane/feature names (e.g. `'Top Plane@part1-1'`) or spatial hints (`'FACE:x,y,z'`, `'EDGE:x,y,z'`).
- `sw_list_components(top_level_only: bool = True)`: Lists all components in assembly with suppression, grounding state, and bounding boxes.
- `sw_check_interference(treat_coincidence_as_interference: bool = False)`: Detects mechanical collisions and clash volumes.

### H. 2D Drafting & Manufacturing Drawings (9 Tools)
- `sw_new_drawing(template_path: str = "")`: Creates a new 2D drawing sheet.
- `sw_create_drawing_view(model_path: str, orientation: str = "*Front", x_mm: float = 100.0, y_mm: float = 100.0, scale: str = "1:1")`: Inserts a model view ('*Front', '*Top', '*Right', '*Isometric').
- `sw_create_standard_views(model_path: str, center_x_mm: float = 150.0, center_y_mm: float = 120.0, spacing_mm: float = 90.0, include_isometric: bool = True, scale: str = "1:1")`: Automatically generates standard 3-view orthogonal projections + optional Isometric.
- `sw_create_section_view(parent_view_name: str, cut_start_x_mm: float, cut_start_y_mm: float, cut_end_x_mm: float, cut_end_y_mm: float, placement_x_mm: float, placement_y_mm: float, section_label: str = "A", reverse_direction: bool = False)`: Generates dynamic Section Views (e.g. Section A-A) along a cutting line.
- `sw_list_drawing_views()`: Enumerates all drawing views on the active sheet.
- `sw_auto_dimension(view_name: str, scheme: str = "baseline", horizontal_placement: str = "above", vertical_placement: str = "right")`: Automatically places dimensions on a specified view.
- `sw_add_drawing_note(text: str, x_mm: float = 20.0, y_mm: float = 20.0)`: Inserts an annotation note or title block label.
- `sw_insert_bom_table(view_name: str, x_mm: float = 200.0, y_mm: float = 50.0, bom_type: str = "top_level", configuration: str = "Default", table_template: str = "")`: Inserts a manufacturing Bill of Materials (BOM) table on the active drawing sheet.
- `sw_export_drawing(output_path: str, format_type: str = "auto")`: Silently exports drawing to PDF, DXF, DWG, or native SLDDRW.

---

## 2. Standard Workflows (Synchronized with Exact Tool Schemas)

### Workflow 1: Parametric 3D Part Design
1. Initialize part: `sw_new_part()`.
2. Sketch base profile on "Front Plane": `sw_create_sketch_on_plane(plane_name="Front Plane")`.
3. Draw geometry using mm coordinates (`sw_draw_circle`, `sw_draw_rectangle`, etc.).
4. Exit sketch: `sw_close_sketch()`.
5. Boss extrude or revolve: `sw_boss_extrude(depth_mm=25.0)` or `sw_revolve_boss(angle_deg=360.0)`.
6. Add secondary features:
   - For ports/runners: create 3D path curve, exit sketch, and call `sw_boss_sweep(circular_profile_diameter_mm=12.0)`.
   - For teeth/bolt circles: cut single tooth via `sw_cut_extrude(depth_mm=...)` and pattern via `sw_circular_pattern(feature_name="Cut-Extrude1", total_instances=18, total_angle_deg=360.0, axis_x_mm=0, axis_y_mm=0, axis_z_mm=0)`.
   - For stress relief: call `sw_fillet(radius_mm=2.0)`.
7. Assign material: `sw_set_material(material_name="6061 Alloy")`.
8. Verify volume and mass: `sw_get_mass_properties()`.
9. Save to disk: `sw_save_doc(output_path="c:/models/gear.sldprt")`.

### Workflow 2: Kinematic Assembly
1. Initialize assembly: `sw_new_assembly()`.
2. Insert base grounding component: `sw_insert_component(component_path="c:/models/housing.sldprt", x_mm=0.0, y_mm=0.0, z_mm=0.0)`.
3. Ground base component: `sw_set_component_fixed(component_name="housing-1", fixed=True)`.
4. Insert second component: `sw_insert_component(component_path="c:/models/shaft.sldprt", x_mm=50.0, y_mm=0.0, z_mm=0.0)`.
5. Apply mates (e.g., concentric for shaft in bore, coincident for seating face):
   - `sw_add_mate(mate_type="concentric", entity1="FACE:0,0,0", entity2="FACE:50,0,0")`
   - `sw_add_mate(mate_type="coincident", entity1="Front Plane@housing-1", entity2="Front Plane@shaft-1")`
6. Verify assembly clearances: `sw_check_interference()`.
7. Save assembly: `sw_save_doc(output_path="c:/models/gearbox.sldasm")`.

### Workflow 3: Production 2D Drafting
1. Ensure the 3D model is saved to disk.
2. Initialize drawing: `sw_new_drawing()`.
3. Insert standard views: `sw_create_standard_views(model_path="c:/models/gear.sldprt", center_x_mm=150.0, center_y_mm=120.0, spacing_mm=90.0)`.
4. Add internal section view:
   - `sw_create_section_view(parent_view_name="Drawing View1", cut_start_x_mm=150.0, cut_start_y_mm=70.0, cut_end_x_mm=150.0, cut_end_y_mm=170.0, placement_x_mm=320.0, placement_y_mm=120.0, section_label="A")`.
5. Add manufacturing note: `sw_add_drawing_note(text="MATERIAL: 6061-T6 ALUMINUM\\nTOLERANCE: +/- 0.05mm", x_mm=20.0, y_mm=20.0)`.
6. Export to PDF: `sw_export_drawing(output_path="c:/models/gear_blueprint.pdf", format_type="pdf")`.

---

## 3. Grounding & Anti-Hallucination Guidelines
- Never invent parameters that do not exist in the tool schemas above.
- Always verify active document status using `sw_get_session_info()` or `sw_list_open_documents()` before issuing geometric operations.
- Always check return values of `sw_get_mass_properties()` to ensure solid volume $> 0$ after extrusions or cuts.

## 4. LLM Token Efficiency & Context Management
- **Query Tool Filtering**: When querying engineering materials with `sw_list_materials(search="1020")`, always provide a specific search query or classification keyword rather than dumping the full catalog.
- **Context Compaction**: In multi-part CAD sessions (e.g. engine development), recommend the `/compact` command after completing each major component (e.g. after modeling the crankshaft or piston) to keep the context window lean (< 25k tokens).
- **Subagent Workflows**: For independent component modeling, delegate the construction of individual parts to subagents to prevent monolithic context expansion.
