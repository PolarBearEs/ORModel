import inspect
from collections.abc import Callable, Sequence
from functools import wraps
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar, cast

from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .database import get_session, get_session_from_context
from .exceptions import DoesNotExist, MultipleObjectsReturned, SessionContextError

if TYPE_CHECKING:
    from .base import ORModel

# Generic Type variable for the ORModel model
ModelType = TypeVar("ModelType", bound="ORModel")


def with_auto_session(func: Callable) -> Callable:
    """Decorator to automatically create a session if one doesn't exist in the context."""

    @wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            get_session_from_context()
            return await func(self, *args, **kwargs)
        except SessionContextError:
            async with get_session():
                return await func(self, *args, **kwargs)

    return wrapper


class AutoSessionMetaclass(type):
    """Metaclass that adds automatic session management to public async methods."""

    EXCLUDED_METHODS: set[str] = set()

    def __new__(mcs, name: str, bases: tuple[type, ...], attrs: dict[str, Any]) -> type:
        for method_name, method in list(attrs.items()):
            is_public = not method_name.startswith("_")
            is_not_excluded = method_name not in mcs.EXCLUDED_METHODS

            if is_public and is_not_excluded and inspect.iscoroutinefunction(method):
                attrs[method_name] = with_auto_session(method)

        return super().__new__(mcs, name, bases, attrs)


class Query(Generic[ModelType], metaclass=AutoSessionMetaclass):
    """Represents an immutable query that can be chained or executed."""

    def __init__(self, model_cls: type[ModelType], statement: Any | None = None):
        self._model_cls = model_cls
        self._statement = statement if statement is not None else select(self._model_cls)

    def _clone(self) -> Self:
        """Creates a copy of the query to allow chaining."""
        new_query = Query(self._model_cls, self._statement)
        return cast(Self, new_query)

    def _get_session(self) -> AsyncSession:
        """Resolve current request/task session from context."""
        return get_session_from_context()

    async def _execute(self):
        """Executes the internal statement."""
        session = self._get_session()
        return await session.exec(self._statement)

    async def all(self) -> Sequence[ModelType]:
        """Executes the query and returns all results."""
        results = await self._execute()
        return results.all()

    async def first(self) -> ModelType | None:
        """Executes the query and returns the first result or None."""
        result_obj = await self._execute()
        return result_obj.first()

    async def one_or_none(self) -> ModelType | None:
        """Executes the query and returns exactly one result or None."""
        session = self._get_session()
        result_obj = await session.exec(self._statement.limit(2))
        all_results = result_obj.all()
        count = len(all_results)
        if count == 0:
            return None
        if count == 1:
            return all_results[0]
        raise MultipleObjectsReturned(f"Expected one or none for {self._model_cls.__name__}, but found {count}")

    async def one(self) -> ModelType:
        """Executes the query and returns exactly one result."""
        session = self._get_session()
        result_obj = await session.exec(self._statement.limit(2))
        all_results = result_obj.all()
        count = len(all_results)

        if count == 0:
            raise DoesNotExist(f"{self._model_cls.__name__} matching query does not exist.")
        if count > 1:
            raise MultipleObjectsReturned(f"Expected one result for {self._model_cls.__name__}, but found {count}")
        return all_results[0]

    async def get(self, *args: ColumnElement[bool], **kwargs: Any) -> ModelType:
        """Retrieves a single object matching the criteria (applied via filter)."""
        return await self.filter(*args, **kwargs).one()

    def filter(self, *args: ColumnElement[bool], **kwargs: Any) -> Self:
        """Filters query by SQLAlchemy expressions and keyword equality conditions."""
        new_query = self._clone()
        conditions = list(args)
        for key, value in kwargs.items():
            field_name = key.split("__")[0]
            if not hasattr(self._model_cls, field_name):
                raise AttributeError(f"'{self._model_cls.__name__}' has no attribute '{field_name}' for filtering")
            attr = getattr(self._model_cls, field_name)
            conditions.append(attr == value)
        if conditions:
            new_query._statement = new_query._statement.where(*conditions)
        return new_query

    async def update(self, **kwargs: Any) -> int:
        """Performs a bulk update on all rows matching the current query filter."""
        if not kwargs:
            return 0

        update_stmt = sa_update(self._model_cls).values(**kwargs)

        where_clause = self._statement.whereclause
        if where_clause is not None:
            update_stmt = update_stmt.where(where_clause)

        session = self._get_session()
        result = await session.exec(update_stmt)
        return result.rowcount

    async def count(self) -> int:
        """Returns the count of objects matching the query."""
        where_clause = self._statement.whereclause
        count_statement = select(func.count()).select_from(self._model_cls)
        if where_clause is not None:
            count_statement = count_statement.where(where_clause)

        session = self._get_session()
        result = await session.exec(count_statement)
        return cast(int, result.one())

    def order_by(self, *args: Any) -> Self:
        """Applies ordering to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.order_by(*args)
        return new_query

    def limit(self, count: int) -> Self:
        """Applies a limit to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.limit(count)
        return new_query

    def offset(self, count: int) -> Self:
        """Applies an offset to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.offset(count)
        return new_query

    def join(self, target: Any) -> Self:
        """Applies a join to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.join(target)
        return cast(Self, new_query)


