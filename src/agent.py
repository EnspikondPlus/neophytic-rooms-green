from typing import Any
from pydantic import BaseModel, HttpUrl, ValidationError
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message

from messenger import Messenger
from rooms.client import RoomsEnv
from rooms.models import RoomsAction, Command
import json


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
        self.env = RoomsEnv(**env_config)
        
        try:
            # Reset environment and get initial observation
            result = self.env.reset(encoding=encoding)
            obs = result.observation
            
            step_count = 0
            conversation_history = []
            total_reward = 0.0
            success = False
            
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
            while not obs.done and step_count < max_steps:
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
                result = self.env.step(action)
                obs = result.observation
                total_reward += result.reward or 0.0
                step_count += 1
                
                conversation_history.append({"step": step_count, "observation": obs.model_dump(), "reward": result.reward})
                
                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(f"Step {step_count}: Executed {action.command.value}, reward: {result.reward:.2f}")
                )
                
                if obs.done:
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
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"Error during benchmark: {str(e)}")
            )
            raise

    def _create_prompt(self, obs, step_count: int, previous_action) -> str:
        """Create a prompt for the solver agent based on current observation."""
        prompt = f"""You are solving a Rooms navigation puzzle. Current state (Step {step_count}):

Current Room: {obs.current_room}
Phase: {"Observation" if obs.committed == 0 else "Execution"}
Keys Held: {obs.current_keys}
Steps Remaining: {obs.steps_remaining}

Rooms Visited: {obs.room_visited}
Rooms Inspected: {obs.room_inspected}

Room Properties (for inspected rooms, -1 means unknown):
- Locked: {obs.room_locked}
- Has Key: {obs.room_haskey}
- Is Exit: {obs.room_exit}

Your goal is to reach the exit room and unlock it if necessary.

Available commands:
- MOVE <room_number>: Move to an adjacent room
- INSPECT: Inspect current room (only in execution phase)
- USEKEY: Use a key to unlock current room
- GETKEY: Pick up key in current room
- COMMIT: Switch from observation to execution phase

Respond with a JSON object containing your action:
{{"command": "MOVE", "target_room": 1}}
or
{{"command": "INSPECT"}}
or
{{"command": "USEKEY"}}
etc.
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