import json
import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, TextPart, Role
from uuid import uuid4
import httpx

from rooms.server.rooms_environment import RoomsEnvironment
from rooms.models import RoomsAction, Command


# Environment tests, no environment server needed.

def test_rooms_env_reset():
    """Test that environment resets properly."""
    env = RoomsEnvironment()
    obs = env.reset(encoding="089000000c0c0000000000000")
    
    assert obs.current_room == 0
    assert obs.committed == 0
    assert obs.current_keys == 0


def test_rooms_env_move():
    """Test movement in the environment."""
    env = RoomsEnvironment()
    env.reset(encoding="089000000c0c0000000000000")
    
    action = RoomsAction(command=Command.MOVE, target_room=1)
    obs = env.step(action)
    
    assert obs is not None


def test_rooms_env_commit():
    """Test commit action."""
    env = RoomsEnvironment()
    env.reset(encoding="089000000c0c0000000000000")
    
    action = RoomsAction(command=Command.COMMIT)
    obs = env.step(action)
    
    assert obs.committed == 1


def test_invalid_encoding():
    """Test that invalid encoding raises error."""
    env = RoomsEnvironment()
    
    with pytest.raises(ValueError):
        env.reset(encoding="invalid")


# Green agent tests, for A2A conformance

@pytest.fixture
async def green_agent_client(agent):
    """Create an A2A client for the green agent (proctor)."""
    async with httpx.AsyncClient(timeout=60) as httpx_client:
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=agent)
        agent_card = await resolver.get_agent_card()
        config = ClientConfig(httpx_client=httpx_client, streaming=False)
        factory = ClientFactory(config)
        yield factory.create(agent_card)


@pytest.mark.asyncio
async def test_green_agent_card(agent):
    """Test that green agent card is properly configured."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{agent}/.well-known/agent-card.json")
        assert response.status_code == 200
        
        card = response.json()
        assert card["name"] == "Rooms Benchmark Proctor"
        assert len(card["skills"]) > 0
        assert card["skills"][0]["id"] == "rooms_benchmark"


@pytest.mark.asyncio
async def test_green_agent_missing_participants(green_agent_client):
    """Test that green agent rejects requests with missing participants (solver)."""
    request = {
        "participants": {},  # Missing solver role
        "config": {"encoding": "089000000c0c0000000000000"}
    }
    
    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )
    
    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_missing_config(green_agent_client):
    """Test that green agent rejects requests with missing config."""
    request = {
        "participants": {"solver": "http://localhost:8000"},
        "config": {}  # Missing encoding
    }
    
    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )
    
    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_invalid_encoding(green_agent_client):
    """Test that green agent rejects invalid encoding format."""
    request = {
        "participants": {"solver": "http://localhost:8000"},
        "config": {"encoding": "invalid"}  # Not 25 hex chars
    }
    
    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )
    
    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_valid_request_no_solver(green_agent_client):
    """Test that green agent accepts valid request structure (will fail without purple solver agent)."""
    request = {
        "participants": {"solver": "http://localhost:8000"},  # Purple agent URL
        "config": {
            "encoding": "089000000c0c0000000000000",
            "max_steps": 10,
            "steps_remaining": 30
        }
    }
    
    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )
    
    # This will fail when trying to connect to solver, but should get past validation
    async for event in green_agent_client.send_message(message):
        task, update = event
        # Should at least start working (not rejected due to validation)
        assert task.status.state.value in ["working", "failed"]
        break