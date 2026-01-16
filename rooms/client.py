from typing import Dict
from openenv.core.client_types import StepResult
from openenv.core import EnvClient
from .models import RoomsAction, RoomsObservation, RoomsState

class RoomsEnv(EnvClient[RoomsAction, RoomsObservation, RoomsState]):
    def reset(self, encoding: str) -> RoomsObservation:
        return super().reset(encoding=encoding)

    def _step_payload(self, action: RoomsAction) -> Dict:
        return {
            "command": action.command.value,
            "target_room": action.target_room,
        }

    def _parse_result(self, payload: Dict) -> StepResult[RoomsObservation]:
        observation = RoomsObservation(**payload["observation"])
        return StepResult(
            observation=observation,
            reward=payload.get("reward", 0.0),
            done=payload.get("done", False)
        )

    def _parse_state(self, payload: Dict) -> RoomsState:
        return RoomsState(**payload)
