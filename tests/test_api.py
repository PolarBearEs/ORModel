# tests/test_api.py

import pytest
from httpx import AsyncClient

# Import models if needed for constructing payloads or verifying responses
# from examples.models import Hero, Team

# Mark all tests in this module to use pytest-asyncio
pytestmark = pytest.mark.asyncio


# --- Test Team Endpoints ---

async def test_create_team_success(async_client: AsyncClient):
    """Test creating a team successfully."""
    team_data = {"name": "Justice League", "headquarters": "Hall of Justice"}
    response = await async_client.post("/teams/", json=team_data)
    print(response.json())
    print(response.json())
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == team_data["name"]
    assert data["headquarters"] == team_data["headquarters"]
    assert "id" in data
    assert isinstance(data["id"], int)

async def test_create_team_duplicate_name(async_client: AsyncClient):
    """Test creating a team with a duplicate name fails."""
    team_data = {"name": "Avengers", "headquarters": "Tower"}
    # Create the first one
    response1 = await async_client.post("/teams/", json=team_data)
    assert response1.status_code == 201

    # Attempt to create again with the same name
    response2 = await async_client.post("/teams/", json=team_data)
    assert response2.status_code == 409 # Based on endpoint logic returning Conflict
    data = response2.json()
    assert "detail" in data
    assert "already exists" in data["detail"]

async def test_read_teams_empty(async_client: AsyncClient):
    """Test reading teams when none exist."""
    response = await async_client.get("/teams/")
    assert response.status_code == 200
    assert response.json() == []

async def test_read_teams_with_data(async_client: AsyncClient):
    """Test reading teams after creating some."""
    team1_data = {"name": "Team A", "headquarters": "HQ A"}
    team2_data = {"name": "Team B", "headquarters": "HQ B"}
    await async_client.post("/teams/", json=team1_data)
    await async_client.post("/teams/", json=team2_data)

    response = await async_client.get("/teams/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = sorted([t["name"] for t in data])
    assert names == ["Team A", "Team B"]


# --- Test Hero Endpoints ---

async def test_create_hero_success(async_client: AsyncClient):
    """Test creating a hero successfully."""
    # Optional: Create a team first if hero requires team_id
    team_resp = await async_client.post("/teams/", json={"name": "Sidekicks", "headquarters": "Basement"})
    team_id = team_resp.json()["id"]

    hero_data = {"name": "Robin", "secret_name": "Dick Grayson", "age": 17, "team_id": team_id}
    response = await async_client.post("/heroes/", json=hero_data)

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == hero_data["name"]
    assert data["secret_name"] == hero_data["secret_name"]
    assert data["age"] == hero_data["age"]
    assert data["team_id"] == hero_data["team_id"]
    assert "id" in data

async def test_create_hero_missing_data(async_client: AsyncClient):
    """Test creating a hero with missing required data fails validation."""
    # Missing 'secret_name' which is required by the model
    hero_data = {"name": "Incomplete"}
    response = await async_client.post("/heroes/", json=hero_data)
    assert response.status_code == 422 # Unprocessable Entity (FastAPI validation error)

async def test_read_heroes_empty(async_client: AsyncClient):
    """Test reading heroes when none exist."""
    response = await async_client.get("/heroes/")
    assert response.status_code == 200
    assert response.json() == []

async def test_read_heroes_with_data(async_client: AsyncClient):
    """Test reading heroes after creating some."""
    h1_resp = await async_client.post("/heroes/", json={"name": "Batman", "secret_name": "Bruce Wayne", "age": 40})
    h2_resp = await async_client.post("/heroes/", json={"name": "Superman", "secret_name": "Clark Kent", "age": 35})
    assert h1_resp.status_code == 201
    assert h2_resp.status_code == 201

    response = await async_client.get("/heroes/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = sorted([h["name"] for h in data])
    assert names == ["Batman", "Superman"]

async def test_read_single_hero_success(async_client: AsyncClient):
    """Test reading a single existing hero by ID."""
    hero_data = {"name": "Wonder Woman", "secret_name": "Diana Prince", "age": 800}
    create_resp = await async_client.post("/heroes/", json=hero_data)
    assert create_resp.status_code == 201
    hero_id = create_resp.json()["id"]

    response = await async_client.get(f"/heroes/{hero_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == hero_id
    assert data["name"] == hero_data["name"]

async def test_read_single_hero_not_found(async_client: AsyncClient):
    """Test reading a single non-existent hero by ID."""
    response = await async_client.get("/heroes/99999")
    assert response.status_code == 404

async def test_update_hero_success(async_client: AsyncClient):
    """Test updating an existing hero successfully."""
    hero_data = {"name": "Flash", "secret_name": "Barry Allen", "age": 28}
    create_resp = await async_client.post("/heroes/", json=hero_data)
    assert create_resp.status_code == 201
    hero_id = create_resp.json()["id"]

    update_data = {"age": 29, "secret_name": "Bartholomew Henry Allen"}
    response = await async_client.patch(f"/heroes/{hero_id}", json=update_data)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == hero_id
    assert data["name"] == hero_data["name"] # Name wasn't updated
    assert data["age"] == update_data["age"] # Age was updated
    assert data["secret_name"] == update_data["secret_name"] # Secret name was updated

async def test_update_hero_not_found(async_client: AsyncClient):
    """Test updating a non-existent hero."""
    response = await async_client.patch("/heroes/99999", json={"age": 100})
    assert response.status_code == 404

async def test_delete_hero_success(async_client: AsyncClient):
    """Test deleting an existing hero successfully."""
    hero_data = {"name": "Green Lantern", "secret_name": "Hal Jordan", "age": 32}
    create_resp = await async_client.post("/heroes/", json=hero_data)
    assert create_resp.status_code == 201
    hero_id = create_resp.json()["id"]

    # Delete the hero
    delete_resp = await async_client.delete(f"/heroes/{hero_id}")
    assert delete_resp.status_code == 204

    # Verify it's gone
    get_resp = await async_client.get(f"/heroes/{hero_id}")
    assert get_resp.status_code == 404

async def test_delete_hero_not_found(async_client: AsyncClient):
    """Test deleting a non-existent hero."""
    response = await async_client.delete("/heroes/99999")
    assert response.status_code == 404