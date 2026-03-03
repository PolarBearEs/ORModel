from sqlmodel import Field, Relationship

from ormodel import ORModel


# Example Model 1
class Team(ORModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)  # Added unique constraint
    headquarters: str

    # Define the relationship back to Hero (one-to-many)
    # Use list[] for the "many" side
    heroes: list["Hero"] = Relationship(back_populates="team")


# Example Model 2
class Hero(ORModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    secret_name: str
    age: int | None = Field(default=None, index=True)

    # Foreign Key to Team table
    team_id: int | None = Field(default=None, foreign_key="team.id")

    # Define the relationship to Team (many-to-one)
    # back_populates links it to the 'heroes' attribute in Team
    team: Team | None = Relationship(back_populates="heroes")


# You can add more models here following the same pattern
