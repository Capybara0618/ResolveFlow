"""The five whitelisted business tools, served over real MCP stdio (C06.2b).

``docs/agent-spec.md:26-32`` fixes the whitelist: this package implements exactly those five, no more.

- :mod:`resolveflow.tools.upstream` — the reads, and the rules that apply to all five (a refusal is never
  retried with another id, NOT_FOUND is a failed observation rather than a negative fact, an oversized body is
  refused rather than truncated).
- :mod:`resolveflow.tools.catalog` — the tools as plain functions with no MCP in sight, so their rules are
  testable without a protocol handshake.
- :mod:`resolveflow.tools.server` — the stdio server, thin on purpose: it owns the protocol and the per-run
  trace page budget, and nothing else.
"""
