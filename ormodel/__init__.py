import sqlmodel as _sqlmodel

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

metadata = ORModel.metadata

for _name in getattr(_sqlmodel, "__all__", ()):
    globals()[_name] = getattr(_sqlmodel, _name)

__all__ = [
    *getattr(_sqlmodel, "__all__", ()),
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
    "metadata",
]
