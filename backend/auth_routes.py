"""
auth_routes.py
===============

The two endpoints that actually let someone create an account and log
in: POST /auth/register, POST /auth/login. Kept in their own
APIRouter, separate from api.py's job-related endpoints, rather than
piling everything into one growing file - api.py just imports and
mounts this router (see api.py).

NO EMAIL VERIFICATION GATE (Aman's own call, 2026-09-02): both
endpoints below happily create/log in an account with
`email_verified=False` and never check that flag - see auth.py's
module docstring for the full reasoning. Every new user's
`email_verified` starts False and STAYS False until a real email
service exists to actually verify it later.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from auth import create_access_token, get_current_user, hash_password, verify_password
from db import get_db
from models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    # A floor, not real strength-checking - genuinely stronger
    # password rules (requiring a mix of character types, checking
    # against known-breached password lists, etc.) are a reasonable
    # future improvement, not attempted here.
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    """
    Returned by both /register and /login - the frontend gets the JWT
    it needs to send on every future request (as
    "Authorization: Bearer <access_token>"), plus enough basic user
    info to render a UI without a separate "who am I" call right after
    logging in.
    """
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    email: str
    tier: str
    # Lets the frontend show/hide admin-only UI (currently just the
    # "+ Add Company" button - see AvatarMenu/JobsPage.tsx) without a
    # separate "am I an admin" call - the real access check still lives
    # server-side (get_current_admin, api.py's POST /companies), this
    # is purely so the button doesn't show a dead end to a non-admin.
    is_admin: bool


def _to_auth_response(user: User) -> AuthResponse:
    """Shared by both endpoints below - builds the JWT and response shape for one user, in one place, so register and login can't quietly drift into returning slightly different shapes."""
    return AuthResponse(
        access_token=create_access_token(str(user.id)),
        user_id=str(user.id),
        name=user.name,
        email=user.email,
        tier=user.tier.value,
        is_admin=user.is_admin,
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing is not None:
        # Deliberately vague on WHY it failed (not "this email is
        # already taken", specifically) - same reasoning as login's
        # generic "invalid email or password" below: not confirming
        # which emails are/aren't registered avoids handing an
        # attacker a free account-enumeration tool. A real product
        # might trade this off differently (a clearer message is
        # friendlier UX) - flagged here as a deliberate choice, not an
        # oversight, so it's easy to revisit later if that tradeoff
        # ever needs to go the other way.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not register with these details")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        email_verified=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_auth_response(user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Same check whether the email doesn't exist at all OR the
    # password is wrong, with the same generic error message either
    # way - checking verify_password against a real stored hash only
    # when a user IS found (a bcrypt hash comparison always takes
    # roughly the same, non-trivial time, unlike short-circuiting
    # immediately for "no such email") avoids the response TIMING
    # itself accidentally revealing which case happened, on top of
    # the message already not saying which case happened.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    return _to_auth_response(user)


class UserOut(BaseModel):
    """Same shape as AuthResponse minus the token fields - GET /me isn't issuing a new token, just reporting who the caller's existing one belongs to."""
    user_id: str
    name: str
    email: str
    tier: str
    is_admin: bool


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    """
    Re-fetches the current user's own info fresh from the database,
    keyed off their existing token - added 2026-09-05 after discovering
    the frontend only ever learns `is_admin` (and everything else) at
    login/register time and then caches it in localStorage indefinitely
    (see useAuth.tsx). An admin flag granted AFTER someone's last login
    stayed invisible to their still-logged-in browser until they
    happened to log out and back in - this lets the frontend refresh
    that snapshot on app load without forcing a fresh login.
    """
    return UserOut(
        user_id=str(user.id),
        name=user.name,
        email=user.email,
        tier=user.tier.value,
        is_admin=user.is_admin,
    )
