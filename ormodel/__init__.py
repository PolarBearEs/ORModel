# ormodel/__init__.py

from sqlmodel import SQLModel, select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from .base import ORModel, get_defined_models
from .database import (
    database_context,
    db_session_context,
    get_engine,
    get_session,
    get_session_from_context,
    init_database,
    shutdown_database,
)
from .exceptions import DoesNotExist, MultipleObjectsReturned, SessionContextError
from .manager import Manager, Query

__all__ = [
    "SQLModel",
    "select",
    "AsyncSession",
    "ORModel",
    "get_defined_models",
    "database_context",
    "db_session_context",
    "get_engine",
    "get_session",
    "get_session_from_context",
    "init_database",
    "shutdown_database",
    "DoesNotExist",
    "MultipleObjectsReturned",
    "SessionContextError",
    "Manager",
    "Query",
    "and_"
]

metadata = ORModel.metadata
