from typing import Optional
from ormodel import Field, Relationship # Import Relationship if defining relations

# Import the base ORModel from YOUR library using the NEW name
from ormodel import ORModel # <-- Ensure this uses your library's base

# Example Model 1
class Team(ORModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True) # Added unique constraint
    headquarters: str

    # Define the relationship back to Hero (one-to-many)
    # Use list[] for the "many" side
    heroes: list["Hero"] = Relationship(back_populates="team")

# Example Model 2
class Hero(ORModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    secret_name: str
    age: Optional[int] = Field(default=None, index=True)

    # Foreign Key to Team table
    team_id: Optional[int] = Field(default=None, foreign_key="team.id")

    # Define the relationship to Team (many-to-one)
    # back_populates links it to the 'heroes' attribute in Team
    team: Optional[Team] = Relationship(back_populates="heroes")

# You can add more models here following the same pattern