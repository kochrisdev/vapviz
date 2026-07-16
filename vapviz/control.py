"""
Live run control (Pause / Resume / Stop) — the return lane.

vapviz is normally a one-directional tracer (agent → store → UI). This module
adds the small amount of state needed to send lifecycle commands *back* to a
running, **in-process** agent. It is **cooperative**: the tracer checks a run's
desired state at each step checkpoint (see ``tracer._check_control``) and obeys
it — a polite halt at the next checkpoint, never a force-kill.

Design + rationale: ``docs/notes/DESIGN-agent-control.md``.

The control *latch* (``RunControl``) lives in the store as ephemeral in-memory
state (guarded by the store's lock, like tags) — it is **not** part of the event
log or the graph reducers, and is **not** persisted. The only things that touch
the event lane are (1) an inert ``control`` audit event emitted by the server for
the timeline, and (2) the ``stopped`` marker on ``agent_end`` that gives a run
its first-class ``stopped`` status.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Lifecycle states ────────────────────────────────────────────────────────
# "desired" = what the user asked for (set by the server); "acked" = what the
# agent has actually done (set by the tracer when it reaches a checkpoint), so
# the UI can show the honest cooperative lag ("pausing…" → "paused").
RUNNING = "running"
PAUSED = "paused"
STOPPED = "stopped"
DESIRED_STATES = (RUNNING, PAUSED, STOPPED)

# UI action verb → desired lifecycle state.
ACTION_TO_DESIRED = {"pause": PAUSED, "resume": RUNNING, "stop": STOPPED}

# How long a parked agent waits between control re-checks. It's a *safety
# re-poll*, not the happy path — ``set_desired`` wakes a sync agent immediately
# via the store's per-run Event; this only bounds latency if a wake is missed,
# so resume/stop is honored within CONTROL_POLL seconds even in the worst case.
CONTROL_POLL = 0.1


@dataclass
class RunControl:
    """A run's live control latch. ``desired`` is set by the server; ``acked``
    is set by the tracer when it acts on it at a checkpoint."""

    desired: str = RUNNING
    acked: str = RUNNING
    updated_at: float = 0.0


class VapStopped(Exception):
    """Raised at a tracer checkpoint when a run's desired state is ``stopped``.

    Propagates out of ``trace``/``atrace`` so the agent's own code unwinds and
    actually stops. Catch it (``except vapviz.VapStopped``) if you want a
    graceful shutdown instead of unwinding to the top.
    """

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} stopped by user request")
        self.run_id = run_id
