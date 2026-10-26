"""Reject corrupted D4 claims in memory while preserving archived evidence."""
import copy
import sys
from pathlib import Path

import audit as checker


def verify(raw):
    saved=checker.read
    mutations=[]
    for kind in ("unbounded fallback","limiter over-admission","cross-owner unlock"):
        def altered(path,kind=kind):
            data=copy.deepcopy(saved(path))
            if path.parent.name=="d4-dual-faults-02" and path.name=="summary.json":
                if kind=="unbounded fallback":data["rows"][0]["metrics_a"]["resolveflow.product_reviews.database.peak[]:VALUE"]=9
                if kind=="cross-owner unlock":
                    next(r for r in data["rows"] if r["condition"]=="C" and r["scenario"]=="R04")["new_owner_lock_after_old_return"]="0"
            if path.parent.name=="d4-limiter-01" and path.name=="summary.json" and kind=="limiter over-admission":
                next(r for r in data["windows"][0]["write"] if r["status"]==429)["status"]=200
            return data
        checker.read=altered
        try:checker.audit(raw)
        except AssertionError:mutations.append(kind)
        else:raise AssertionError("accepted corrupted claim: "+kind)
        finally:checker.read=saved
    assert len(mutations)==3
    return {"rejected_mutations":mutations,"changed_files":0,"network_requests":0}


if __name__=="__main__":
    import json
    with Path(sys.argv[2]).open("xb")as output:output.write((json.dumps(verify(Path(sys.argv[1])),indent=2)+"\n").encode())
