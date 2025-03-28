# ormodel/base.py
from typing import ClassVar, Type, TypeVar

from sqlmodel import SQLModel

from .manager import Manager

# Type variable still refers conceptually to the model type
ModelType = TypeVar("ModelType", bound="ORModel") # <-- Update bound type

# Keep track of defined models
_defined_models = []

class ORModel(SQLModel):
    """
    Base ORM Model class with a Manager attached.
    Subclass from this for your project models.
    """
    # ClassVar tells type checkers this belongs to the class, not instances
    # Type hint needs to refer to the new class name, use string forward reference
    objects: ClassVar[Manager["ORModel"]] # type: ignore # Specific type attached below

    # Reference the central metadata from the original SQLModel library
    # This ensures Alembic can find tables correctly.
    metadata = SQLModel.metadata

    # This helps attaching the manager correctly when subclassing
    def __init_subclass__(cls: Type[ModelType], **kwargs):
        super().__init_subclass__(**kwargs)
        # Attach a manager instance specific to this subclass
        cls.objects = Manager(cls) # type: ignore
        if not getattr(cls, "__abstract__", False): # Don't add abstract models
            _defined_models.append(cls)
        # print(f"Attached Manager to model: {cls.__name__}") # Debug print


# Optional: Function to get all defined models (useful for Alembic)
def get_defined_models() -> list[Type[ORModel]]: # <-- Update return type hint
    # Filter out potential abstract base classes if necessary
    return [m for m in _defined_models if hasattr(m, "__table__")]