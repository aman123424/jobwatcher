"""
auth.py
=======

Password hashing, JWT creation/verification, and the FastAPI
dependency (`get_current_user`) that protected endpoints use to find
out who's actually making a request.

WHAT'S DELIBERATELY NOT HERE YET (Aman's own call, 2026-09-02): no
email verification enforcement. `User.email_verified` still exists as
a column (see models.py) and every new account starts with it False,
but nothing in this file - or anywhere else right now - ever CHECKS
that flag before letting someone register, log in, or use any part of
the app. That's intentional: there's no email-sending service wired up
yet (see PROJECT_LOG.md), so gating access on a verification step
nobody can complete would just lock everyone out. Revisit this once a
real email service exists - the AuthToken model (models.py) already
has an "email_verify" purpose ready for exactly that, unused for now.

JWT, NOT auth_tokens: this file issues stateless JWTs for the ACCESS
token - the token itself, once signed, is never stored in the
database, and a request is authenticated purely by checking the JWT's
signature and expiry, not by looking anything up. This is a
completely different, unrelated mechanism from the `AuthToken`
database table (models.py) - that table is specifically for
email-verification and password-reset LINKS, which have to be
persisted server-side because they're emailed out and clicked later.
Nothing in this file touches the AuthToken table at all.

TWO KINDS OF TOKEN, DELIBERATELY DIFFERENT SHAPES (added 2026-09-10):
the ACCESS token above is short-lived and stateless - a JWT nothing
ever looks up. The REFRESH token (issue_refresh_token /
validate_and_rotate_refresh_token / revoke_refresh_token below) is
long-lived and STATEFUL on purpose - it's an opaque random string, its
HASH persisted in the `refresh_tokens` table (models.py), specifically
so it CAN be looked up, rotated, and revoked - none of which a
signature-only JWT can ever do. The access token is never stored
anywhere (frontend keeps it in memory only - see useAuth.tsx); the
refresh token lives exclusively in an HttpOnly cookie the frontend's
JS never reads, set/cleared by auth_routes.py.
"""

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db import get_db
from models import RefreshToken, User

JWT_SECRET = os.environ["JWT_SECRET"]
# HS256 (a single shared secret signs AND verifies) rather than an
# RS256 public/private keypair - the extra complexity of asymmetric
# signing only pays off when some OTHER service needs to verify tokens
# without holding the signing secret itself, which isn't the case here
# (this same backend both issues and checks every token).
JWT_ALGORITHM = "HS256"
# How long an access token stays valid before it needs refreshing via
# the refresh-token flow below. Deliberately short (unlike the old
# single 7-day token this replaced) - a short window bounds how much
# damage a STOLEN access token can do, since the thing that actually
# needs to survive weeks (the refresh token) never touches JS at all
# (HttpOnly cookie) and is the one with real server-side revocation.
ACCESS_TOKEN_EXPIRY = timedelta(minutes=15)
# How long a refresh token stays valid before it's fully expired (as
# opposed to revoked early - see validate_and_rotate_refresh_token).
# Long, since re-logging in every 30 days is the whole point of having
# a refresh flow at all - what keeps this safe despite the length is
# rotation + reuse detection below, not a short lifetime.
REFRESH_TOKEN_EXPIRY = timedelta(days=30)
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"


def hash_password(plain_password: str) -> str:
    """
    Turns a plain-text password into a bcrypt hash safe to store in
    `users.password_hash`. bcrypt automatically generates and embeds a
    random "salt" into the hash itself (visible as part of the output
    string) - this is WHY two different users with the identical
    password end up with two completely different stored hashes, which
    is exactly the property that makes a stolen password_hash column
    useless for looking up who shares a password with whom.
    """
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Checks a login attempt's plain-text password against the stored hash - never the other way around (a hash can't be reversed back into the original password)."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    """
    Builds a signed JWT for one user. `sub` ("subject" - a standard
    JWT claim name, not something we invented) holds the user's id;
    `exp` ("expiry" - also standard) is when this token stops being
    valid, checked automatically by jwt.decode() below without us
    needing to compare timestamps ourselves.
    """
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + ACCESS_TOKEN_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _hash_refresh_token(raw_token: str) -> str:
    """
    SHA-256 of the raw refresh token - same reasoning as
    hash_password() above for why we never store the raw value: a
    leaked `refresh_tokens` table shouldn't hand out working sessions.
    Plain SHA-256 (not bcrypt) is the right tool here, unlike for
    passwords - this input is already a 32-byte cryptographically
    random string (see issue_refresh_token below), not a short,
    guessable human password, so there's no brute-force risk bcrypt's
    deliberate slowness exists to defend against.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def issue_refresh_token(db: Session, user_id: str, family_id: "uuid.UUID | None" = None) -> tuple[str, RefreshToken]:
    """
    Creates one new refresh token row and returns (raw_token, row) -
    the raw value is what actually goes in the cookie; the row (with
    only the HASH persisted) is what auth_routes.py sets `Set-Cookie`
    from and, on rotation, links via `replaced_by_id`.

    `family_id`: omitted on a fresh login (a new family is born -
    see auth_routes.py's login/register), passed through unchanged on
    a rotation (see validate_and_rotate_refresh_token below) - this is
    what lets _revoke_family() kill every token descended from one
    login in a single query when reuse is detected.
    """
    raw_token = secrets.token_urlsafe(32)
    row = RefreshToken(
        user_id=user_id,
        family_id=family_id or uuid.uuid4(),
        token_hash=_hash_refresh_token(raw_token),
        expires_at=datetime.now(timezone.utc) + REFRESH_TOKEN_EXPIRY,
    )
    db.add(row)
    db.flush()  # populates row.id without a full commit - callers control the transaction boundary
    return raw_token, row


