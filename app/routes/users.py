from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_admin
from app.database import db
from app.models.user import UserOut

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(admin: dict = Depends(get_current_admin)):
    """List all registered users (admin only)."""
    users = await db.users.find().to_list(length=None)
    return [
        UserOut(
            id=str(u["_id"]),
            name=u["name"],
            email=u["email"],
            role=u.get("role", "user"),
        )
        for u in users
    ]
