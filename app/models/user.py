from pydantic import BaseModel, EmailStr


# Fields required to register a new user
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


# Fields required to log a user in
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# User data returned to clients (never includes the password)
class UserOut(BaseModel):
    id: str
    name: str
    email: str
    role: str = "user"
