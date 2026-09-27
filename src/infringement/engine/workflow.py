"""Workflow and activity decorators, and the context workflow code runs against."""

from collections.abc import Callable
from typing import Literal

Queue = Literal["local", "lambda"]


def workflow(fn: Callable) -> Callable:
    raise NotImplementedError


def activity(queue: Queue) -> Callable[[Callable], Callable]:
    """Register an activity and where it runs: in the worker, or on Lambda via SQS."""
    raise NotImplementedError
