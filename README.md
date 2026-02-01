# Neophytic Rooms Green Agent

A green agent for the AgentBeats competition built on the template for building [A2A (Agent-to-Agent)](https://a2a-protocol.org/latest/) green agents compatible with the [AgentBeats](https://agentbeats.dev) platform.

## Project Structure

```
src/
├─ server.py                  # Server setup and agent card configuration
├─ executor.py                # A2A request handling
├─ agent.py                   # Agent implementation
└─ messenger.py               # A2A messaging utilities
benchmarks/
├─ room_gen.py                # Room system generation script
└─ standard_systems.json      # A set of 200 standardized systems for benchmarking
rooms/
└─ server/
   ├─ environment_logic.py    # Helper for environment functionality
   └─ rooms_environment.py    # OpenEnv environment manager
├─ client.py                  # OpenEnv client manager
└─ models.                    # OpenEnv data class manager
tests/
└─ test_agent.py              # Agent tests
Dockerfile                    # Docker configuration
pyproject.toml                # Python dependencies
.github/
└─ workflows/
   └─ test-and-publish.yml # CI workflow
```

## Getting Started

To see how to make a green agent for AgentBeats, see this [draft PR](https://github.com/RDI-Foundation/green-agent-template/pull/3).

## Running Server Locally

You can create a `.venv` first, if needed.

```bash
uv sync

uv run green-server
```

## Running Tests Locally

Make sure that the server is running first!

```bash
uv sync --extra test

uv run pytest tests/test_agent.py -v
```

## Running with Docker
```bash
docker build -t neophytic-rooms .

docker run --rm neophytic-rooms
```

## About the Benchmark
The Neophytic Rooms Green Agent administers the "Rooms" game benchmark, which is an original benchmark created for AgentBeats. The benchmark assesses agents' abilities to navigate a system of rooms with limited and obfuscated information, resource management pressure, and high memory and planning requirements.

Each configuration of the Rooms agent is a different system of 2-8 rooms. Rooms are connected and may contain keys or be locked, but this is not visible to the agent until it INSPECTs a room. An agent starts in a room and must find its way to the exit over two phases. In each phase, the agent can choose from a small action space of MOVE, INSPECT, GETKEY, USEKEY, and COMMIT. MOVE moves the agent to an adjacent room to their current room, with some phase-specific nuance. INSPECT allows the agent to inspect a room, learning adjacent room connections, and whether the room is locked, is the exit, or has a key. GETKEY allows the agent to pick up a key in a room, and USEKEY allows the agent to unlock a room by using a key. COMMIT changes the phase from Observation to Execution, and cannot be reversed.

During the Observation phase, the agent is free to move around the room system, and every room they move into is automatically inspected. However, moving costs more during the Observation phase. Agents can move through locked rooms during Observation, but cannot leave using the exit, or GETKEY or USEKEY. After the Observation phase, the Agent may lose the state of observed rooms, and is reset to their starting room. During the Execution phase, agents have access to more actions and are now actively trying to find the exit and leave using the knowledge gained in Observation. However, the number of actions (steps) agents have in Execution is limited.

Using this system, the Rooms Green Agent tests agentic ability at logical reasoning with imperfect information, cost-benefit analysis, long-term memory, and failure recognition. There are several configurations of room systems of various difficulty prebuilt into the Rooms agent, and additional configurations can be generated using an encoding schema, allowing for high scalability.

## Work in Progress
Currently, the benchmark isn't entirely well-polished. There is much more functionality to add, and some more testing and robustness would be good. The plan is to update this benchmark soon to make some improvements, regardless of whether it counts for submission later on.
