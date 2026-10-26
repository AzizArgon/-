import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.limits import check_login_allowed, check_register_allowed, client_ip, login_failures, registrations
from app.core.security import create_access_token, hash_password, verify_password
from app.db.database import get_db
from app.db.models import User, UserRole
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        user=UserOut.model_validate(user),
    )


@router.get("/options")
def options():
    """What the register page must ask: the invite code for sellers on the public server."""
    return {"seller_invite_required": bool(settings.seller_invite_code)}


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_register_allowed(ip)
    code = settings.seller_invite_code
    if data.role == "seller" and code and not secrets.compare_digest(data.invite_code.encode(), code.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "invite_required"})
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(data.password), role=UserRole(data.role))
    db.add(user)
    db.commit()
    db.refresh(user)
    registrations.hit(ip)
    return _token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    check_login_allowed(ip)
    user = db.scalar(select(User).where(User.email == data.email.lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        login_failures.hit(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _token_response(user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
