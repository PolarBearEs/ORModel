from sqlmodel import Field

from ormodel import Manager
from ormodel.base import ORModel, get_defined_models


# Define a concrete test model
class ConcreteModel(ORModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str


# Define an abstract test model
class AbstractModel(ORModel, __abstract__=True):
    pass


# Define another concrete test model
class AnotherConcreteModel(ORModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    value: str


def test_ormodel_subclass_attaches_manager():
    """Test that ORModel subclasses automatically get a Manager."""
    assert hasattr(ConcreteModel, "objects")
    assert isinstance(ConcreteModel.objects, Manager)
    assert ConcreteModel.objects._model_cls == ConcreteModel  # Corrected attribute


def test_abstract_model_does_not_get_manager_attached_to_defined_models():
    """Test that abstract models are not added to the defined models list."""
    initial_defined_models = len(get_defined_models())

    class TempAbstract(ORModel, __abstract__=True):
        id: int | None = Field(default=None, primary_key=True)

    # Abstract models should not increase the count of defined models
    assert len(get_defined_models()) == initial_defined_models
