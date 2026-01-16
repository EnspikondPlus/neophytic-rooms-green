from typing import Any
from pydantic import BaseModel, HttpUrl, ValidationError
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message

from .messenger import Messenger
from rooms.server.rooms_environment import RoomsEnvironment
from rooms.models import RoomsAction, Command
import json
import traceback


class EvalRequest(BaseModel):
    """Request format sent by the AgentBeats platform to green agents."""
    participants: dict[str, HttpUrl]  # role -> agent URL
    config: dict[str, Any]


class Agent:
    # One participant: the agent being evaluated
    required_roles: list[str] = ["solver"]
    # Required config: the room encoding
    required_config_keys: list[str] = ["encoding"]

    def __init__(self):
        self.messenger = Messenger()
        self.env = None

    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        missing_roles = set(self.required_roles) - set(request.participants.keys())
        if missing_roles:
            return False, f"Missing roles: {missing_roles}"

        missing_config_keys = set(self.required_config_keys) - set(request.config.keys())
        if missing_config_keys:
            return False, f"Missing config keys: {missing_config_keys}"

        # Validate encoding format
        encoding = request.config.get("encoding", "")
        if not isinstance(encoding, str) or len(encoding) != 25:
            return False, "Encoding must be a 25-character hex string"

        return True, "ok"

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        """Run the Rooms environment benchmark with the solver agent."""
        input_text = get_message_text(message)

        try:
            request: EvalRequest = EvalRequest.model_validate_json(input_text)
            ok, msg = self.validate_request(request)
            if not ok:
                await updater.reject(new_agent_text_message(msg))
                return
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return

        solver_url = str(request.participants["solver"])
        encoding = request.config["encoding"]
        max_steps = request.config.get("max_steps", 50)
        
        # Optional environment parameters
        env_config = {
            "steps_remaining": request.config.get("steps_remaining", 30),
            "obs_inspect_weight": request.config.get("obs_inspect_weight", 3.0),
            "failure_show": request.config.get("failure_show", True),
            "failure_consequence": request.config.get("failure_consequence", False),
            "commit_reset": request.config.get("commit_reset", False),
        }

        await updater.update_status(
            TaskState.working, 
            new_agent_text_message(f"Starting Rooms benchmark with encoding {encoding}")
        )

        # Initialize environment
        self.env = RoomsEnvironment(**env_config)
        
        try:
            # Reset environment and get initial observation
            obs = self.env.reset(encoding=encoding)
            
            step_count = 0
            conversation_history = []
            total_reward = 0.0
            success = False
            done = False
            
            # Start new conversation with solver
            self.messenger.reset()
            
            # Initial prompt to the solver
            initial_prompt = self._create_prompt(obs, step_count, None)
            conversation_history.append({"step": step_count, "observation": obs.model_dump(), "prompt": initial_prompt})
            
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"Step {step_count}: Sending initial observation to solver")
            )
            
            # Main interaction loop
            while not done and step_count < max_steps:
                # Get action from solver
                response = await self.messenger.talk_to_agent(
                    message=initial_prompt if step_count == 0 else self._create_prompt(obs, step_count, None),
                    url=solver_url,
                    new_conversation=(step_count == 0),
                    timeout=60
                )
                
                conversation_history.append({"step": step_count, "solver_response": response})
                
                # Parse action from solver's response
                action = self._parse_action(response)
                
                if action is None:
                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(f"Step {step_count}: Failed to parse action from solver")
                    )
                    break
                
                conversation_history.append({"step": step_count, "action": action.model_dump()})
                
                # Execute action in environment
                obs = self.env.step(action)
                
                step_reward = getattr(obs, 'reward', 0.0)
                if step_reward is None: step_reward = 0.0
                total_reward += step_reward
                
                step_count += 1
                
                # Check for done flag in the observation object
                if hasattr(obs, 'done'):
                    done = obs.done
                elif hasattr(obs, 'terminated'):
                    done = obs.terminated
                
                conversation_history.append({"step": step_count, "observation": obs.model_dump(), "reward": step_reward})
                
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(f"Step {step_count}: Executed {action.command.value}, reward: {step_reward:.2f}")
                )
                
                if done:
                    # Determine success (e.g., if total reward is positive, you found the exit)
                    if total_reward > 0:
                        success = True
                    break
            
            # Prepare results
            results = {
                "success": success,
                "total_reward": total_reward,
                "steps_taken": step_count,
                "max_steps": max_steps,
                "encoding": encoding,
                "final_observation": obs.model_dump(),
                "conversation_history": conversation_history,
            }
            
            summary = (
                f"Benchmark completed!\n"
                f"Success: {success}\n"
                f"Total Reward: {total_reward:.2f}\n"
                f"Steps Taken: {step_count}/{max_steps}\n"
                f"Final State: {'Exit reached' if success else 'Failed or timeout'}"
            )
            
            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=summary)),
                    Part(root=DataPart(data=results))
                ],
                name="Rooms Benchmark Result",
            )
            
        except Exception as e:
            print(f"❌ Error during benchmark execution: {str(e)}")
            traceback.print_exc()
            
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"Error during benchmark: {str(e)}")
            )
            raise

    def _create_prompt(self, obs, step_count: int, previous_action) -> str:
        """Create a prompt for the solver agent based on current observation."""
        prompt = f"""You are solving a Rooms navigation puzzle. Current state (Move {step_count}):

Current Room: {obs.current_room}
Phase: {"Observation" if obs.committed == 0 else "Execution"}
Keys Held: {obs.current_keys}
Steps Remaining: {obs.steps_remaining}

Room Status (1 means true and 0 means false):
Rooms Visited: {obs.room_visited}
Rooms Inspected: {obs.room_inspected}

Room Properties (1 means true and 0 means false for inspected rooms; -1 means unknown):
- Locked: {obs.room_locked}
- Has Key: {obs.room_haskey}
- Is Exit: {obs.room_exit}

You are in a system of up to 8 rooms (indexed 0-7) that are all connected in one graph. Your goal is to find (and if needed, unlock) the exit room and leave.
On each turn, you can do one of: MOVE, INSPECT, GETKEY, USEKEY, COMMIT.
MOVE to move into a room that is connected to your current room. In Observation phase, moving into a room automatically performs the INSPECT action in the room you move to, and you can move through locked rooms, but moves are more costly. In Execution phase, you may not MOVE if your current room is locked, unless it is back to a previous room you have visited.
INSPECT your current room to know which rooms it connects to, if it is locked, and if it contains a key inside.
GETKEY to pick-up a key in your current room, if it has a key.
USEKEY to use a key in your current room to unlock it if it was locked.
COMMIT to change the phase from Observation to Execution. This cannot be undone.

Actions in the Observation phase do not use your remaining steps, but are more costly than actions in the Execution phase. 
Actions in the Execution phase use one step per action, even if that action fails. If you run out of steps, you fail.

Rules and strategy reminders:
1. In Observation phase:
   - You can MOVE to any connected room to explore, and automatically INSPECT that room without further command use.
   - You cannot GETKEY, USEKEY, INSPECT at any time.
   - COMMIT switches to Execution phase, and you are reset to your starting room.
   - Keep track of keys, locked rooms, and exits. This information may go away during Execution phase.
2. In Execution phase:
   - You may MOVE to adjacent rooms if your current room is unlocked, or if you are moving into a room you have already visited.
   - INSPECT the current room if it has not been inspected.
   - USEKEY to unlock a locked room only if you have a key.
   - GETKEY to pick up a key in the current room if one exists.
3. The goal is to reach the exit room and unlock it if necessary.
4. Avoid unnecessary moves that increase weighted steps used.

Available commands:
- MOVE <room_number>: Move to an adjacent room, rooms are numbered 0-7
- INSPECT: Inspect current room (only in execution phase)
- USEKEY: Use a key to unlock current room
- GETKEY: Pick up key in current room
- COMMIT: Switch from observation to execution phase

Respond only with a JSON object containing your action, for example:
{{"command": "MOVE", "target_room": 1}}
or
{{"command": "INSPECT"}}
or
{{"command": "USEKEY"}}
or
{{"command": "GETKEY"}}
or
{{"command": "COMMIT"}}
"""
        return prompt

    def _parse_action(self, response: str) -> RoomsAction | None:
        """Parse the solver's response into a RoomsAction."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            
            # Find JSON in the response
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start == -1 or end == 0:
                return None
            
            json_str = response[start:end]
            action_data = json.loads(json_str)
            
            command_str = action_data.get("command", "").upper()
            
            # Map command string to enum
            try:
                command = Command[command_str]
            except KeyError:
                return None
            
            target_room = action_data.get("target_room")
            
            return RoomsAction(command=command, target_room=target_room)
            
        except (json.JSONDecodeError, KeyError, ValueError):
            return None