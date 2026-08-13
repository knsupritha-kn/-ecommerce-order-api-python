from fastapi import APIRouter, HTTPException, status

from app.auth.utils import create_access_token, hash_password, verify_password
from app.database import db
from app.models.user import UserCreate, UserLogin, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    """Create a new user account with a hashed password."""
    if await db.users.find_one({"email": user.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user_doc = {
        "name": user.name,
        "email": user.email,
        "password": hash_password(user.password),
        "role": "user",
    }
    result = await db.users.insert_one(user_doc)

    return UserOut(
        id=str(result.inserted_id),
        name=user.name,
        email=user.email,
        role=user_doc["role"],
    )


@router.post("/login")
async def login(credentials: UserLogin):
    """Verify email/password and issue a JWT access token."""
    user = await db.users.find_one({"email": credentials.email})
    if not user or not verify_password(credentials.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user["_id"])})
    return {"access_token": access_token, "token_type": "bearer"}
