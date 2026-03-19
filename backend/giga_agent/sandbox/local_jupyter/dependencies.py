from __future__ import annotations

from dataclasses import dataclass
from importlib import util

JUPYTER_REQUIRED_MODULES = {
    "jupyter_server": "jupyter-server",
    "ipykernel": "ipykernel",
}
JUPYTER_INSTALL_COMMAND = 'pip install -U "giga-agent[jupyter]"'


@dataclass(slots=True)
class MissingDependenciesError(ValueError):
    missing_modules: list[str]
    provider_type: str = "local_jupyter"

    def __post_init__(self) -> None:
        message = (
            "Required Jupyter dependencies are not installed. "
            f"Install them with: {JUPYTER_INSTALL_COMMAND}"
        )
        ValueError.__init__(self, message)

    def to_detail(self) -> dict[str, str | list[str]]:
        return {
            "error": "missing_dependencies",
            "provider_type": self.provider_type,
            "missing": self.missing_modules,
            "install": JUPYTER_INSTALL_COMMAND,
        }


def get_missing_jupyter_modules() -> list[str]:
    missing_modules: list[str] = []
    for module_name in JUPYTER_REQUIRED_MODULES:
        if util.find_spec(module_name) is None:
            missing_modules.append(module_name)
    return missing_modules


def ensure_jupyter_dependencies(*, provider_type: str = "local_jupyter") -> None:
    missing_modules = get_missing_jupyter_modules()
    if missing_modules:
        raise MissingDependenciesError(
            missing_modules=missing_modules,
            provider_type=provider_type,
        )
