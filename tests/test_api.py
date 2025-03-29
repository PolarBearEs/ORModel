# tests/test_api.py

import pytest
from httpx import AsyncClient

# Mark all tests in this module to use pytest-asyncio
pytestmark = pytest.mark.asyncio


# --- Test Team Endpoints ---

async def test_create_team_success(async_client: AsyncClient):
    """Test creating a team successfully."""
    team_data = {"name": "Justice League", "headquarters": "Hall of Justice"}
    print("\n--- test_create_team_success: Sending POST /teams/ ---")
    response = await async_client.post("/teams/", json=team_data)
    print(f"--- test_create_team_success: Response Status: {response.status_code} ---")
    print(f"--- test_create_team_success: Response JSON: {response.json()} ---")

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
    print("\n--- test_create_team_duplicate_name: Sending first POST /teams/ ---")
    response1 = await async_client.post("/teams/", json=team_data)
    assert response1.status_code == 201

    # Attempt to create again with the same name
    print("--- test_create_team_duplicate_name: Sending second POST /teams/ ---")
    response2 = await async_client.post("/teams/", json=team_data)
    print(f"--- test_create_team_duplicate_name: Response 2 Status: {response2.status_code} ---")
    print(f"--- test_create_team_duplicate_name: Response 2 JSON: {response2.json()} ---")
    assert response2.status_code == 409 # Conflict
    data = response2.json()
    assert "detail" in data
    assert "already exists" in data["detail"]

async def test_read_teams_empty(async_client: AsyncClient):
    """Test reading teams when none exist."""
    print("\n--- test_read_teams_empty: Sending GET /teams/ ---")
    response = await async_client.get("/teams/")
    print(f"--- test_read_teams_empty: Response Status: {response.status_code} ---")
    print(f"--- test_read_teams_empty: Response JSON: {response.json()} ---")
    assert response.status_code == 200
    assert response.json() == []

async def test_read_teams_with_data(async_client: AsyncClient):
    """Test reading teams after creating some."""
    team1_data = {"name": "Team A", "headquarters": "HQ A"}
    team2_data = {"name": "Team B", "headquarters": "HQ B"}
    print("\n--- test_read_teams_with_data: Creating teams ---")
    await async_client.post("/teams/", json=team1_data)
    await async_client.post("/teams/", json=team2_data)

    print("--- test_read_teams_with_data: Sending GET /teams/ ---")
    response = await async_client.get("/teams/")
    print(f"--- test_read_teams_with_data: Response Status: {response.status_code} ---")
    print(f"--- test_read_teams_with_data: Response JSON: {response.json()} ---")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = sorted([t["name"] for t in data])
    assert names == ["Team A", "Team B"]


# --- Test Hero Endpoints ---

async def test_create_hero_success(async_client: AsyncClient):
    """Test creating a hero successfully."""
    # Create a team first
    team_resp = await async_client.post("/teams/", json={"name": "Sidekicks", "headquarters": "Basement"})
    assert team_resp.status_code == 201
    team_id = team_resp.json()["id"]

    hero_data = {"name": "Robin", "secret_name": "Dick Grayson", "age": 17, "team_id": team_id}
    print("\n--- test_create_hero_success: Sending POST /heroes/ ---")
    response = await async_client.post("/heroes/", json=hero_data)
    print(f"--- test_create_hero_success: Response Status: {response.status_code} ---")
    print(f"--- test_create_hero_success: Response JSON: {response.json()} ---")

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == hero_data["name"]
    assert data["secret_name"] == hero_data["secret_name"]
    assert data["age"] == hero_data["age"]
    assert data["team_id"] == hero_data["team_id"]
    assert "id" in data

async def test_create_hero_missing_data(async_client: AsyncClient):
    """Test creating a hero with missing required data fails validation."""
    hero_data = {"name": "Incomplete"} # Missing 'secret_name'
    print("\n--- test_create_hero_missing_data: Sending POST /heroes/ ---")
    response = await async_client.post("/heroes/", json=hero_data)
    print(f"--- test_create_hero_missing_data: Response Status: {response.status_code} ---")
    assert response.status_code == 422 # Unprocessable Entity

