from pathlib import PurePosixPath

JUPYTER_PORT = 8888
S3_MOUNT_PREFIX = "/bucket/"
_S3_KEY_PREFIX = "giga_agent"
_S3_SUFFIX_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

_E2B_HOME_DIR = PurePosixPath("/home/user")
_E2B_SHELL_POLL_INTERVAL_SEC = 0.3
_SHELL_STATUS_RUNNING = "running"
_SHELL_STATUS_COMPLETED = "completed"
_SHELL_STATUS_FAILED = "failed"
