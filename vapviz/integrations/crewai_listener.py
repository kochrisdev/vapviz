"""
vapviz event listener for CrewAI.

Hooks into CrewAI's native event bus (``BaseEventListener``) to automatically
trace Crew runs, Tasks, Agent executions, Tool calls, and LLM calls as vapviz
nodes — no manual instrumentation needed.

Two usage modes
---------------

**Auto mode** — creates a new vapviz run for each ``crew.kickoff()`` call:

    import vapviz
    from vapviz.integrations.crewai_listener import VapCrewAIListener

    vapviz.configure(db="vapviz.db")
    VapCrewAIListener()        # instantiate once before kickoff()

    crew = Crew(agents=[...], tasks=[...])
    crew.kickoff(inputs={"topic": "AI"})

**Manual mode** — attach CrewAI nodes to an existing ``RunContext`` so
the crew appears as a sub-section of a larger pipeline trace:

    import vapviz
    from vapviz.integrations.crewai_listener import VapCrewAIListener

    with vapviz.trace("My Pipeline") as run:
        with run.step("pre_process", kind="step") as step:
            step.set_input({...}); ...
            step.set_output({...})

        listener = VapCrewAIListener(run=run)
        crew.kickoff(inputs={...})

Requirements
------------
    pip install "vapviz[crewai]"
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from ..tracer import _uid, NodeKind, StepContext, RunContext
from ..events import EventType

# ---------------------------------------------------------------------------
# Optional CrewAI import guard
# ---------------------------------------------------------------------------

try:
    from crewai.events import (
        crewai_event_bus,
        BaseEventListener,
        CrewKickoffStartedEvent,
        CrewKickoffCompletedEvent,
        TaskStartedEvent,
        TaskCompletedEvent,
        AgentExecutionStartedEvent,
        AgentExecutionCompletedEvent,
        ToolUsageStartedEvent,
        ToolUsageFinishedEvent,
        LLMCallStartedEvent,
        LLMCallCompletedEvent,
    )
    _CREWAI_AVAILABLE = True
except ImportError:
    # Stub so the module can be imported without crewai installed.
    # VapCrewAIListener will raise ImportError at instantiation time.
    class BaseEventListener:  # type: ignore[no-redef]
        pass
    _CREWAI_AVAILABLE = False

# Optional events (added in later CrewAI versions)
try:
    from crewai.events import CrewKickoffFailedEvent as _CrewFailedEvent  # type: ignore[assignment]
    _HAS_CREW_FAILED = True
except ImportError:
    _HAS_CREW_FAILED = False

try:
    from crewai.events import TaskFailedEvent as _TaskFailedEvent  # type: ignore[assignment]
    _HAS_TASK_FAILED = True
except ImportError:
    _HAS_TASK_FAILED = False

try:
    from crewai.events import AgentExecutionErrorEvent as _AgentExecErrorEvent  # type: ignore[assignment]
    _HAS_AGENT_EXEC_ERROR = True
except ImportError:
    _HAS_AGENT_EXEC_ERROR = False

try:
    from crewai.events import ToolUsageErrorEvent as _ToolErrorEvent  # type: ignore[assignment]
    _HAS_TOOL_ERROR = True
except ImportError:
    _HAS_TOOL_ERROR = False

try:
    from crewai.events import LLMCallFailedEvent as _LLMFailedEvent  # type: ignore[assignment]
    _HAS_LLM_FAILED = True
except ImportError:
    _HAS_LLM_FAILED = False


# ---------------------------------------------------------------------------
# VapCrewAIListener
# ---------------------------------------------------------------------------


class VapCrewAIListener(BaseEventListener):  # type: ignore[misc]
    """
    vapviz tracing integration for CrewAI.

    Hooks into CrewAI's event bus to trace Crew runs, Tasks, Agent
    executions, Tool calls, and LLM calls as vapviz nodes with inputs,
    outputs, durations, token usage, and USD cost.

    Parameters
    ----------
    run:
        Optional ``RunContext`` yielded by ``vapviz.trace()``. When provided
        (manual mode), CrewAI tasks appear as children of this run's root
        node. When omitted (auto mode), a new vapviz run is created
        automatically for each ``crew.kickoff()`` call and closed when
        the crew finishes.

    Example — auto mode::

        import vapviz
        from vapviz.integrations.crewai_listener import VapCrewAIListener

        vapviz.configure(db="vapviz.db")
        VapCrewAIListener()          # register once before crew runs

        result = crew.kickoff(inputs={"topic": "AI"})

    Example — manual mode::

        import vapviz
        from vapviz.integrations.crewai_listener import VapCrewAIListener

        with vapviz.trace("Full Pipeline") as run:
            listener = VapCrewAIListener(run=run)
            result = crew.kickoff(inputs={...})
    """

    def __init__(self, run: Optional[RunContext] = None) -> None:
        if not _CREWAI_AVAILABLE:
            raise ImportError(
                "crewai is required for VapCrewAIListener. "
                'Install it with: pip install "vapviz[crewai]"'
            )
        self._provided_run: Optional[RunContext] = run

        # Thread safety for all shared state
        self._lock = threading.Lock()

        # Auto-mode: maps crew_started event_id -> RunContext
        self._runs: dict[str, RunContext] = {}

        # Crew root StepContext: crew_started event_id -> StepContext
        # (in manual mode this is the step inside the provided run;
        #  in auto mode this is the run's own root_ctx)
        self._crew_roots: dict[str, StepContext] = {}

        # Current active crew event_id (for sequential single-crew runs)
        self._current_crew_event_id: Optional[str] = None

        # Task nodes keyed by stable task id (str(task.id)); the human
        # label lives only on the node. AgentExecutionStartedEvent carries
        # no task_name/task_id (crewai 1.14.6) — only event.task.id — so
        # the id is the one key shared by all task-related events.
        self._task_nodes: dict[str, StepContext] = {}
        # started_event_id -> task key (for matching task end/fail events)
        self._task_event_to_key: dict[str, str] = {}

        # Agent execution nodes: started event_id -> StepContext
        self._agent_exec_nodes: dict[str, StepContext] = {}
        # agent_id -> most recent active agent execution StepContext
        self._agent_by_id: dict[str, StepContext] = {}

        # Tool nodes: started event_id -> StepContext
        self._tool_nodes: dict[str, StepContext] = {}

        # LLM nodes: call_id -> StepContext
        self._llm_nodes: dict[str, StepContext] = {}

        # Must be last — triggers setup_listeners()
        super().__init__()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_store(self) -> Any:
        if self._provided_run is not None:
            return self._provided_run._store
        import vapviz.store as _sm
        return _sm.default_store

    def _get_run_id(self, crew_event_id: Optional[str] = None) -> Optional[str]:
        if self._provided_run is not None:
            return self._provided_run.run_id
        eid = crew_event_id or self._current_crew_event_id
        if eid:
            with self._lock:
                run = self._runs.get(eid)
            if run:
                return run.run_id
        return None

    def _make_ctx(
        self,
        label: str,
        kind: str,
        parent_id: Optional[str],
        run_id: str,
    ) -> StepContext:
        return StepContext(
            run_id=run_id,
            node_id=_uid(),
            node_kind=NodeKind(kind),
            label=label,
            parent_id=parent_id,
            store=self._get_store(),
        )

    def _get_crew_root(self) -> Optional[StepContext]:
        """Return the active crew root StepContext.

        In auto mode this is the run's own root_ctx; in manual mode it is the
        'crew/…' step that was created inside the provided run.  Either way it
        is stored in ``_crew_roots`` by the kickoff-started handler, so we
        always prefer that over the fallback run root.
        """
        with self._lock:
            eid = self._current_crew_event_id
            if eid:
                ctx = self._crew_roots.get(eid)
                if ctx is not None:
                    return ctx
        # Fallback: no kickoff seen yet — return the provided run's root so
        # that any nodes created before a kickoff still have a valid parent.
        if self._provided_run is not None:
            return self._provided_run._root_ctx
        return None

    # ------------------------------------------------------------------
    # setup_listeners — called by BaseEventListener.__init__
    # ------------------------------------------------------------------

    def setup_listeners(self, crewai_event_bus) -> None:  # noqa: N802
        bus = crewai_event_bus

        # ── Crew lifecycle ─────────────────────────────────────────────────

        @bus.on(CrewKickoffStartedEvent)
        def _on_crew_start(source, event) -> None:
            crew_name = _safe_str(getattr(event, "crew_name", None)) or "Crew"
            inputs = getattr(event, "inputs", None) or {}

            if self._provided_run is not None:
                # Manual mode: create a "crew/…" step node under the existing run
                run_id = self._provided_run.run_id
                root = self._provided_run._root_ctx
                ctx = self._make_ctx(
                    label=f"crew/{crew_name}",
                    kind="step",
                    parent_id=root.node_id,
                    run_id=run_id,
                )
                ctx.set_input({"crew": crew_name, "inputs": _truncate(inputs)})
                ctx._emit(EventType.STEP_START)
            else:
                # Auto mode: create a new vapviz run
                import vapviz.store as _sm
                store = _sm.default_store
                run = RunContext(label=crew_name, store=store)
                run._start()
                if inputs:
                    run._root_ctx.set_input({"inputs": _truncate(inputs)})
                ctx = run._root_ctx
                with self._lock:
                    self._runs[event.event_id] = run

            with self._lock:
                self._crew_roots[event.event_id] = ctx
                self._current_crew_event_id = event.event_id

        @bus.on(CrewKickoffCompletedEvent)
        def _on_crew_end(source, event) -> None:
            output = getattr(event, "output", None)
            crew_event_id = (
                getattr(event, "started_event_id", None)
                or self._current_crew_event_id
            )

            with self._lock:
                run = self._runs.pop(crew_event_id, None)
                crew_root = self._crew_roots.pop(crew_event_id, None)
                if self._current_crew_event_id == crew_event_id:
                    self._current_crew_event_id = None

            if self._provided_run is not None and crew_root is not None:
                # Manual mode: close the crew step
                out_str = _safe_str(output)
                crew_root.set_output({"output": out_str[:500] if out_str else "completed"})
                crew_root._emit(
                    EventType.STEP_END,
                    {"input": crew_root._input, "output": crew_root._output},
                )
            elif run is not None:
                # Auto mode: close the run
                run._end()

        if _HAS_CREW_FAILED:
            @bus.on(_CrewFailedEvent)
            def _on_crew_fail(source, event) -> None:
                error = getattr(event, "error", None) or "Crew execution failed"
                crew_event_id = (
                    getattr(event, "started_event_id", None)
                    or self._current_crew_event_id
                )
                with self._lock:
                    run = self._runs.pop(crew_event_id, None)
                    self._crew_roots.pop(crew_event_id, None)
                    if self._current_crew_event_id == crew_event_id:
                        self._current_crew_event_id = None
                if self._provided_run is None and run is not None:
                    run._end(error=Exception(_safe_str(error) or "Crew failed"))

        # ── Task lifecycle ─────────────────────────────────────────────────

        @bus.on(TaskStartedEvent)
        def _on_task_start(source, event) -> None:
            task_obj = getattr(event, "task", None)
            task_name = (
                (getattr(task_obj, "name", None) if task_obj else None)
                or getattr(event, "task_name", None)
                or (getattr(task_obj, "description", "") if task_obj else None)
                or "task"
            )
            # crewai fills task_name with the full description when the task
            # has no explicit name — keep the node label short.
            task_name = _first_words(_safe_str(task_name), 6) or "task"

            run_id = self._get_run_id()
            if run_id is None:
                return

            crew_root = self._get_crew_root()
            parent_id = crew_root.node_id if crew_root else None

            ctx = self._make_ctx(
                label=f"task/{task_name}",
                kind="step",
                parent_id=parent_id,
                run_id=run_id,
            )

            input_data: dict[str, Any] = {"task": task_name}
            if task_obj and hasattr(task_obj, "description"):
                input_data["description"] = task_obj.description[:300]
            context_val = getattr(event, "context", None)
            if context_val:
                input_data["context"] = _safe_str(context_val)[:200]
            ctx.set_input(input_data)
            ctx._emit(EventType.STEP_START)

            task_key = _task_key(event) or event.event_id
            with self._lock:
                self._task_nodes[task_key] = ctx
                self._task_event_to_key[event.event_id] = task_key

        @bus.on(TaskCompletedEvent)
        def _on_task_end(source, event) -> None:
            started_id = getattr(event, "started_event_id", None)
            with self._lock:
                task_key = (
                    self._task_event_to_key.pop(started_id, None)
                    if started_id
                    else None
                ) or _task_key(event)
                ctx = self._task_nodes.pop(task_key, None) if task_key else None

            if ctx is None:
                return

            task_output = getattr(event, "output", None)
            out_str: Optional[str] = None
            if task_output is not None:
                if hasattr(task_output, "raw"):
                    out_str = _safe_str(task_output.raw)
                else:
                    out_str = _safe_str(task_output)
            ctx.set_output({"output": (out_str or "")[:500]})
            ctx._emit(EventType.STEP_END, {"input": ctx._input, "output": ctx._output})

        if _HAS_TASK_FAILED:
            @bus.on(_TaskFailedEvent)
            def _on_task_fail(source, event) -> None:
                started_id = getattr(event, "started_event_id", None)
                error = getattr(event, "error", None) or "Task failed"
                with self._lock:
                    task_key = (
                        self._task_event_to_key.pop(started_id, None)
                        if started_id
                        else None
                    ) or _task_key(event)
                    ctx = self._task_nodes.pop(task_key, None) if task_key else None
                if ctx is not None:
                    ctx._emit(EventType.ERROR, {
                        "error": _safe_str(error),
                        "error_type": type(error).__name__ if not isinstance(error, str) else "TaskError",
                    })

        # ── Agent execution lifecycle ──────────────────────────────────────

        @bus.on(AgentExecutionStartedEvent)
        def _on_agent_exec_start(source, event) -> None:
            agent_obj = getattr(event, "agent", None)
            agent_role = (
                getattr(event, "agent_role", None)
                or (getattr(agent_obj, "role", None) if agent_obj else None)
                or "agent"
            )
            agent_id = (
                getattr(event, "agent_id", None)
                or (_safe_str(getattr(agent_obj, "id", None)) if agent_obj else None)
                or agent_role
            )
            # The agent's parent task is matched by stable task id —
            # AgentExecutionStartedEvent has task_name/task_id = None
            # (crewai 1.14.6); only event.task.id is populated.
            task_key = _task_key(event)

            run_id = self._get_run_id()
            if run_id is None:
                return

            # Parent = current task node, else crew root.
            # NOTE: _get_crew_root() acquires self._lock internally, so it must
            # be called *outside* any self._lock block to avoid a deadlock.
            with self._lock:
                parent_ctx = self._task_nodes.get(task_key) if task_key else None
            if parent_ctx is None:
                parent_ctx = self._get_crew_root()
            parent_id = parent_ctx.node_id if parent_ctx else None

            ctx = self._make_ctx(
                label=f"agent/{agent_role}",
                kind="step",
                parent_id=parent_id,
                run_id=run_id,
            )

            input_data: dict[str, Any] = {"role": agent_role}
            task_prompt = getattr(event, "task_prompt", None)
            if task_prompt:
                input_data["task_prompt"] = _safe_str(task_prompt)[:400]
            tools = getattr(event, "tools", None)
            if tools:
                tool_names = [getattr(t, "name", _safe_str(t)) for t in tools[:12]]
                input_data["tools"] = tool_names
            ctx.set_input(input_data)
            ctx._emit(EventType.STEP_START)

            with self._lock:
                self._agent_exec_nodes[event.event_id] = ctx
                self._agent_by_id[agent_id] = ctx

        @bus.on(AgentExecutionCompletedEvent)
        def _on_agent_exec_end(source, event) -> None:
            started_id = getattr(event, "started_event_id", None)
            agent_obj = getattr(event, "agent", None)
            agent_id = (
                getattr(event, "agent_id", None)
                or (_safe_str(getattr(agent_obj, "id", None)) if agent_obj else None)
                or ""
            )
            output = getattr(event, "output", None)

            with self._lock:
                ctx = (
                    self._agent_exec_nodes.pop(started_id, None)
                    if started_id
                    else None
                )
                if agent_id:
                    self._agent_by_id.pop(agent_id, None)

            if ctx is None:
                return

            ctx.set_output({"output": (_safe_str(output) or "")[:500]})
            ctx._emit(EventType.STEP_END, {"input": ctx._input, "output": ctx._output})

        if _HAS_AGENT_EXEC_ERROR:
            @bus.on(_AgentExecErrorEvent)
            def _on_agent_exec_error(source, event) -> None:
                started_id = getattr(event, "started_event_id", None)
                agent_id = getattr(event, "agent_id", None) or ""
                error = getattr(event, "error", None) or "Agent execution failed"
                with self._lock:
                    ctx = (
                        self._agent_exec_nodes.pop(started_id, None)
                        if started_id
                        else None
                    )
                    if agent_id:
                        self._agent_by_id.pop(agent_id, None)
                if ctx is not None:
                    ctx._emit(EventType.ERROR, {
                        "error": _safe_str(error),
                        "error_type": type(error).__name__ if not isinstance(error, str) else "AgentError",
                    })

        # ── Tool call lifecycle ────────────────────────────────────────────

        @bus.on(ToolUsageStartedEvent)
        def _on_tool_start(source, event) -> None:
            tool_name = _safe_str(getattr(event, "tool_name", None)) or "tool"
            agent_id = _safe_str(getattr(event, "agent_id", None)) or ""

            run_id = self._get_run_id()
            if run_id is None:
                return

            with self._lock:
                agent_ctx = self._agent_by_id.get(agent_id)
            parent_id = agent_ctx.node_id if agent_ctx else None

            ctx = self._make_ctx(
                label=tool_name,
                kind="tool",
                parent_id=parent_id,
                run_id=run_id,
            )

            tool_args = getattr(event, "tool_args", None)
            input_data: dict[str, Any] = {}
            if isinstance(tool_args, dict):
                input_data = {k: str(v)[:200] for k, v in list(tool_args.items())[:20]}
            elif tool_args is not None:
                input_data = {"args": _safe_str(tool_args)[:300]}
            ctx.set_input(input_data)
            ctx._emit(EventType.TOOL_CALL)

            with self._lock:
                self._tool_nodes[event.event_id] = ctx

        @bus.on(ToolUsageFinishedEvent)
        def _on_tool_end(source, event) -> None:
            started_id = getattr(event, "started_event_id", None)
            tool_output = getattr(event, "output", None)
            from_cache = getattr(event, "from_cache", False)

            with self._lock:
                ctx = self._tool_nodes.pop(started_id, None) if started_id else None

            if ctx is None:
                return

            output_data: dict[str, Any] = {
                "output": (_safe_str(tool_output) or "")[:500]
            }
            if from_cache:
                output_data["from_cache"] = True
            ctx.set_output(output_data)
            ctx._emit(EventType.TOOL_RESULT, {"input": ctx._input, "output": ctx._output})

        if _HAS_TOOL_ERROR:
            @bus.on(_ToolErrorEvent)
            def _on_tool_error(source, event) -> None:
                started_id = getattr(event, "started_event_id", None)
                error = getattr(event, "error", None) or "Tool error"
                with self._lock:
                    ctx = self._tool_nodes.pop(started_id, None) if started_id else None
                if ctx is not None:
                    ctx._emit(EventType.ERROR, {
                        "error": _safe_str(error),
                        "error_type": type(error).__name__ if not isinstance(error, str) else "ToolError",
                    })

        # ── LLM call lifecycle ─────────────────────────────────────────────

        @bus.on(LLMCallStartedEvent)
        def _on_llm_start(source, event) -> None:
            model = _safe_str(getattr(event, "model", None)) or "llm"
            call_id = _safe_str(getattr(event, "call_id", None)) or _uid()
            from_agent = getattr(event, "from_agent", None)
            agent_id = (
                _safe_str(getattr(event, "agent_id", None))
                or (_safe_str(getattr(from_agent, "id", None)) if from_agent else None)
                or ""
            )

            run_id = self._get_run_id()
            if run_id is None:
                return

            with self._lock:
                agent_ctx = self._agent_by_id.get(agent_id)
            parent_id = agent_ctx.node_id if agent_ctx else None

            ctx = self._make_ctx(
                label=f"llm/{model}",
                kind="llm",
                parent_id=parent_id,
                run_id=run_id,
            )

            messages = getattr(event, "messages", None)
            input_data: dict[str, Any] = {"model": model}
            if messages is not None:
                if isinstance(messages, list):
                    input_data["messages"] = [
                        _serialize_message(m) for m in messages[:10]
                    ]
                elif isinstance(messages, str):
                    input_data["messages"] = messages[:500]
            tools = getattr(event, "tools", None)
            if tools:
                input_data["tools_count"] = len(tools)
            ctx.set_input(input_data)
            ctx._emit(EventType.LLM_CALL)

            with self._lock:
                self._llm_nodes[call_id] = ctx

        @bus.on(LLMCallCompletedEvent)
        def _on_llm_end(source, event) -> None:
            call_id = _safe_str(getattr(event, "call_id", None))
            model = _safe_str(getattr(event, "model", None)) or ""
            usage = getattr(event, "usage", None) or {}
            response = getattr(event, "response", None)
            call_type = getattr(event, "call_type", None)

            with self._lock:
                ctx = self._llm_nodes.pop(call_id, None) if call_id else None

            if ctx is None:
                return

            output_data: dict[str, Any] = {}

            # Extract response text
            if response is not None:
                if isinstance(response, str):
                    output_data["text"] = response[:500]
                elif hasattr(response, "choices"):
                    try:
                        text = response.choices[0].message.content or ""
                        output_data["text"] = text[:500]
                    except (AttributeError, IndexError):
                        output_data["response"] = _safe_str(response)[:300]
                else:
                    output_data["response"] = _safe_str(response)[:300]

            # Extract token usage (LiteLLM-style dict)
            if isinstance(usage, dict):
                input_tok = (
                    usage.get("prompt_tokens")
                    or usage.get("input_tokens")
                    or usage.get("promptTokens")
                    or 0
                )
                output_tok = (
                    usage.get("completion_tokens")
                    or usage.get("output_tokens")
                    or usage.get("completionTokens")
                    or 0
                )
                if input_tok or output_tok:
                    output_data["usage"] = {
                        "input_tokens": input_tok,
                        "output_tokens": output_tok,
                    }
                    # Auto-attach cost for known models
                    try:
                        from ..cost import calculate_cost
                        cost = calculate_cost(model, input_tok, output_tok)
                        if cost is not None:
                            output_data["cost_usd"] = round(cost, 8)
                    except Exception:
                        pass

            if call_type is not None:
                output_data["call_type"] = _safe_str(call_type)

            ctx.set_output(output_data)
            ctx._emit(
                EventType.LLM_RESPONSE,
                {"input": ctx._input, "output": ctx._output},
            )

        if _HAS_LLM_FAILED:
            @bus.on(_LLMFailedEvent)
            def _on_llm_fail(source, event) -> None:
                call_id = _safe_str(getattr(event, "call_id", None))
                error = getattr(event, "error", None) or "LLM call failed"
                with self._lock:
                    ctx = self._llm_nodes.pop(call_id, None) if call_id else None
                if ctx is not None:
                    ctx._emit(EventType.ERROR, {
                        "error": _safe_str(error),
                        "error_type": type(error).__name__ if not isinstance(error, str) else "LLMError",
                    })

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def detach(self) -> None:
        """
        Flush and close any pending open nodes.

        Normally not needed — the crew lifecycle events close everything
        automatically. Call this in manual mode if you need to guarantee
        all nodes are closed before the ``with vapviz.trace(...)`` block exits.
        """
        with self._lock:
            for ctx in list(self._llm_nodes.values()):
                ctx._emit(EventType.ERROR, {
                    "error": "Listener detached before LLM call completed",
                    "error_type": "ListenerDetached",
                })
            self._llm_nodes.clear()

            for ctx in list(self._tool_nodes.values()):
                ctx._emit(EventType.ERROR, {
                    "error": "Listener detached before tool call completed",
                    "error_type": "ListenerDetached",
                })
            self._tool_nodes.clear()

            for ctx in list(self._agent_exec_nodes.values()):
                ctx._emit(EventType.STEP_END, {
                    "input": ctx._input, "output": ctx._output,
                })
            self._agent_exec_nodes.clear()
            self._agent_by_id.clear()

            for ctx in list(self._task_nodes.values()):
                ctx._emit(EventType.STEP_END, {
                    "input": ctx._input, "output": ctx._output,
                })
            self._task_nodes.clear()
            self._task_event_to_key.clear()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _task_key(event: Any) -> Optional[str]:
    """Stable identity for a task, shared by all task-related events.

    Prefers ``event.task.id`` (the only populated field on
    AgentExecutionStartedEvent in crewai 1.14.6), falling back to the
    event's own ``task_id``.
    """
    task_obj = getattr(event, "task", None)
    task_id = (
        (getattr(task_obj, "id", None) if task_obj is not None else None)
        or getattr(event, "task_id", None)
    )
    key = _safe_str(task_id)
    return key or None


def _safe_str(value: Any) -> str:
    """Convert any value to str, returning empty string on failure."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _truncate(value: Any, max_len: int = 300) -> Any:
    """Truncate long string values inside dicts / lists for display."""
    if isinstance(value, dict):
        return {k: _truncate(v, max_len) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [_truncate(v, max_len) for v in value[:10]]
    if isinstance(value, str) and len(value) > max_len:
        return value[:max_len] + "…"
    return value


def _first_words(text: str, n: int) -> str:
    """Return the first *n* words of *text*, joined by spaces."""
    words = text.split()
    return " ".join(words[:n]) if words else text


def _serialize_message(msg: Any) -> dict:
    """Convert a LiteLLM/dict message to a plain serializable dict."""
    if isinstance(msg, dict):
        return {k: str(v)[:200] for k, v in list(msg.items())[:8]}
    if hasattr(msg, "model_dump"):
        try:
            return msg.model_dump()
        except Exception:
            pass
    if hasattr(msg, "dict"):
        try:
            return msg.dict()
        except Exception:
            pass
    return {"content": _safe_str(msg)[:200]}
