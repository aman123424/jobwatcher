from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Makes `import db` / `import models` work from here - alembic/ is a
# subfolder of backend/, and db.py/models.py live directly in
# backend/. `prepend_sys_path = .` in alembic.ini (relative to
# alembic.ini itself, i.e. backend/) already handles this in practice,
# but importing directly below is what actually pulls in Base.metadata.
import db
import models  # noqa: F401 - imported so every model class registers itself on db.Base.metadata before we read it below; the import itself is the point, nothing in this file calls it by name.

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Our models' actual table definitions - this is what lets
# `alembic revision --autogenerate` compare "what does the database
# currently look like" against "what do models.py's classes say it
# should look like" and generate a migration for the difference.
target_metadata = db.Base.metadata

# The real connection string - read from DATABASE_URL (which db.py
# already loaded from .env via load_dotenv() when we imported it
# above), NOT from alembic.ini's sqlalchemy.url (deliberately left
# blank there - see the comment in alembic.ini for why: that file is
# committed to git, and a real password must never end up in it).
#
# The .replace("%", "%%") is NOT part of the real connection string -
# it's purely to survive passing through configparser (what Alembic's
# Config object is built on), which treats "%" as its OWN special
# interpolation character (see alembic.ini's "%(here)s") and otherwise
# misinterprets a percent-encoded password's "%40"-style sequences as
# a broken interpolation reference, not literal characters. configparser
# correctly un-escapes "%%" back to one literal "%" internally, so the
# actual value SQLAlchemy ends up using to connect is unaffected.
config.set_main_option("sqlalchemy.url", db.DATABASE_URL.replace("%", "%%"))

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
