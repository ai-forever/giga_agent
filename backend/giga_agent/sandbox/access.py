LOCAL_DOCKER_PROVIDER = "local_docker"
LOCAL_JUPYTER_PROVIDER = "local_jupyter"
ADMIN_ONLY_SANDBOX_PROVIDERS = {
    LOCAL_DOCKER_PROVIDER,
    LOCAL_JUPYTER_PROVIDER,
}


def is_admin_only_provider_type(provider_type: str) -> bool:
    return provider_type in ADMIN_ONLY_SANDBOX_PROVIDERS


def is_provider_type_allowed_for_user(
    provider_type: str,
    *,
    is_superuser: bool,
) -> bool:
    if is_superuser:
        return True
    return not is_admin_only_provider_type(provider_type)

def ensure_provider_type_creatable_by_user(
    provider_type: str,
    *,
    is_superuser: bool,
) -> None:
    if not is_superuser and is_admin_only_provider_type(provider_type):
        raise PermissionError("Access denied")


def filter_provider_types_for_user(
    provider_types: list[str],
    *,
    is_superuser: bool,
) -> list[str]:
    if is_superuser:
        return provider_types
    return [
        provider_type
        for provider_type in provider_types
        if is_provider_type_allowed_for_user(
            provider_type,
            is_superuser=is_superuser,
        )
    ]