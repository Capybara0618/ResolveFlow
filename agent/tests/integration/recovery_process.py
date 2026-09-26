"""Child process for CF6: real SDK/PG and deterministic synthetic model/tool IO."""
import json
import os
import sys

from resolveflow.harness.model import MockModelClient
from resolveflow.runtime.db import Database
from resolveflow.runtime.durable import DurableRun
from resolveflow.runtime.factory import DeploymentConfig, build_investigation
from resolveflow.runtime.worker import RunWorker
from tests.unit.test_harness_loop import StubTools, observation, propose


def main():
    database = Database(schema=sys.argv[1])
    window = sys.argv[2]
    script = [{"kind": "READ_TOOL", "tool_name": "get_order_context", "arguments": {}},
              propose("MANUAL_REVIEW", summary="synthetic recovery")]
    model = MockModelClient(script=script)
    tools = StubTools() if window == "resume-tool" else StubTools(observation())
    investigate = build_investigation(database=database, config=DeploymentConfig(mode="mock"), model=model, tools=tools)
    import resolveflow.runtime.factory as factory
    def fault(stage):
        if stage == window:
            os._exit(73)
    factory.DurableRun = lambda db, facts: DurableRun(db, facts, fault=fault)
    outcome = RunWorker(database, investigate, recoverable=True).run_once()
    print(json.dumps({"kind": outcome.callback_kind, "reason": outcome.result.reason_code,
                      "models": model.calls, "tools": len(tools.calls)}))
    database.close()


if __name__ == "__main__":
    main()
