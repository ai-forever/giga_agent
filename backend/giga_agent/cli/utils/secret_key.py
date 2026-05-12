from __future__ import annotations

import os
import secrets

_SECRET_KEY_ENV = "GIGA_AGENT_SECRET_KEY"
_DEV_SECRET_KEY_FILE = ".secret_key"


def ensure_dev_secret_key_env() -> None:
    existing_secret = (os.getenv(_SECRET_KEY_ENV) or "").strip()
    if existing_secret:
        return

    from giga_agent.core.paths import ensure_giga_agent_dir

    project_root = ensure_giga_agent_dir()
    secret_key_path = project_root / _DEV_SECRET_KEY_FILE
    if secret_key_path.exists():
        file_secret = secret_key_path.read_text(encoding="utf-8").strip()
        if file_secret:
            os.environ[_SECRET_KEY_ENV] = file_secret
            return

    generated_secret = secrets.token_hex(32)
    secret_key_path.write_text(f"{generated_secret}\n", encoding="utf-8")
    os.environ[_SECRET_KEY_ENV] = generated_secret
