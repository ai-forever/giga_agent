from jwt.exceptions import ExpiredSignatureError, PyJWTError
from langgraph_sdk import Auth

from giga_agent.core.db import get_session_factory
from giga_agent.modules.auth import security
from giga_agent.models.users import UserRepository

# The "Auth" object is a container that LangGraph will use to mark our authentication function
auth = Auth()


# The `authenticate` decorator tells LangGraph to call this function as middleware
# for every request. This will determine whether the request is allowed or not
@auth.authenticate
async def get_current_user(authorization: str | None) -> Auth.types.MinimalUserDict:
    """Check if the user's token is valid."""
    if not authorization:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    try:
        scheme, token = authorization.split()
    except ValueError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    if scheme.lower() != "bearer":
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    try:
        user_id = security.get_user_id_from_token(token)
    except ExpiredSignatureError:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Token expired")
    except PyJWTError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )
    except ValueError:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )

    factory = await get_session_factory()
    async with factory() as session:
        # Cache-first with DB fallback.
        user = await UserRepository.get_cached_or_db(user_id, session=session)

    if user is None:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Could not validate credentials"
        )
    if not user.is_active:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Inactive user")

    return {
        "identity": str(user.id),
    }


@auth.on.threads.create
async def inject_team_id(ctx, value):
    """Inject team_id into thread metadata."""
    if "metadata" not in value:
        value["metadata"] = {}
    value["metadata"]["user_id"] = ctx.user["identity"]
    return value  # Return modified value


@auth.on
async def add_owner(
    ctx: Auth.types.AuthContext,  # Contains info about the current user
    value: dict,  # The resource being created/accessed
):
    filters = {"user_id": ctx.user.identity}
    metadata = value.setdefault("metadata", {})
    metadata.update(filters)

    # Only let users see their own resources
    return filters
