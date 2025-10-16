import inspect
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any, Generic, Self, TypeVar, cast

from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlalchemy.sql.elements import BinaryExpression
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .database import get_session, get_session_from_context
from .exceptions import DoesNotExist, MultipleObjectsReturned, SessionContextError

# Generic Type variable for the ORModel model
ModelType = TypeVar("ModelType", bound="ORModel")  # Use string forward reference

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


class ManagerMetaclass(type):
    """Metaclass that automatically adds session management to all public async Manager methods."""

    EXCLUDED_METHODS = ["filter"]

    def __new__(mcs, name: str, bases: tuple, attrs: dict[str, Any]) -> type:
        for method_name, method in list(attrs.items()):
            is_public = not method_name.startswith("_")
            is_not_excluded = method_name not in mcs.EXCLUDED_METHODS

            if is_public and is_not_excluded and inspect.iscoroutinefunction(method):
                # Apply the new decorator
                attrs[method_name] = with_auto_session(method)

        return super().__new__(mcs, name, bases, attrs)


class Query(Generic[ModelType]):
    """Represents a query that can be chained or executed."""

    def __init__(self, model_cls: type[ModelType], session: AsyncSession, statement: Any | None = None):
        self._model_cls = model_cls
        self._session = session
        self._statement = statement if statement is not None else select(self._model_cls)

    def _clone(self) -> Self:
        """Creates a copy of the query to allow chaining."""
        new_query = Query(self._model_cls, self._session)
        new_query._statement = self._statement
        return cast(Self, new_query)

    async def _execute(self):
        """Executes the internal statement."""
        return await self._session.exec(self._statement)

    async def all(self) -> Sequence[ModelType]:
        """Executes the query and returns all results."""
        results = await self._execute()
        return results.all()

    async def first(self) -> ModelType | None:
        """Executes the query and returns the first result or None."""
        result_obj = await self._session.exec(self._statement)
        return result_obj.first()

    async def one_or_none(self) -> ModelType | None:
        """
        Executes the query and returns exactly one result or None.
        Raises MultipleObjectsReturned if multiple results found.
        """
        result_obj = await self._session.exec(self._statement.limit(2))
        all_results = result_obj.all()
        count = len(all_results)
        if count == 0:
            return None
        if count == 1:
            return all_results[0]
        raise MultipleObjectsReturned(f"Expected one or none for {self._model_cls.__name__}, but found {count}")

    async def one(self) -> ModelType:
        """
        Executes the query and returns exactly one result.
        Raises DoesNotExist if no object is found.
        Raises MultipleObjectsReturned if multiple objects are found.
        """
        result_obj = await self._session.exec(self._statement.limit(2))
        all_results = result_obj.all()
        count = len(all_results)

        if count == 0:
            raise DoesNotExist(f"{self._model_cls.__name__} matching query does not exist.")
        if count > 1:
            raise MultipleObjectsReturned(f"Expected one result for {self._model_cls.__name__}, but found {count}")
        return all_results[0]

    async def get(self, *args: BinaryExpression, **kwargs: Any) -> ModelType:
        """
        Retrieves a single object matching the criteria (applied via filter).
        Raises DoesNotExist if no object is found.
        Raises MultipleObjectsReturned if multiple objects are found.
        """
        return await self.filter(*args, **kwargs).one()

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> Self:
        """
        Filters the query based on SQLAlchemy BinaryExpressions or keyword arguments.
        Returns a new Query instance.
        """
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
        """
        Performs a bulk update on all objects matching the current query filter.

        This is a direct database operation and is highly efficient. It does NOT
        trigger any ORM events, validations, or lifecycle hooks on the models.

        Args:
            **kwargs: Keyword arguments mapping column names to their new values.

        Returns:
            The number of rows updated.
        """
        if not kwargs:
            return 0  # Nothing to update

        update_stmt = sa_update(self._model_cls).values(**kwargs)

        where_clause = self._statement.whereclause
        if where_clause is not None:
            update_stmt = update_stmt.where(where_clause)

        result = await self._session.exec(update_stmt)
        return result.rowcount

    async def count(self) -> int:
        """Returns the count of objects matching the query."""
        pk_col = getattr(self._model_cls, self._model_cls.__mapper__.primary_key[0].name)
        where_clause = self._statement.whereclause
        count_statement = select(func.count(pk_col)).select_from(self._model_cls)
        if where_clause is not None:
            count_statement = count_statement.where(where_clause)
        result = await self._session.exec(count_statement)
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


