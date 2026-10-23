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
from ormodel import create_tables, database_context, get_session

async def main() -> None:
    async with database_context("sqlite+aiosqlite:///./example.db"):
        await create_tables()
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
- SQLite gets automatic lock-contention defaults: `busy_timeout=30000`, `foreign_keys=ON`, and file-based databases use `journal_mode=WAL` with `synchronous=NORMAL`.
- SQLite still allows only one writer at a time. These defaults reduce `database is locked` failures by waiting longer and using WAL, but they do not make writes fully parallel.

### Session modes

- Explicit session mode (`async with get_session()`): all ORM calls in the block share one session/transaction.
- Auto-session mode (calling manager/query methods without an active context): each call gets its own short-lived session.
- In auto-session mode, returned objects can be detached once the call ends. For relationship access after the call, prefer explicit session mode.

## API reference

The API follows three rules:

- **Reads take filters**: SQL expressions (`Hero.age >= 18`) and/or exact-match keywords (`name="Flash"`).
- **Writes take model instances**, so the values you persist are the Pydantic models you already have.
- **Every single-row write has a bulk counterpart.**

`Model.objects` is a `Manager`, which is itself an unfiltered `Query`: everything you can call on
`Hero.objects.filter(...)` you can call on `Hero.objects` directly. Builders return a new immutable `Query`;
everything that touches the database is `async`.

### Reading

| Method | Returns | Notes |
| --- | --- | --- |
| `filter(*expr, **exact)` | `Query` | Add `WHERE` clauses. |
| `order_by(*columns)` / `limit(n)` / `offset(n)` / `join(target, ...)` | `Query` | Shape the query. |
| `all()` | `Sequence[Model]` | Every matching row. |
| `first()` | `Model \| None` | First matching row, or `None`. |
| `one()` / `one_or_none()` | `Model` / `Model \| None` | Exactly one row; raises `MultipleObjectsReturned` on >1 (`one()` raises `DoesNotExist` on 0). |
| `get(*expr, **exact)` / `get_or_none(*expr, **exact)` | `Model` / `Model \| None` | Shortcuts for `filter(...).one()` / `filter(...).one_or_none()`. |
| `exists()` | `bool` | Whether anything matches. |
| `count()` | `int` | Number of rows the query returns (joins/limit/offset respected). |

```python
adults = await Hero.objects.filter(Hero.age >= 18).order_by(Hero.name).all()
flash = await Hero.objects.get_or_none(name="Flash")
```

### Writing

| Single row | Bulk | Notes |
| --- | --- | --- |
| `Model.objects.create(**values)` | `Model.objects.bulk_create(objs)` | `create` validates `values` into a model first. |
| `instance.save()` | | Insert or update this instance, then refresh it. |
| `Model.objects.get_or_create(obj, *, on=None)` | | Return the row matching `obj`, or insert `obj`. |
| `Model.objects.upsert(obj, *, on=None, update_fields=None)` | `Model.objects.bulk_upsert(objs, *, on=None, update_fields=None)` | Update the row matching `obj`, or insert `obj`. |
| `instance.delete()` | `query.delete(*, each=False)` | |
| | `query.update(*, each=False, **values)` | Set `values` on every matching row. |

`get_or_create`, `upsert` and `bulk_upsert` share the same arguments:

- `on`: the fields that identify an existing row. A field name, a column (`Hero.name`) or a list of them;
  defaults to the primary key.
- `update_fields`: the fields copied onto an existing row. Defaults to the fields **explicitly set** on the
  instance, so values you didn't pass never overwrite stored data.

All three return what was stored: `get_or_create` and `upsert` return `(instance, created)`, `bulk_upsert` returns
the number of rows written.

```python
team, created = await Team.objects.get_or_create(Team(name="Avengers", headquarters="NY"), on=Team.name)

# Only secret_name and age are copied onto an existing "Flash"; nothing else is touched.
hero, created = await Hero.objects.upsert(Hero(name="Flash", secret_name="Barry", age=28), on="name")

# One INSERT ... ON CONFLICT per 500 rows instead of a SELECT + INSERT per row.
await Team.objects.bulk_upsert(teams_from_api, on=Team.name)

# Bulk writes on a filtered query
await Hero.objects.filter(Hero.age < 18).update(team_id=None)
await Hero.objects.filter(name="Flash").delete()
```

Differences worth knowing:

- `get_or_create`/`upsert` look the row up first, so `on` can be any fields. When nothing matches they insert
  inside a SAVEPOINT: if a concurrent insert wins the race, the existing row is used and your transaction stays
  usable.
- `bulk_upsert` uses the database's native `INSERT ... ON CONFLICT` (SQLite and PostgreSQL). `on` must be covered
  by a unique constraint or index, and instances repeating the same `on` values collapse to the last one.
- `query.update()`/`query.delete()` refuse to run on an unfiltered query unless you pass `each=True`, so
  `await Hero.objects.delete()` can't wipe a table when you meant `await hero.delete()`. They also refuse
  `limit()`/`offset()` rather than silently touching every matching row.

### Database and sessions

| Function | Returns | Notes |
| --- | --- | --- |
| `init_database(database_url, echo_sql=False)` | `None` | Create the engine. Repeating the same URL is a no-op; a different URL raises. |
| `shutdown_database()` | `None` | Dispose the engine. |
| `database_context(database_url, echo_sql=False)` | async context manager | `init_database` + `shutdown_database` for scripts. Cannot be nested. |
| `create_tables(drop_existing=False)` | `None` | Create every table defined by your models. |
| `get_session()` | async context manager | Transaction scope: commit on success, rollback on error. |
| `get_session_from_context()` | `AsyncSession` | The current session; raises `SessionContextError` if none. |
| `get_engine()` | `AsyncEngine` | The initialized engine. |

Only an entry point (a script's `main`, an app's lifespan) should open `database_context` or call
`init_database`. Code running underneath uses `get_session()`.

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
