from collections.abc import Awaitable, Callable, Iterable, Sequence
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, Generic, ParamSpec, TypeVar, cast

from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import delete as sqlmodel_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import SelectOfScalar

from .database import get_session, get_session_from_context
from .exceptions import DoesNotExist, MultipleObjectsReturned, SessionContextError

if TYPE_CHECKING:
    from .base import ORModel

# Generic Type variable for the ORModel model
ModelType = TypeVar("ModelType", bound="ORModel")
S = TypeVar("S")
P = ParamSpec("P")
R = TypeVar("R")

_DIALECT_INSERTS: dict[str, Callable[[Any], Any]] = {"sqlite": sqlite_insert, "postgresql": postgresql_insert}

# A field reference: either its name or the class attribute (e.g. "name" or Hero.name)
FieldRef = Any


def with_auto_session(
    func: Callable[Concatenate[S, P], Awaitable[R]],
) -> Callable[Concatenate[S, P], Awaitable[R]]:
    """Run the wrapped method in a short-lived session if none is active in the context."""

    @wraps(func)
    async def wrapper(self: S, *args: P.args, **kwargs: P.kwargs) -> R:
        try:
            get_session_from_context()
        except SessionContextError:
            async with get_session():
                return await func(self, *args, **kwargs)
        return await func(self, *args, **kwargs)

    return wrapper


class Query(Generic[ModelType]):
    """Immutable query: builder methods return a new Query, async methods execute it."""

    def __init__(self, model_cls: type[ModelType], statement: SelectOfScalar[ModelType] | None = None):
        self._model_cls = model_cls
        self._base_statement = statement

    @property
    def _statement(self) -> SelectOfScalar[ModelType]:
        # Built lazily: managers are created in __init_subclass__, before the table is mapped.
        if self._base_statement is None:
            return select(self._model_cls)
        return self._base_statement

    def _derive(self, statement: SelectOfScalar[ModelType]) -> "Query[ModelType]":
        return Query(self._model_cls, statement)

    def _get_session(self) -> AsyncSession:
        """Resolve current request/task session from context."""
        return get_session_from_context()

    def _bulk_where(self, operation: str, each: bool) -> ColumnElement[bool] | None:
        """Return the WHERE clause for bulk operations, refusing ones that would touch rows by accident."""
        if self._statement._limit_clause is not None or self._statement._offset_clause is not None:
            raise ValueError(f"{operation}() does not support limit()/offset(); filter the rows instead.")
        where_clause = self._statement.whereclause
        if where_clause is None and not each:
            raise ValueError(f"{operation}() on an unfiltered query affects every row; pass each=True to confirm.")
        return where_clause

    # --- Builders ---

    def filter(self, *args: ColumnElement[bool], **kwargs: Any) -> "Query[ModelType]":
        """Filters query by SQLAlchemy expressions and exact-match keyword conditions."""
        conditions = list(args)
        for key, value in kwargs.items():
            if not hasattr(self._model_cls, key):
                raise AttributeError(f"'{self._model_cls.__name__}' has no attribute '{key}' for filtering")
            conditions.append(getattr(self._model_cls, key) == value)
        if not conditions:
            return self
        return self._derive(self._statement.where(*conditions))

    def order_by(self, *args: Any) -> "Query[ModelType]":
        """Applies ordering to the query."""
        return self._derive(self._statement.order_by(*args))

    def limit(self, count: int) -> "Query[ModelType]":
        """Applies a limit to the query."""
        return self._derive(self._statement.limit(count))

    def offset(self, count: int) -> "Query[ModelType]":
        """Applies an offset to the query."""
        return self._derive(self._statement.offset(count))

    def join(self, target: Any, *args: Any, **kwargs: Any) -> "Query[ModelType]":
        """Applies a join to the query."""
        return self._derive(self._statement.join(target, *args, **kwargs))

    # --- Execution ---

    @with_auto_session
    async def all(self) -> Sequence[ModelType]:
        """Executes the query and returns all results."""
        result = await self._get_session().exec(self._statement)
        return result.all()

    @with_auto_session
    async def first(self) -> ModelType | None:
        """Executes the query and returns the first result or None."""
        result = await self._get_session().exec(self._statement)
        return result.first()

    @with_auto_session
    async def one_or_none(self) -> ModelType | None:
        """Executes the query and returns exactly one result or None."""
        result = await self._get_session().exec(self._statement.limit(2))
        rows = result.all()
        if len(rows) > 1:
            raise MultipleObjectsReturned(f"Expected one or none for {self._model_cls.__name__}, but found {len(rows)}")
        return rows[0] if rows else None

    @with_auto_session
    async def one(self) -> ModelType:
        """Executes the query and returns exactly one result."""
        result = await self._get_session().exec(self._statement.limit(2))
        rows = result.all()
        if not rows:
            raise DoesNotExist(f"{self._model_cls.__name__} matching query does not exist.")
        if len(rows) > 1:
            raise MultipleObjectsReturned(f"Expected one result for {self._model_cls.__name__}, but found {len(rows)}")
        return rows[0]

    async def get(self, *args: ColumnElement[bool], **kwargs: Any) -> ModelType:
        """Retrieves a single object matching the criteria (applied via filter)."""
        return await self.filter(*args, **kwargs).one()

    async def get_or_none(self, *args: ColumnElement[bool], **kwargs: Any) -> ModelType | None:
        """Like get(), but returns None instead of raising DoesNotExist."""
        return await self.filter(*args, **kwargs).one_or_none()

    @with_auto_session
    async def exists(self) -> bool:
        """Returns whether the query matches at least one row."""
        result = await self._get_session().exec(select(self._statement.exists()))
        return bool(result.one())

    @with_auto_session
    async def count(self) -> int:
        """Returns the count of objects matching the query (joins, limit and offset included)."""
        subquery = self._statement.order_by(None).subquery()
        result = await self._get_session().exec(select(func.count()).select_from(subquery))
        return cast(int, result.one())

    @with_auto_session
    async def update(self, *, each: bool = False, **values: Any) -> int:
        """Sets `values` on every row matching the query. An unfiltered query requires each=True."""
        where_clause = self._bulk_where("update", each)
        if not values:
            return 0
        stmt = sa_update(self._model_cls).values(**values)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self._get_session().exec(stmt)
        return result.rowcount

    @with_auto_session
    async def delete(self, *, each: bool = False) -> int:
        """Deletes every row matching the query. An unfiltered query requires each=True."""
        where_clause = self._bulk_where("delete", each)
        stmt = sqlmodel_delete(self._model_cls)
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self._get_session().exec(stmt)
        return result.rowcount