async def test_read_heroes_empty(async_client: AsyncClient):
    """Test reading heroes when none exist."""
    print("\n--- test_read_heroes_empty: Sending GET /heroes/ ---")
    response = await async_client.get("/heroes/")
    print(f"--- test_read_heroes_empty: Response Status: {response.status_code} ---")
    assert response.status_code == 200
    assert response.json() == []

async def test_read_heroes_with_data(async_client: AsyncClient):
    """Test reading heroes after creating some."""
    print("\n--- test_read_heroes_with_data: Creating heroes ---")
    h1_resp = await async_client.post("/heroes/", json={"name": "Batman", "secret_name": "Bruce Wayne", "age": 40})
    h2_resp = await async_client.post("/heroes/", json={"name": "Superman", "secret_name": "Clark Kent", "age": 35})
    assert h1_resp.status_code == 201
    assert h2_resp.status_code == 201

    print("--- test_read_heroes_with_data: Sending GET /heroes/ ---")
    response = await async_client.get("/heroes/")
    print(f"--- test_read_heroes_with_data: Response Status: {response.status_code} ---")
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

    print(f"\n--- test_read_single_hero_success: Sending GET /heroes/{hero_id} ---")
    response = await async_client.get(f"/heroes/{hero_id}")
    print(f"--- test_read_single_hero_success: Response Status: {response.status_code} ---")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == hero_id
    assert data["name"] == hero_data["name"]

async def test_read_single_hero_not_found(async_client: AsyncClient):
    """Test reading a single non-existent hero by ID."""
    print("\n--- test_read_single_hero_not_found: Sending GET /heroes/99999 ---")
    response = await async_client.get("/heroes/99999")
    print(f"--- test_read_single_hero_not_found: Response Status: {response.status_code} ---")
    assert response.status_code == 404

async def test_update_hero_success(async_client: AsyncClient):
    """Test updating an existing hero successfully."""
    hero_data = {"name": "Flash", "secret_name": "Barry Allen", "age": 28}
    create_resp = await async_client.post("/heroes/", json=hero_data)
    assert create_resp.status_code == 201
    hero_id = create_resp.json()["id"]

    update_data = {"age": 29, "secret_name": "Bartholomew Henry Allen"}
    print(f"\n--- test_update_hero_success: Sending PATCH /heroes/{hero_id} ---")
    response = await async_client.patch(f"/heroes/{hero_id}", json=update_data)
    print(f"--- test_update_hero_success: Response Status: {response.status_code} ---")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == hero_id
    assert data["name"] == hero_data["name"]
    assert data["age"] == update_data["age"]
    assert data["secret_name"] == update_data["secret_name"]

async def test_update_hero_not_found(async_client: AsyncClient):
    """Test updating a non-existent hero."""
    print("\n--- test_update_hero_not_found: Sending PATCH /heroes/99999 ---")
    response = await async_client.patch("/heroes/99999", json={"age": 100})
    print(f"--- test_update_hero_not_found: Response Status: {response.status_code} ---")
    assert response.status_code == 404

async def test_delete_hero_success(async_client: AsyncClient):
    """Test deleting an existing hero successfully."""
    hero_data = {"name": "Green Lantern", "secret_name": "Hal Jordan", "age": 32}
    create_resp = await async_client.post("/heroes/", json=hero_data)
    assert create_resp.status_code == 201
    hero_id = create_resp.json()["id"]

    print(f"\n--- test_delete_hero_success: Sending DELETE /heroes/{hero_id} ---")
    delete_resp = await async_client.delete(f"/heroes/{hero_id}")
    print(f"--- test_delete_hero_success: Response Status: {delete_resp.status_code} ---")
    assert delete_resp.status_code == 204

    # Verify it's gone
    print(f"--- test_delete_hero_success: Sending GET /heroes/{hero_id} to verify deletion ---")
    get_resp = await async_client.get(f"/heroes/{hero_id}")
    print(f"--- test_delete_hero_success: Verification GET Response Status: {get_resp.status_code} ---")
    assert get_resp.status_code == 404

async def test_delete_hero_not_found(async_client: AsyncClient):
    """Test deleting a non-existent hero."""
    print("\n--- test_delete_hero_not_found: Sending DELETE /heroes/99999 ---")
    response = await async_client.delete("/heroes/99999")
    print(f"--- test_delete_hero_not_found: Response Status: {response.status_code} ---")
    assert response.status_code == 404