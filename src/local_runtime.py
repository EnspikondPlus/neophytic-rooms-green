# src/local_runtime.py
from typing import Any, List, Optional
from a2a.types import Message, TaskState, Part, DataPart, TextPart

class LocalTaskUpdater:
    """
    Simulates the A2A TaskUpdater for local execution.
    Captures artifacts and prints status updates to console.
    """
    def __init__(self):
        self.artifacts: List[Any] = []
        self.status_history: List[str] = []
        self._terminal_state_reached = False

    async def update_status(self, state: TaskState, message: Message) -> None:
        text = message.parts[0].root.text if message.parts else ""
        self.status_history.append(f"[{state.value}] {text}")
        print(f"  > {text}")

    async def add_artifact(self, parts: List[Part], name: str) -> None:
        self.artifacts.append({"name": name, "parts": parts})

    async def complete(self) -> None:
        self._terminal_state_reached = True

    async def reject(self, message: Message) -> None:
        text = message.parts[0].root.text
        print(f"❌ REJECTED: {text}")
        self._terminal_state_reached = True

    async def failed(self, message: Message) -> None:
        text = message.parts[0].root.text
        print(f"❌ FAILED: {text}")
        self._terminal_state_reached = True

    def get_result_data(self) -> Optional[dict]:
        """Helper to extract the DataPart from the saved artifact."""
        for artifact in self.artifacts:
            for part in artifact["parts"]:
                if isinstance(part.root, DataPart):
                    return part.root.data
        return None