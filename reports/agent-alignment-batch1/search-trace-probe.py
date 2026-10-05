"""Reproduce candidate-count telemetry with the real dense index and a scripted SDK model."""
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent/src"))

from resolveflow.harness.model import MockModelClient  # noqa: E402
from resolveflow.harness.sdk_runner import AgentScopeRunner  # noqa: E402
from scripts.agent_eval import metadata, persist  # noqa: E402
from scripts.evaluation.dataset import ALIGNED_DATA, export_case  # noqa: E402
from scripts.evaluation.environment import business_tools, dispatch_facts, environment  # noqa: E402
from scripts.evaluation.models import CaptureModel  # noqa: E402

destination = Path(sys.argv[1])
if destination.exists():
    raise FileExistsError(destination)
report = metadata("synthetic_search_trace_probe", ALIGNED_DATA)
case = export_case("A01A", ALIGNED_DATA)
run_id = str(uuid.uuid4())
model = CaptureModel(MockModelClient(script=[
    {"kind": "SEARCH_POLICY", "query": "已付款未发货", "arguments": {"top_k": 2}},
    {"kind": "ESCALATE", "reason_codes": ["PROBE_END"], "summary": "Synthetic telemetry check"},
]))
with environment(dataset=ALIGNED_DATA) as (_, index, encoder, pins):
    pin = pins[case["bundle_id"]]
    with business_tools(case, pin, run_id=run_id, case_id=case["case_id"]) as (tools, requests):
        runner = AgentScopeRunner(model=model, tools=tools,
                                  facts=dispatch_facts(case, pin, run_id=run_id, case_id=case["case_id"]),
                                  policy_index=index, policy_embedder=encoder)
        result = runner.run()
        observation = next(o for o in result.observations if o.tool_name == "search_policy")
        trace = next(t for t in result.trajectory if t.get("action") == "search_policy")
        count = len(observation.result["hits"])
        report.update(harness_manifest=runner.manifest(), requests=model.records,
                      observations=[o.model_dump(mode="json") for o in result.observations],
                      trajectory=result.trajectory, reason_code=result.reason_code, notices=result.notices,
                      http_reads=requests, paid_model_calls=0,
                      summary={"candidate_count": count, "trajectory_hits": trace["hits"],
                               "matched": trace["hits"] == count == observation.result["hit_count"]})
persist(destination, report)
print(report["summary"])
assert report["summary"]["matched"] and count == 2
