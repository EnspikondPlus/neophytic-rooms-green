import json
import pytest
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, TextPart, Role
from uuid import uuid4
import httpx

# Import the actual environment, not the client
from rooms.server.rooms_environment import RoomsEnvironment
from rooms.models import RoomsAction, Command


# ============================================================================
# Environment Tests (no server needed - tests the environment directly)
# ============================================================================

def test_rooms_env_reset():
    """Test that environment resets properly."""
    env = RoomsEnvironment()  # Use the actual environment
    obs = env.reset(encoding="089000000c0c0000000000000")
    
    assert obs.current_room == 0
    assert obs.committed == 0
    assert obs.current_keys == 0


def test_rooms_env_move():
    """Test movement in the environment."""
    env = RoomsEnvironment()
    env.reset(encoding="089000000c0c0000000000000")
    
    # Try to move (will depend on the encoding's room connections)
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


# ============================================================================
# Green Agent Tests (requires green agent server running on port 9009)
# ============================================================================

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
        "participants": {},  # Missing "solver" role
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
        "config": {}  # Missing "encoding"
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


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires a running purple solver agent on port 8000")
async def test_full_benchmark_with_purple_agent(green_agent_client):
    """
    Full integration test - requires a purple solver agent running.
    
    Architecture:
    - Purple Agent (solver) at http://localhost:8000
    - Green Agent (proctor) at http://localhost:9009 (this agent)
    - Rooms Environment (managed by green agent)
    
    To run this test:
    1. Start a purple solver agent on port 8000
    2. Start this green agent on port 9009: python src/server.py
    3. Run: pytest tests/test_agent.py::test_full_benchmark_with_purple_agent -v
    """
    request = {
        "participants": {
            "solver": "http://localhost:8000"  # Purple agent that solves the puzzle
        },
        "config": {
            "encoding": "089000000c0c0000000000000",
            "max_steps": 50,
            "steps_remaining": 30,
            "obs_inspect_weight": 3.0
        }
    }
    
    message = Message(
        kind="message",
        role=Role.user,
        parts=[Part(TextPart(kind="text", text=json.dumps(request)))],
        message_id=uuid4().hex,
    )
    
    final_event = None
    async for event in green_agent_client.send_message(message):
        final_event = event
    
    task, update = final_event
    assert task.status.state.value == "completed"
    assert len(task.artifacts) > 0
    
    # Check that results contain expected fields
    artifact = task.artifacts[0]
    data_part = next(p.root for p in artifact.parts if hasattr(p.root, 'data'))
    results = data_part.data
    
    assert "success" in results
    assert "total_reward" in results
    assert "steps_taken" in results
    assert "conversation_history" in results
    
    # Verify the conversation history shows interaction between green and purple agents
    assert len(results["conversation_history"]) > 0
    print(f"\nBenchmark Results:")
    print(f"  Success: {results['success']}")
    print(f"  Total Reward: {results['total_reward']}")
    print(f"  Steps Taken: {results['steps_taken']}")