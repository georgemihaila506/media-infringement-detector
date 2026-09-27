"""Lambda entry point. The same run_activity is used by the local runner."""

import json
from typing import Any


def run_activity(task: dict[str, Any]) -> None:
    """Run one activity task and report its result to the results queue."""
    raise NotImplementedError


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    failures = []
    for record in event["Records"]:
        try:
            run_activity(json.loads(record["body"]))
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
