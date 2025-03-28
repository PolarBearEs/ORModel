import asyncio
from typing import Any, Generic, List, Optional, Sequence, Type, TypeVar, cast

from sqlalchemy import func, select as sa_select
from sqlmodel import select
from sqlalchemy.sql.elements import BinaryExpression
from sqlmodel.ext.asyncio.session import AsyncSession

from .database import get_session_from_context
from .exceptions import DoesNotExist, MultipleObjectsReturned

# Generic Type variable for the ORModel model
ModelType = TypeVar("ModelType", bound="ORModel") # Use string forward reference


class Query(Generic[ModelType]):
    """Represents a query that can be chained or executed."""

    def __init__(self, model_cls: Type[ModelType], session: AsyncSession):
        self._model_cls = model_cls
        self._session = session
        # Ensure we select the model class itself, not just columns
        self._statement = select(self._model_cls) # Initial statement selects all rows of ModelType

    def _clone(self) -> "Query[ModelType]":
        """Creates a copy of the query to allow chaining."""
        new_query = Query(self._model_cls, self._session)
        new_query._statement = self._statement # Copy the statement reference
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
        # Use limit(1) for potentially better performance if supported well by db/driver
        # results = await self._session.exec(self._statement.limit(1))
        results = await self._execute()
        return results.first()

    async def one_or_none(self) -> Optional[ModelType]:
        """Executes the query and returns exactly one result or None.
        Raises MultipleObjectsReturned if multiple results found.
        """
        # Limit to 2 to check if more than one exists efficiently
        cloned_statement = self._statement.limit(2)
        results = await self._session.exec(cloned_statement)
        all_results = results.all()
        count = len(all_results)
        if count == 0:
            return None
        if count == 1:
            return all_results[0]
        raise MultipleObjectsReturned(
            f"Expected one or none for {self._model_cls.__name__}, but found {count}"
        )

    async def one(self) -> ModelType:
        """
        Executes the query and returns exactly one result.
        Raises DoesNotExist if no object is found.
        Raises MultipleObjectsReturned if multiple objects are found.
        """
        # Limit to 2 to check efficiently
        cloned_statement = self._statement.limit(2)
        results = await self._session.exec(cloned_statement)
        all_results = results.all()
        count = len(all_results)

        if count == 0:
            raise DoesNotExist(f"{self._model_cls.__name__} matching query does not exist.")
        if count > 1:
            raise MultipleObjectsReturned(
                f"Expected one result for {self._model_cls.__name__}, but found {count}"
            )
        return all_results[0]


    async def get(self, *args: BinaryExpression, **kwargs: Any) -> ModelType:
        """
        Retrieves a single object matching the criteria (applied via filter).
        Raises DoesNotExist if no object is found.
        Raises MultipleObjectsReturned if multiple objects are found.
        """
        filtered_query = self.filter(*args, **kwargs)
        # Use one() method which includes the necessary checks and exceptions
        try:
            # print(f"Executing 'get' query: {filtered_query._statement}") # Debug print
            return await filtered_query.one()
        except DoesNotExist:
             # Re-raise with a potentially more specific message for get()
             raise DoesNotExist(f"{self._model_cls.__name__} matching query does not exist.")
        except MultipleObjectsReturned:
             # Re-raise with a potentially more specific message for get()
             raise MultipleObjectsReturned(
                f"get() returned more than one {self._model_cls.__name__}"
            )

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> "Query[ModelType]":
        """
        Filters the query based on SQLAlchemy BinaryExpressions (e.g., Model.field == value)
        or keyword arguments (e.g., field=value).
        Returns a new Query instance.
        """
        new_query = self._clone()
        conditions = list(args)
        for key, value in kwargs.items():
            # Handle Django-style lookups like field__eq, field__lt etc. if desired
            # For now, just basic equality
            field_name = key.split("__")[0] # Basic handling for potential future lookups

            if not hasattr(self._model_cls, field_name):
                raise AttributeError(f"'{self._model_cls.__name__}' has no attribute '{field_name}' for filtering")
            attr = getattr(self._model_cls, field_name)
            conditions.append(attr == value) # Simple equality check

        if conditions:
            new_query._statement = new_query._statement.where(*conditions)

        return new_query

    async def count(self) -> int:
        """Returns the count of objects matching the query."""
        # Create a count statement based on the filtered statement's where clause
        # Use func.count('*') or func.count(self._model_cls.id) - counting primary key is common
        pk_col = getattr(self._model_cls, self._model_cls.__mapper__.primary_key[0].name) # Get PK column

        # Extract the WHERE clause from the current statement
        where_clause = self._statement.whereclause

        # Build the count statement
        count_statement = sa_select(func.count(pk_col)).select_from(self._model_cls)
        if where_clause is not None:
            count_statement = count_statement.where(where_clause)

        # print(f"Executing 'count' query: {count_statement}") # Debug print
        result = await self._session.exec(count_statement)
        scalar_result = result.scalar_one()
        return cast(int, scalar_result) # Cast for type safety

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