class Manager(Query[ModelType]):
    """`Model.objects`: an unfiltered Query over the model plus instance-level write helpers."""

    def __init__(self, model_cls: type[ModelType]):
        super().__init__(model_cls)

    @with_auto_session
    async def create(self, **values: Any) -> ModelType:
        """Validates `values` into a new instance, inserts it and returns it."""
        obj = self._model_cls.model_validate(values)
        session = self._get_session()
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    @with_auto_session
    async def bulk_create(self, objs: Iterable[ModelType]) -> list[ModelType]:
        """Inserts many instances in a single flush."""
        objs = list(objs)
        session = self._get_session()
        session.add_all(objs)
        await session.flush()
        return objs

    @with_auto_session
    async def get_or_create(
        self, obj: ModelType, *, on: FieldRef | Sequence[FieldRef] | None = None
    ) -> tuple[ModelType, bool]:
        """
        Returns the stored row matching `obj` on the `on` fields, or inserts `obj`.

        `on` defaults to the primary key. The returned flag is True when `obj` was inserted.
        """
        lookup = self._lookup(obj, on)
        if lookup:
            existing = await self.filter(**lookup).one_or_none()
            if existing is not None:
                return existing, False
        return await self._insert_or_fetch(obj, lookup)

    @with_auto_session
    async def upsert(
        self,
        obj: ModelType,
        *,
        on: FieldRef | Sequence[FieldRef] | None = None,
        update_fields: Sequence[FieldRef] | None = None,
    ) -> tuple[ModelType, bool]:
        """
        Inserts `obj`, or copies its values onto the stored row matching it on the `on` fields.

        `on` defaults to the primary key. When updating, only the fields explicitly set on `obj`
        are copied, unless `update_fields` names them. The returned flag is True when `obj` was inserted.
        """
        lookup = self._lookup(obj, on)
        fields = self._update_fields([obj], self._on_fields(on), update_fields)
        existing = await self.filter(**lookup).one_or_none() if lookup else None
        if existing is None:
            existing, created = await self._insert_or_fetch(obj, lookup)
            if created:
                return existing, True

        changed = False
        for name in fields:
            value = getattr(obj, name)
            if getattr(existing, name) != value:
                setattr(existing, name, value)
                changed = True
        if changed:
            session = self._get_session()
            session.add(existing)
            await session.flush()
            await session.refresh(existing)
        return existing, False

    @with_auto_session
    async def bulk_upsert(
        self,
        objs: Iterable[ModelType],
        *,
        on: FieldRef | Sequence[FieldRef] | None = None,
        update_fields: Sequence[FieldRef] | None = None,
        chunk_size: int = 500,
    ) -> int:
        """
        Inserts many instances with native `INSERT ... ON CONFLICT DO UPDATE` (SQLite and PostgreSQL).

        Same rules as upsert(), except that `on` must be covered by a unique constraint or index, conflicting
        rows get the union of the fields set on the instances, and instances repeating the same `on` values
        collapse to the last one. Returns the number of rows written; the instances are not refreshed.
        """
        objs = list(objs)
        keys = self._on_fields(on)
        table = self._model_cls.__table__  # type: ignore[attr-defined]
        rows: dict[tuple[Any, ...], dict[str, Any]] = {}
        for obj in objs:
            row = {column.key: getattr(obj, column.key) for column in table.columns}
            rows[tuple(row[key] for key in keys)] = row
        if not rows:
            return 0
        values = list(rows.values())
        # Leave unset primary keys to the database (autoincrement), as a regular insert would.
        for key in self._primary_key():
            if key not in keys and all(row[key] is None for row in values):
                for row in values:
                    del row[key]
        updates = self._update_fields(objs, keys, update_fields)

        session = self._get_session()
        dialect = session.bind.dialect.name if session.bind is not None else None
        if dialect not in _DIALECT_INSERTS:
            raise NotImplementedError(f"bulk_upsert() is not supported for the {dialect!r} dialect.")
        for start in range(0, len(values), chunk_size):
            stmt = _DIALECT_INSERTS[dialect](table).values(values[start : start + chunk_size])
            if updates:
                stmt = stmt.on_conflict_do_update(
                    index_elements=keys, set_={name: stmt.excluded[name] for name in updates}
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=keys)
            await session.exec(stmt)
        # The statement bypasses the identity map: refresh instances this session already holds.
        for held in list(session.identity_map.values()):
            if isinstance(held, self._model_cls) and tuple(getattr(held, key) for key in keys) in rows:
                await session.refresh(held)
        return len(values)

    # --- Helpers ---

    def _primary_key(self) -> list[str]:
        return [column.key for column in self._model_cls.__table__.primary_key]  # type: ignore[attr-defined]

    def _field_name(self, field: FieldRef) -> str:
        name = field if isinstance(field, str) else getattr(field, "key", None)
        if not isinstance(name, str) or name not in self._model_cls.model_fields:
            raise AttributeError(f"'{self._model_cls.__name__}' has no field {field!r}")
        return name

    def _on_fields(self, on: FieldRef | Sequence[FieldRef] | None) -> list[str]:
        """Resolve `on` to field names, defaulting to the primary key."""
        if on is None:
            return self._primary_key()
        fields = [on] if isinstance(on, str) or not isinstance(on, Sequence) else on
        if not fields:
            raise ValueError("`on` must name at least one field.")
        return [self._field_name(field) for field in fields]

    def _lookup(self, obj: ModelType, on: FieldRef | Sequence[FieldRef] | None) -> dict[str, Any]:
        """Build the `{field: value}` lookup taken from `obj`; empty when matching on an unset primary key."""
        lookup = {name: getattr(obj, name) for name in self._on_fields(on)}
        if on is None and all(value is None for value in lookup.values()):
            return {}
        return lookup

    def _update_fields(
        self, objs: Iterable[ModelType], keys: Iterable[str], update_fields: Sequence[FieldRef] | None
    ) -> list[str]:
        """Fields copied onto an existing row: `update_fields`, or every field explicitly set on `objs`."""
        if update_fields is not None:
            fields = [self._field_name(field) for field in update_fields]
            if primary_key := set(fields) & set(self._primary_key()):
                raise ValueError(f"update_fields cannot include the primary key: {sorted(primary_key)}")
            return fields
        fields_set: set[str] = set().union(*(obj.model_fields_set for obj in objs))
        return sorted(fields_set - set(keys) - set(self._primary_key()))

    async def _insert_or_fetch(self, obj: ModelType, lookup: dict[str, Any]) -> tuple[ModelType, bool]:
        """Insert `obj` in a savepoint; if a concurrent insert wins the race, return that row instead."""
        session = self._get_session()
        try:
            async with session.begin_nested():
                session.add(obj)
                await session.flush()
        except IntegrityError:
            existing = await self.filter(**lookup).one_or_none() if lookup else None
            if existing is None:
                raise
            return existing, False
        await session.refresh(obj)
        return obj, True
