from fastapi import HTTPException, Request, status
from app.core.config import settings


async def get_current_user(request: Request):
    """
    Validate the X-API-Secret header.
    Returns a simple user object with an `id` attribute for compatibility.
    """
    secret = request.headers.get("X-API-Secret")

    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "X-API-Secret header missing", "error_code": "secret_missing"},
        )

    if secret != settings.api_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "Invalid API secret", "error_code": "secret_invalid"},
        )

    # Return a simple namespace so `.id` still works if anyone accesses user.id
    class _User:
        id = settings.default_user_id

    return _User()


async def get_current_user_id(request: Request) -> str:
    """Shortcut that returns just the user ID string after validating the secret."""
    user = await get_current_user(request)
    return user.id
