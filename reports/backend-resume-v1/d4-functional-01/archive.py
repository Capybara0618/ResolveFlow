"""Archive structured synthetic D4 records, preserving byte hashes without raw JVM logs or databases."""
import hashlib
import io
import json
import sys
import tarfile
import tempfile
from pathlib import Path

from audit import audit


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(raw,target):
    paths=sorted(p for p in raw.rglob("*") if p.is_file())
    assert paths and all(p.suffix in (".json",".jsonl",".java",".yml",".yaml",".xml",".ready",".entered",".release") for p in paths)
    hashes={}
    with tarfile.open(target/"evidence.tar.xz","x:xz") as output:
        for path in paths:
            name=path.relative_to(raw).as_posix();data=path.read_bytes();hashes[name]=sha(data)
            member=tarfile.TarInfo(name);member.size=len(data);member.mtime=0;member.mode=0o644
            output.addfile(member,io.BytesIO(data))
    extracted=Path(tempfile.mkdtemp(prefix="d4-evidence-roundtrip-",dir="tmp"))
    with tarfile.open(target/"evidence.tar.xz","r:xz") as source:
        assert set(source.getnames())==set(hashes)
        for name,digest in hashes.items():assert sha(source.extractfile(name).read())==digest
        source.extractall(extracted,filter="data")
    assert json.loads(json.dumps(audit(extracted)))==json.loads((target/"summary.json").read_text(encoding="utf-8"))
    result={"files":hashes,"file_count":len(hashes),"archive_sha256":sha((target/"evidence.tar.xz").read_bytes()),"extracted_offline_audit_identical":True}
    with(target/"archive-index.json").open("xb")as output:output.write((json.dumps(result,indent=2)+"\n").encode())
    print("archived and independently verified",len(hashes),"structured files")


if __name__=="__main__":
    archive(Path(sys.argv[1]),Path(sys.argv[2]))