class Manager(Generic[ModelType]):
    """Provides Django-style access to query operations for a model."""

    def __init__(self, model_cls: Type[ModelType]):
        self._model_cls = model_cls
        self._session: Optional[AsyncSession] = None  # Use sqlmodel.AsyncSession

    def _get_session(self) -> AsyncSession:
        """Internal helper to get the session from context."""
        # Cache session within manager instance only if needed, context var is better
        return get_session_from_context()

    def _get_base_query(self) -> Query[ModelType]:
        """Internal helper to create a base Query object."""
        return Query(self._model_cls, self._get_session())

    # --- Pass-through methods to Query ---

    async def all(self) -> Sequence[ModelType]:
        """Returns all objects of this model type."""
        return await self._get_base_query().all()

    def filter(self, *args: BinaryExpression, **kwargs: Any) -> Query[ModelType]:
        """Starts a filtering query."""
        return self._get_base_query().filter(*args, **kwargs)

    async def get(self, *args: BinaryExpression, **kwargs: Any) -> ModelType:
        """Retrieves a single object matching criteria."""
        # Pass args directly to the query's get method
        return await self._get_base_query().get(*args, **kwargs)

    async def count(self) -> int:
        """Returns the total count of objects for this model."""
        return await self._get_base_query().count()

    # --- Manager-specific methods ---

    async def create(self, **kwargs: Any) -> ModelType:
        """Creates a new object, saves it to the DB, and returns it."""
        session = self._get_session()
        try:
            # model_validate might raise validation errors
            db_obj = self._model_cls.model_validate(kwargs)
        except Exception as e: # Catch validation errors specifically if needed
             print(f"Validation error during create: {e}")
             raise # Re-raise validation error

        session.add(db_obj)
        try:
            # print(f"Attempting to commit create for {self._model_cls.__name__}") # Debug
            await session.flush() # Flush to send INSERT to DB, get potential errors
            await session.refresh(db_obj) # Refresh to get DB defaults (like ID)
            # Commit is often handled by middleware, but flush/refresh are needed here
            # print(f"Successfully created and refreshed: {db_obj}") # Debug
            return db_obj
        except Exception as e: # Catch potential db errors (like unique constraints)
            # print(f"Database error during create/flush: {e}") # Debug
            # Rollback might happen in middleware, but good to have here too
            await session.rollback() # Be careful not to interfere with outer transaction
            raise # Re-raise the database error


    async def get_or_create(self, defaults: Optional[dict[str, Any]] = None, **kwargs: Any) -> tuple[ModelType, bool]:
        """
        Looks for an object with the given kwargs. Creates one if it doesn't exist.
        Returns a tuple of (object, created), where created is a boolean.
        """
        session = self._get_session()
        defaults = defaults or {}
        try:
            # Use filter().one_or_none() for safety if multiple could match kwargs
            # Using get() assumes kwargs uniquely identify the object
            obj = await self.get(**kwargs)
            return obj, False
        except DoesNotExist:
            create_kwargs = kwargs.copy()
            create_kwargs.update(defaults)
            # print(f"Object not found, attempting create with: {create_kwargs}") # Debug
            # Need to handle potential race conditions if run concurrently without locks
            # A simple approach is to try creating and catch integrity errors
            try:
                 # Use self.create to ensure validation and flush/refresh happen
                 obj = await self.create(**create_kwargs)
                 return obj, True
            except Exception as create_exc: # Broadly catch errors during creation attempt
                 # If creation failed, perhaps it was created by another request
                 # between our 'get' and 'create'. Try getting it again.
                 # print(f"Create failed ({create_exc}), trying get again.") # Debug
                 try:
                      obj = await self.get(**kwargs)
                      return obj, False # It was created by someone else
                 except DoesNotExist:
                      # If it still doesn't exist, the create error was real
                      raise create_exc from None


    async def update_or_create(self, defaults: Optional[dict[str, Any]] = None, **kwargs: Any) -> tuple[ModelType, bool]:
        """
        Looks for an object with the given kwargs. Updates it if it exists (using defaults),
        otherwise creates a new one.
        Returns a tuple of (object, created).
        """
        session = self._get_session()
        defaults = defaults or {}
        try:
            # Attempt to get the object based on kwargs
            # Use filter + one_or_none or handle MultipleObjectsReturned if kwargs are not unique
            obj = await self.get(**kwargs)

            # Object exists, update it with defaults
            updated = False
            for key, value in defaults.items():
                if hasattr(obj, key) and getattr(obj, key) != value:
                    setattr(obj, key, value)
                    updated = True

            if updated:
                session.add(obj) # Add to session to track changes
                try:
                    await session.flush() # Send UPDATE to DB
                    await session.refresh(obj) # Refresh instance state
                    # Commit handled by middleware/context
                except Exception:
                    # Rollback potentially handled by middleware
                    raise
            return obj, False # Return False for created flag

        except DoesNotExist:
            # Object doesn't exist, create it using kwargs and defaults combined
            create_kwargs = kwargs.copy()
            create_kwargs.update(defaults)
            # print(f"Object not found for update, attempting create with: {create_kwargs}") # Debug
            # Similar race condition potential as get_or_create
            try:
                 # Use self.create for validation and flush/refresh
                 instance_data = await self.create(**create_kwargs)
                 return instance_data, True
            except Exception as create_exc:
                 # print(f"Create failed during update_or_create ({create_exc}), trying get again.") # Debug
                 # If create failed (e.g., race condition), try get again
                 try:
                      obj = await self.get(**kwargs)
                      # If get succeeds now, it was created concurrently. We didn't update it.
                      # Decide if you need to apply the 'defaults' update here anyway.
                      # For simplicity, we just return the concurrently created object.
                      return obj, False
                 except DoesNotExist:
                      # If it still doesn't exist, the original create error was valid
                      raise create_exc from None

    async def delete(self, instance: ModelType) -> None:
        """Deletes a specific model instance."""
        session = self._get_session()
        await session.delete(instance)
        try:
            await session.flush() # Send DELETE to DB
            # Commit handled by middleware/context
        except Exception:
            # Rollback potentially handled by middleware
            raise

    # --- Bulk Operations (Example Implementations) ---

    async def bulk_create(self, objs: List[ModelType]) -> List[ModelType]:
        """Performs bulk inserts using session.add_all()."""
        session = self._get_session()
        session.add_all(objs)
        try:
            await session.flush() # Flush to send inserts
            # Refreshing multiple objects after bulk insert can be tricky/inefficient.
            # Often, you might skip refresh or refresh selectively if needed.
            # For simplicity, we return the original objects (potentially without DB defaults like IDs yet)
            # Or re-fetch them if IDs are crucial immediately after.
            # Commit handled by middleware/context.
            return objs
        except Exception:
            # Rollback potentially handled by middleware
            raise

    # bulk_update is more complex with SQLAlchemy core or ORM, often involving session.execute(update(...))
    # For simplicity, it's often handled by iterating and updating, or using lower-level SQLAlchemy.