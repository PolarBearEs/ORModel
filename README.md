# ORModel

[![codecov](https://codecov.io/gh/PolarBearEs/ORModel/graph/badge.svg)](https://codecov.io/gh/PolarBearEs/ORModel)

Async ORM utilities on top of `sqlmodel` with a `Model.objects` manager API and automatic session handling.

## What you get

- `ORModel` base class for models.
- `Model.objects` manager for query + write operations.
- Async session helpers: `init_database`, `shutdown_database`, `database_context`, `get_session`.
- SQLModel/SQLAlchemy-native filtering with expressions like `Hero.objects.filter(Hero.age >= 18)`.
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
- `get_session()` is the async DB session context manager built on SQLModel/SQLAlchemy `AsyncSession`, and manages transaction scope:
  - commit on success
  - rollback on exception
- Manager/query methods can run without explicit `get_session()`; an automatic short-lived session is created when needed.
- For web apps, use request-scoped `async with get_session()` middleware.

### Session modes

- Explicit session mode (`async with get_session()`): all ORM calls in the block share one session/transaction.
- Auto-session mode (calling manager/query methods without an active context): each call gets its own short-lived session.
- In auto-session mode, returned objects can be detached once the call ends. For relationship access after the call, prefer explicit session mode.

## API reference

`Model.objects` is a `Manager`. Query-building methods return a `Query`, and execution methods are `async`.

### Manager (`Model.objects`)

| Method | Returns | Notes |
| --- | --- | --- |
| `all()` | `Sequence[Model]` | Fetch all rows for model. |
| `first()` | `Model \| None` | First row or `None`. |
| `one()` | `Model` | Exactly one row; raises on 0 or >1. |
| `one_or_none()` | `Model \| None` | `None` on 0 rows; raises on >1. |
| `get(*expr, **filters)` | `Model` | Single row lookup; raises `DoesNotExist` / `MultipleObjectsReturned`. |
| `filter(*expr, **filters)` | `Query[Model]` | Build filtered query. |
| `order_by(*columns)` | `Query[Model]` | Build ordered query. |
| `limit(n)` | `Query[Model]` | Build limited query. |
| `offset(n)` | `Query[Model]` | Build offset query. |
| `join(target)` | `Query[Model]` | Build joined query. |
| `count()` | `int` | Count rows. |
| `update(**values)` | `int` | Bulk update matching rows; returns affected row count. |
| `create(**values)` | `Model` | Validate + insert + refresh one row. |
| `get_or_create(defaults=None, **filters)` | `tuple[Model, bool]` | `(obj, created)`; creates if not found. |
| `update_or_create(defaults=None, **filters)` | `tuple[Model, bool]` | `(obj, created)`; updates found row or creates new row. |
| `delete()` | `int` | Bulk-delete all rows for this model. |
| `bulk_create(list[Model])` | `list[Model]` | Insert many instances with `session.add_all`. |

### Query (`Model.objects.filter(...)`)

| Method | Returns | Notes |
| --- | --- | --- |
| `filter(*expr, **filters)` | `Query[Model]` | Add `WHERE` clauses (`*expr` for SQL expressions, `**filters` for exact field equality only). |
| `order_by(*columns)` | `Query[Model]` | Add ordering. |
| `limit(n)` | `Query[Model]` | Add SQL `LIMIT`. |
| `offset(n)` | `Query[Model]` | Add SQL `OFFSET`. |
| `join(target)` | `Query[Model]` | Add SQL `JOIN`. |
| `all()` | `Sequence[Model]` | Execute and return all rows. |
| `first()` | `Model \| None` | Execute and return first row. |
| `one()` | `Model` | Execute expecting exactly one row. |
| `one_or_none()` | `Model \| None` | Execute expecting <=1 row. |
| `get(*expr, **filters)` | `Model` | Shortcut for `filter(...).one()`. |
| `count()` | `int` | Count matching rows. |
| `update(**values)` | `int` | Bulk update matching rows. |
| `delete()` | `int` | Bulk delete matching rows. |

Comparison filters use SQL expressions:

```python
adults = await Hero.objects.filter(Hero.age > 18).all()
teens = await Hero.objects.filter(Hero.age >= 13, Hero.age < 20).all()
```

Keyword filters remain exact-match only:

```python
exact_18 = await Hero.objects.filter(age=18).all()
```

### Model instance methods (`ORModel`)

| Method | Returns | Notes |
| --- | --- | --- |
| `save()` | `Self` | Insert/update current instance and refresh it. |
| `delete()` | `None` | Delete current instance. |

### Database/session helpers

| Function | Returns | Notes |
| --- | --- | --- |
| `init_database(database_url, echo_sql=False)` | `None` | Initialize engine + sessionmaker. |
| `shutdown_database()` | `None` | Dispose engine and clear factory. |
| `database_context(database_url, echo_sql=False)` | async context manager | Convenience wrapper for init/shutdown in scripts. |
| `get_session()` | async context manager | Transaction scope: commit on success, rollback on error. |
| `get_engine()` | `AsyncEngine` | Access initialized engine. |
| `get_session_from_context()` | `AsyncSession` | Get current context session; raises if absent. |

### Exceptions

| Exception | When raised |
| --- | --- |
| `DoesNotExist` | A query expected one row and found none. |
| `MultipleObjectsReturned` | A query expected one row and found more than one. |
| `SessionContextError` | A session was required but none exists in context. |

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

@app.get("/heroes", dependencies=[Depends(db_session_scope)])
async def read_heroes():
    return await Hero.objects.all()
```

If your app genuinely needs DB scope for every request, use middleware instead:

```python
from fastapi import Request

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    async with get_session():
        return await call_next(request)
```

## Repository Pattern Example

You can keep data access in repository classes and keep business logic in services.
See the complete runnable example in:

- `examples/repository_pattern.py`

Minimal shape:

```python
class HeroRepository:
    async def create(self, **data) -> Hero:
        return await Hero.objects.create(**data)

    async def list_adults(self) -> list[Hero]:
        return list(await Hero.objects.filter(Hero.age >= 18).order_by(Hero.name).all())

class HeroService:
    def __init__(self, heroes: HeroRepository):
        self.heroes = heroes

    async def register(self, name: str, secret_name: str, age: int) -> Hero:
        return await self.heroes.create(name=name, secret_name=secret_name, age=age)
```

Usage:

```python
async with database_context("sqlite+aiosqlite:///./example.db"):
    async with get_session():
        service = HeroService(HeroRepository())
        await service.register("Flash", "Barry Allen", 28)
```

## Commands (consistent `uv run` style)

From repository root:

- Run examples as modules (for example, `python -m examples.standalone`), not as direct files.
- Run tests: `uv run pytest -v`
- Run tests with coverage: `uv run pytest --cov=ormodel --cov-branch --cov-report=xml`
- Run API example: `uv run python -m examples.api`
- Run standalone example: `uv run python -m examples.standalone`
- Run repository-pattern example: `uv run python -m examples.repository_pattern`
- Run alembic in examples: `cd examples && uv run alembic upgrade head`

## Development notes

- Tests use SQLite via configured `DATABASE_URL` (default in `pyproject.toml` is `sqlite+aiosqlite:///./default.db`) and recreate schema per test.
- Package exports live in `ormodel/__init__.py`.

## License

MIT
