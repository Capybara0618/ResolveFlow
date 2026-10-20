"""Application-owned weights only; runs still own credentials, generation pins and observations."""

from __future__ import annotations

import threading

from resolveflow.policies.retrieval import Embedder, embedder


class SupportEmbeddings:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: str | None = None
        self._encoder: Embedder | None = None

    def get(self, local_path: str | None) -> Embedder:
        with self._lock:
            if self._encoder is None or self._path != local_path:
                encoder = embedder(local_path=local_path)
                self._path, self._encoder = local_path, encoder
            return self._encoder

    def clear(self) -> None:
        with self._lock:
            self._encoder = None
            self._path = None
