class BenchmarkValidationError(ValueError):
    """Raised when an artifact violates an IFC benchmark semantic invariant."""


class SchemaValidationError(BenchmarkValidationError):
    """Raised when an artifact does not conform to its machine-readable schema."""
