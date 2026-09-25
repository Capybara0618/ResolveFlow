"""AS01.1: our hard constraints as AgentScope middleware, over the existing guards.

The migration's load-bearing question is not "does AgentScope have a loop" — it plainly does — but **can our
constraints be placed where no model or tool call can get past them**. `docs/agentscope-migration.md:47` requires
an "actual API → interception point → test" table, and `:50` requires each model request to check run/fence/
deadline and count the attempt *before* it is made, counting the final system prompt, messages and tool schemas
rather than only a new packet.

Nothing here reimplements a constraint. It calls `harness/budget.py` and `harness/actions.py` — the modules C06.4
already tested — because a second copy of the budget rules is exactly how the two copies start disagreeing.

**The two hooks, and why these two:**

* ``on_model_call`` is the only place every model request passes through, including AgentScope's own retries,
  output repairs and (if enabled) compression and closing summaries. Reserving there means the count is of
  *requests*, which is what ``docs/agent-spec.md:40`` caps at 12 — not of "reasoning rounds", which would miss
  the extra calls.
* ``on_check_permission`` is the gate AgentScope consults **before** executing a tool. Refusing there makes
  "illegal action ⇒ zero tool executions" true by construction rather than by hoping, and it is where a whole
  batch can be rejected before any member of it runs (``docs/agentscope-migration.md:41``).

**What this module deliberately does not do.** It does not translate AgentScope tool calls into our six-kind ABI
(that is AS02's adapter work, and AS01.1's mapping test records what the translation has to cover). And it does
not implement recovery: a middleware hook is a convenient place to *check* a fence, not evidence that state can
be restored under one — ``docs/agentscope-migration.md:58` and AS01.2 exist because that distinction is the
whole recovery question.
"""

from __future__ import annotations

from typing import Any, Final

from agentscope.middleware import MiddlewareBase

# The project's own guards, imported rather than reimplemented. `tests/conftest.py` puts `agent/src` on the path;
# a spike with its own copy of the budget rules would pass while the production rules changed.
from resolveflow.harness.budget import (
    REASON_BUDGET_STEP_TOKENS,
    BudgetExhaustedError,
    BudgetGuard,
    RunBudget,
)

__all__ = [
    "ALLOW",
    "DENY",
    "BudgetMiddleware",
    "CountingMiddleware",
    "RefusingPermissionMiddleware",
    "ToolNames",
]

#: What an illegal action produces at the permission hook. Spelled as data rather than as a library import so
#: the mapping is visible in one place; the test asserts the library agrees.
ALLOW: Final = "allow"
DENY: Final = "deny"


def _string_elements(node: Any) -> list[str]:
    """The string literals inside an assignment's value, whatever wrapper the module used.

    ``WHITELIST`` is declared as ``Final[frozenset[str]] = frozenset({...})``, and ``ast.literal_eval`` refuses a
    ``Call`` — so the elements are collected by walking for string constants instead. This is the second thing
    this reader got wrong before it worked (the first was not knowing about annotated assignments at all), which
    is why it raises on anything unexpected rather than returning a partial set: a whitelist that quietly parsed
    as four names would make the permission tests pass while testing the wrong list.
    """
    import ast

    if isinstance(node, ast.Call):
        collected: list[str] = []
        for argument in node.args:
            collected.extend(_string_elements(argument))
        return collected
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        collected = []
        for element in node.elts:
            collected.extend(_string_elements(element))
        return collected
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    raise AssertionError(f"the whitelist holds something this reader does not understand: {ast.dump(node)[:120]}")


class ToolNames:
    """The whitelist, read from the project's own ABI module rather than restated.

    The spike's venv does not install `resolveflow`, so this reads the set from the agent project's ``actions.py``
    by path. That keeps "AgentScope must not widen the whitelist" pinned to the one list the project already
    tests instead of to a second copy living in a spike.
    """

    def __init__(self, names: frozenset[str]) -> None:
        self._names = names

    @classmethod
    def from_project(cls, path: Any) -> ToolNames:
        """Read ``WHITELIST`` out of the project's ABI module by parsing it, not by importing it.

        Parsing rather than importing: ``actions.py`` imports pydantic and the contract types, which the spike's
        own lock does not carry, and pulling them in would defeat the isolation this spike exists for. The AST is
        read for both spellings the module could use — a plain assignment and an annotated one
        (``WHITELIST: Final[frozenset[str]] = frozenset({...})`` is what the file actually has, and a reader that
        only handled the first form failed loudly here rather than silently returning an empty set).
        """
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        found: Any = None
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            if any(isinstance(target, ast.Name) and target.id == "WHITELIST" for target in targets):
                found = value
        if found is None:
            raise AssertionError(f"WHITELIST not found in {path}")
        names = frozenset(_string_elements(found))
        if len(names) != 5:
            # A whitelist that is empty or wrong would make the "illegal action is refused" tests pass for the
            # wrong reason — everything, or the wrong things, would be illegal.
            raise AssertionError(f"WHITELIST parsed as {sorted(names)} from {path}; expected the five tools")
        return cls(names)

    def __contains__(self, name: str) -> bool:
        return name in self._names

    def __iter__(self) -> Any:
        return iter(sorted(self._names))

    def __len__(self) -> int:
        return len(self._names)


