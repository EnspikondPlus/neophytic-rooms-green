from typing import Optional, List
from pydantic import Field
from enum import Enum
from openenv.core.env_server.types import Action, Observation, State

class Command(str, Enum):
    MOVE = "move"           # move between connected rooms
    INSPECT = "inspect"     # inspect the current room
    USEKEY = "usekey"       # use a key to unlock the current, locked room
    GETKEY = "getkey"       # get a key from the current room, that has a key
    COMMIT = "commit"       # switch from observation to execution phase

class RoomsAction(Action):
    command: Command                    # command from above
    target_room: Optional[int] = None   # room to move to if moving

class RoomsObservation(Observation):
    # Agent Knowledge
    current_room: int = Field(..., description="Room the agent is currently in.")
    committed: int = Field(..., description="Whether observation phase is over, 0 if no, 1 if yes.")
    failure_last: int = Field(..., description="Whether last action failed, -1 if unknown, 0 if not failure, 1 if failure/")

    # Room Observations
    room_visited: List[int] = Field( ..., description="Visited rooms by index, 0 if not visited, 1 if visited.")
    room_inspected: List[int] = Field(..., description="Inspected rooms by index, 0 if not inspected, 1 if inspected.")
    room_known_connects: List[List[int]] = Field(..., description="Observed room connections by (i,j) index, -1 if unknown, 0 if no connection, 1 if connection.")
    room_locked: List[int] = Field(..., description="Whether current room is locked, -1 if unknown, 0 if unlocked, 1 if locked.")
    room_haskey: List[int] = Field(..., description="Whether current room contains a key, -1 if unknown, 0 if no key, 1 if key.")
    room_exit: List[int] = Field(..., description="Whether current room is the exit, -1 if unknown, 0 if not exit, 1 if exit.")

    # Resources Management Knowledge
    current_keys: int = Field(..., description="Number of keys currently held.")
    actions_remaining: int = Field(..., description="Number of execution phase steps remaining.")
    obs_inspect_weight: float = Field(..., description="Cost of inspecting a room in the observation phase.")

class RoomsState(State):
    # Environment State
    episode_id: str                     # id of the current episode
    action_count: int                   # number of actions taken
    weighted_loss: float                # loss (score) of actions taken
    encoding: str                       # room system layout encoding
    done: bool                          # run finished or not
    success: bool                       # exited rooms or not

    # Agent State
    current_room: int                   # current room of agent, 0-7
    committed: int                      # whether observation phase over, 0 no, 1 yes
    failure_last: int                   # whether agent failed last action, -1 unknown, 0 no, 1 yes

    # Room State
    room_included: List[int]            # whether room in system, 0 no, 1 yes
    room_connections: List[List[int]]   # whether rooms connected, 0 no, 1 yes
    room_locked: List[int]              # whether room locked, 0 no, 1 yes
    room_haskey: List[int]              # whether room has key, 0 no, 1 yes
    room_exit: List[int]                # whether room is exit, 0 no, 1 yes
    room_visited: List[int]             # whether room has been visited by agent, 0 no, 1 yes
    room_inspected: List[int]           # whether room has been inspected by agent, 0 no, 1 yes

    # Resources State
    current_keys: int                   # number of keys agent has
    actions_remaining: int              # number of execution actions left
    obs_inspect_weight: float           # weight of using inspect in observation mode, should be positive

    # Modifier State
    failure_show: bool                  # whether to indicate agent failure
    failure_consequence: float          # loss when agent fails, set to 0.0 to disable, should be positive
    commit_reset: bool                  # whether to reset agent knowledge after phase change