"""How remote activity tasks leave the engine and results come back."""

from typing import Any, Protocol


class ActivityTransport(Protocol):
    def send(self, task: dict[str, Any]) -> None: ...


class InProcessTransport:
    """Runs activities synchronously in-process. For tests."""

    def send(self, task: dict[str, Any]) -> None:
        raise NotImplementedError
