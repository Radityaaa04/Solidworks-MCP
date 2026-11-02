# SolidWorks 2026 Model Context Protocol (MCP) Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks 2026](https://img.shields.io/badge/SolidWorks-2026-red.svg)](https://www.solidworks.com/)
[![MCP Standard](https://img.shields.io/badge/MCP-Standard-green.svg)](https://modelcontextprotocol.io/)

Production-grade, thread-safe Model Context Protocol (MCP) server for **SolidWorks 2026** (and 2023–2025) CAD automation. Enables LLMs (Antigravity, Claude Desktop, Cursor, Claude Code) to create parts, generate 2D/3D sketches, build parametric 3D features, manage assemblies & mates, apply engineering materials, generate technical 2D drawings, inspect mass properties, modify parametric equations, and close the visual feedback loop via multimodal viewport capture.

---

## 🏛️ Architecture & Reliability Highlights

Unlike basic hobbyist scripts, this server is engineered for mission-critical stability:

1. **Dedicated STA COM Worker Queue**: SolidWorks is strictly a Single-Threaded Apartment (STA) COM server. All COM calls are dispatched sequentially through a dedicated background thread running `pythoncom.CoInitializeEx(COINIT_APARTMENTTHREADED)` with continuous Windows Message Pumping (`pythoncom.PumpWaitingMessages()`), preventing RPC deadlocks and `0x8001010E (RPC_E_WRONG_THREAD)`.
2. **Zero COM Pointer Leaks**: Raw COM dispatch pointers (`win32com.client.CDispatch`) never cross thread boundaries. All results are converted into pure Python dictionaries / DTOs before reaching the asyncio event loop.
3. **Dual Unit Normalization**:
   - Direct Geometry API calls (lines, circles, extrusions, sweeps) are strictly converted from millimeters to SolidWorks internal SI **Meters**.
   - Equation Manager calls format explicit unit strings (e.g. `"Thickness" = 10mm`) to prevent document unit corruption.
4. **Silent Error Suppression**: Configured with `swShowErrorsEveryRebuild = False` and `swOpenDocOptions_Silent` to eliminate blocking Windows modal pop-ups during automated execution.
5. **Safe Rollback**: Does not blindly call `EditUndo()` on extrusion failure; instead, it safely terminates dangling sketch modes (`InsertSketch(True)`) and selectively deletes corrupt features via `feat.Select2()` + `EditDelete()`.
6. **Clean stdio Transport**: Logging is strictly redirected to `sys.stderr` to keep `sys.stdout` 100% clean for JSON-RPC frames.

---

## 🛠️ Registered MCP Tools (52 Dedicated CAD Tools)

### 1. Document Lifecycle & Export (8 Tools)
- `sw_get_session_info`: Check SolidWorks connection, revision, and active document.
- `sw_new_part`: Create a new blank Part document using auto-detected or custom template.
- `sw_new_assembly`: Create a new blank Assembly document.
- `sw_open_doc`: Open an existing `.sldprt`, `.sldasm`, or `.slddrw` silently.
- `sw_save_doc`: Save active document in-place or to a new path.
- `sw_close_doc`: Close active document with optional save.
- `sw_list_open_documents`: List all open CAD files in the session.
- `sw_export_cad`: Export to STEP (AP214), STL, Parasolid (`.x_t`), DXF, or PDF.

### 2. 2D Sketching & Parametric Features (15 Tools)
- `sw_create_sketch_on_plane`: Activate sketch on "Front Plane", "Top Plane", or "Right Plane" (with multi-lingual resolution).
- `sw_create_sketch_on_face`: Activate sketch directly on a planar model face via spatial coordinate hints.
- `sw_close_sketch`: Exit active sketch mode.
- `sw_draw_line`: Draw 2D line segment between two points (in mm).
- `sw_draw_centerline`: Draw 2D construction centerline for revolve axes and symmetry (in mm).
- `sw_draw_rectangle`: Draw 2D corner rectangle from $(x_1, y_1)$ to $(x_2, y_2)$ (in mm).
- `sw_draw_circle`: Draw 2D circle with center and radius (in mm).
- `sw_draw_arc`: Draw 2D three-point arc (in mm).
- `sw_boss_extrude`: Extrude active sketch profile into a 3D solid boss (in mm).
- `sw_cut_extrude`: Remove material with active sketch profile (in mm).
- `sw_revolve_boss`: Revolve sketch profile around axis entity (in degrees).
- `sw_revolve_cut`: Revolve cut material around axis entity (in degrees).
- `sw_fillet`: Apply constant-radius fillet on selected edges/faces (in mm).
- `sw_chamfer`: Apply angle-distance chamfer on selected edges (in mm & degrees).
- `sw_rebuild`: Force complete model regeneration and verify constraint sanity.

### 3. Advanced Features & Kinematic Skeleton (7 Tools)
- `sw_boss_sweep`: Sweep solid body along trajectory path with circular or sketch profile.
- `sw_cut_sweep`: Cut sweep material along trajectory path.
- `sw_circular_pattern`: Pattern feature circularly around cylindrical axis or coordinates.
- `sw_create_reference_plane`: Create reference datum planes with distance offset, angle inclination, parallel, coincident, or perpendicular constraints.
- `sw_mirror_feature`: Mirror features or solid bodies across reference datum planes.
- `sw_create_3d_sketch`: Activate 3D sketch mode for multi-plane master kinematic wireframes.
- `sw_draw_3d_line`: Draw 3D spatial vector line segment $(x_1, y_1, z_1)$ to $(x_2, y_2, z_2)$.

### 4. Assemblies & Kinematic Constraints (5 Tools)
- `sw_insert_component`: Insert external part/subassembly into active assembly document.
- `sw_set_component_fixed`: Ground/fix or float assembly components.
- `sw_add_mate`: Add geometric mates (`coincident`, `concentric`, `parallel`, `perpendicular`, `distance`, `angle`).
- `sw_list_components`: List all assembly components and suppression states.
- `sw_check_interference`: Run clash detection and verify zero interference volume.

### 5. Materials & Engineering Properties (3 Tools)
- `sw_set_material`: Apply engineering material from SolidWorks material database (e.g., AISI 1020, 6061-T6 Aluminum).
- `sw_get_material`: Retrieve current assigned material and database origin.
- `sw_list_materials`: List available materials within a specified database.

### 6. Parametric Equations & Dimensions (3 Tools)
- `sw_get_equations`: List all global variables and parametric equations in the active document.
- `sw_set_global_variable`: Add or modify global variables with strict unit formatting.
- `sw_modify_dimension`: Modify specific feature/sketch dimension values directly.

### 7. Technical 2D Drafting & Manufacturing Documentation (8 Tools)
- `sw_new_drawing`: Create new 2D technical drawing from template.
- `sw_create_drawing_view`: Create standard named view (Front, Top, Isometric, etc.).
- `sw_create_standard_views`: Generate automatic 3-view standard engineering layout.
- `sw_create_section_view`: Generate full or offset cutting section view (e.g. Section A-A) with directional arrows.
- `sw_list_drawing_views`: List all drawing views on active drawing sheet.
- `sw_auto_dimension`: Automatically generate baseline manufacturing dimensions.
- `sw_add_drawing_note`: Insert engineering title block or callout notes.
- `sw_export_drawing`: Export drawing sheet directly to PDF or DXF.

### 8. Inspection & Multimodal Vision (3 Tools)
- `sw_get_mass_properties`: Compute mass (g/kg), volume ($mm^3$), surface area ($mm^2$), and Center of Mass coordinates.
- `sw_get_feature_tree`: Traverse and inspect the complete hierarchical feature tree.
- `sw_capture_viewport`: Capture active 3D model viewport into a high-res PNG image for multimodal LLM visual verification.

---

## 🚀 Quickstart & Installation

### Requirements
- **Windows 10 / 11 (64-bit)**
- **SolidWorks 2023, 2024, 2025, or 2026** installed and licensed
- **Python 3.10+ (64-bit)** or [uv](https://docs.astral.sh/uv/)

### Installation via uv
```powershell
git clone <repository_url>
cd solidworks-mcp
uv sync
```

---

## ⚙️ Configuration for MCP Clients

### Claude Desktop (`claude_desktop_config.json`)
Location: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\solidworks-mcp",
        "run",
        "python",
        "-m",
        "sw_mcp.server"
      ]
    }
  }
}
```

### Antigravity (`mcp_config.json`)
```json
{
  "mcpServers": {
    "solidworks_cad": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\path\\to\\solidworks-mcp",
        "run",
        "python",
        "-m",
        "sw_mcp.server"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

---

## 🧪 Testing & Verification

The suite includes offline mock AST contract tests and live COM validation:

```powershell
# 1. Run full unit and registration tests
uv run pytest tests/ -v

# 2. Run Protocol Contract verification (AST & schema compliance)
uv run python tests/validation/protocol_contract.py

# 3. Run Offline Core test suite
uv run python tests/validation/offline_core.py
```
