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

JWT, NOT auth_tokens: this file issues stateless JWTs for session/
login purposes - the token itself, once signed, is never stored in
the database, and a request is authenticated purely by checking the
JWT's signature and expiry, not by looking anything up. This is a
completely different, unrelated mechanism from the `AuthToken`
database table (models.py) - that table is specifically for
email-verification and password-reset LINKS, which have to be
persisted server-side because they're emailed out and clicked later.
Nothing in this file touches the AuthToken table at all.
"""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from db import get_db
from models import User

JWT_SECRET = os.environ["JWT_SECRET"]
# HS256 (a single shared secret signs AND verifies) rather than an
# RS256 public/private keypair - the extra complexity of asymmetric
# signing only pays off when some OTHER service needs to verify tokens
# without holding the signing secret itself, which isn't the case here
# (this same backend both issues and checks every token).
JWT_ALGORITHM = "HS256"
# How long an access token stays valid before a user has to log in
# again. Deliberately a single, longer-lived token with no separate
# refresh-token flow for v1 - refresh-token rotation/revocation is
# real, genuine infrastructure that isn't worth building before the
# app has actual users to justify it. Worth revisiting if session
# length or logout-everywhere-on-demand ever becomes a real need.
JWT_EXPIRY = timedelta(days=7)


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
        "exp": datetime.now(timezone.utc) + JWT_EXPIRY,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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
