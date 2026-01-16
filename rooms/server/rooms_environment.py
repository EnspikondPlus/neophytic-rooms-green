from uuid import uuid4
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import Observation, State
from ..models import RoomsAction, RoomsState, Command
from .environment_logic import decode_room_system, build_observation

class RoomsEnvironment(Environment):
    def __init__(self,
                 steps_remaining: int = 30,
                 obs_inspect_weight: float = 3.0,
                 failure_show: bool = True,
                 failure_consequence: bool = False,
                 commit_reset: bool = False):
        self.steps_remaining = steps_remaining
        self.obs_inspect_weight = obs_inspect_weight
        self.failure_show = failure_show
        self.failure_consequence = failure_consequence
        self.commit_reset = commit_reset

        self._state = RoomsState(
            episode_id="not-started",
            step_count=0,
            room_included=[0]*8,
            room_connections=[[0]*8 for _ in range(8)],
            room_locked=[0]*8,
            room_haskey=[0]*8,
            room_exit=[0]*8,
            room_visited=[0]*8,
            room_inspected=[0]*8,
            current_room=0,
            current_keys=0,
            committed=0,
            done=False,
            weighted_steps_used=0,
            steps_remaining=self.steps_remaining,
            obs_inspect_weight=self.obs_inspect_weight,
            failure_show=self.failure_show,
            failure_consequence=self.failure_consequence,
            commit_reset=self.commit_reset,
            failure_last=0,
            encoding=""
        )

    def reset(self, encoding: str) -> Observation:
        room_data = decode_room_system(encoding)
        self._state = RoomsState(
            episode_id=str(uuid4()),
            step_count=0,
            room_included=room_data["room_included"],
            room_connections=room_data["room_connections"],
            room_locked=room_data["room_locked"],
            room_haskey=room_data["room_haskey"],
            room_exit=room_data["room_exit"],
            room_visited=[0]*8,
            room_inspected=[0]*8,
            current_room=room_data["current_room"],
            current_keys=0,
            committed=0,
            done=False,
            weighted_steps_used=0,
            failure_last=0,
            steps_remaining=self.steps_remaining,
            obs_inspect_weight=self.obs_inspect_weight,
            failure_show=self.failure_show,
            failure_consequence=self.failure_consequence,
            commit_reset=self.commit_reset,
            encoding=encoding
        )
        self.current_room = room_data["current_room"]
        self._state.room_visited[self.current_room] = 1
        obs = build_observation(self._state)
        obs.done = self._state.done
        obs.reward = -1.0 * self._state.weighted_steps_used
        return obs

    def step(self, action: RoomsAction) -> Observation:
        self._state.step_count += 1
        self._execute_command(action.command, action.target_room)
        obs = build_observation(self._state)
        obs.done = self._state.done
        obs.reward = -1.0 * self._state.weighted_steps_used
        return obs
    
    def _execute_command(self, command: Command, target_room: int = None):
        state = self._state
        if (state.committed == 0):
            match(command):
                case Command.MOVE:
                    if (target_room == None
                        or state.room_connections[state.current_room][target_room] == 0):
                        state.failure_last = 1
                    else:
                        state.current_room = target_room
                        state.room_visited[target_room] = 1
                        state.room_inspected[target_room] = 1
                        state.weighted_steps_used += state.obs_inspect_weight
                        state.failure_last = 0

                case Command.COMMIT:
                    state.committed = 1
                    if (state.commit_reset):
                        state.room_inspected = [0]*8
                    state.room_visited=[0]*8
                    state.current_room = self.current_room
                    state.room_visited[self.current_room] = 1
                    state.failure_last = 0
                case _:
                    state.failure_last = 1
        else:
            match(command):
                case Command.MOVE:
                    if (target_room == None
                        or state.room_connections[state.current_room][target_room] == 0
                        or state.room_locked[state.current_room] == 1 and state.room_visited[target_room] == 0):
                        state.failure_last = 1
                    else:
                        state.current_room = target_room
                        state.room_visited[target_room] = 1
                        state.failure_last = 0
                case Command.INSPECT:
                    if (state.room_inspected[state.current_room] == 1):
                        state.failure_last = 1
                    else:
                        state.room_inspected[state.current_room] = 1
                        state.failure_last = 0
                case Command.USEKEY:
                    if (state.current_keys <= 0
                        or state.room_locked[state.current_room] == 0):
                        state.failure_last = 1
                    else:
                        state.current_keys -= 1
                        state.room_locked[state.current_room] = 0
                        state.failure_last = 0
                case Command.GETKEY:
                    if (state.room_haskey[state.current_room] == 0):
                        state.failure_last = 1
                    else:
                        state.current_keys += 1
                        state.room_haskey[state.current_room] = 0
                        state.failure_last = 0
                case _:
                    state.failure_last = 0
            state.weighted_steps_used += 1.0
            state.steps_remaining -= 1
            if (state.room_exit[state.current_room] == 1
                and state.room_locked[state.current_room] == 0):
                state.done = True
        if (state.failure_consequence and state.failure_last == 1):
            state.weighted_steps_used += 1.0

    @property
    def state(self) -> State:
        return self._state