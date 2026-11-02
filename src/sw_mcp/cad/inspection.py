"""Model Inspection and Viewport Capture for SolidWorks.

Extracts mass properties, feature tree hierarchy, bounding box,
and captures the active viewport into a PNG image for multimodal LLM feedback.
"""

import logging
import os
from typing import Any, Dict, List

from PIL import Image
from sw_mcp.cad.document import DocumentManager
from sw_mcp.core.exceptions import SolidWorksError
from sw_mcp.core.units import convert_mass_properties, kg_to_grams, meters_to_mm

logger = logging.getLogger("sw_mcp.cad.inspection")

swSaveAsOptions_Silent = 1


class InspectionManager:
    """Manages CAD model inspection, mass properties, and visual capture."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def get_mass_properties(self) -> Dict[str, Any]:
        """
        Compute and return mass, volume, surface area, center of mass, density,
        material name, and moments of inertia with millimeter and gram conversions.
        """
        doc = self.doc_mgr.get_active_doc()
        ext = doc.Extension

        # Extract material name if assigned
        material_name = "Not Assigned (Default 1000 kg/m^3)"
        try:
            mat_id = getattr(doc, "MaterialIdName", "")
            if mat_id and "|" in str(mat_id):
                parts = str(mat_id).split("|")
                material_name = parts[1] if len(parts) >= 2 else str(mat_id)
        except Exception:
            pass

        try:
            # 1. Try modern CreateMassProperty property interface
            mp = ext.CreateMassProperty
            if mp:
                mass_kg = mp.Mass
                vol_m3 = mp.Volume
                sa_m2 = mp.SurfaceArea
                com = mp.CenterOfMass  # Tuple of (x, y, z) in meters
                density_kg_m3 = round(float(getattr(mp, "Density", 0.0)), 4)

                # Extract moments of inertia about center of mass (WhereTaken = 0)
                moi_dict = None
                try:
                    moi_raw = mp.GetMomentOfInertia(0)
                    if moi_raw and len(moi_raw) == 9:
                        moi_dict = {
                            "Lxx": round(moi_raw[0], 8),
                            "Lxy": round(moi_raw[1], 8),
                            "Lxz": round(moi_raw[2], 8),
                            "Lyx": round(moi_raw[3], 8),
                            "Lyy": round(moi_raw[4], 8),
                            "Lyz": round(moi_raw[5], 8),
                            "Lzx": round(moi_raw[6], 8),
                            "Lzy": round(moi_raw[7], 8),
                            "Lzz": round(moi_raw[8], 8),
                        }
                except Exception:
                    pass

                return {
                    "mass_kg": round(mass_kg, 6),
                    "mass_g": round(kg_to_grams(mass_kg), 3),
                    "volume_mm3": round(vol_m3 * 1e9, 3),
                    "volume_cm3": round(vol_m3 * 1e6, 3),
                    "surface_area_mm2": round(sa_m2 * 1e6, 3),
                    "density_kg_m3": density_kg_m3,
                    "density_g_cm3": round(density_kg_m3 / 1000.0, 6),
                    "material": material_name,
                    "center_of_mass_mm": {
                        "x": round(meters_to_mm(com[0]), 4),
                        "y": round(meters_to_mm(com[1]), 4),
                        "z": round(meters_to_mm(com[2]), 4),
                    },
                    "moments_of_inertia_cg_kg_m2": moi_dict,
                }
        except Exception as e:
            logger.debug("CreateMassProperty failed: %s", e)

        # 2. Fallback to GetMassProperties2 array
        try:
            raw = ext.GetMassProperties2(1, 0)
            if raw and len(raw) >= 6:
                res = convert_mass_properties(list(raw))
                if isinstance(res, dict) and "error" in res:
                    raise SolidWorksError(res["error"])
                return res
        except SolidWorksError:
            raise
        except Exception as e:
            logger.warning("GetMassProperties2 fallback also failed: %s", e)

        raise SolidWorksError("Unable to calculate mass properties for active document.")

    def list_feature_tree(self) -> List[Dict[str, Any]]:
        """Traverse the entire model feature tree and list features with their types."""
        doc = self.doc_mgr.get_active_doc()
        features: List[Dict[str, Any]] = []
        feat = doc.FirstFeature

        while feat is not None:
            features.append({
                "name": feat.Name,
                "type": feat.GetTypeName2,
                "created": True,
            })
            feat = feat.GetNextFeature

        return features

    def capture_viewport(self, output_path: str) -> Dict[str, Any]:
        """
        Capture the current 3D viewport into a PNG image file.
        Enables multimodal LLMs (Claude, Gemini) to inspect their CAD model visually.
        """
        doc = self.doc_mgr.get_active_doc()
        abs_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        if not abs_path.lower().endswith(".png"):
            abs_path += ".png"

        # Capture viewport bitmap via native SaveBMP and convert cleanly to PNG via Pillow
        temp_bmp = abs_path + ".tmp.bmp"
        try:
            try:
                bmp_ok = doc.SaveBMP(temp_bmp, 0, 0)
            except Exception as e:
                raise SolidWorksError(f"SaveBMP threw an exception: {e}") from e

            if not bmp_ok or not os.path.exists(temp_bmp):
                raise SolidWorksError(f"SaveBMP failed to capture viewport to temporary bitmap: {temp_bmp}")

            try:
                with Image.open(temp_bmp) as img:
                    img.save(abs_path, "PNG")
            except Exception as e:
                raise SolidWorksError(f"Failed converting captured bitmap to PNG at {abs_path}: {e}") from e
        finally:
            if os.path.exists(temp_bmp):
                try:
                    os.remove(temp_bmp)
                except Exception:
                    pass

        if not (os.path.exists(abs_path) and os.path.getsize(abs_path) > 0):
            raise SolidWorksError(f"Failed to capture viewport screenshot to: {abs_path}")

        file_size = os.path.getsize(abs_path)
        with Image.open(abs_path) as img:
            width, height = img.size

        return {
            "captured": True,
            "path": abs_path,
            "width": width,
            "height": height,
            "file_size_bytes": file_size,
        }
