"""The live model client: one provider request per decision (C08.1b-2).

``docs/agent-spec.md:40`` allows at most one model retry and requires **every attempt to be counted**; the budget in
:mod:`resolveflow.harness.budget` is what counts them. That is why this client has no retry loop at all: an internal
retry would be a provider call nothing reserved, and ``docs/agent-harness.md:39``'s "调用前预占" would stop
describing what was actually spent. A caller that wants the one allowed retry asks again — through the layer that
charges for it.

Four rules are enforced here rather than left to a provider's goodwill:

* **The ceiling is mandatory.** :meth:`LiveModelClient.decide` refuses a call with no ``max_output_tokens`` instead
  of sending an uncapped request: output that was never reserved cannot be charged, and
  ``docs/agent-harness.md:39``'s 额度为0不得调用 is the same rule seen from the other side.
* **One attempt.** A 4xx is a refusal (the run stops, ``docs/agent-spec.md:36``'s FORBIDDEN discipline), a 5xx or a
  timeout is an outage for the caller to retry. Both are raised after exactly one transmission.
* **Missing usage is ESTIMATED, never zero.** ``docs/agent-spec.md:44``: 缺provider准确计数时标ESTIMATED. A silent
  zero refunds the output reservation, so an absent ``usage`` block is estimated from the text actually sent and
  received, using the same counter the manifest pins.
* **The credential is not recorded.** The key travels in a header; the record keeps the body, its canonical hash, the
  status, the usage and the mode — never the secret (``docs/agent-harness.md:33``: 不存密钥).

Non-JSON assistant text is retained in an inert response record, not interpreted
into an action. Usage is settled normally. The domain action gate owns the single
correction opportunity and its persisted reconstruction (docs/harness-correction-loop.md).

Not yet part of this: a test that talks to a real provider. Any such sample spends money and needs the user's
agreement (``tasks/handoff-current.md`` §2), so the offline capture tests are what this slice delivers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeGuard

from resolveflow.harness.context import canonical_json, estimate_tokens, hash_document
from resolveflow.harness.model import MODEL_MODE_LIVE, ModelReply, ModelUsage

if TYPE_CHECKING:
    from agentscope.message import Msg as Message

__all__ = [
    "HttpResponse",
    "LiveModelClient",
    "ModelRefusedError",
    "ModelUnavailableError",
    "Transport",
]


class ModelRefusedError(Exception):
    """The provider refused this request and would refuse it again.

    A 4xx cannot be corrected by changing the model's JSON output.
    """


class ModelUnavailableError(Exception):
    """The decision did not happen for a reason a later attempt can change.

    A 5xx, a timeout, a connection failure, or a 200 with nothing readable in it. The attempt was still made and
    still counted; whether to spend another one is the budget's decision, not this client's.
    """


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """What a transport hands back: a status and a body, nothing provider-specific."""

    status: int
    body: bytes


#: The whole network surface, injectable so a test can capture a request without opening a socket.
Transport = Callable[[str, bytes, dict[str, str], float], HttpResponse]


@dataclass(slots=True)
class LiveModelClient:
    """A model reached over HTTP, satisfying :class:`~resolveflow.harness.model.ModelClient`.

    ``provider``/``model_id``/``parameters`` are declared rather than discovered because the frozen manifest records
    them (``docs/agent-harness.md:33``: 参数只记录实际发送值) — what is declared here is what goes on the wire and
    what the manifest pins.
    """

    endpoint: str
    model_id: str
    provider: str = "openai-compatible"
    #: The credential **value**. Kept so it can be sent; never written to a record.
    api_key: str = ""
    #: Sent verbatim as top-level request members. The ceiling is applied after these, so a declared parameter can
    #: never widen it.
    parameters: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    #: The provider's own name for the ceiling. Configurable because the compatible endpoints disagree about it;
    #: whatever is used ends up in the recorded body, so the choice is auditable rather than implicit.
    ceiling_parameter: str = "max_tokens"
    transport: Transport | None = None
    #: ``docs/core-scope.md`` keeps mock and live results distinguishable after the fact.
    mode: str = MODEL_MODE_LIVE
    model_alias: str | None = None
    #: One entry per attempt: the request that was sent (credential-free), its hash, the status and the usage.
    requests: list[dict[str, Any]] = field(default_factory=list)
    #: How many provider calls this client has made. Equal to ``len(requests)``; stated separately because "how many
    #: calls did we spend" is the question a budget asks.
    calls: int = 0

    def prepare_request(self, *, system: str, messages: list[Message], max_output_tokens: int) -> dict[str, Any]:
        """Exact credential-free provider body, available before transmission for durable reservation."""
        return self._body(system=system, messages=messages, max_output_tokens=max_output_tokens)

    def decide(
        self,
        *,
        system: str,
        messages: list[Message],
        context: dict[str, Any] | None = None,
        sent_context: Any = None,
        max_output_tokens: int | None = None,
    ) -> ModelReply:
        if max_output_tokens is None or max_output_tokens <= 0:
            raise ValueError(
                "a live model call needs the harness's reserved max_output_tokens ceiling; sending an uncapped "
                "request would spend output that no reservation covers"
            )

        body = self._body(system=system, messages=messages, max_output_tokens=max_output_tokens)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self.calls += 1
        try:
            response = self._send(payload, headers)
        except ModelUnavailableError as outage:
            # A failed attempt is still an attempt: it is recorded so ``calls`` and ``requests`` agree, and so a run
            # that spent a call on a timeout can show where the call went.
            self._record(body=body, status=None, failure=str(outage))
            raise
        self._record(body=body, status=response.status)

        if 400 <= response.status < 500:
            raise ModelRefusedError(
                f"the provider refused the request ({response.status}): {_snippet(response.body)}"
            )
        if not 200 <= response.status < 300:
            raise ModelUnavailableError(
                f"the provider answered {response.status}: {_snippet(response.body)}"
            )

        answered = _envelope_of(response.body)
        content = _content_of(answered)
        decision = _decision_of(content)
        usage = _usage_of(answered, request_text=canonical_json(body), answer_text=content)
        served = answered.get("model") if isinstance(answered, Mapping) else None
        return ModelReply(
            decision=decision,
            usage=usage,
            mode=self.mode,
            model_alias=(served if isinstance(served, str) and served else (self.model_alias or self.model_id)),
        )

    def _send(self, payload: bytes, headers: dict[str, str]) -> HttpResponse:
        """Exactly one transmission. Every failure path of this method is an attempt that happened."""
        transport = self.transport or _urllib_transport
        try:
            return transport(self.endpoint, payload, headers, self.timeout_seconds)
        except TimeoutError as error:
            raise ModelUnavailableError(f"the provider timed out: {error}") from error
        except OSError as error:
            raise ModelUnavailableError(f"the provider could not be reached: {error}") from error

    def _body(self, *, system: str, messages: list[Message], max_output_tokens: int) -> dict[str, Any]:
        """The provider request.

        Declared parameters first and the ceiling **after** them, so a configured ``max_tokens`` cannot widen what
        the harness reserved. An empty ``system`` adds nothing: ``ModelClient`` states that it means P0 already
        carries the prompt, and a second system message would send the prompt twice.
        """
        rendered: list[dict[str, str]] = []
        if system:
            rendered.append({"role": "system", "content": system})
        for message in messages:
            rendered.append({"role": str(message.role), "content": _text_of(message)})
        body: dict[str, Any] = dict(self.parameters)
        body["model"] = self.model_id
        body["messages"] = rendered
        body[self.ceiling_parameter] = int(max_output_tokens)
        return body

    def _record(self, *, body: Mapping[str, Any], status: int | None, failure: str | None = None) -> None:
        """Keep the request, not the credential.

        The body cannot contain the key by construction — it travels in a header — and no header is recorded, so the
        record is credential-free without a redaction pass that could miss a case.
        """
        self.requests.append(
            {
                "url": self.endpoint,
                "provider": self.provider,
                "model_id": self.model_id,
                "body": dict(body),
                "body_hash": hash_document(dict(body)),
                "authenticated": bool(self.api_key),
                "status": status,
                "failure": failure,
                "mode": self.mode,
                "attempts": 1,
            }
        )


def _default_transport(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - the endpoint is configuration, not user input


def _urllib_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> HttpResponse:
    """The real transport. A refusal is returned rather than raised so the caller classifies it once."""
    # S310 audits both the Request and the open call; the scheme comes from configured endpoint, not from input.
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        response = _default_transport(request, timeout)
        try:
            return HttpResponse(status=int(response.status), body=response.read())
        finally:
            response.close()
    except urllib.error.HTTPError as error:
        return HttpResponse(status=int(error.code), body=error.read())


def _text_of(message: Message) -> str:
    """The text blocks of one provider-agnostic turn, joined.

    Only text blocks: AgentScope attaches its own hint and tool blocks, and forwarding those as prose would send a
    provider the SDK's bookkeeping as if the model had said it.
    """
    from agentscope.message import TextBlock

    return "\n".join(block.text for block in message.get_content_blocks() if isinstance(block, TextBlock))


def _envelope_of(raw: bytes) -> dict[str, Any]:
    """The provider's JSON envelope, or an outage.

    An unreadable 200 is an outage rather than a refusal: nothing about the request said "do not try this again", and
    the retry decision belongs to the caller.
    """
    try:
        parsed = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as error:
        raise ModelUnavailableError(f"the provider answered 200 with unreadable JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ModelUnavailableError("the provider answered 200 with something that is not an object")
    return parsed


def _content_of(envelope: Mapping[str, Any]) -> str:
    """The assistant's text out of an OpenAI-shaped envelope."""
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelUnavailableError("the provider answered 200 without a completion to read")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else None
    content = message.get("content") if isinstance(message, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise ModelUnavailableError("the provider answered 200 without assistant content")
    return content


def _decision_of(text: str) -> dict[str, Any]:
    """The decision object, extracted leniently about packaging and strictly about content.

    A provider habitually wraps JSON in a code fence or a sentence, so the packaging is tolerated. Anything that is
    not a JSON object becomes an inert durable record: no action is guessed from prose.
    The action gate supplies bounded correction feedback after usage is settled.
    """
    candidate = _unfenced(text)
    parsed = _loads(candidate)
    if parsed is None:
        parsed = _first_object(candidate)
    if not isinstance(parsed, dict):
        # Inert, durable transport record. The action gate rejects it and owns the
        # single correction opportunity. No action is guessed from the raw text.
        return {"kind": "__INVALID_MODEL_JSON__", "raw_output": text}
    return parsed


def _unfenced(text: str) -> str:
    candidate = text.strip()
    if not candidate.startswith("```"):
        return candidate
    lines = candidate.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _first_object(text: str) -> Any:
    """The first balanced ``{...}`` span, so an answer with prose around it still yields its decision."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            character = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    parsed = _loads(text[start : index + 1])
                    if parsed is not None:
                        return parsed
                    break
        start = text.find("{", start + 1)
    return None


def _usage_of(envelope: Mapping[str, Any], *, request_text: str, answer_text: str) -> ModelUsage:
    """The provider's counts when it reports them, otherwise an ESTIMATED pair that is never zero.

    ``docs/agent-spec.md:44``: 缺provider准确计数时标ESTIMATED, and the budget must not refund a reservation on a
    zero it was handed. Estimating from the text that actually crossed the wire is the conservative direction
    ``docs/agent-harness.md:37`` asks for (未知token/计费保守估计).
    """
    block = envelope.get("usage")
    if isinstance(block, Mapping):
        prompt = block.get("prompt_tokens")
        completion = block.get("completion_tokens")
        if _is_count(prompt) and _is_count(completion):
            return ModelUsage(input_tokens=int(prompt), output_tokens=int(completion), estimated=False)
    return ModelUsage(
        input_tokens=estimate_tokens(request_text),
        output_tokens=estimate_tokens(answer_text),
        estimated=True,
    )


def _is_count(value: Any) -> TypeGuard[int]:
    """Narrowing rather than a bare ``bool``, so the caller can use the value it just validated as an ``int``."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _snippet(body: bytes) -> str:
    return body.decode("utf-8", "replace")[:400]
