"""Read-only saved-action diagnosis; better feedback does not retroactively fix model decisions."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "agent/src"), str(ROOT / "agent")]

from resolveflow.support.engine import SupportAgent
from resolveflow.support.grounding import ground_answer
from resolveflow.support.navigation import render_navigation
from resolveflow.support.protocol import AnswerParts, SupportInput
from resolveflow.support.stages import StageError
from resolveflow.support.tasks import render_answer
from tests.integration.test_support_dialogue_api import TokenizedScript

RAW = ROOT / "reports/customer-answer-fact-fields-v1/live-v1/runtime-results.json"
OUT = ROOT / "reports/customer-answer-fact-fields-v1/source-feedback-review.json"


def diagnose():
    digest = hashlib.sha256(RAW.read_bytes()).hexdigest()
    run = json.loads(RAW.read_text(encoding="utf-8"))["support_runs"][0]
    request = SupportInput.model_validate({**run["input_json"],
        "deadline_at": dt.datetime.now(dt.UTC) + dt.timedelta(seconds=120)})
    models = [c for c in run["calls"] if c["kind"] == "model"]
    tools = [c for c in run["calls"] if c["kind"] == "tool"]

    class Saved:
        position = 0

        def read(self, name, arguments):
            call = tools[self.position]
            self.position += 1
            assert call["request_json"] == {"name": name, "arguments": arguments}
            return call["response_json"][0]

    saved = Saved()
    model = TokenizedScript(mode="live", script=[m["response_json"]["decision"] for m in models])
    agent = SupportAgent(request, model, saved, architecture="staged-v1")
    result = agent.run()
    assert result["reason"] == "INVALID_DECISION" and result["answer"] is None
    assert model.calls == len(models) == 5 and saved.position == len(tools) == 2
    first = json.loads(model.packets[3]["feedback"])
    assert {g["need"] for g in first["source_gaps"]} == {"ORDER", "GUIDE"}
    original_packet = json.loads(models[3]["request_json"]["messages"][-1]["content"])
    old_feedback = json.loads(original_packet["feedback"])
    last = AnswerParts.model_validate(models[-1]["response_json"]["decision"])
    navigation = render_navigation(last, agent.citations, strict=True, required={"t2": "REFUND_APPLICATION"},
                                   conversation_state=request.context.get("conversation_state"))
    grounded = ground_answer(navigation, request, agent.citations)
    answer = render_answer(grounded, agent.tasks.tasks)
    try:
        agent.stage.check_sources(answer, agent.citations, agent.dialogue.lifecycles)
    except StageError as error:
        final_gaps = error.gaps
    else:
        raise AssertionError("Saved last answer must still fail without ORDER")
    assert final_gaps == [{"task_id": "t2", "need": "ORDER"}]
    assert hashlib.sha256(RAW.read_bytes()).hexdigest() == digest
    return {"diagnostic_only": True, "strict_replay": False, "deadline_refreshed_for_offline_execution": True,
        "raw_sha256": digest, "new_provider_calls": 0, "business_writes": 0,
        "original_first_feedback": old_feedback, "new_first_feedback": first,
        "saved_actions_consumed": model.calls, "saved_tools_consumed": saved.position,
        "saved_actions_still_failed": True, "final_source_gaps": final_gaps,
        "last_fact_rendering": last.fact_rendering, "fact_rendered_but_not_published_text": answer.text}


if __name__ == "__main__":
    value = diagnose()
    assert not OUT.exists(), "Never overwrite a saved diagnosis"
    OUT.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print({"old_actions_still_failed": True, "new_first_feedback_includes": ["ORDER", "GUIDE"],
           "new_provider_calls": 0})
