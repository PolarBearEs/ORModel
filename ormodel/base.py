# ormodel/base.py
from typing import TYPE_CHECKING, ClassVar, Self, TypeVar

from sqlmodel import SQLModel

from .manager import Manager, with_auto_session

# Type variable still refers conceptually to the model type
ModelType = TypeVar("ModelType", bound="ORModel")  # <-- Update bound type

# Keep track of defined models
_defined_models = []


class ORModel(SQLModel):
    """
    Base ORM Model class with a Manager attached.
    Subclass from this for your project models.
    """

    # ClassVar tells type checkers this belongs to the class, not instances
    # Type hint needs to refer to the new class name, use string forward reference

    if TYPE_CHECKING:
        objects: ClassVar[Manager[Self]]  # Specific type attached below
    else:
        objects: ClassVar[Manager["ORModel"]]  # Specific type attached below

    # Reference the central metadata from the original SQLModel library
    # This ensures Alembic can find tables correctly.
    metadata = SQLModel.metadata

    # This helps attaching the manager correctly when subclassing
    def __init_subclass__(cls: type[ModelType], **kwargs):
        super().__init_subclass__(**kwargs)
        # Attach a manager instance specific to this subclass
        cls.objects = Manager(cls)
        if not getattr(cls, "__abstract__", False):  # Don't add abstract models
            _defined_models.append(cls)
        # print(f"Attached Manager to model: {cls.__name__}") # Debug print

    @with_auto_session
    async def save(self) -> Self:
        """
        Saves the current model instance to the database.
        If the instance has a primary key, it will be updated; otherwise, it will be created.
        """
        session = self.objects._get_session()
        session.add(self)
        await session.flush()
        await session.refresh(self)
        return self

    @with_auto_session
    async def delete(self) -> None:
        """
        Deletes the current model instance from the database.
        """
        session = self.objects._get_session()
        await session.delete(self)
        await session.flush()


# Optional: Function to get all defined models (useful for Alembic)
def get_defined_models() -> list[type[ORModel]]:  # <-- Update return type hint
    # Filter out potential abstract base classes if necessary
    return [m for m in _defined_models if hasattr(m, "__table__")]
