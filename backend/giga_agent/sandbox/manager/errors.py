class SandboxManagerError(Exception):
    pass


class SandboxNotFoundError(SandboxManagerError):
    pass


class ProviderNotFoundError(SandboxManagerError):
    pass


class SandboxStateError(SandboxManagerError):
    pass


class SandboxBusyError(SandboxManagerError):
    pass


class FileNotFoundForUserError(SandboxManagerError):
    pass


class FileAccessError(SandboxManagerError):
    pass


class StorageOperationError(SandboxManagerError):
    pass
