# SolidWorks 2026 CAD Automation Rules

When creating, modifying, assembling, or drafting engineering models in SolidWorks 2026 SP4.1 via the `solidworks_cad` MCP server:

## 1. Units and Input Standards
- **Always use millimeter (mm) and degree (deg) values**: All geometric tool parameters (`_mm`, `_deg`) expect standard engineering dimensions in mm and degrees. The server handles internal conversions to SolidWorks SI units (meters, radians). Never pre-convert coordinates to meters.
- **Inspect mass properties in grams and mm³**: Mass property responses (`sw_get_mass_properties`) report mass in grams, volume in mm³, and surface area in mm².

## 2. Geometric Grounding and Feature Sequences
- **Verify active session state**: Always invoke `sw_get_session_info` or `sw_list_open_documents` before initiating sketches or feature operations.
- **Reference planes**: Default planes are named `"Front Plane"`, `"Top Plane"`, and `"Right Plane"`. Ensure sketches are properly closed (`sw_close_sketch`) before creating solid extrusions (`sw_boss_extrude`) or revolves (`sw_revolve_boss`).
- **Sweeps and Profiles**: When using `sw_boss_sweep` or `sw_cut_sweep`, ensure the trajectory path sketch is created and exited first. Circular profiles are generated directly by specifying `circular_profile_diameter_mm` (or alias `diameter_mm`).
- **Patterns**: For `sw_circular_pattern`, provide required `feature_name`, and either `axis_entity_name` or cylindrical face coordinates `(axis_x_mm, axis_y_mm, axis_z_mm)`.
- **Rebuilds**: Invoke `sw_rebuild()` (accepts optional `force=True`) to regenerate geometry.
- **Fillets & Chamfers**: Pass `radius_mm` / `distance_mm` and optional edge coordinates `(edge_x_mm, edge_y_mm, edge_z_mm)`. Do not pass string lists.

## 3. Assembly and Kinematic Constraints
- **Ground the primary component**: Insert the first component using `sw_insert_component(component_path=...)` and immediately ground it using `sw_set_component_fixed(component_name=..., fixed=True)` to eliminate unconstrained rigid body motion. Note: `sw_insert_component` does not accept a `fixed` argument.
- **Mate references**: Use `sw_add_mate(mate_type, entity1, entity2, alignment='aligned', flip=False, distance_mm=0.0, angle_deg=0.0)`. Pass entity references as single strings: either plane/feature name (`'Top Plane@part1-1'`) or spatial coordinate hint (`'FACE:x,y,z'`, `'EDGE:x,y,z'`).
- **Interference verification**: Run `sw_check_interference` after mating components to confirm zero volume clash before finalizing assemblies.

## 4. 2D Drafting and Manufacturing Documentation
- **Save prior to drafting**: Drawing views reference disk files. Always save parts (`sw_save_doc(output_path=...)`) before creating drawing documents (`sw_new_drawing`).
- **Section views**: Use `sw_create_section_view(parent_view_name, cut_start_x_mm, cut_start_y_mm, cut_end_x_mm, cut_end_y_mm, placement_x_mm, placement_y_mm, section_label='A', reverse_direction=False)` to document internal bores, porting, and fluid passages.
- **Exporting artifacts**: Export production-ready sheets using `sw_export_drawing(output_path=..., format_type='pdf')` and capture high-resolution renders with `sw_capture_viewport(output_path=...)`.

## 5. Token Efficiency and Context Management
- **Targeted Queries**: Always filter `sw_list_materials` with a specific keyword (`search='...'` or `classification='...'`) to avoid context window flooding.
- **Periodic Compaction**: In long CAD sessions involving multiple parts or assemblies, recommend `/compact` after completing each discrete component milestone to prevent attention degradation and token exhaustion.
