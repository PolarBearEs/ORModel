import sqlmodel as _sqlmodel
from sqlmodel import *  # noqa: F403

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

# Re-export based on what from sqlmodel import * actually does
_sqlmodel_reexports = getattr(_sqlmodel, "__all__", [n for n in dir(_sqlmodel) if not n.startswith("_")])

__all__ = [
    *_sqlmodel_reexports,
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