class Manager(Generic[ModelType], metaclass=ManagerMetaclass):
    """Provides Django-style access to query operations for a model."""

    def __init__(self, model_cls: type[ModelType]):
        self._model_cls = model_cls
        self._session: AsyncSession | None = None
        self._statement = None

    def _get_session(self) -> AsyncSession:
        """Internal helper to get the session from context."""
        return get_session_from_context()

    def _get_base_query(self) -> Query[ModelType]:
        """Internal helper to create a base Query object."""
        session = self._get_session()
        query_obj = Query(self._model_cls, session, self._statement)
        self._statement = None  # Reset statement after creating Query object
        return query_obj

    async def all(self) -> Sequence[ModelType]:
        """Returns all objects of this model type."""
        return await self._get_base_query().all()

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> Self:
        """Starts a filtering query."""
        if self._statement is None:
            self._statement = select(self._model_cls)

        conditions = list(args)
        for key, value in kwargs.items():
            field_name = key.split("__")[0]
            if not hasattr(self._model_cls, field_name):
                raise AttributeError(f"'{self._model_cls.__name__}' has no attribute '{field_name}' for filtering")
            attr = getattr(self._model_cls, field_name)
            conditions.append(attr == value)
        if conditions:
            self._statement = self._statement.where(*conditions)
        return self

    def order_by(self, *args: Any) -> Self:
        """Applies ordering to the query."""
        if self._statement is None:
            self._statement = select(self._model_cls)
        self._statement = self._statement.order_by(*args)
        return self

    async def get(self, *args: BinaryExpression, **kwargs: Any) -> ModelType:
        """Retrieves a single object matching criteria."""
        return await self._get_base_query().get(*args, **kwargs)

    async def count(self) -> int:
        """Returns the total count of objects for this model."""
        return await self._get_base_query().count()

    async def update(self, **kwargs: Any) -> int:
        """
        Performs a bulk update on all objects matching the current query filter.

        This is a direct database operation and is highly efficient. It does NOT
        trigger any ORM events, validations, or lifecycle hooks on the models.

        Args:
            **kwargs: Keyword arguments mapping column names to their new values.

        Returns:
            The number of rows updated.
        """
        return await self._get_base_query().update(**kwargs)

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
        """
        Looks for an object with the given kwargs. Creates one if it doesn't exist.
        Returns a tuple of (object, created), where created is a boolean.
        """
        defaults = defaults or {}
        try:
            obj = await self.get(**kwargs)
            return obj, False
        except DoesNotExist:
            create_kwargs = {**kwargs, **defaults}
            try:
                obj = await self.create(**create_kwargs)
                return obj, True
            except Exception as create_exc:
                try:
                    obj = await self.get(**kwargs)
                    return obj, False
                except DoesNotExist:
                    raise create_exc from None

    async def update_or_create(self, defaults: dict[str, Any] | None = None, **kwargs: Any) -> tuple[ModelType, bool]:
        """
        Looks for an object with given kwargs. Updates it if it exists, otherwise creates.
        Returns a tuple of (object, created).
        """
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
                instance_data = await self.create(**create_kwargs)
                return instance_data, True
            except Exception as create_exc:
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

    def join(self, target: Any) -> Self:
        """
        Applies a join to the query, allowing filtering and retrieval across related models.

        Args:
            target: The target model or relationship to join with.

        Returns:
            A new Manager instance with the join applied.
        """
        if self._statement is None:
            self._statement = select(self._model_cls)
        self._statement = self._statement.join(target)
        return self
