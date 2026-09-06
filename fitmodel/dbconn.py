"""
fitmodel/dbconn.py
===================

A standalone DB connection for fitmodel, deliberately NOT sharing
backend/db.py's module - fitmodel is meant to be an independently
runnable component with its own dependency footprint (see
fitmodel/README.md), and importing backend/db.py directly would couple
this component's runtime to backend/'s internal file layout, which
already changed once this session (scoring.py -> scoring/ package).
Reading the same DATABASE_URL from the same real .env file keeps there
being exactly one source of truth for the connection string, without
fitmodel needing to know how backend/ is organized internally.

The ONE deliberate exception is TrainingExample itself (models.py,
below) - reimplementing that ORM model a second time here would risk
schema drift between two copies, which is worse than the one narrow
import.

NAMED "dbconn", NOT "db" - CONFIRMED REAL BUG hit while building this:
backend/models.py itself does `from db import Base`, and Python
resolves module names via the sys.modules cache before sys.path order
even matters - if this file were also named db.py, our own (still
initializing) module would satisfy that import instead of backend's
real db.py, raising a circular-import ImportError for Base. A
different filename sidesteps the collision entirely.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).parent.parent / "backend"
load_dotenv(BACKEND_DIR / ".env")

sys.path.insert(0, str(BACKEND_DIR))
from models import TrainingExample  # noqa: E402

import os  # noqa: E402

engine = create_engine(os.environ["DATABASE_URL"], echo=False)
SessionLocal = sessionmaker(bind=engine)

__all__ = ["SessionLocal", "TrainingExample"]
