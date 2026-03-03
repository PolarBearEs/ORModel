# ORModel

[![codecov](https://codecov.io/github/PolarBearEs/ORModel/graph/badge.svg?token=XOGU4WU6CO)](https://codecov.io/github/PolarBearEs/ORModel)

Async ORM utilities on top of `sqlmodel` with a Django-like manager API (`Model.objects`) and automatic session handling.

## What you get

- `ORModel` base class for models.
- `Model.objects` manager for query + write operations.
- Async session helpers: `init_database`, `shutdown_database`, `database_context`, `get_session`.
- Query chaining (`filter`, `order_by`, `join`, `limit`, `offset`) with immutable query objects.
- Auto-session wrapping for manager/query execution methods when no session exists in context.

## Requirements

- Python `3.11+`
- `uv`

## Install

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## Quick start

```python
from sqlmodel import Field
from ormodel import ORModel

class Hero(ORModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    secret_name: str
```

```python
import asyncio
from ormodel import database_context, get_session

async def main() -> None:
    async with database_context("sqlite+aiosqlite:///./example.db"):
        async with get_session():
            hero = await Hero.objects.create(name="Flash", secret_name="Barry")
            same = await Hero.objects.get(id=hero.id)
            print(same)

asyncio.run(main())
```

## Session model

- `init_database(...)` initializes the async engine/sessionmaker once per process.
- `get_session()` manages transaction scope:
  - commit on success
  - rollback on exception
- Manager/query methods can run without explicit `get_session()`; an automatic short-lived session is created when needed.
- For web apps, use request-scoped `async with get_session()` middleware.

## Query and manager API

Common read/query calls:

```python
await Hero.objects.all()
await Hero.objects.get(name="Flash")
await Hero.objects.filter(Hero.age >= 18).order_by(Hero.id).all()
await Hero.objects.filter(name="Flash").update(age=29)
await Hero.objects.count()
```

Write helpers:

```python
hero = await Hero.objects.create(name="Flash", secret_name="Barry")
hero.age = 29
await hero.save()
await hero.delete()

obj, created = await Hero.objects.get_or_create(name="Flash", defaults={"secret_name": "Barry"})
obj, created = await Hero.objects.update_or_create(name="Flash", defaults={"age": 30})
```

## FastAPI integration pattern

Use lifespan for DB lifecycle and a route-level dependency for DB transaction scope:

```python
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from ormodel import init_database, shutdown_database, get_session

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database("sqlite+aiosqlite:///./example.db")
    yield
    await shutdown_database()

app = FastAPI(lifespan=lifespan)

async def db_session_scope() -> AsyncGenerator[None, None]:
    async with get_session():
        yield

DB = [Depends(db_session_scope)]

@app.get("/heroes", dependencies=DB)
async def read_heroes():
    return await Hero.objects.all()
```

If your app genuinely needs DB scope for every request, use middleware instead.

## Commands (consistent `uv run` style)

From repository root:

- Run tests: `uv run pytest -v`
- Run tests with coverage: `uv run pytest --cov=ormodel --cov-branch --cov-report=xml`
- Run API example: `uv run python -m examples.api`
- Run standalone example: `uv run python -m examples.standalone`
- Run alembic in examples: `cd examples && uv run alembic upgrade head`

## Development notes

- Tests use SQLite via configured `DATABASE_URL` (default in `pyproject.toml` is `sqlite+aiosqlite:///./default.db`) and recreate schema per test.
- Package exports live in `ormodel/__init__.py`.

## License

MIT