class Manager(Generic[ModelType], metaclass=AutoSessionMetaclass):
    """Provides Django-style access to query operations for a model."""

    _DELEGATED_QUERY_METHODS = {
        "all",
        "first",
        "one",
        "one_or_none",
        "get",
        "count",
        "update",
    }

    def __init__(self, model_cls: type[ModelType]):
        self._model_cls = model_cls

    def _get_session(self) -> AsyncSession:
        """Internal helper to get the session from context."""
        return get_session_from_context()

    def _query(self) -> Query[ModelType]:
        """Create a fresh Query object for this manager call."""
        return Query(self._model_cls)

    def __getattr__(self, name: str) -> Any:
        """Delegate query-execution methods to a fresh Query instance."""
        if name in self._DELEGATED_QUERY_METHODS:
            return getattr(self._query(), name)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def filter(self, *args: ColumnElement[bool], **kwargs: Any) -> Query[ModelType]:
        """Start a filtering query."""
        return self._query().filter(*args, **kwargs)

    def order_by(self, *args: Any) -> Query[ModelType]:
        """Start an ordered query."""
        return self._query().order_by(*args)

    def limit(self, count: int) -> Query[ModelType]:
        """Start a limited query."""
        return self._query().limit(count)

    def offset(self, count: int) -> Query[ModelType]:
        """Start an offset query."""
        return self._query().offset(count)

    def join(self, target: Any) -> Query[ModelType]:
        """Start a joined query."""
        return self._query().join(target)

    async def create(self, **kwargs: Any) -> ModelType:
        """Creates a new object, saves it to the DB, and returns it."""
        session = self._get_session()
        db_obj = self._model_cls.model_validate(kwargs)
        session.add(db_obj)
        try:
            await session.flush()
            await session.refresh(db_obj)
            return db_obj
        except Exception:
            await session.rollback()
            raise

    async def get_or_create(self, defaults: dict[str, Any] | None = None, **kwargs: Any) -> tuple[ModelType, bool]:
        """Looks up an object by kwargs, creating it when it does not exist."""
        defaults = defaults or {}
        try:
            obj = await self.get(**kwargs)
            return obj, False
        except DoesNotExist:
            create_kwargs = {**kwargs, **defaults}
            try:
                obj = await self.create(**create_kwargs)
                return obj, True
            except IntegrityError as create_exc:
                try:
                    obj = await self.get(**kwargs)
                    return obj, False
                except DoesNotExist:
                    raise create_exc from None

    async def update_or_create(self, defaults: dict[str, Any] | None = None, **kwargs: Any) -> tuple[ModelType, bool]:
        """Looks up an object by kwargs, updating it or creating it when absent."""
        session = self._get_session()
        defaults = defaults or {}
        try:
            obj = await self.get(**kwargs)
            updated = False
            for key, value in defaults.items():
                if hasattr(obj, key) and getattr(obj, key) != value:
                    setattr(obj, key, value)
                    updated = True
            if updated:
                session.add(obj)
                await session.flush()
                await session.refresh(obj)
            return obj, False
        except DoesNotExist:
            create_kwargs = {**kwargs, **defaults}
            try:
                obj = await self.create(**create_kwargs)
                return obj, True
            except IntegrityError as create_exc:
                try:
                    obj = await self.get(**kwargs)
                    return obj, False
                except DoesNotExist:
                    raise create_exc from None

    async def delete(self, instance: ModelType) -> None:
        """Deletes a specific model instance."""
        await instance.delete()

    async def bulk_create(self, objs: list[ModelType]) -> list[ModelType]:
        """Performs bulk inserts using session.add_all()."""
        session = self._get_session()
        session.add_all(objs)
        await session.flush()
        return objs
