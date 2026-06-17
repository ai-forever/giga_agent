class SecureExecError(RuntimeError):
    """Base error for secure process launch failures."""


class SecureExecUnsupportedError(SecureExecError):
    """Raised when secure execution is not supported on this platform."""


class SecureExecBinaryMissingError(SecureExecError):
    """Raised when the OS sandbox executable is not installed."""


class SandboxAccessDeniedError(PermissionError):
    """Raised when a path is outside the sandbox access policy."""
