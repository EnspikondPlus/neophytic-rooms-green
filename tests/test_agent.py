import json
import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, TextPart, Role
from uuid import uuid4
import httpx

from rooms.server.rooms_environment import RoomsEnvironment
from rooms.models import RoomsAction, Command


# ---------------------------------------------------------------------------
# Environment tests — no server needed, exercises RoomsEnvironment directly.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Green agent A2A conformance tests — require the proctor server to be running.
# ---------------------------------------------------------------------------


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
        assert card["name"] == "Neophytic Rooms Green"
        assert len(card["skills"]) > 0
        assert card["skills"][0]["id"] == "neophytic_rooms_green"


@pytest.mark.asyncio
async def test_green_agent_missing_participants(green_agent_client):
    """Test that green agent rejects requests with missing participants (solver)."""
    request = {
        "participants": {},  # Missing solver role
        "config": {"generate": True, "count": 1},
    }

    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(root=TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )

    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_missing_config(green_agent_client):
    """Test that green agent rejects requests with missing required config keys."""
    request = {
        "participants": {"solver": "http://localhost:8000"},
        "config": {},  # Missing 'generate' and 'count'
    }

    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(root=TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )

    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_partial_config(green_agent_client):
    """Test that green agent rejects requests missing one of the two required config keys."""
    request = {
        "participants": {"solver": "http://localhost:8000"},
        "config": {"generate": True},  # Has 'generate' but missing 'count'
    }

    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(root=TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )

    async for event in green_agent_client.send_message(message):
        task, update = event
        assert task.status.state.value == "rejected"
        break


@pytest.mark.asyncio
async def test_green_agent_valid_request_no_solver(green_agent_client):
    """
    Test that a well-formed request passes validation and enters the working state.
    The run will ultimately fail because no solver is listening at the target URL,
    but the point of this test is that the request is not rejected at validation time.
    """
    request = {
        "participants": {"solver": "http://localhost:8000"},
        "config": {
            "generate": True,
            "count": 1,
        },
    }

    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(root=TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )

    async for event in green_agent_client.send_message(message):
        task, update = event
        # Validation passed — agent moved past reject into the run loop.
        # It will fail when trying to reach the solver, but must not be "rejected".
        assert task.status.state.value in ["working", "failed", "completed"]
        break