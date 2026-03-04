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

# We want to re-export everything from sqlmodel as well
_sqlmodel_public_names = [n for n in dir(_sqlmodel) if not n.startswith("_")]

__all__ = [
    *_sqlmodel_public_names,
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
