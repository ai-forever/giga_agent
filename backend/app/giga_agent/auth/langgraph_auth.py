from jwt.exceptions import ExpiredSignatureError, PyJWTError
from langgraph_sdk import Auth

from giga_agent.core.db import get_session_factory
from giga_agent.auth import security
from giga_agent.models.users import UserRepository, UserShort

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

    # Cache-first: on hit, avoid opening a DB session entirely.
    user = await UserRepository.get_from_cache(user_id)
    if user is None:
        factory = await get_session_factory()
        async with factory() as db:
            user_repo = UserRepository(db)
            user = await user_repo.get_by_id(user_id, use_cache=False)

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
