from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from giga_agent.subagents.schema import AgentManifest

MAX_AGENT_MANIFEST_BYTES = 128 * 1024
MAX_AGENT_PROMPT_CHARS = 100_000


class AgentManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedAgentManifest:
    metadata: AgentManifest
    prompt: str
    path: Path


def parse_agent_manifest(path: str | Path) -> ParsedAgentManifest:
    resolved = Path(path).resolve()
    try:
        raw_bytes = resolved.read_bytes()
    except OSError as exc:
        raise AgentManifestError(f"cannot read {resolved}: {exc}") from exc
    if len(raw_bytes) > MAX_AGENT_MANIFEST_BYTES:
        raise AgentManifestError(f"agent manifest is too large: {resolved}")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgentManifestError(f"agent manifest must be UTF-8: {resolved}") from exc

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AgentManifestError(f"missing YAML frontmatter in {resolved}")
    try:
        end = next(
            i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise AgentManifestError(
            f"unterminated YAML frontmatter in {resolved}"
        ) from exc

    frontmatter = "\n".join(lines[1:end])
    prompt = "\n".join(lines[end + 1 :]).strip()
    if not prompt:
        raise AgentManifestError(f"agent prompt is empty in {resolved}")
    if len(prompt) > MAX_AGENT_PROMPT_CHARS:
        raise AgentManifestError(f"agent prompt is too large in {resolved}")
    try:
        loaded = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise AgentManifestError(f"malformed YAML in {resolved}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise AgentManifestError(f"frontmatter must be a mapping in {resolved}")
    try:
        metadata = AgentManifest.model_validate(loaded)
    except ValidationError as exc:
        raise AgentManifestError(f"invalid agent manifest {resolved}: {exc}") from exc
    return ParsedAgentManifest(metadata=metadata, prompt=prompt, path=resolved)
