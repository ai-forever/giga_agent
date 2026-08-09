from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
TOOL_REF_PATTERN = re.compile(
    r"^(?:[a-z0-9][a-z0-9_-]*/[a-zA-Z0-9_.:-]+|"
    r"connector:[a-z0-9][a-z0-9_-]*/[a-zA-Z0-9_.:-]+)$"
)


class AgentSkillRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    source: str | None = Field(default=None, min_length=1, max_length=2048)
    ref: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_source_fields(self) -> "AgentSkillRequirement":
        if self.ref and not self.source:
            raise ValueError("skill ref requires source")
        return self


class AgentToolRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: Literal["read"] = "read"
    allow: list[str] = Field(default_factory=list, max_length=256)
    deny: list[str] = Field(default_factory=list, max_length=256)

    @field_validator("allow", "deny")
    @classmethod
    def validate_tool_refs(cls, refs: list[str]) -> list[str]:
        result: list[str] = []
        for raw in refs:
            value = raw.strip()
            if not TOOL_REF_PATTERN.fullmatch(value):
                raise ValueError(f"invalid tool reference: {raw!r}")
            if value not in result:
                result.append(value)
        return result


AllowedToolEffect = Literal["read", "write", "destructive"]


class AgentCapabilityPolicy(BaseModel):
    """Capability policy used by user-created sub-agents.

    Built-in manifests continue to use :class:`AgentToolRules`; this compact
    policy is deliberately category-based and contains no tool references.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_effects: list[AllowedToolEffect] = Field(default_factory=lambda: ["read"])

    @field_validator("allowed_effects")
    @classmethod
    def normalize_effects(cls, values: list[AllowedToolEffect]) -> list[AllowedToolEffect]:
        result: list[AllowedToolEffect] = []
        for value in values:
            if value not in result:
                result.append(value)
        return result


class AgentManifest(BaseModel):
    """Strict v1 YAML frontmatter for a built-in agent."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1024)
    tags: list[str] = Field(default_factory=list, max_length=32)
    icon: str | None = Field(default=None, max_length=128)
    skills: list[AgentSkillRequirement] = Field(default_factory=list, max_length=64)
    modules: list[str] = Field(default_factory=list, max_length=64)
    connectors: list[str] = Field(default_factory=list, max_length=64)
    tools: AgentToolRules = Field(default_factory=AgentToolRules)
    examples: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not AGENT_ID_PATTERN.fullmatch(value):
            raise ValueError("id must contain lowercase letters, digits, '_' or '-'")
        return value

    @field_validator("modules", "connectors", "tags")
    @classmethod
    def normalize_ids(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for raw in values:
            value = raw.strip()
            if not value:
                raise ValueError("empty values are not allowed")
            if value not in result:
                result.append(value)
        return result

    @model_validator(mode="after")
    def unique_skills(self) -> "AgentManifest":
        names = [item.name for item in self.skills]
        if len(names) != len(set(names)):
            raise ValueError("skill names must be unique")
        return self
