import asyncio
from typing import Any, Generic, List, Optional, Sequence, Type, TypeVar, cast, Callable, Awaitable, Dict
from functools import wraps
import inspect
from sqlalchemy import func, update as sa_update, select as sa_select
from sqlmodel import select
from sqlalchemy.sql.elements import BinaryExpression
from sqlmodel.ext.asyncio.session import AsyncSession

from .database import get_session_from_context, get_session
from .exceptions import DoesNotExist, MultipleObjectsReturned, SessionContextError

# Generic Type variable for the ORModel model
ModelType = TypeVar("ModelType", bound="ORModel")  # Use string forward reference


async def _with_auto_session(func: Callable, self: Any, *args: Any, **kwargs: Any) -> Any:
    """Function to automatically create a session if one doesn't exist in the context."""
    try:
        get_session_from_context()
        return await func(self, *args, **kwargs)
    except SessionContextError:
        async with get_session() as session:
            return await func(self, *args, **kwargs)


class ManagerMetaclass(type):
    """Metaclass that automatically adds session management to all public async Manager methods."""

    EXCLUDED_METHODS = ["filter"]

    def __new__(mcs, name: str, bases: tuple, attrs: Dict[str, Any]) -> type:
        def make_wrapper(method_to_wrap: Callable) -> Callable:
            """
            This helper function creates a closure that captures the correct
            method at definition time, solving the late binding issue.
            """

            @wraps(method_to_wrap)
            async def session_wrapped_method(self: Any, *args: Any, **kwargs: Any) -> Any:
                return await _with_auto_session(method_to_wrap, self, *args, **kwargs)

            return session_wrapped_method

        for method_name, method in list(attrs.items()):
            is_public = not method_name.startswith("_")
            is_not_excluded = method_name not in mcs.EXCLUDED_METHODS

            if is_public and is_not_excluded and inspect.iscoroutinefunction(method):
                # Replace the original method with the correctly wrapped version
                attrs[method_name] = make_wrapper(method)

        return super().__new__(mcs, name, bases, attrs)


class Query(Generic[ModelType]):
    """Represents a query that can be chained or executed."""

    def __init__(self, model_cls: Type[ModelType], session: AsyncSession):
        self._model_cls = model_cls
        self._session = session
        self._statement = select(self._model_cls)

    def _clone(self) -> "Query[ModelType]":
        """Creates a copy of the query to allow chaining."""
        new_query = Query(self._model_cls, self._session)
        new_query._statement = self._statement
        return new_query

    async def _execute(self):
        """Executes the internal statement."""
        return await self._session.exec(self._statement)

    async def all(self) -> Sequence[ModelType]:
        """Executes the query and returns all results."""
        results = await self._execute()
        return results.all()

    async def first(self) -> Optional[ModelType]:
        """Executes the query and returns the first result or None."""
        result_obj = await self._session.exec(self._statement)
        return result_obj.first()

    async def one_or_none(self) -> Optional[ModelType]:
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

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> "Query[ModelType]":
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

        result = await self._session.execute(update_stmt)
        return result.rowcount

    async def count(self) -> int:
        """Returns the count of objects matching the query."""
        pk_col = getattr(self._model_cls, self._model_cls.__mapper__.primary_key[0].name)
        where_clause = self._statement.whereclause
        count_statement = sa_select(func.count(pk_col)).select_from(self._model_cls)
        if where_clause is not None:
            count_statement = count_statement.where(where_clause)
        result = await self._session.exec(count_statement)
        return cast(int, result.scalar_one())

    def order_by(self, *args: Any) -> "Query[ModelType]":
        """Applies ordering to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.order_by(*args)
        return new_query

    def limit(self, count: int) -> "Query[ModelType]":
        """Applies a limit to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.limit(count)
        return new_query

    def offset(self, count: int) -> "Query[ModelType]":
        """Applies an offset to the query."""
        new_query = self._clone()
        new_query._statement = new_query._statement.offset(count)
        return new_query


class Manager(Generic[ModelType], metaclass=ManagerMetaclass):
    """Provides Django-style access to query operations for a model."""

    def __init__(self, model_cls: Type[ModelType]):
        self._model_cls = model_cls
        self._session: Optional[AsyncSession] = None

    def _get_session(self) -> AsyncSession:
        """Internal helper to get the session from context."""
        return get_session_from_context()

    def _get_base_query(self) -> Query[ModelType]:
        """Internal helper to create a base Query object."""
        return Query(self._model_cls, self._get_session())

    async def all(self) -> Sequence[ModelType]:
        """Returns all objects of this model type."""
        return await self._get_base_query().all()

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> Query[ModelType]:
        """Starts a filtering query."""
        return self._get_base_query().filter(*args, **kwargs)

    async def get(self, *args: BinaryExpression, **kwargs: Any) -> ModelType:
        """Retrieves a single object matching criteria."""
        return await self._get_base_query().get(*args, **kwargs)

    async def count(self) -> int:
        """Returns the total count of objects for this model."""
        return await self._get_base_query().count()

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

    async def get_or_create(self, defaults: Optional[dict[str, Any]] = None, **kwargs: Any) -> tuple[ModelType, bool]:
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

    async def update_or_create(
        self, defaults: Optional[dict[str, Any]] = None, **kwargs: Any
    ) -> tuple[ModelType, bool]:
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
        session = self._get_session()
        await session.delete(instance)
        await session.flush()

    async def bulk_create(self, objs: List[ModelType]) -> List[ModelType]:
        """Performs bulk inserts using session.add_all()."""
        session = self._get_session()
        session.add_all(objs)
        await session.flush()
        return objs
