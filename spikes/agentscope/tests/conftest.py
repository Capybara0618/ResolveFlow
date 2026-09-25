"""Make the agent project's own guards importable from the spike.

AS01.1's whole claim is that AgentScope can be bounded by **the constraints C06.4 already built and tested**, not
by a second implementation of them. So the spike imports `resolveflow.harness.budget` and
`resolveflow.harness.actions` from `agent/src` rather than copying them: a copy in the spike would let the two
drift, and the drift would be invisible — the spike would keep passing while the production guards changed.

The spike has its own virtualenv and its own lock (`spikes/agentscope/uv.lock`), so it cannot *install*
`resolveflow`. Putting `agent/src` on `sys.path` gives it the source without pinning the agent project's
dependency graph into the spike, which is the isolation `docs/agentscope-migration.md:89` asks for.

This is a deliberate exception to the spike's isolation and it is recorded as one: it means the spike's results
depend on the working tree at `agent/src`, so `reports/agentscope-migration/compatibility.md` records the agent
revision the run was made against.
"""

from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
AGENT_SRC = REPO_ROOT / "agent" / "src"

if str(AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(AGENT_SRC))
