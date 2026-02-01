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
import random
from .benchmarks.room_gen import generate_random_system
from pathlib import Path

BASE_DIR = Path(__file__).resolve()
json_path = BASE_DIR / "benchmarks" / "standard_systems.json"

class EvalRequest(BaseModel):
    """Request format sent by the AgentBeats platform to green agents."""
    participants: dict[str, HttpUrl]
    config: dict[str, Any]


class Agent:
    # Single participant: agent being evaluated
    required_roles: list[str] = ["solver"]
    # Required config: look at README for detailed explanation
    required_config_keys: list[str] = ["generate", "count"]

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
        generate = bool(request.config["generate"])
        count = int(request.config["count"])
        difficulty = request.config.get("difficulty", "random")
        no_loops = bool(request.config.get("no_loops", False))

        room_systems = self._queue_runs(generate, count, difficulty, no_loops)

        # Optional environment parameters
        env_config = {
            "actions_remaining": request.config.get("actions_remaining", 30),
            "obs_inspect_weight": request.config.get("obs_inspect_weight", 3.0),
            "failure_show": request.config.get("failure_show", True),
            "failure_consequence": request.config.get("failure_consequence", 0.0),
            "commit_reset": request.config.get("commit_reset", True),
        }
        max_steps = env_config["actions_remaining"]

        await updater.update_status(
            TaskState.working,
            new_agent_text_message(f"Running {len(room_systems)} room systems. Good luck!")
        )

        all_run_results: list[dict] = []

        for run_index, run in enumerate(room_systems):
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(f"[{run_index + 1}/{len(room_systems)}] Starting run with encoding {run['encoding']}")
            )

            self.env = RoomsEnvironment(**env_config)
            try:
                obs = self.env.reset(encoding=run["encoding"])
                step_count = 0
                conversation_history = []
                weighted_loss = 0.0
                success = False
                done = False

                self.messenger.reset()

                # Initial prompt to the solver
                initial_prompt = self._create_prompt(obs, step_count)
                conversation_history.append({"step": step_count, "observation": obs.model_dump(), "prompt": initial_prompt})

                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(f"[{run_index + 1}/{len(room_systems)}] Step {step_count}: Sending initial observation to solver")
                )

                # Main interaction loop
                while not done:
                    # Get action from solver
                    response = await self.messenger.talk_to_agent(
                        message=initial_prompt if step_count == 0 else self._create_prompt(obs, step_count),
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
                            new_agent_text_message(f"[{run_index + 1}/{len(room_systems)}] Step {step_count}: Failed to parse action from solver — aborting this run")
                        )
                        break

                    conversation_history.append({"step": step_count, "action": action.model_dump()})

                    # Execute action in environment
                    obs = self.env.step(action)

                    step_reward = getattr(obs, 'reward', 0.0)
                    if step_reward is None:
                        step_reward = 0.0
                    weighted_loss = step_reward

                    step_count += 1

                    # Check for done flag in the observation object
                    if hasattr(obs, 'done'):
                        done = obs.done

                    conversation_history.append({"step": step_count, "observation": obs.model_dump(), "loss": weighted_loss})

                    await updater.update_status(
                        TaskState.working,
                        new_agent_text_message(f"[{run_index + 1}/{len(room_systems)}] Step {step_count}: Executed {action.command.value}, loss: {weighted_loss:.2f}")
                    )

                    if done:
                        success = obs.success if hasattr(obs, 'success') else False
                        break

                # Store this run's result
                all_run_results.append({
                    "run_index": run_index,
                    "success": success,
                    "total_loss": weighted_loss,
                    "steps_taken": step_count,
                    "max_steps": max_steps,
                    "encoding": run["encoding"],
                    "final_observation": obs.model_dump(),
                    "conversation_history": conversation_history,
                })

            except Exception as e:
                # Log the error but do not raise
                print(f"❌ Error during run {run_index + 1}: {str(e)}")
                traceback.print_exc()

                await updater.update_status(
                    TaskState.working,
                    new_agent_text_message(f"[{run_index + 1}/{len(room_systems)}] Error: {str(e)} — continuing to next run")
                )

                all_run_results.append({
                    "run_index": run_index,
                    "success": False,
                    "total_loss": None,
                    "steps_taken": None,
                    "max_steps": max_steps,
                    "encoding": run["encoding"],
                    "error": str(e),
                })

        # All runs complete, output full summary
        total_runs = len(all_run_results)
        successful_runs = [r for r in all_run_results if r["success"]]
        errored_runs = [r for r in all_run_results if "error" in r]
        completed_runs = [r for r in all_run_results if r["total_loss"] is not None]

        success_rate = len(successful_runs) / total_runs if total_runs > 0 else 0.0
        avg_loss = (
            sum(r["total_loss"] for r in completed_runs) / len(completed_runs)
            if completed_runs else None
        )
        avg_steps = (
            sum(r["steps_taken"] for r in completed_runs) / len(completed_runs)
            if completed_runs else None
        )

        # Per-run summaries
        per_run_lines = []
        for r in all_run_results:
            if "error" in r:
                per_run_lines.append(
                    f"  Run {r['run_index'] + 1}: ERROR — {r['error']}"
                )
            else:
                status = "✅ Success" if r["success"] else "❌ Failed"
                per_run_lines.append(
                    f"  Run {r['run_index'] + 1}: {status} | "
                    f"Loss: {r['total_loss']:.2f} | "
                    f"Steps: {r['steps_taken']}/{r['max_steps']}"
                )

        summary = (
            f"========== Rooms Benchmark — Full Summary ==========\n\n"
            f"Per-Run Results:\n"
            + "\n".join(per_run_lines) + "\n\n"
            f"----------------------------------------------------\n"
            f"Aggregate Statistics:\n"
            f"  Total Runs:      {total_runs}\n"
            f"  Successful:      {len(successful_runs)}\n"
            f"  Failed:          {total_runs - len(successful_runs) - len(errored_runs)}\n"
            f"  Errored:         {len(errored_runs)}\n"
            f"  Success Rate:    {success_rate:.1%}\n"
            f"  Avg Loss:        {f'{avg_loss:.2f}' if avg_loss is not None else 'N/A'}\n"
            f"  Avg Steps Used:  {f'{avg_steps:.1f}' if avg_steps is not None else 'N/A'}\n"
            f"===================================================="
        )

        aggregate = {
            "total_runs": total_runs,
            "successful_runs": len(successful_runs),
            "errored_runs": len(errored_runs),
            "success_rate": success_rate,
            "avg_loss": avg_loss,
            "avg_steps": avg_steps,
            "max_steps": max_steps,
            "per_run_results": all_run_results,
        }

        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=summary)),
                Part(root=DataPart(data=aggregate))
            ],
            name="Rooms Benchmark — Full Summary",
        )

    def _queue_runs(self, generate: bool, count: int, difficulty: str, no_loops: bool):
        difficulties = {
            "tutorial":  {"rooms": (2, 3), "locks": (0, 0), "softlock": False},
            "easy":      {"rooms": (4, 5), "locks": (0, 1), "softlock": False},
            "medium":    {"rooms": (5, 6), "locks": (1, 2), "softlock": True},
            "hard":      {"rooms": (6, 7), "locks": (2, 3), "softlock": True},
            "very_hard": {"rooms": (7, 8), "locks": (3, 4), "softlock": True},
        }
        real_difficulty = difficulty
        cases = []
        if generate:
            for i in range(count):
                if real_difficulty == "random":
                    # BUG FIX: random.choice on .values() requires a list
                    difficulty = random.choice(list(difficulties.keys()))
                config = difficulties[difficulty]
                sys_data = generate_random_system(
                    difficulty_settings=config,
                    graph_mode="general",
                    no_loops=no_loops,
                    require_softlock=config["softlock"]
                )
                case = {
                    "id": f"generated_{i}",
                    "encoding": sys_data["encoding"],
                    "difficulty": difficulty,
                    "optimal_steps": sys_data["optimal_steps"],
                    "description": sys_data["description"],
                    "graph_mode": sys_data["graph_mode"],
                    "has_cycles": sys_data["has_cycles"],
                    "softlock_possible": sys_data["softlock_possible"],
                }
                cases.append(case)
        else:
            # BUG FIX: json.loads() expects a string, not a file object — use .read()
            with open(json_path) as jsonfile:
                data = json.loads(jsonfile.read())
            total_tests = {}
            all_cases = []
            for category in data.keys():
                # BUG FIX: data is a plain dict from JSON, use [] not .cases
                total_tests[category] = len(data[category]["cases"])
                all_cases = all_cases + data[category]["cases"]
            total_tests["total"] = sum(total_tests.values())
            if difficulty == "random":
                count = min(count, 100)
                count = max(count, 0)
                cases = random.sample(all_cases, count)
            else:
                count = min(count, total_tests[difficulty])
                count = max(count, 0)
                # BUG FIX: use the correct variable `difficulty`, not the loop var `category`
                cases = random.sample(data[difficulty]["cases"], count)
        return cases


    def _create_prompt(self, obs, step_count: int) -> str:
        """Create a prompt for the solver agent based on current observation."""
        prompt = f"""You are solving a Rooms navigation puzzle. Current state (Move {step_count}):

Current Room: {obs.current_room}
Phase: {"Observation" if obs.committed == 0 else "Execution"}
Keys Held: {obs.current_keys}
Steps Remaining: {obs.actions_remaining}

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
            response = response.strip()
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start == -1 or end == 0:
                return None
            
            json_str = response[start:end]
            action_data = json.loads(json_str)
            
            command_str = action_data.get("command", "").upper()
            
            try:
                command = Command[command_str]
            except KeyError:
                return None
            
            target_room = action_data.get("target_room")
            
            return RoomsAction(command=command, target_room=target_room)
            
        except (json.JSONDecodeError, KeyError, ValueError):
            return None