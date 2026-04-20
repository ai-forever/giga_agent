from pathlib import PurePosixPath

JUPYTER_PORT = 8888
BUCKET_PREFIX = "/bucket/"
_LOCAL_FILE_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
MANAGED_LABEL = "giga_agent.managed"
PROVIDER_TYPE_LABEL = "giga_agent.provider_type"
PROVIDER_ID_LABEL = "giga_agent.provider_id"
SANDBOX_ID_LABEL = "giga_agent.sandbox_id"
OWNER_ID_LABEL = "giga_agent.owner_id"
_CONTAINER_HOME_DIR = PurePosixPath("/root")
_SHELL_POLL_INTERVAL_SEC = 0.2
_SHELL_STATUS_RUNNING = "running"
_SHELL_STATUS_COMPLETED = "completed"
_SHELL_STATUS_FAILED = "failed"
_CONTAINER_PYTHON_BIN = "python"
