"""Offline GPU worker for an existing CUDA Python environment; JSON lines over local stdio only."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from importlib.metadata import version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    started = time.perf_counter()
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required; no CPU fallback")
    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model, local_files_only=True)
    model = model.to(device="cuda:0", dtype=torch.float32).eval()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    environment = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "transformers": version("transformers"),
        "device": str(next(model.parameters()).device),
        "dtype": str(next(model.parameters()).dtype),
        "cuda_build": torch.version.cuda,
        "gpu_name": torch.cuda.get_device_name(0),
        "gpu_capability": list(torch.cuda.get_device_capability(0)),
        "threads": torch.get_num_threads(),
        "synchronized_timing": True,
        "tf32": False,
        "activation": "sigmoid-single-logit",
    }
    print(
        json.dumps(
            {
                "ready": True,
                "environment": environment,
                "model_load_including_import_ms": (time.perf_counter() - started) * 1000,
            }
        ),
        flush=True,
    )
    for line in sys.stdin:
        request = json.loads(line)
        method = request["method"]
        if method == "close":
            break
        if method == "synchronize":
            torch.cuda.synchronize()
            response = {"ok": True}
        elif method == "stats":
            response = {
                **environment,
                "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
                "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            }
        elif method == "predict":
            pairs = request["pairs"]
            lengths = [len(tokenizer(a, b, truncation=False)["input_ids"]) for a, b in pairs]
            if any(n > 512 for n in lengths):
                raise ValueError("pair exceeds fixed encoder window")
            torch.cuda.synchronize()
            started = time.perf_counter()
            scores = []
            with torch.inference_mode():
                for i in range(0, len(pairs), 8):
                    part = pairs[i : i + 8]
                    inputs = tokenizer(
                        [p[0] for p in part], [p[1] for p in part], padding=True, truncation=False, return_tensors="pt"
                    ).to("cuda:0")
                    logits = model(**inputs).logits
                    if logits.ndim != 2 or logits.shape[1] != 1:
                        raise ValueError("expected a single relevance logit")
                    scores.extend(torch.sigmoid(logits[:, 0]).cpu().tolist())
            torch.cuda.synchronize()
            response = {"scores": scores, "gpu_predict_ms": (time.perf_counter() - started) * 1000}
        else:
            raise ValueError("unknown offline method")
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
