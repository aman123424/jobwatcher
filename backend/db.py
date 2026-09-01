"""
db.py
=====

Where the app's database connection lives - one SQLAlchemy "engine"
(a connection factory, not a single connection) and one session
factory, both built once here and imported everywhere else that needs
to talk to Postgres, rather than every file constructing its own.

WHERE THE CONNECTION STRING COMES FROM: DATABASE_URL, read from a
local .env file (via python-dotenv) for local development / running
Alembic migrations from a terminal, or from a real environment
variable set directly in Lambda's configuration once the API itself
starts reading/writing the database - NEVER hardcoded here. See
.env.example for the expected format. The real .env is gitignored -
only the placeholder-filled .env.example is committed.

WHY SQLALCHEMY 2.0-STYLE (DeclarativeBase, not the older
declarative_base() function): this project started fresh in 2026,
long after SQLAlchemy 2.0 became the stable, current way to write
models - no reason to use the older pattern just because more
tutorials online still show it.
"""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Loads variables from a local .env file into the process environment,
# if one exists (harmless no-op in Lambda, where DATABASE_URL will be
# set as a real Lambda environment variable instead - load_dotenv()
# simply finds no .env file there and does nothing).
load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]

# `echo=False` - set to True temporarily if you ever need to see the
# actual SQL SQLAlchemy is generating, e.g. while debugging a query.
engine = create_engine(DATABASE_URL, echo=False)

# A session is one unit-of-work / one conversation with the database -
# `SessionLocal()` creates a new one; `autoflush`/`autocommit` left at
# SQLAlchemy 2.0's own sensible defaults (autocommit doesn't exist as
# a session-level concept anymore in 2.0 - each session is explicitly
# committed or rolled back by the code using it).
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """
    Every table in models.py inherits from this. SQLAlchemy uses
    whatever inherits from Base to know which tables exist when
    Alembic autogenerates a migration - see alembic/env.py, which
    imports Base.metadata from here (via models.py) for exactly that
    reason.
    """
    pass


def get_db():
    """
    FastAPI dependency (see auth_routes.py for how it's actually
    used: `db: Session = Depends(get_db)`) - hands an endpoint one
    fresh SQLAlchemy session for the lifetime of that one request,
    then closes it afterward no matter what happens (success, an
    unhandled exception, doesn't matter - the `finally` always runs).

    WHY A NEW SESSION PER REQUEST, NOT ONE SHARED SESSION: a
    SQLAlchemy session isn't safe to use from multiple requests at
    once (it's a single unit-of-work, not a connection pool itself -
    the actual pooling happens one level down, inside `engine`, which
    IS safe to share). One fresh session per request is the standard,
    correct pattern - cheap to create, and keeps each request's
    database work fully isolated from every other request's.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
