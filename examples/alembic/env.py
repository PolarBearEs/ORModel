# examples/alembic/env.py
import os
import sys
from logging.config import fileConfig
import asyncio # Needed for run_async if using async engine features directly

from sqlalchemy import engine_from_config, pool
# Use create_engine for sync operations if needed directly
# from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncEngine # Import AsyncEngine if using async connection

from alembic import context

# --- Add this section ---
# Ensure the project root ('ormodel/' directory containing pyproject.toml) is in the Python path
project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
print(f"Project dir added to sys.path: {project_dir}")

# Import your library's base metadata and config using the NEW name
try:
    from ormodel import metadata as target_metadata # Use the metadata from the library
    from ormodel.config import get_settings
    print("Successfully imported ormodel metadata and settings.")
except ImportError as e:
    print(f"Error importing from ormodel library: {e}")
    print("Ensure the library is installed correctly (e.g., `uv pip install -e .[dev]`)")
    sys.exit(1) # Exit if core components can't be imported

# Import your application's models so they register with the metadata
# Make sure the path 'examples.models' is correct relative to the project_dir
try:
    # This import triggers the __init_subclass__ in ormodel.base.ORModel
    # which registers the models with the central 'metadata' object.
    import examples.models
    print(f"Successfully imported example models from: {examples.models.__file__}")
    # Optional: Verify models are in metadata
    # print(f"Metadata tables: {target_metadata.tables.keys()}")
except ImportError as e:
    print(f"Error importing application models (e.g., examples.models): {e}")
    print("Ensure 'examples' directory is accessible and models.py exists.")
    # Decide if this is fatal or if migrations can proceed without app models
    # sys.exit(1)

# Get settings to access the database URL
settings = get_settings()
# --- End added section ---

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# --- Inject the database URL from settings into the config ---
# Use the ALEMBIC specific SYNC URL from settings
alembic_db_url = settings.ALEMBIC_DATABASE_URL
if not alembic_db_url:
    print("Error: ALEMBIC_DATABASE_URL is not set in settings.")
    print("Please configure it in your .env file or environment variables.")
    sys.exit(1)

# Set the sqlalchemy.url in the Alembic config object
# This ensures it's available for both online and offline modes
config.set_main_option("sqlalchemy.url", alembic_db_url)
print(f"Using database URL for Alembic: {config.get_main_option('sqlalchemy.url')}")
# --- End injection ---

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata is imported from ormodel above
# target_metadata = None # Remove or comment out this line

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True, # Render values directly in SQL script for offline mode
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Helper function to run migrations within a context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata
        # include_schemas=True, # Add if using multiple schemas
        # compare_type=True, # Add if needed for custom types comparison
        )

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Create engine using config from alembic.ini (which now has the correct sync URL)
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        # future=True # Use future=True if using SQLAlchemy 2.0 style sync engine
    )

    if isinstance(connectable, AsyncEngine):
        # If connectable is async (shouldn't be based on ALEMBIC_DATABASE_URL, but check)
        # print("Running migrations online using async engine") # Debug
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose() # Dispose async engine
    elif connectable is not None:
        # If connectable is sync
        # print("Running migrations online using sync engine") # Debug
        with connectable.connect() as connection:
            do_run_migrations(connection)
        # Sync engine dispose might not be strictly necessary with NullPool
        # connectable.dispose() # Uncomment if using a different pool
    else:
        print("Error: Could not create engine for online migrations.")
        sys.exit(1)


# Determine mode and run migrations
if context.is_offline_mode():
    print("Running migrations in offline mode...")
    run_migrations_offline()
else:
    print("Running migrations in online mode...")
    # Use asyncio.run for the async online migration function
    asyncio.run(run_migrations_online())

print("Alembic env.py finished.")