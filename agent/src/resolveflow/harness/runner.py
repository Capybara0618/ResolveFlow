"""AS02.2: `runner` is now a **name**, not a loop.

C06.4 put two things in this file: the vocabulary a run is described in, and a self-written ``while`` loop that
drove one. AS02.2 moved both — the vocabulary to :mod:`resolveflow.harness.vocabulary` (because it is the interface
everything else reads) and the loop to AgentScope, assembled in :mod:`resolveflow.harness.sdk_runner`.

The reason this file still exists, and still exports the same names, is that removing it would mean touching every
importer for no benefit — and, more to the point, **its emptiness is the evidence**:
`docs/agentscope-migration.md:34` requires exactly one production loop, and after AS02.2 there is exactly one. If
someone reintroduces a ``while`` here, this docstring is what says that is a regression rather than a refactor.

What is deliberately **not** kept: ``HarnessRunner``. A compatibility alias would let new code depend on a driver
that no longer exists, and the honest thing is for an import of it to fail loudly. Callers and tests use
:class:`~resolveflow.harness.sdk_runner.AgentScopeRunner`.
"""

from __future__ import annotations

from resolveflow.harness.vocabulary import (
    HARNESS_SYSTEM_PROMPT,
    REASON_ACTION_REFUSED,
    REASON_COMPLETED,
    REASON_TOOL_CALLS_EXHAUSTED,
    REASON_TOOL_FAILED,
    RunFacts,
    RunResult,
    ToolExecutor,
)

__all__ = [
    "HARNESS_SYSTEM_PROMPT",
    "REASON_ACTION_REFUSED",
    "REASON_COMPLETED",
    "REASON_TOOL_CALLS_EXHAUSTED",
    "REASON_TOOL_FAILED",
    "RunFacts",
    "RunResult",
    "ToolExecutor",
]
