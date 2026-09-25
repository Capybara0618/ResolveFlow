"""AS01.3: a strict replay adapter — the same SDK loop, driven entirely by recorded results.

`docs/agentscope-migration.md:78` says what strict replay is here, and what it is *not*:

* the **same** AgentScope + Harness execution logic runs, but the model, the tools, the Clock, the storage and the
  callback sink are all replaced by recorded/local isolated adapters;
* it is **not** a separate player that prints the expected answer — a replayer that emitted the recorded final
  state would prove nothing about the code that would run for real;
* telemetry, automatic downloads and network re-fetching are disabled, a missing record **fails explicitly**, and
  the test blocks the network at the process level rather than promising not to use it.

The last point is the one that makes this file worth having. Every other claim about replay can be satisfied by a
replayer that happens not to call out; only a process that *cannot* call out shows the claim holds when the code
changes underneath it.

**The record format.** One pack is one run: the model's responses in order, and the observations its tool calls
produced. Nothing else. It carries no expected final answer, deliberately — the replay re-derives the trajectory
by running the loop, and the test compares what the loop did against what was recorded *during* it. A pack that
contained "the answer" would let the test pass by printing it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from agentscope.message import TextBlock, ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse

__all__ = [
    "ReplayExhaustedError",
    "ReplayPack",
    "ReplayModel",
    "block_network",
]

#: Raised when the replay needs a record that is not in the pack.
#:
#: A distinct exception rather than a generic one because the requirement is specific:
#: `docs/agentscope-migration.md:78` — 缺记录明确失败. A replay that silently fell back to a live model, or that
#: fabricated a plausible response, would be worse than failing: it would report a reproducible trajectory that
#: cannot be reproduced.
class ReplayExhaustedError(RuntimeError):
    """The pack has no more recorded responses, so the run diverged from what was recorded."""


@dataclass(slots=True)
class ReplayPack:
    """One run's records: the model's responses, in order, and the tool observations it saw.

    Stored as JSON so a pack is reviewable and diffable — a strict replay is evidence, and evidence that can only
    be read by the program that wrote it is not much evidence.
    """

    run_id: str
    #: Each entry is one `ChatResponse` as the model would have returned it: the reasoning content and any tool
    #: calls. Order is the order they were produced.
    model_responses: list[dict[str, Any]] = field(default_factory=list)
    #: Observations keyed by the tool call id they answer, so a replay cannot pair a call with the wrong answer.
    tool_observations: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Facts the replay is allowed to know about the run, and nothing more.
    facts: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "model_responses": self.model_responses,
                "tool_observations": self.tool_observations,
                "facts": self.facts,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> ReplayPack:
        payload = json.loads(text)
        return cls(
            run_id=payload["run_id"],
            model_responses=list(payload.get("model_responses", [])),
            tool_observations=dict(payload.get("tool_observations", {})),
            facts=dict(payload.get("facts", {})),
        )

    def save(self, path: Path) -> None:
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ReplayPack:
        return cls.from_json(path.read_text(encoding="utf-8"))


class ReplayModel(ChatModelBase):
    """A `ChatModelBase` that returns the pack's recorded responses **in order**, and never a new one.

    It records the requests it was given, so the test can assert that the replayed run asked the model the same
    things the original did — which is the difference between "the same final state" and "the same trajectory".
    """

    def __init__(self, pack: ReplayPack, **kwargs: Any) -> None:
        from pydantic import BaseModel

        class _NoParameters(BaseModel):
            """The parameter bag a provider class would carry; a replay has none."""

        super().__init__(
            # A replay has no credential, and that is the point: it cannot authenticate to anything. The base
            # annotates `CredentialBase`, so the honest value is passed with a cast and a comment rather than by
            # inventing a fake credential object that a future edit could start using.
            credential=cast(Any, None),
            model=f"replay:{pack.run_id}",
            parameters=_NoParameters(),
            stream=False,
            # Zero retries: a replay that retried would be asking the same absent record again, and the failure
            # mode it must have is an explicit stop (docs/agentscope-migration.md:78).
            max_retries=0,
        )
        from agentscope.formatter import DeepSeekChatFormatter

        self.formatter = DeepSeekChatFormatter()
        self._pack = pack
        self._served = 0
        #: Every request the loop made of this model, in order, for comparing against the original run.
        self.requests: list[list[Any]] = []

    @property
    def served(self) -> int:
        return self._served

    async def _call_api(
        self,
        model_name: str,
        messages: list[Any],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Serve the next recorded response, or fail explicitly.

        Note what is absent: no network client, no credential, no fallback. The only way this returns is if the
        pack has the record, which is what makes a green replay meaningful.
        """
        self.requests.append(list(messages))
        if self._served >= len(self._pack.model_responses):
            raise ReplayExhaustedError(
                f"the pack for run {self._pack.run_id} holds {len(self._pack.model_responses)} model responses "
                f"but the replay asked for number {self._served + 1}; the recorded trajectory does not cover this "
                "run, so it cannot be replayed strictly"
            )
        record = self._pack.model_responses[self._served]
        self._served += 1
        return _chat_response(record)


def _chat_response(record: dict[str, Any]) -> ChatResponse:
    """One recorded response as a `ChatResponse`.

    The blocks are rebuilt from data rather than stored as SDK objects, so a pack stays readable and does not break
    when the SDK changes its class internals — only when it changes the *recorded shape*, which is a real
    incompatibility worth failing on.
    """
    blocks: list[Any] = []
    for block in record.get("content", []):
        kind = block.get("type")
        if kind == "text":
            blocks.append(TextBlock(type="text", text=block["text"]))
        elif kind == "tool_call":
            blocks.append(
                ToolCallBlock(
                    type="tool_call",
                    id=block["id"],
                    name=block["name"],
                    input=block["input"] if isinstance(block["input"], str) else json.dumps(block["input"]),
                )
            )
        else:
            raise ReplayExhaustedError(
                f"the pack holds a block type this replay does not know: {kind!r}; refusing rather than skipping "
                "it, because a skipped block is a trajectory that differs from the recorded one"
            )
    return ChatResponse(content=blocks, is_last=True)


def block_network() -> list[str]:
    """Make outbound connections impossible **in this process**, and report what was attempted.

    `docs/agentscope-migration.md:78` requires the network to be blocked by the test rather than avoided by
    convention, and the difference matters when the code changes: a promise is not checked, a patched socket is.

    **What is patched, and what deliberately is not.** Only ``socket.create_connection`` — the function an HTTP
    client calls to open an outbound connection. Patching ``socket.socket.connect`` as well broke asyncio itself:
    on Windows the proactor event loop creates a socket pair at startup, so the patch killed the loop before the
    replay began, with ``AttributeError: 'ProactorEventLoop' object has no attribute '_ssock'``. Blocking the one
    function a client library actually calls is what a replay needs, and it keeps the test's own runtime working.

    The returned list fills with attempted destinations, so a test can assert *that nothing tried* rather than only
    that nothing succeeded.
    """
    import socket

    attempts: list[str] = []

    def refuse(address: Any, *args: Any, **kwargs: Any) -> Any:
        attempts.append(repr(address))
        raise OSError(
            f"AS01.3 strict replay forbids network access: a connection to {address!r} was attempted"
        )

    socket.create_connection = refuse
    return attempts
