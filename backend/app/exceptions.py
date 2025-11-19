"""
Custom exceptions for better error handling.
"""


class ChangeSetValidationError(ValueError):
    """Raised when change-set validation fails."""
    pass


class ChangeSetStructureError(ValueError):
    """Raised when change-set structure is invalid (e.g., missing placeholder references)."""
    pass


class DatabaseOperationError(RuntimeError):
    """Raised when a database operation fails."""
    pass


class LLMOperationError(RuntimeError):
    """Raised when an LLM operation fails."""
    pass

