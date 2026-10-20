"""Keep the project's pinned evaluation environment separate from an existing CUDA interpreter."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
from pathlib import Path


class GPUWorker:
    def __init__(self, python: Path, model: Path, log: Path):
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(str(model), local_files_only=True)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log = log.open("x", encoding="utf-8")
        self.process = subprocess.Popen(  # noqa: S603 - explicit local interpreter, fixed repo worker and arguments
            [str(python), "-u", str(Path(__file__).with_name("customer_rerank_gpu_worker.py")), "--model", str(model)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert self.process.stdout is not None
        atexit.register(self.close)
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("GPU worker failed to initialize; inspect its local stderr log")
        self.ready = json.loads(line)
        self.gpu_predict_ms = 0.0

    def request(self, method, **arguments):
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps({"method": method, **arguments}, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("GPU worker ended without a complete response")
        return json.loads(line)

    def synchronize(self):
        self.request("synchronize")

    def predict(self, pairs, **kwargs):
        if kwargs != {"batch_size": 8, "show_progress_bar": False}:
            raise ValueError("experiment inference settings differ")
        response = self.request("predict", pairs=pairs)
        self.gpu_predict_ms = response["gpu_predict_ms"]
        return response["scores"]

    def close(self):
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.write('{"method":"close"}\n')
            self.process.stdin.flush()
            self.process.wait(timeout=30)
        self.log.close()
