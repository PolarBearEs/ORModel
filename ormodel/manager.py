from collections.abc import Awaitable, Callable, Iterable, Sequence
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate, Generic, ParamSpec, TypeVar, cast

from sqlalchemy import func
from sqlalchemy import update as sa_update
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

    def _where_only(self, operation: str) -> ColumnElement[bool] | None:
        """Return the WHERE clause for bulk operations, refusing clauses they would silently drop."""
        if self._statement._limit_clause is not None or self._statement._offset_clause is not None:
            raise ValueError(f"{operation}() does not support limit()/offset(); filter the rows instead.")
        return self._statement.whereclause

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

    @with_auto_session
    async def count(self) -> int:
        """Returns the count of objects matching the query (joins, limit and offset included)."""
        subquery = self._statement.order_by(None).subquery()
        result = await self._get_session().exec(select(func.count()).select_from(subquery))
        return cast(int, result.one())

    @with_auto_session
    async def update(self, **values: Any) -> int:
        """Performs a bulk update on all rows matching the current query filter."""
        if not values:
            return 0
        stmt = sa_update(self._model_cls).values(**values)
        where_clause = self._where_only("update")
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        result = await self._get_session().exec(stmt)
        return result.rowcount

    @with_auto_session
    async def delete(self) -> int:
        """Performs a bulk delete on all rows matching the current query filter."""
        stmt = sqlmodel_delete(self._model_cls)
        where_clause = self._where_only("delete")
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
        existing = await self.filter(**lookup).one_or_none() if lookup else None
        if existing is None:
            existing, created = await self._insert_or_fetch(obj, lookup)
            if created:
                return existing, True

        if update_fields is not None:
            fields = {self._field_name(f) for f in update_fields}
        else:
            fields = set(obj.model_fields_set) - lookup.keys() - set(self._primary_key())

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

    # --- Helpers ---

    def _primary_key(self) -> list[str]:
        return [column.key for column in self._model_cls.__table__.primary_key]  # type: ignore[attr-defined]

    def _field_name(self, field: FieldRef) -> str:
        name = field if isinstance(field, str) else getattr(field, "key", None)
        if not isinstance(name, str) or name not in self._model_cls.model_fields:
            raise AttributeError(f"'{self._model_cls.__name__}' has no field {field!r}")
        return name

    def _lookup(self, obj: ModelType, on: FieldRef | Sequence[FieldRef] | None) -> dict[str, Any]:
        """Build the `{field: value}` lookup taken from `obj`; empty when matching on an unset primary key."""
        if on is None:
            lookup = {name: getattr(obj, name) for name in self._primary_key()}
            return lookup if any(value is not None for value in lookup.values()) else {}
        fields = [on] if isinstance(on, str) or not isinstance(on, Sequence) else on
        if not fields:
            raise ValueError("`on` must name at least one field.")
        return {name: getattr(obj, name) for name in map(self._field_name, fields)}

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
