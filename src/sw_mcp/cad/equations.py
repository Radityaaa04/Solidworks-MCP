"""Parametric & Equation Table Management for SolidWorks.

Enables reading and setting Global Variables and model Dimensions
with explicit unit protection and automatic rebuild.
"""

import logging
from typing import Any, Dict, List

from sw_mcp.cad.document import DocumentManager
from sw_mcp.core.exceptions import CADRebuildError, ParameterNotFoundError, SolidWorksError
from sw_mcp.core.units import format_equation_string, mm_to_meters

logger = logging.getLogger("sw_mcp.cad.equations")


class EquationManager:
    """Manages SolidWorks Equation Table and Dimension parameters."""

    def __init__(self, doc_mgr: DocumentManager):
        self.doc_mgr = doc_mgr

    def get_equations(self) -> List[Dict[str, Any]]:
        """List all equations and global variables defined in the active document."""
        doc = self.doc_mgr.get_active_doc()
        eqn_mgr = doc.GetEquationMgr
        if eqn_mgr is None:
            raise SolidWorksError("Failed to retrieve Equation Manager from active document.")

        count = eqn_mgr.GetCount
        results: List[Dict[str, Any]] = []

        for i in range(count):
            try:
                eq_str = eqn_mgr.Equation(i)
                val = eqn_mgr.Value(i)
                results.append({
                    "index": i,
                    "equation": eq_str,
                    "evaluated_value": val,
                })
            except Exception as e:
                logger.warning("Could not read equation index %d: %s", i, e)

        return results

    def set_global_variable(self, name: str, value: float, unit: str = "mm") -> Dict[str, Any]:
        """
        Add or update a global variable in the Equation Table.
        Appends explicit unit (e.g. 'mm') to avoid unit misinterpretations.
        """
        doc = self.doc_mgr.get_active_doc()
        eqn_mgr = doc.GetEquationMgr
        if eqn_mgr is None:
            raise SolidWorksError("Equation Manager not available.")

        eq_str = format_equation_string(name, value, unit)
        count = eqn_mgr.GetCount
        target_name = name.strip().replace('"', "").lower()
        found_index = -1

        for i in range(count):
            curr_eq = eqn_mgr.Equation(i)
            # SolidWorks equation syntax: "Name" = Value or Name = Value
            if "=" in curr_eq:
                lhs = curr_eq.split("=")[0].strip().replace('"', "").lower()
                if lhs == target_name:
                    found_index = i
                    break

        if found_index >= 0:
            # Modify existing equation
            eqn_mgr.Equation(found_index, eq_str)
            action = "updated"
        else:
            # Add new global variable at the end of the table
            res = eqn_mgr.Add2(-1, eq_str, True)
            if res < 0:
                raise SolidWorksError(f"Failed to add equation: {eq_str}")
            action = "created"

        # Rebuild to apply equation changes
        rebuild_res = doc.EditRebuild3
        if rebuild_res is False:
            raise SolidWorksError(f"Rebuild failed after setting global variable '{name}'.")

        return {
            "name": name,
            "equation": eq_str,
            "action": action,
            "rebuilt": True,
        }

    def modify_dimension(self, dimension_name: str, value_mm: float) -> Dict[str, Any]:
        """
        Modify a specific feature dimension directly (e.g. 'D1@Sketch1' or 'Length@Boss-Extrude1').
        value_mm: New dimension value in millimeters.
        """
        doc = self.doc_mgr.get_active_doc()
        val_m = mm_to_meters(value_mm)

        dim = doc.Parameter(dimension_name)
        if dim is None:
            raise ParameterNotFoundError(f"Dimension parameter '{dimension_name}' not found in active model.")

        dim.SystemValue = val_m
        rebuilt = doc.EditRebuild3
        if not rebuilt:
            raise CADRebuildError(f"Model rebuild failed after modifying dimension '{dimension_name}'.")

        return {
            "dimension": dimension_name,
            "new_value_mm": value_mm,
            "system_value_m": val_m,
            "rebuilt": True,
        }
