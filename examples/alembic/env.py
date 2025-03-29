# examples/alembic/env.py
import os
import sys
from logging.config import fileConfig
import asyncio

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# --- Project Setup ---
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
print(f"Project dir added to sys.path: {project_dir}")

# --- Import Library Metadata and Example Config Loader ---
try:
    # Import metadata directly from the library
    from ormodel import metadata as target_metadata
    # Import settings loader from the EXAMPLE's config module
    from examples.config import get_settings
    print("Successfully imported ormodel metadata and example settings.")
except ImportError as e:
    print(f"Error importing from ormodel library or examples.config: {e}")
    sys.exit(1)

# --- Import Example Models (to ensure they register with library metadata) ---
try:
    import examples.models
    print(f"Successfully imported example models from: {examples.models.__file__}")
    print(f"Metadata tables after model import: {target_metadata.tables.keys()}")
except ImportError as e:
    print(f"Error importing application models (e.g., examples.models): {e}")
    sys.exit(1)

# --- Load Example Settings and Configure Alembic ---
settings = get_settings() # Load settings using the example's config loader
config = context.config

# Set the sqlalchemy.url in the Alembic config object using the example settings
alembic_db_url = settings.ALEMBIC_DATABASE_URL
if not alembic_db_url:
    print("Error: ALEMBIC_DATABASE_URL is not set in settings (examples/.env).")
    sys.exit(1)
config.set_main_option("sqlalchemy.url", alembic_db_url)
print(f"Using database URL for Alembic: {config.get_main_option('sqlalchemy.url')}")

# --- Logging Setup ---
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Migration Functions (remain largely the same) ---
# target_metadata is now imported from ormodel

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata, # Use library metadata
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    """Helper function to run migrations within a context."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    ) # Uses sync URL from config

    if isinstance(connectable, AsyncEngine):
        # This block should generally not be hit if using sync ALEMBIC_DATABASE_URL
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()
    elif connectable is not None:
        # Standard sync engine path
        with connectable.connect() as connection:
            do_run_migrations(connection)
    else:
        print("Error: Could not create engine for online migrations.")
        sys.exit(1)

# --- Run ---
if context.is_offline_mode():
    print("Running migrations in offline mode...")
    run_migrations_offline()
else:
    print("Running migrations in online mode...")
    asyncio.run(run_migrations_online())

print("Alembic env.py finished.")