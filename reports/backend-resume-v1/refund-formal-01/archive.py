"""Archive only formal structured evidence and verify every archived byte."""

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(raw, target):
    files = sorted(p for d in raw.glob("refund-formal-*") for p in d.rglob("*") if p.is_file())
    files += [raw / "refund-formal-final-database.json"]
    assert files and all(p.suffix in (".json", ".jsonl", ".py", ".java", ".md") for p in files)
    assert not (target / "evidence.tar.xz").exists()
    hashes = {}
    with tarfile.open(target / "evidence.tar.xz", "x:xz") as output:
        for path in files:
            name = path.relative_to(raw).as_posix()
            data = path.read_bytes()
            hashes[name] = sha(data)
            member = tarfile.TarInfo(name)
            member.size, member.mtime, member.mode = len(data), 0, 0o644
            output.addfile(member, io.BytesIO(data))
    with tarfile.open(target / "evidence.tar.xz", "r:xz") as source:
        assert set(source.getnames()) == set(hashes)
        for name, digest in hashes.items():
            assert sha(source.extractfile(name).read()) == digest
    result = {"raw_directory": str(raw), "files": hashes, "file_count": len(hashes),
              "archive_sha256": sha((target / "evidence.tar.xz").read_bytes()),
              "boundary": "structured synthetic evidence only; no database snapshots or raw process logs"}
    with (target / "archive-index.json").open("xb") as output:
        output.write((json.dumps(result, indent=2) + "\n").encode())
    print("verified archive:", len(hashes), "files")


if __name__ == "__main__":
    archive(Path(sys.argv[1]), Path(sys.argv[2]))
