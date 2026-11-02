"""Custom exceptions for SolidWorks MCP Server."""

class SolidWorksError(Exception):
    """Base exception for all SolidWorks automation errors."""
    pass

class COMConnectionError(SolidWorksError):
    """Raised when unable to connect to or launch SolidWorks COM application."""
    pass

class DocumentNotFoundError(SolidWorksError):
    """Raised when an operation is attempted with no active document, or file not found."""
    pass

class FeatureCreationError(SolidWorksError):
    """Raised when a 2D sketch, extrusion, cut, or feature operation fails."""
    pass

class CADRebuildError(SolidWorksError):
    """Raised when SolidWorks model rebuild reports errors or fails constraint checks."""
    pass

class ParameterNotFoundError(SolidWorksError):
    """Raised when a requested dimension or global variable does not exist."""
    pass

class InvalidSelectionError(SolidWorksError):
    """Raised when an entity, face, edge, or component cannot be selected or found."""
    pass

class MateError(SolidWorksError):
    """Raised when assembly mating fails or over-defines kinematics."""
    pass

class DrawingError(SolidWorksError):
    """Raised when 2D drawing creation, view projection, or drafting operation fails."""
    pass
