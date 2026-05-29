from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    STATE_UPDATE = "state_update"
    ERROR = "error"


class NodeKind(str, Enum):
    AGENT = "agent"
    STEP = "step"
    TOOL = "tool"
    LLM = "llm"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class VapEvent(BaseModel):
    id: str
    run_id: str
    timestamp: float
    type: EventType
    node_id: str
    node_kind: NodeKind
    node_label: str
    parent_id: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1


class GraphNode(BaseModel):
    id: str
    kind: NodeKind
    label: str
    status: NodeStatus = NodeStatus.PENDING
    parent_id: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: str = "execution"


class RunSummary(BaseModel):
    run_id: str
    label: str
    status: NodeStatus
    started_at: float
    ended_at: Optional[float] = None
    node_count: int = 0
    event_count: int = 0
    total_cost_usd: Optional[float] = None


class RunGraph(BaseModel):
    run_id: str
    label: str
    status: NodeStatus
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    started_at: float
    ended_at: Optional[float] = None
