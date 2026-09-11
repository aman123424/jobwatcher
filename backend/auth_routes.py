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

REFRESH-TOKEN COOKIE ATTRIBUTES (added 2026-09-10) - `samesite="none"`
IN PRODUCTION, not the more-restrictive "strict" a from-scratch design
would default to: this API and the frontend are genuinely different
origins in production (the frontend is CloudFront, the API is a Lambda
function URL - see api.py's CORS origin list) rather than the same
site on different ports, and a browser never attaches a
SameSite=Strict OR even Lax cookie to a cross-site fetch() at all - the
cookie would just silently never arrive at /auth/refresh. "none" is
what actually works for this deployment shape; it's paired with
`secure=True` (required by browsers for "none" anyway, and required
for "none" to even be accepted) and CORS's `allow_credentials=True`
(api.py) to keep it scoped to exactly this frontend origin, not open
to arbitrary cross-site senders.

`secure=True` ALSO means the browser refuses to store or send the
cookie over plain HTTP at all - which local dev (http://127.0.0.1:8000)
is. Without the ENVIRONMENT check below, the entire refresh flow would
silently work in production and silently NEVER WORK locally (the
cookie just never gets set - no error, no exception, just an empty
cookie jar), which is exactly the kind of thing that's invisible until
someone tries to actually develop against it. `ENVIRONMENT` (see
.env.example) defaults to "development" so a fresh local checkout gets
a plain-HTTP-safe cookie (`secure=False`, `samesite="lax"` - the
correct pair for same-origin-ish local dev) with no setup step;
production's Lambda config sets ENVIRONMENT=production explicitly.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from auth import (
    REFRESH_TOKEN_COOKIE_NAME,
    RefreshTokenError,
    RefreshTokenReused,
    create_access_token,
    get_current_user,
    hash_password,
    issue_refresh_token,
    revoke_refresh_token,
    validate_and_rotate_refresh_token,
    verify_password,
)
from db import get_db
from models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_IS_PRODUCTION = os.environ.get("ENVIRONMENT", "development") == "production"


def _set_refresh_cookie(response: Response, raw_refresh_token: str) -> None:
    """
    Shared by register/login/refresh below - one place setting the
    cookie's attributes so all three can't quietly drift apart. `path`
    scoped to "/auth" (not the whole API): the browser then only ever
    attaches this cookie to /auth/refresh and /auth/logout, never to
    every other request the frontend makes - the refresh token has no
    business being sent to, say, GET /jobs.
    """
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=raw_refresh_token,
        httponly=True,
        secure=_IS_PRODUCTION,
        samesite="none" if _IS_PRODUCTION else "lax",
        path="/auth",
        max_age=30 * 24 * 60 * 60,  # 30 days, matches auth.py's REFRESH_TOKEN_EXPIRY
    )


def _clear_refresh_cookie(response: Response) -> None:
    """delete_cookie needs the same path/secure/samesite the cookie was originally set with - browsers match a deletion by its full attribute set, not just the name, so a mismatch here would silently no-op instead of actually clearing it."""
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path="/auth",
        secure=_IS_PRODUCTION,
        samesite="none" if _IS_PRODUCTION else "lax",
    )


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


def _issue_session(response: Response, db: Session, user: User) -> AuthResponse:
    """
    Shared by register/login/refresh below - issues BOTH tokens for one
    user and sets the refresh cookie on `response`, in one place, so
    the three endpoints that start/renew a session can't quietly drift
    into doing this differently. `family_id` deliberately omitted here
    (register/login only - see auth.py's issue_refresh_token) - a
    brand new login always starts a brand new token family; only
    /auth/refresh's rotation passes an existing family_id through.
    """
    raw_refresh_token, _ = issue_refresh_token(db, str(user.id))
    db.commit()
    _set_refresh_cookie(response, raw_refresh_token)
    return AuthResponse(
        access_token=create_access_token(str(user.id)),
        user_id=str(user.id),
        name=user.name,
        email=user.email,
        tier=user.tier.value,
        is_admin=user.is_admin,
    )


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
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
    return _issue_session(response, db, user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
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

    return _issue_session(response, db, user)


@router.post("/refresh", response_model=AuthResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Called by the frontend's fetch wrapper (see client.ts's request())
    whenever an access token has expired (a 401) or on a fresh page
    load, to silently obtain a new one - see useAuth.tsx for why the
    access token lives in memory only and needs re-establishing on
    every reload. Reads the refresh token from the cookie the browser
    attaches automatically (never from a request body - the frontend's
    JS never has this value to send even if it wanted to).

    Both failure cases (no cookie at all, or validate_and_rotate_
    refresh_token rejecting it) return the same 401 - from the caller's
    side, "not logged in" and "your session was invalidated" look and
    are handled identically (see useAuth.tsx's bootstrap effect).
    """
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    try:
        new_raw_refresh_token, user = validate_and_rotate_refresh_token(db, raw_refresh_token)
    except RefreshTokenReused:
        # The whole family's already revoked by validate_and_rotate_
        # refresh_token itself - clear the now-dead cookie so this
        # browser stops trying to use it, then report the same generic
        # 401 as any other invalid-refresh case (not "you got hacked",
        # which would just be alarming without anything the user can
        # do about it from here beyond logging in again anyway).
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalidated - please log in again")
    except RefreshTokenError:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    _set_refresh_cookie(response, new_raw_refresh_token)
    return AuthResponse(
        access_token=create_access_token(str(user.id)),
        user_id=str(user.id),
        name=user.name,
        email=user.email,
        tier=user.tier.value,
        is_admin=user.is_admin,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Revokes the current refresh token server-side (see auth.py's
    revoke_refresh_token - ONLY this one token, not its whole family:
    logging out isn't a theft signal) and clears the cookie. This is
    the actual capability the old single-stateless-JWT design couldn't
    offer at all - there was nothing server-side to revoke. No auth
    dependency required: a browser with no cookie (already logged out)
    or an expired one just gets a no-op, same 204 either way - logout
    should never itself be the thing that fails.
    """
    raw_refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_NAME)
    if raw_refresh_token is not None:
        revoke_refresh_token(db, raw_refresh_token)
    response.delete_cookie(REFRESH_TOKEN_COOKIE_NAME, path="/auth")


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