def _revoke_family(db: Session, family_id: "uuid.UUID") -> None:
    """
    Revokes every still-valid token descended from one login in one
    query - see validate_and_rotate_refresh_token's reuse-detection
    branch for why this exists: an already-rotated-out token being
    presented again means an attacker and the real user both hold a
    copy, so the whole chain has to die, not just the one presented.
    """
    db.query(RefreshToken).filter(
        RefreshToken.family_id == family_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": datetime.now(timezone.utc)})


class RefreshTokenError(Exception):
    """Base class for every way /auth/refresh can fail - auth_routes.py catches this uniformly and returns a 401, the same "not authenticated" response regardless of which specific case fired (unknown/expired/reused), same reasoning get_current_user already applies to access-token failures."""


class RefreshTokenReused(RefreshTokenError):
    """The specific case where an already-revoked (rotated-out) token was presented again - see validate_and_rotate_refresh_token's docstring."""


def validate_and_rotate_refresh_token(db: Session, raw_token: str) -> tuple[str, User]:
    """
    The heart of the rotation flow, called from POST /auth/refresh.
    On success: revokes the presented token, issues a brand new one in
    the same family, and returns (new_raw_token, user) - the caller
    sets the new raw token as the new cookie value. Every refresh both
    extends the session AND replaces the token being used, so a token
    is only ever presented successfully once.

    On reuse (the presented token's hash matches a row that's already
    revoked): this is a real signal of theft, not just an expired
    session - if nobody had stolen this token, it could only have been
    revoked by THIS SAME client already rotating past it, so a second
    presentation means someone else has a copy. Response: revoke the
    entire family (_revoke_family) rather than just rejecting this one
    request, forcing a real login again for whoever's the legitimate
    user - the attacker's copy stops working at the same time.

    Raises a RefreshTokenError subclass on any failure; never returns
    a partial/invalid result.
    """
    token_hash = _hash_refresh_token(raw_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row is None:
        raise RefreshTokenError("Unknown refresh token")

    if row.revoked_at is not None:
        _revoke_family(db, row.family_id)
        db.commit()
        raise RefreshTokenReused("Refresh token reuse detected")

    if row.expires_at < datetime.now(timezone.utc):
        raise RefreshTokenError("Refresh token expired")

    user = db.get(User, row.user_id)
    if user is None:
        raise RefreshTokenError("User no longer exists")

    new_raw_token, new_row = issue_refresh_token(db, str(user.id), family_id=row.family_id)
    row.revoked_at = datetime.now(timezone.utc)
    row.replaced_by_id = new_row.id
    db.commit()
    return new_raw_token, user


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    """
    Called from POST /auth/logout - revokes ONLY the one token being
    used, not its whole family (unlike the reuse-detection case above:
    a normal logout isn't a theft signal, so there's no reason to also
    kill any OTHER device/session the same login might have going).
    Silently does nothing if the token's already gone/revoked/unknown
    - logout should never fail just because the cookie was already
    stale, since clearing it client-side is the part that actually
    matters to the user.
    """
    token_hash = _hash_refresh_token(raw_token)
    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


# FastAPI's own helper for reading a standard
# "Authorization: Bearer <token>" header out of a request - used below
# as a dependency so every protected endpoint gets this parsed
# automatically instead of each one reading the raw header itself.
_bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    The FastAPI dependency every protected endpoint will use (once
    those endpoints exist) - e.g. `user: User = Depends(get_current_user)`
    as a parameter. Decodes and verifies the JWT from the request's
    Authorization header, then loads the matching real User row from
    the database. Raises a 401 if the token is missing, invalid,
    expired, or somehow refers to a user that no longer exists -
    every one of those cases is treated identically from the caller's
    point of view (not authenticated), rather than leaking WHICH
    specific thing was wrong.
    """
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """
    Same as get_current_user above, plus an `is_admin` check - used by
    admin-only endpoints (currently just POST /companies, see api.py).
    Builds ON TOP of get_current_user (a dependency depending on
    another dependency) rather than duplicating the JWT-decode logic,
    so login validity and the admin check can never drift apart.

    403 ("Forbidden"), not 401 ("Unauthorized") - the token IS valid
    and DOES identify a real, logged-in user; they're just not
    ALLOWED to do this specific thing, a genuinely different case from
    "you're not logged in at all."
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