class BudgetMiddleware(MiddlewareBase):
    """Reserves every model call against the run's budget, before the call happens.

    ``docs/agentscope-migration.md:51`` is explicit that the SDK's own "you are running out of budget, wrap up"
    nudge does not replace a pre-call refusal backed by a durable ledger. So this hook refuses rather than
    advises: a rejected reservation means the provider is never contacted, and the count that matters is of
    requests the provider saw.
    """

    def __init__(self, guard: BudgetGuard) -> None:
        self.guard = guard
        #: Requests this hook let through, and requests it refused. Both are asserted, because "the budget
        #: stopped it" and "the provider was never called" are different claims.
        self.allowed = 0
        self.refused = 0
        self.refusals: list[str] = []

    async def on_model_call(
        self, agent: Any, input_kwargs: dict[str, Any], next_handler: Any
    ) -> Any:
        """Count the *whole* input, then either refuse or let the call proceed.

        The input estimate uses AgentScope's own ``count_tokens``, which walks the messages **and** appends the
        tool JSON schemas (``ChatModelBase.count_tokens``). Using only the new context packet would undercount
        exactly the part that grows — ``docs/agentscope-migration.md:50`` names this: 输入计数覆盖最终system、
        messages、工具Schema及provider包装.
        """
        messages = input_kwargs.get("messages") or []
        tools = input_kwargs.get("tools")
        model = getattr(agent, "model", None)
        estimated_input = 0
        if model is not None and hasattr(model, "count_tokens"):
            estimated_input = await model.count_tokens(messages, tools)
        try:
            # Output is reserved at the per-step cap rather than at zero: the answer's length is not knowable
            # beforehand, and reserving zero would make the cumulative output cap unenforceable
            # (the C06.4① lesson, kept).
            self.guard.reserve_model_call(
                input_tokens=estimated_input, output_tokens=self.guard.budget.step_output_tokens
            )
        except BudgetExhaustedError as exhausted:
            self.refused += 1
            self.refusals.append(exhausted.reason_code)
            raise
        self.allowed += 1
        return await next_handler()


class RefusingPermissionMiddleware(MiddlewareBase):
    """Refuses a tool call the run's ABI does not permit, before AgentScope executes it.

    The refusal is a ``deny`` decision, and the spike's test asserts the *tool body never ran* rather than that
    a decision object came back: a permission hook that returned "deny" and was ignored would satisfy the
    weaker assertion, and that is the failure mode worth excluding.
    """

    def __init__(self, allowed: Any) -> None:
        self.allowed = allowed
        #: Names this hook refused, so the test can say which rule fired.
        self.refused: list[str] = []

    def _decision(self, deny: bool, message: str) -> Any:
        from agentscope.permission import PermissionBehavior, PermissionDecision

        return PermissionDecision(
            behavior=PermissionBehavior.DENY if deny else PermissionBehavior.ALLOW,
            message=message,
        )

    async def on_check_permission(
        self, agent: Any, input_kwargs: dict[str, Any], next_handler: Any
    ) -> Any:
        """Allow a whitelisted read; deny anything else.

        The batch semantics live in the caller (``docs/agentscope-migration.md:41``: 混有非法动作…时整批拒绝):
        AgentScope consults this per tool call, so a batch containing one illegal member is refused member by
        member before any of them runs, because the *first* illegal member is denied and the run stops there.
        """
        tool = input_kwargs.get("tool") or input_kwargs.get("tool_call")
        name = getattr(tool, "name", None) or (tool.get("name") if isinstance(tool, dict) else None)
        if name is None:
            name = str(input_kwargs.get("tool_name", ""))
        # AgentScope namespaces MCP tools as `mcp__<server>__<tool>`; the whitelist is of tool names, so the
        # namespace is stripped rather than added to the list (a second list is how the two drift).
        bare = name.split("__")[-1] if name.startswith("mcp__") else name
        if bare not in self.allowed:
            self.refused.append(bare)
            return self._decision(True, f"{bare!r} is not one of the five whitelisted tools")
        return await next_handler()


class CountingMiddleware(MiddlewareBase):
    """Counts how many tool bodies actually executed.

    The measurement the acceptance criterion needs: "an illegal tool action ⇒ zero tool executions" is a
    statement about the *tool*, so it has to be counted where the tool runs, not where the decision is made.
    """

    def __init__(self) -> None:
        self.executions: list[str] = []

    def note(self, name: str) -> None:
        self.executions.append(name)


def budget_guard(budget: RunBudget | None = None) -> BudgetGuard:
    """A guard over the spec's budget, or a smaller one for a test that wants to reach the cap quickly."""
    return BudgetGuard(budget or RunBudget())


#: The reason code a step-cap refusal carries, re-exported so a test does not have to import two modules.
REASON_STEP: Final = REASON_BUDGET_STEP_TOKENS
