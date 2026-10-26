"""Offline validation of D4 development probes. No business or provider network access."""
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def gauge(row,node,name):
    values=[v for k,v in row["metrics_"+node].items() if k.startswith("resolveflow.product_reviews."+name+"[")]
    assert len(values)==1
    return values[0]


def event_windows(folder,product):
    events=[json.loads(line) for path in folder.glob("*-events.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]
    events=[e for e in events if e.get("product")==product]
    starts={e["call"]:e for e in events if e["stage"]=="page_start"}
    ends={e["call"]:e for e in events if e["stage"]=="page_end"}
    assert starts.keys()==ends.keys()
    timeline=[]
    for call,start in starts.items():
        a=datetime.fromisoformat(start["at"].replace("Z","+00:00"));b=datetime.fromisoformat(ends[call]["at"].replace("Z","+00:00"))
        assert b>=a
        timeline.extend([(a,1),(b,-1)])
    active=peak=0
    for _,delta in sorted(timeline,key=lambda e:(e[0],e[1])):
        active+=delta;peak=max(peak,active);assert active>=0
    assert active==0
    return {"calls":len(starts),"peak_business_load_windows":peak}


def audit(raw):
    manifest=read(raw/"manifest.json")
    for name,digest in manifest["final_sources"].items():
        assert hashlib.sha256((raw/"final-sources"/name).read_bytes()).hexdigest()==digest
    faults,extra=raw/"d4-dual-faults-02",raw/"d4-dual-extra-01"
    fault_rows=read(faults/"summary.json")["rows"]
    extra_rows=read(extra/"summary.json")["rows"]
    assert len(fault_rows)==12 and len(extra_rows)==4
    assert {(r["condition"],r["scenario"]) for r in fault_rows}=={(c,s) for c in ("B","C") for s in ("cold-smoke","R02","R03","R04","R05","R06-timeout")}
    assert {(r["condition"],r["scenario"]) for r in extra_rows}=={(c,s) for c in ("B","C") for s in ("R01-ttl-burst","R06-disconnect")}
    windows=[]
    for row in fault_rows+extra_rows:
        c,s=row["condition"],row["scenario"]
        for node in ("a","b"):
            assert gauge(row,node,"database.inflight")==0
            assert 0<=gauge(row,node,"database.peak")<=8
        if s=="cold-smoke":
            w=event_windows(faults,row["fixture"]["product"])
            assert w["calls"]==w["peak_business_load_windows"]==(2 if c=="B" else 1)
            windows.append({"condition":c,"scenario":s,**w})
        if s=="R02":
            assert row["failed"]["status"]==500 and row["recovered"]["status"]==200
        if s=="R03":
            assert row["old_pid"]!=row["new_pid"] and 0<=row["recovery_ms"]<=5000
            assert row["attempts"][-1]["status"]==200
            assert all(a["status"]==503 for a in row["attempts"][:-1])
        if s=="R04":
            assert row["actual_process_suspended"] and row["pause_ms"]>=2000
            assert row["new_owner_lock_after_old_return"]==("1" if c=="C" else "0")
            if c=="C":
                assert row["metrics_a"]["resolveflow.product_reviews.cache.write[tag(outcome=lease_lost)]:COUNT"]>=1
                assert row["metrics_a"]["resolveflow.product_reviews.rebuild.lock[tag(outcome=lease_lost)]:COUNT"]>=1
        if s=="R05":
            assert row["new_epoch"]==row["old_epoch"]+1
            assert "committed-new-reply" not in str(row["old_response"]["body"])
            assert "committed-new-reply" in str(row["new_response"]["body"])
            assert row["new_response"]["body"]==row["final_response"]["body"]
        if s=="R06-timeout":
            assert len(row["responses"])==33 and {r["status"] for r in row["responses"]}<={200,503}
            assert gauge(row,"a","database.peak")==gauge(row,"b","database.peak")==8
            assert row["recovered"]["status"]==200
        if s=="R01-ttl-burst":
            assert row["ttl_wait_ms"]>=31000 and row["independent_response"]["status"]==200
            assert row["independent_product"]!=row["fixture"]["product"]
            assert len(row["responses"])==30
            status=Counter(r["status"] for r in row["responses"])
            assert status==({200:30} if c=="B" else {200:1,503:29})
            w=event_windows(extra,row["fixture"]["product"])
            assert w["calls"]==(27 if c=="B" else 2) # Includes one pre-TTL initial fill.
            if c=="C":assert w["peak_business_load_windows"]==1
            windows.append({"condition":c,"scenario":s,**w,"statuses":dict(status)})
        if s=="R06-disconnect":
            assert len(row["disconnect_responses"])==4
            assert all(r["status"]==200 for r in row["disconnect_responses"]+row["restored_responses"])
    limiter=read(raw/"d4-limiter-01/summary.json")
    assert limiter["status"]=="PASSED" and len(limiter["windows"])==3
    assert len(set(limiter["pids"]))==2
    for row in limiter["windows"]:
        for action in ("write","reply"):
            assert Counter(r["status"] for r in row[action])=={200:6,429:6}
            assert {r["node"] for r in row[action]}=={0,1}
        assert row["downstream_http_calls"]==12
    assert limiter["unavailable"]["status"]==503
    assert limiter["downstream_http_calls"]==len(limiter["calls"])==38
    plans=read(raw/"workspace-sql.json")
    assert {r["profile"] for r in plans}=={"REVIEW_PUBLIC","REVIEW_NEXT","MINE","UNCLAIMED","SEARCH","SECOND_STORE","ALL"}
    for row in plans:
        assert row["sql_count"]==len(row["statements"])==3
        assert len(row["projection"]["items"])==20
        assert all(stmt["plan"] for stmt in row["statements"])
        if row["profile"] in ("REVIEW_PUBLIC","REVIEW_NEXT"):
            assert "idx_case_review_queue" in str(row["statements"][1]["plan"])
    return {"functional_rows":16,"conditions":["B cache on lock off","C cache on lock on"],"business_load_windows":windows,
        "limiter_windows":3,"limited_requests":36,"allowed_window_requests":36,"downstream_http_calls_including_other_account_controls":38,
        "workspace_cases":20000,"workspace_profiles":7,"workspace_statements_per_page":3,"model_requests":0,
        "boundary":"development functional evidence, not formal R120 or HTTP p95; business-load windows include explicit post-query gates; Redis failure allows bounded fallback overlap"}


if __name__=="__main__":
    result=audit(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("xb") as output:output.write((json.dumps(result,indent=2)+"\n").encode())
    print(json.dumps(result))
