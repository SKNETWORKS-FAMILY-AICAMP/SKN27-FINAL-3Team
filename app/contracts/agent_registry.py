"""Typed public capability contract for production Agent adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentCapabilityContract(BaseModel):
    """Public metadata for one callable production Agent."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["agent_capability.v1"] = "agent_capability.v1"
    node_code: str = Field(min_length=1, max_length=120)
    node_name: str = Field(min_length=1, max_length=200)
    node_type: Literal["agent"] = "agent"
    owner: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    capability_status: Literal["available"] = "available"
    execution_modes: list[Literal["sync"]] = Field(default_factory=lambda: ["sync"])
    input_schema: Literal["agent_input.v1"] = "agent_input.v1"
    output_schema: Literal["agent_output.v1"] = "agent_output.v1"
    timeout_seconds: int = Field(gt=0, le=600)
    required_inputs: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    handoff_to: list[str] = Field(default_factory=list)
