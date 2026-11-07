"""Material Assignment, Physical Properties & Engineering Database Catalog for SolidWorks.

Enables applying engineering materials (e.g. AISI 1020, 6061 Alloy, Brass, ABS),
querying active material configurations, parsing standard mechanical properties
(tensile strength, yield strength, elastic modulus, Poisson's ratio), and
catalog discovery across SolidWorks material databases (.sldmat).
"""

import logging
import os
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

import pythoncom
import win32com.client
from sw_mcp.cad.document import DocumentManager
from sw_mcp.core.exceptions import DocumentNotFoundError, SolidWorksError

logger = logging.getLogger("sw_mcp.cad.material")

# Standard SolidWorks material database search paths
DEFAULT_SLDMAT_PATHS = [
    r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english\sldmaterials\solidworks materials.sldmat",
    r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\english\sldmaterials\SolidWorks DIN Materials.sldmat",
    r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\Custom Materials\Custom Materials.sldmat",
]


class MaterialManager:
    """Manages physical material assignment, queries, and engineering property catalogs."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr
        self._cache_initialized = False
        self._materials_catalog: Dict[str, Dict[str, Any]] = {}
        self._classifications: Dict[str, List[str]] = {}

    def _ensure_catalog_cache(self) -> None:
        """Parse standard .sldmat XML databases once to build local engineering catalog cache."""
        if self._cache_initialized:
            return

        for path in DEFAULT_SLDMAT_PATHS:
            if not os.path.exists(path):
                continue
            try:
                tree = ET.parse(path)
                root = tree.getroot()
                db_name = os.path.basename(path)

                for elem in root.iter():
                    if elem.tag.endswith("classification"):
                        class_name = elem.attrib.get("name", "General")
                        if class_name not in self._classifications:
                            self._classifications[class_name] = []

                        for mat in elem.iter():
                            if mat.tag.endswith("material"):
                                mat_name = mat.attrib.get("name")
                                if not mat_name:
                                    continue

                                if mat_name not in self._classifications[class_name]:
                                    self._classifications[class_name].append(mat_name)

                                # Extract physical & mechanical properties
                                props: Dict[str, Any] = {
                                    "name": mat_name,
                                    "classification": class_name,
                                    "database_file": db_name,
                                }
                                for pprops in mat.iter():
                                    if pprops.tag.endswith("physicalproperties"):
                                        for prop_elem in pprops:
                                            tag = prop_elem.tag.split("}")[-1]
                                            disp = prop_elem.attrib.get("displayname", tag)
                                            val_str = prop_elem.attrib.get("value", "")
                                            try:
                                                val = float(val_str)
                                            except (ValueError, TypeError):
                                                val = val_str
                                            props[disp] = val

                                self._materials_catalog[mat_name.lower()] = props

            except Exception as e:
                logger.warning("Failed parsing material database %s: %s", path, e)

        self._cache_initialized = True

    def list_materials(
        self, classification: Optional[str] = None, search: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List available materials from the engineering catalog,
        with optional classification filter (e.g. 'Steel', 'Aluminium Alloys')
        or search keyword (e.g. '1020', 'Brass').
        """
        self._ensure_catalog_cache()

        results: Dict[str, List[str]] = {}
        target_class = classification.lower() if classification else None
        target_search = search.lower() if search else None

        for c_name, mats in self._classifications.items():
            if target_class and target_class not in c_name.lower():
                continue

            filtered_mats = []
            for m in mats:
                if target_search and target_search not in m.lower():
                    continue
                filtered_mats.append(m)

            if filtered_mats:
                results[c_name] = filtered_mats

        total_matches = sum(len(m) for m in results.values())
        return {
            "total_matches": total_matches,
            "filter_classification": classification,
            "filter_search": search,
            "classifications": results,
        }

    def get_material_properties(self, material_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve mechanical and physical properties for a material from the catalog."""
        self._ensure_catalog_cache()
        return self._materials_catalog.get(material_name.strip().lower())

    def get_active_part(self) -> Any:
        """Retrieve the active ModelDoc2 part instance or raise error if not a Part."""
        doc = self.doc_mgr.get_active_doc()
        # In SolidWorks: swDocPART = 1
        if doc.GetType != 1:
            raise SolidWorksError(
                f"Material operations are only valid for Part documents (.sldprt). Active document type is {doc.GetType}."
            )
        return doc

    def get_material(self, config_name: str = "") -> Dict[str, Any]:
        """
        Query the material currently assigned to the active part document.
        config_name: Specific configuration name, or empty string for active configuration.
        """
        doc = self.get_active_part()

        active_config_name = "Default"
        try:
            config = doc.ConfigurationManager.ActiveConfiguration
            if config and getattr(config, "Name", None):
                active_config_name = str(config.Name)
        except Exception:
            pass

        if not config_name:
            config_name = active_config_name

        database_name = ""
        material_name = ""

        # Method 1: IPartDoc.GetMaterialPropertyName2 via VT_BYREF VARIANT
        try:
            v_db = win32com.client.VARIANT(
                pythoncom.VT_BYREF | pythoncom.VT_BSTR, ""
            )
            raw_name = doc.GetMaterialPropertyName2(config_name, v_db)
            if raw_name:
                material_name = str(raw_name).strip()
            if v_db.value:
                database_name = str(v_db.value).strip()
        except Exception as e:
            logger.debug("GetMaterialPropertyName2 query failed: %s", e)

        # Method 2: Fallback / complement via MaterialIdName (must contain pipe format: Database|Material|Id)
        if not material_name:
            try:
                mat_id = getattr(doc, "MaterialIdName", "")
                if mat_id and "|" in str(mat_id):
                    parts = str(mat_id).split("|")
                    if len(parts) >= 2:
                        database_name = parts[0]
                        material_name = parts[1]
            except Exception as e:
                logger.debug("MaterialIdName fallback failed: %s", e)

        # Look up mechanical properties from catalog
        props = self.get_material_properties(material_name) if material_name else None

        # Query density corresponding to the requested configuration
        density_kg_m3 = 0.0
        is_active_config = config_name.strip().lower() == active_config_name.strip().lower()
        if is_active_config:
            try:
                mp = doc.Extension.CreateMassProperty
                if mp:
                    density_kg_m3 = round(float(mp.Density), 3)
            except Exception:
                pass
            if density_kg_m3 == 0.0 and props and isinstance(props.get("Mass Density"), (int, float)):
                density_kg_m3 = round(float(props["Mass Density"]), 3)
        else:
            if props and isinstance(props.get("Mass Density"), (int, float)):
                density_kg_m3 = round(float(props["Mass Density"]), 3)
            else:
                try:
                    show_cfg = getattr(doc, "ShowConfiguration2", None)
                    if callable(show_cfg) and show_cfg(config_name):
                        try:
                            mp = doc.Extension.CreateMassProperty
                            if mp:
                                density_kg_m3 = round(float(mp.Density), 3)
                        finally:
                            show_cfg(active_config_name)
                except Exception:
                    pass

        return {
            "assigned": bool(material_name),
            "material_name": material_name or "None",
            "database": database_name or "None",
            "configuration": config_name,
            "density_kg_m3": density_kg_m3,
            "density_g_cm3": round(density_kg_m3 / 1000.0, 5),
            "mechanical_properties": props,
        }

    def set_material(
        self,
        material_name: str,
        database_name: str = "SolidWorks Materials",
        config_name: str = "",
    ) -> Dict[str, Any]:
        """
        Assign an engineering material to the active part configuration.

        material_name: Name of the material (e.g. 'AISI 1020', '6061 Alloy', 'Brass').
                       Pass empty string '' to remove/clear the assigned material.
        database_name: Name of the database (e.g. 'SolidWorks Materials' or full path).
        config_name: Target configuration name, or empty string for active configuration.
        """
        doc = self.get_active_part()

        if not config_name:
            config = doc.ConfigurationManager.ActiveConfiguration
            config_name = config.Name if config else "Default"

        target_material = material_name.strip()
        target_db = database_name.strip()

        # Execute assignment via SetMaterialPropertyName2
        try:
            doc.SetMaterialPropertyName2(config_name, target_db, target_material)
        except Exception as e:
            raise SolidWorksError(
                f"Failed calling SetMaterialPropertyName2 with material '{target_material}' "
                f"on config '{config_name}': {e}"
            ) from e

        # Force rebuild to recalculate mass and physical properties
        try:
            doc.ForceRebuild3(True)
        except Exception as e:
            logger.warning("Rebuild after material assignment failed: %s", e)

        # Verify assignment
        verified = self.get_material(config_name)

        if target_material:
            # Strict verification: Ensure SolidWorks did not silently discard an invalid material name
            if not verified["assigned"] or verified["material_name"].lower() != target_material.lower():
                raise SolidWorksError(
                    f"Material '{target_material}' could not be assigned. SolidWorks rejected the name. "
                    f"Please verify valid names using sw_list_materials."
                )
        else:
            # Clear material verification: Ensure material was actually cleared
            if verified["assigned"] or (verified["material_name"] and verified["material_name"].lower() != "none"):
                raise SolidWorksError(
                    f"Clearing material on config '{config_name}' was silently rejected by SolidWorks."
                )

        logger.info(
            "Successfully set material '%s' (DB: %s, Config: %s)",
            target_material,
            database_name,
            config_name,
        )

        return {
            "success": True,
            "material_name": verified["material_name"],
            "database": verified["database"],
            "configuration": config_name,
            "assigned": verified["assigned"],
            "density_kg_m3": verified["density_kg_m3"],
            "density_g_cm3": verified["density_g_cm3"],
            "mechanical_properties": verified["mechanical_properties"],
        }
