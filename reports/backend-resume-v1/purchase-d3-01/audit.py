"""Offline reconstruction of D3 statement counts and exact legacy projection equality."""
import hashlib
import json
import sys
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(raw):
    frozen=read(raw/"baseline-manifest.json")
    for name,sha in frozen["sources"].items():
        assert digest(raw/"baseline-sources"/name)==sha
    for name,sha in frozen["baseline_files"].items():
        assert digest(raw/name)==sha
    candidate=read(raw/"candidate-manifest.json")
    for name,sha in candidate["sources"].items():
        assert digest(raw/"candidate-sources"/name)==sha
    before=read(raw/"baseline-verified.json")
    after=read(raw/"candidate-final.json")
    expected={(size,repeat) for size in (1,24,48) for repeat in range(10)}
    assert {(r["size"],r["repeat"]) for r in before}==expected and len(before)==30
    assert {(r["size"],r["repeat"]) for r in after}==expected and len(after)==30
    results=[]
    for size in (1,24,48):
        old=[r for r in before if r["size"]==size]
        new=[r for r in after if r["size"]==size]
        for a,b in zip(old,new,strict=True):
            assert a["repeat"]==b["repeat"] and a["projection"]==b["projection"]
            assert len(a["executed_sql"])==a["sql_count"] and len(b["executed_sql"])==b["sql_count"]
            assert len(a["projection"]["items"])==len(b["projection"]["items"])==size
            assert all("merchant_id" in sql and "customer_id" in sql for sql in b["executed_sql"])
        count_before={r["sql_count"] for r in old}
        count_after={r["sql_count"] for r in new}
        assert len(count_before)==len(count_after)==1
        a,b=count_before.pop(),count_after.pop()
        assert (a,b)=={1:(4,4),24:(110,8),48:(238,8)}[size]
        results.append({"size":size,"repeats":10,"before_sql":a,"after_sql":b,"reduction":1-b/a})
    plans=read(raw/"explain-analyze.json")
    assert len(plans)==8 and all(p["plan"] and p["bindings"] for p in plans)
    fanout=read(raw/"fanout.json")
    assert len(fanout)==180
    assert {(r["stores"],r["size"],r["repeat"],r["selected_store"]) for r in fanout}=={(s,n,i,selected) for s in (1,2,3) for n in (1,24,48) for i in range(10) for selected in (True,False)}
    for row in fanout:
        assert len(row["requests"])==(1 if row["selected_store"] else row["stores"])
    return {"paired_projections_identical":30,"sql":results,"explain_plans":8,"fanout_pages":180,
            "actual_loopback_http_requests":sum(len(r["requests"]) for r in fanout),
            "model_requests":0,"boundary":"business PreparedStatement execution count; synthetic MySQL fixture; HTTP fanout endpoint has explicit empty fixture bodies; no HTTP latency claim"}


if __name__=="__main__":
    result=audit(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("xb") as output:
        output.write((json.dumps(result,indent=2)+"\n").encode())
    print(json.dumps(result))
