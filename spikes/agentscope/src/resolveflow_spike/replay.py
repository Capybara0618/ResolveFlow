"""AS01.3: a strict replay adapter — the same SDK loop, driven entirely by recorded results.

`docs/agentscope-migration.md:78` says what strict replay is here, and what it is *not*:

* the **same** AgentScope + Harness execution logic runs, but the model, the tools, the Clock, the storage and the
  callback sink are all replaced by recorded/local isolated adapters;
* it is **not** a separate player that prints the expected answer — a replayer that emitted the recorded final
  state would prove nothing about the code that would run for real;
* missing records fail explicitly; Python socket/asyncio connection entries are blocked during the probe.
  This is not OS isolation: native clients, subprocesses, existing connections and business-write capability
  isolation still require the production C10 sandbox and adversarial tests.

**The record format.** One pack is one run: the model's responses in order, and the observations its tool calls
produced. Nothing else. It carries no expected final answer, deliberately — the replay re-derives the trajectory
by running the loop, and the test compares what the loop did against what was recorded *during* it. A pack that
contained "the answer" would let the test pass by printing it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
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


@contextmanager
def block_network() -> Iterator[list[str]]:
    """Deny Python socket/asyncio egress during this isolated replay, then restore.

    Enter AFTER the event loop has been initialized (Windows uses socketpair at startup).
    This is a regression guard, not an OS sandbox: native extensions, subprocesses and
    already-connected transports require C10's credential-free, network-isolated process.
    """
    import asyncio
    import socket
    from contextlib import ExitStack
    from unittest.mock import patch

    attempts: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        attempts.append(repr((args, kwargs)))
        raise OSError("AS01.3 strict replay forbids network access")

    with ExitStack() as stack:
        for target, names in (
            (socket, ("create_connection", "getaddrinfo")),
            (socket.socket, ("connect", "connect_ex", "sendto")),
            (asyncio.BaseEventLoop, ("create_connection", "sock_connect", "create_datagram_endpoint")),
        ):
            for name in names:
                stack.enter_context(patch.object(target, name, refuse))
        yield attempts
