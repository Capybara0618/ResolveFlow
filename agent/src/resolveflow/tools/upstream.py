"""The upstream the five tools read from, and the rules for turning answers into observations (C06.2b).

Every tool is a read of an internal route of Case or Commerce (``docs/agent-spec.md:26-32``). This module is
the one place those reads happen, so the rules that apply to **all five** are stated once instead of five times:

- **a refusal is never retried with another id.** ``docs/agent-spec.md:36``: FORBIDDEN 停止，不更换ID重试.
  A refusal is a decision about *who is asking*, and asking again with a different identifier is how a scoped
  read becomes an unscoped one.
- **NOT_FOUND is a failed observation, not a negative fact.** "There is no shipment" is a claim about the
  world; "I could not read a shipment" is what actually happened. Only the second is true, and only the second
  may be recorded — a decision built on the first would be built on something nobody observed.
- **an oversized body is refused, not truncated.** ``docs/agent-spec.md:36``: 原始响应<=256KiB；过大返回明确
  错误并分页. Truncating would hand the model a document that looks complete and is not, and every hash
  computed from it would be a hash of the wrong bytes.
- **the body that is kept is the body that was hashed.** ``content_hash`` is computed from exactly the bytes
  that are stored, so a citation's hash can be re-checked later (``docs/agent-spec.md:52``).

The body limit is applied **while reading**, not after: a ``Content-Length`` can lie or be absent, so the
response is read in bounded chunks and abandoned the moment it exceeds the limit. Checking a header would be a
check on a claim rather than on the bytes.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "MAX_EXCERPT_BYTES",
    "MAX_RAW_BYTES",
    "TOOL_CREDENTIAL_ENV",
    "UpstreamAnswer",
    "UpstreamClient",
    "UpstreamRefusedError",
    "UpstreamUnavailableError",
]

#: ``docs/agent-spec.md:36``: 原始响应<=256KiB.
MAX_RAW_BYTES: Final = 256 * 1024

#: ``docs/agent-spec.md:36``: 给模型的excerpt<=8KiB. The tool result that reaches the model is capped at this;
#: the raw body above is what is stored and hashed.
MAX_EXCERPT_BYTES: Final = 8 * 1024

#: The environment variable a deployment uses to name the credential the tools present. The run-scoped
#: credential route (``POST /internal/v1/runs/{run_id}/tool-credential``) is what a later step mints one from;
#: until then this is how the tools are told who they are, and the tests set it too. The value is a variable
#: *name* on purpose: no credential is written down here, so nothing in this file can leak one.
TOOL_CREDENTIAL_ENV: Final = "RESOLVEFLOW_TOOL_SERVICE_TOKEN"


@dataclass(slots=True)
class UpstreamAnswer:
    """One read that produced bytes: the decoded body and the hash of the bytes it came from."""

    status: int
    body: dict[str, Any]
    raw: bytes

    @property
    def content_hash(self) -> str:
        """sha256 of the exact bytes stored, so a citation can be re-checked later."""
        return hashlib.sha256(self.raw).hexdigest()


class UpstreamRefusedError(Exception):
    """The upstream answered with a status that says the request itself was wrong to make.

    ``status`` is carried so the caller can tell "you may not read this" (403) from "this path is not what you
    think" (404) — the two become different observation codes, and only one of them is a stop.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class UpstreamUnavailableError(Exception):
    """The upstream could not be reached, or answered in a way that might differ next time."""


@dataclass(slots=True)
class UpstreamClient:
    """Reads internal routes. One instance per process; the transport is injectable for tests.

    ``get`` is injected rather than hard-wired so the rules above are testable without a server, the same way
    ``CallbackDelivery`` takes its transport.
    """

    case_base_url: str
    commerce_base_url: str
    service_token: str | None = None
    timeout_seconds: float = 5.0
    _get: Any = field(default=None, repr=False)

    def url(self, service: str, path: str, query: dict[str, Any] | None = None) -> str:
        base = self.case_base_url if service == "case" else self.commerce_base_url
        url = f"{base.rstrip('/')}{path}"
        clean = {key: value for key, value in (query or {}).items() if value is not None}
        return f"{url}?{urllib.parse.urlencode(clean)}" if clean else url

    def read(self, service: str, path: str, query: dict[str, Any] | None = None) -> UpstreamAnswer:
        """Read one route, or say why the read did not happen.

        Raises :class:`UpstreamRefusedError` for a status that will not change (401/403/404 and any other 4xx),
        and :class:`UpstreamUnavailableError` for anything that might: a 5xx, a timeout, a connection that never
        opened, or a body over the limit. The caller turns those into observation codes.
        """
        url = self.url(service, path, query)
        request = urllib.request.Request(url, method="GET")  # noqa: S310 - the base URL is ours, not the model's
        request.add_header("Accept", "application/json")
        token = self.service_token
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            if self._get is not None:
                status, raw = self._get(request)
            else:
                status, raw = _read_bounded(request, self.timeout_seconds)
        except urllib.error.HTTPError as error:
            # An HTTPError body is still a body; read a bounded amount of it so the message can be useful
            # without letting a hostile upstream fill memory through an error path.
            detail = _safe_detail(error)
            if 400 <= error.code < 500:
                raise UpstreamRefusedError(error.code, detail) from error
            raise UpstreamUnavailableError(f"{error.code} from {path}: {detail}") from error
        except TimeoutError as error:
            raise UpstreamUnavailableError(f"timed out reading {path}") from error
        except urllib.error.URLError as error:
            raise UpstreamUnavailableError(f"could not reach {path}: {error.reason}") from error
        except OSError as error:  # a truncated response, a closed socket, a DNS failure already wrapped above
            raise UpstreamUnavailableError(f"could not read {path}: {error}") from error

        if status != 200:
            if 400 <= status < 500:
                raise UpstreamRefusedError(status, f"{status} from {path}")
            raise UpstreamUnavailableError(f"{status} from {path}")
        if len(raw) > MAX_RAW_BYTES:
            msg = f"the response for {path} is {len(raw)} bytes, over the {MAX_RAW_BYTES}-byte limit"
            raise UpstreamUnavailableError(msg)
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise UpstreamUnavailableError(f"{path} did not answer with JSON") from error
        if not isinstance(body, dict):
            raise UpstreamUnavailableError(f"{path} answered with {type(body).__name__}, not an object")
        return UpstreamAnswer(status=status, body=body, raw=raw)


def _read_bounded(request: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    """Read a response, giving up as soon as it exceeds the limit rather than after buffering it all."""
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - our own base URL
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(min(64 * 1024, MAX_RAW_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_RAW_BYTES:
                # Over the limit: stop reading instead of holding the whole body. The caller refuses it.
                return response.status, b"".join(chunks)
        return response.status, b"".join(chunks)


def _safe_detail(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read(2048)
    except Exception:  # noqa: BLE001 - the failure being described is more useful than this one
        return f"HTTP {error.code}"
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return f"HTTP {error.code}"
    if isinstance(parsed, dict):
        for member in ("message", "detail", "error"):
            value = parsed.get(member)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    return f"HTTP {error.code}"