# ORModel

An asynchronous ORM library using SQLModel and providing a Django ORM-like query syntax. Built for use with `asyncio` and tools like FastAPI. Managed with `uv`.

## Features

*   Model definition inheriting from `ormodel.ORModel` (which uses `sqlmodel` features).
*   Django-like manager access (`Model.objects`).
*   Asynchronous query interface (`.all()`, `.filter()`, `.get()`, `.create()`, `.get_or_create()`, `.update_or_create()`).
*   Session management via `contextvars` for easy integration with web frameworks (like FastAPI middleware).
*   Uses SQLAlchemy 2.0+ async capabilities.
*   Requires Alembic for database migrations.

## Installation

Requires Python 3.8+ and `uv`.

1.  **Clone the repository (or create files manually):**
    ```bash
    # git clone https://github.com/yourusername/ormodel.git
    cd ormodel
    ```

2.  **Create and activate virtual environment:**
    ```bash
    uv venv .venv
    source .venv/bin/activate  # or .\venv\Scripts\activate on Windows
    ```

3.  **Install:**
    ```bash
    # Install in editable mode with development dependencies
    uv pip install -e ".[dev]"
    ```

## Configuration

Configure your database connection using a `.env` file in your project root or the `examples/` directory. See `.env.example`.

*   `DATABASE_URL`: Async database connection string (e.g., `postgresql+asyncpg://...`, `sqlite+aiosqlite:///./app.db`).
*   `ALEMBIC_DATABASE_URL`: Sync database connection string for Alembic (e.g., `postgresql+psycopg2://...`, `sqlite:///./app.db`).
*   `ECHO_SQL`: Set to `True` to see generated SQL statements (optional).

## Usage

1.  **Define Models:** Inherit from `ormodel.ORModel`.

    ```python
    # examples/models.py
    from typing import Optional
    from sqlmodel import Field # Keep Field, Relationship imports
    from ormodel import ORModel # <-- Use ORModel base class

    class MyModel(ORModel, table=True): # <-- Inherit from ORModel
        id: Optional[int] = Field(default=None, primary_key=True)
        name: str = Field(index=True)
        value: int
    ```

2.  **Set up Migrations (Alembic):**
    *   `cd examples`
    *   Edit `alembic.ini` (set `sqlalchemy.url = %(SQLA_URL)s`)
    *   Edit `alembic/env.py` to import your models and `ormodel.metadata`.
    *   `alembic revision --autogenerate -m "Initial migration"`
    *   `alembic upgrade head`

3.  **Querying:** Use the `.objects` manager within an async context where the session is managed (e.g., using the provided FastAPI middleware or `async with get_session():`).

    ```python
    import asyncio
    from ormodel import get_session
    from examples.models import MyModel # Your model inheriting from ORModel

    async def main():
        async with get_session(): # Manages session context
            # Create
            obj = await MyModel.objects.create(name="Example", value=10)

            # Get
            retrieved_obj = await MyModel.objects.get(id=obj.id)
            print(retrieved_obj)

            # Filter
            # Note: __gt needs Query enhancement, simple equality shown here
            filtered_objs = await MyModel.objects.filter(name="Example").all()
            print(filtered_objs)

    if __name__ == "__main__":
        # Ensure DB setup if running standalone
        # e.g., await create_db_and_tables() or run migrations
        asyncio.run(main())
    ```

4.  **FastAPI Integration:** See `examples/main.py` for middleware setup and endpoint examples.

## Running the Example

1.  Ensure dependencies are installed (`uv pip install -e ".[dev]"`).
2.  Create `.env` in `examples/` based on `.env.example` (if using non-SQLite DB).
3.  Run migrations (`cd examples`, `alembic upgrade head`).
4.  Run the FastAPI app (`cd ..`, `python examples/main.py` or use Docker Compose).
5.  Access `http://localhost:8000/docs`.