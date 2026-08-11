from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import quote, unquote, urlparse

import httpx
from cashews import cache

from giga_agent.core.logging import get_logger
from giga_agent.models.skill import Skill, SkillSourceType
from giga_agent.modules.skills.manifest import (
    is_skill_manifest_filename,
    select_skill_manifest_file,
)
from giga_agent.modules.skills.parser import ParsedSkill, parse_skill_md
from giga_agent.modules.skills.service import SkillInstallError, SkillsService

GITHUB_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$")
GITHUB_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
MAX_GITHUB_SKILL_FILES = 256
MAX_GITHUB_SKILL_BYTES = 4 * 1024 * 1024
MAX_GITHUB_SKILL_DEPTH = 3
GITHUB_INDEX_TTL_SECONDS = 10 * 60
MAX_GITHUB_INDEX_BYTES = 256 * 1024
GITHUB_INDEX_SCHEMA_VERSION = 1
SKILLS_SH_DOWNLOAD_URL = "https://skills.sh"
SKILLS_SH_DOWNLOAD_TIMEOUT_SECONDS = 10.0
SKILLS_SH_DOWNLOAD_CONCURRENCY = 3
GITHUB_PARTIAL_CLONE_TIMEOUT_SECONDS = 60.0
GITHUB_PARTIAL_CLONE_CONCURRENCY = 2

logger = get_logger(__name__)
_skills_sh_download_semaphore = asyncio.Semaphore(SKILLS_SH_DOWNLOAD_CONCURRENCY)
_partial_clone_semaphore = asyncio.Semaphore(GITHUB_PARTIAL_CLONE_CONCURRENCY)


@dataclass(frozen=True)
class GithubSource:
    repository: str
    ref: str | None = None
    path: str | None = None

    @property
    def normalized(self) -> str:
        return self.repository


@dataclass(frozen=True)
class GithubSkillFile:
    path: str
    blob_sha: str
    size: int


@dataclass(frozen=True)
class GithubSkillCandidate:
    name: str
    description: str
    path: str
    manifest_path: str
    folder_hash: str | None = None
    manifest_sha: str | None = None
    files: tuple[GithubSkillFile, ...] = ()


@dataclass(frozen=True)
class GithubPreview:
    source: GithubSource
    resolved_ref: str
    resolved_commit: str
    skills: tuple[GithubSkillCandidate, ...]
    warnings: tuple[str, ...] = ()
    cache_state: Literal["fresh", "miss"] = "miss"
    cached_at: float | None = None


@dataclass(frozen=True)
class GithubInstallSelection:
    path: str
    replace_existing: bool = False


@dataclass(frozen=True)
class GithubSkillInstall:
    skill: Skill
    resolved_commit: str
    content_hash: str
    status: str = "installed"


@dataclass(frozen=True)
class GithubInstallResult:
    candidate: GithubSkillCandidate
    status: str
    install: GithubSkillInstall | None = None
    error: str | None = None


@dataclass(frozen=True)
class GithubInstallBatch:
    preview: GithubPreview
    results: tuple[GithubInstallResult, ...]


@dataclass(frozen=True)
class GithubSkillUpdate:
    skill: Skill
    source: str | None
    ref: str | None
    path: str | None
    status: Literal[
        "up_to_date", "update_available", "removed_from_source", "uncheckable", "error"
    ]
    available_commit: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _GithubSnapshot:
    source: GithubSource
    resolved_ref: str
    resolved_commit: str
    tree_sha: str
    blobs: tuple[dict[str, Any], ...]
    trees: tuple[dict[str, Any], ...]
    commit_etag: str | None = None


@dataclass(frozen=True)
class _GithubIndex:
    snapshot: _GithubSnapshot
    candidates: tuple[GithubSkillCandidate, ...]
    warnings: tuple[str, ...]
    cached_at: float


@dataclass(frozen=True)
class _CandidateDelivery:
    candidate: GithubSkillCandidate
    files: dict[str, bytes]


def _normalize_skill_path(value: str) -> str:
    path = unquote(value).strip("/")
    if not path or path == ".":
        raise SkillInstallError("GitHub skill path cannot be empty")
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
        raise SkillInstallError("Unsafe GitHub skill path")
    return parsed.as_posix()


def parse_github_source(value: str) -> GithubSource:
    """Normalize owner/repo, GitHub repository URLs, and /tree/... URLs."""

    raw = value.strip()
    if not raw:
        raise SkillInstallError("GitHub source is required")
    if GITHUB_SOURCE_RE.fullmatch(raw):
        return GithubSource(repository=raw.removesuffix(".git"))

    parsed = urlparse(raw)
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        raise SkillInstallError(
            "GitHub source must be owner/repository or an https://github.com URL"
        )
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SkillInstallError("GitHub URL must include owner and repository")
    repository = f"{parts[0]}/{parts[1].removesuffix('.git')}"
    if not GITHUB_SOURCE_RE.fullmatch(repository):
        raise SkillInstallError("Invalid GitHub owner/repository")
    if len(parts) == 2:
        return GithubSource(repository=repository)
    if len(parts) < 4 or parts[2].lower() != "tree":
        raise SkillInstallError(
            "Only GitHub repository and /tree/<ref>/<skill> URLs are supported"
        )
    ref = parts[3].strip()
    if not ref or ref in {".", ".."}:
        raise SkillInstallError("Invalid GitHub ref")
    if len(parts) == 4:
        return GithubSource(repository=repository, ref=ref)
    return GithubSource(
        repository=repository, ref=ref, path=_normalize_skill_path("/".join(parts[4:]))
    )


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "giga-agent-skill-installer",
    }
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_error(response: httpx.Response) -> SkillInstallError:
    if response.status_code in {403, 429}:
        try:
            message = str(response.json().get("message") or "")
        except ValueError:
            message = ""
        if (
            "rate limit" in message.lower()
            or response.headers.get("x-ratelimit-remaining") == "0"
        ):
            return SkillInstallError(
                "GitHub API rate limit reached; try again later or configure GITHUB_TOKEN"
            )
    return SkillInstallError(
        f"GitHub request failed ({response.status_code}); check the public repository URL"
    )


async def _github_response(
    client: httpx.AsyncClient, url: str, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    response = await client.get(url, headers=headers)
    if response.status_code == 304:
        return response
    if response.status_code >= 400:
        raise _github_error(response)
    return response


async def _github_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await _github_response(client, url)
    if response.status_code == 304:
        raise SkillInstallError("Unexpected GitHub conditional response")
    value = response.json()
    if not isinstance(value, dict):
        raise SkillInstallError("Unexpected GitHub response")
    return value


def _json_from_response(response: httpx.Response) -> dict[str, Any]:
    value = response.json()
    if not isinstance(value, dict):
        raise SkillInstallError("Unexpected GitHub response")
    return value


def _snapshot_from_values(
    source: GithubSource,
    resolved_ref: str,
    commit: dict[str, Any],
    tree: dict[str, Any],
    *,
    commit_etag: str | None = None,
) -> _GithubSnapshot:
    commit_sha = str(commit.get("sha") or "")
    tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
    if not commit_sha or not tree_sha:
        raise SkillInstallError("GitHub commit does not contain a tree")
    entries = tree.get("tree")
    if not isinstance(entries, list) or tree.get("truncated"):
        raise SkillInstallError("GitHub repository tree is too large or truncated")
    blobs = tuple(
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "blob"
    )
    trees = tuple(
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") == "tree"
    )
    return _GithubSnapshot(
        source=source,
        resolved_ref=resolved_ref,
        resolved_commit=commit_sha,
        tree_sha=tree_sha,
        blobs=blobs,
        trees=trees,
        commit_etag=commit_etag,
    )


async def _load_snapshot(
    client: httpx.AsyncClient, source: GithubSource
) -> _GithubSnapshot:
    api = f"https://api.github.com/repos/{source.repository}"
    repository_response = await _github_response(client, api)
    repository = _json_from_response(repository_response)
    if repository.get("private") is True:
        raise SkillInstallError("Only public GitHub repositories are supported")
    resolved_ref = source.ref or str(repository.get("default_branch") or "HEAD")
    commit_response = await _github_response(
        client, f"{api}/commits/{quote(resolved_ref, safe='')}"
    )
    commit = _json_from_response(commit_response)
    tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
    if not tree_sha:
        raise SkillInstallError("GitHub commit does not contain a tree")
    tree = await _github_json(client, f"{api}/git/trees/{tree_sha}?recursive=1")
    return _snapshot_from_values(
        source,
        resolved_ref,
        commit,
        tree,
        commit_etag=commit_response.headers.get("etag"),
    )


async def _refresh_snapshot_if_changed(
    client: httpx.AsyncClient, index: _GithubIndex
) -> _GithubSnapshot | None:
    snapshot = index.snapshot
    if not snapshot.commit_etag:
        return await _load_snapshot(client, snapshot.source)
    api = f"https://api.github.com/repos/{snapshot.source.repository}"
    commit_response = await _github_response(
        client,
        f"{api}/commits/{quote(snapshot.resolved_ref, safe='')}",
        headers={"If-None-Match": snapshot.commit_etag},
    )
    if commit_response.status_code == 304:
        return None
    commit = _json_from_response(commit_response)
    tree_sha = str(((commit.get("commit") or {}).get("tree") or {}).get("sha") or "")
    if not tree_sha:
        raise SkillInstallError("GitHub commit does not contain a tree")
    tree = await _github_json(client, f"{api}/git/trees/{tree_sha}?recursive=1")
    return _snapshot_from_values(
        snapshot.source,
        snapshot.resolved_ref,
        commit,
        tree,
        commit_etag=commit_response.headers.get("etag"),
    )


def _entry_blob_sha(entry: dict[str, Any]) -> str:
    sha = str(entry.get("sha") or "")
    if not GITHUB_SHA_RE.fullmatch(sha):
        raise SkillInstallError("Invalid GitHub blob SHA")
    return sha


def _skills_sh_slug(name: str) -> str:
    """Match the skills CLI slug derived from a SKILL.md frontmatter name."""

    slug = re.sub(r"[\s_]+", "-", name.lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    if not slug:
        raise SkillInstallError("SKILL.md name cannot be converted to a skills.sh slug")
    return slug


def _safe_relative_skill_path(value: str) -> str:
    if not value or "\\" in value or any(char in value for char in ("\0", "\r", "\n")):
        raise SkillInstallError("Unsafe skill file path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path == PurePosixPath("."):
        raise SkillInstallError("Unsafe skill file path")
    return path.as_posix()


def _candidate_relative_path(candidate: GithubSkillCandidate, source_path: str) -> str:
    source = PurePosixPath(source_path)
    root = PurePosixPath(candidate.path) if candidate.path else None
    try:
        relative = source.relative_to(root) if root is not None else source
    except ValueError as exc:
        raise SkillInstallError(
            "GitHub skill file is outside of its selected path"
        ) from exc
    return _safe_relative_skill_path(relative.as_posix())


async def _read_raw_skill_manifest(
    client: httpx.AsyncClient,
    snapshot: _GithubSnapshot,
    candidate: GithubSkillCandidate,
) -> ParsedSkill:
    url = (
        f"https://raw.githubusercontent.com/{snapshot.source.repository}/"
        f"{quote(snapshot.resolved_commit, safe='')}/"
        f"{quote(candidate.manifest_path, safe='/')}"
    )
    response = await client.get(url)
    if response.status_code >= 400:
        raise SkillInstallError(
            f"Could not read SKILL.md for skills.sh download ({response.status_code})"
        )
    if len(response.content) > MAX_GITHUB_SKILL_BYTES:
        raise SkillInstallError("SKILL.md exceeds the allowed size")
    try:
        return parse_skill_md(response.text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SkillInstallError(f"Invalid SKILL.md: {exc}") from exc


def _skills_sh_payload(value: object) -> dict[str, bytes]:
    if not isinstance(value, dict) or not isinstance(value.get("files"), list):
        raise SkillInstallError("Unexpected skills.sh download response")

    files: dict[str, bytes] = {}
    total = 0
    for item in value["files"]:
        if not isinstance(item, dict):
            raise SkillInstallError("Unexpected skills.sh file entry")
        raw_path = item.get("path")
        contents = item.get("contents")
        if not isinstance(raw_path, str) or not isinstance(contents, str):
            raise SkillInstallError("Unexpected skills.sh file entry")
        path = _safe_relative_skill_path(raw_path)
        if path in files:
            raise SkillInstallError("skills.sh snapshot contains duplicate files")
        content = contents.encode("utf-8")
        total += len(content)
        if total > MAX_GITHUB_SKILL_BYTES:
            raise SkillInstallError("GitHub skill exceeds the allowed size")
        files[path] = content
        if len(files) > MAX_GITHUB_SKILL_FILES:
            raise SkillInstallError("GitHub skill contains too many files")

    manifest = select_skill_manifest_file(files)
    if manifest is None:
        raise SkillInstallError("skills.sh snapshot does not contain a root SKILL.md")
    try:
        parse_skill_md(files[manifest].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SkillInstallError(f"Invalid skills.sh SKILL.md: {exc}") from exc
    return files


async def _download_skills_sh_snapshot(
    client: httpx.AsyncClient, repository: str, slug: str
) -> dict[str, bytes]:
    owner, repo = repository.split("/", 1)
    url = (
        f"{SKILLS_SH_DOWNLOAD_URL}/api/download/"
        f"{quote(owner, safe='')}/{quote(repo, safe='')}/{quote(slug, safe='')}"
    )
    async with _skills_sh_download_semaphore:
        response = await client.get(url)
    if response.status_code >= 400:
        raise SkillInstallError(f"skills.sh download failed ({response.status_code})")
    try:
        return _skills_sh_payload(response.json())
    except ValueError as exc:
        raise SkillInstallError("Invalid skills.sh download response") from exc


async def _run_git(
    args: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    input_data: bytes | None = None,
) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdin=asyncio.subprocess.PIPE
            if input_data is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise SkillInstallError("Git is required for GitHub skill fallback") from exc
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input_data),
            timeout=GITHUB_PARTIAL_CLONE_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise SkillInstallError("GitHub partial clone timed out") from exc
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise SkillInstallError(
            "GitHub partial clone failed" + (f": {message[-400:]}" if message else "")
        )
    return stdout


def _safe_git_args(*args: str) -> list[str]:
    return [
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "protocol.file.allow=never",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "protocol.git.allow=never",
        "-c",
        "protocol.ssh.allow=never",
        "-c",
        "protocol.version=2",
        *args,
    ]


async def _partial_clone_deliveries(
    snapshot: _GithubSnapshot, candidates: list[GithubSkillCandidate]
) -> dict[str, _CandidateDelivery]:
    selected_files = sorted(
        {file.path for candidate in candidates for file in candidate.files}
    )
    if not selected_files:
        raise SkillInstallError(
            "GitHub skill index does not include files; preview again"
        )
    if len("\n".join(selected_files).encode()) > 128 * 1024:
        raise SkillInstallError(
            "Selected GitHub skill paths are too large for partial clone"
        )
    for source_path in selected_files:
        _safe_relative_skill_path(source_path)

    async with _partial_clone_semaphore:
        with tempfile.TemporaryDirectory(prefix="github_skill_clone_") as tmp:
            temp_root = Path(tmp)
            repo_dir = temp_root / "repository"
            git_home = temp_root / "git-home"
            git_home.mkdir()
            git_env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(git_home),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "/usr/bin/false",
                "GIT_ATTR_NOSYSTEM": "1",
            }
            repository_url = f"https://github.com/{snapshot.source.repository}.git"
            await _run_git(
                _safe_git_args("init", "--quiet", str(repo_dir)), cwd=None, env=git_env
            )
            await _run_git(
                _safe_git_args(
                    "-C", str(repo_dir), "remote", "add", "origin", repository_url
                ),
                cwd=None,
                env=git_env,
            )
            await _run_git(
                _safe_git_args(
                    "-C",
                    str(repo_dir),
                    "fetch",
                    "--depth=1",
                    "--filter=blob:none",
                    "--no-tags",
                    "origin",
                    snapshot.resolved_commit,
                ),
                cwd=None,
                env=git_env,
            )
            fetched_commit = (
                (
                    await _run_git(
                        _safe_git_args("-C", str(repo_dir), "rev-parse", "FETCH_HEAD"),
                        cwd=None,
                        env=git_env,
                    )
                )
                .decode()
                .strip()
            )
            if fetched_commit.lower() != snapshot.resolved_commit.lower():
                raise SkillInstallError(
                    "GitHub partial clone resolved an unexpected commit"
                )
            await _run_git(
                _safe_git_args(
                    "-C", str(repo_dir), "sparse-checkout", "init", "--no-cone"
                ),
                cwd=None,
                env=git_env,
            )
            await _run_git(
                _safe_git_args(
                    "-C",
                    str(repo_dir),
                    "sparse-checkout",
                    "set",
                    "--no-cone",
                    "--stdin",
                ),
                cwd=None,
                env=git_env,
                input_data=("\n".join(selected_files) + "\n").encode(),
            )
            await _run_git(
                _safe_git_args(
                    "-C", str(repo_dir), "checkout", "--quiet", "--detach", "FETCH_HEAD"
                ),
                cwd=None,
                env=git_env,
            )

            deliveries: dict[str, _CandidateDelivery] = {}
            for candidate in candidates:
                files: dict[str, bytes] = {}
                for item in candidate.files:
                    relative = _candidate_relative_path(candidate, item.path)
                    source = repo_dir / Path(*PurePosixPath(item.path).parts)
                    if source.is_symlink() or not source.is_file():
                        raise SkillInstallError(
                            "GitHub partial clone did not contain an expected skill file"
                        )
                    files[relative] = source.read_bytes()
                deliveries[candidate.path] = _CandidateDelivery(candidate, files)
            return deliveries


def _manifest_root(path: str) -> str:
    parent = PurePosixPath(path).parent.as_posix()
    return "" if parent == "." else parent


def _manifest_priority(path: str) -> tuple[int, str]:
    return (
        {"SKILL.md": 0, "skill.md": 1, "Skill.md": 2}.get(PurePosixPath(path).name, 3),
        path,
    )


def _is_within_scope(root: str, source_path: str | None) -> bool:
    if source_path is None:
        depth = len(PurePosixPath(root).parts) if root else 0
    elif root == source_path:
        depth = 0
    elif root.startswith(source_path + "/"):
        depth = len(PurePosixPath(root).relative_to(PurePosixPath(source_path)).parts)
    else:
        return False
    return depth <= MAX_GITHUB_SKILL_DEPTH


def _is_nested_skill(root: str, accepted_roots: list[str]) -> bool:
    return any(
        (parent == "" and root != "")
        or (parent != "" and root.startswith(parent + "/"))
        for parent in accepted_roots
    )


def _candidate_files(
    snapshot: _GithubSnapshot, root: str, manifest: dict[str, Any]
) -> tuple[GithubSkillFile, ...]:
    if not root:
        return (
            GithubSkillFile(
                path=str(manifest["path"]),
                blob_sha=_entry_blob_sha(manifest),
                size=int(manifest.get("size") or 0),
            ),
        )
    root_path = PurePosixPath(root)
    files: list[GithubSkillFile] = []
    for entry in snapshot.blobs:
        path = str(entry.get("path") or "")
        if not path:
            continue
        try:
            PurePosixPath(path).relative_to(root_path)
        except ValueError:
            continue
        files.append(
            GithubSkillFile(
                path=path,
                blob_sha=_entry_blob_sha(entry),
                size=int(entry.get("size") or 0),
            )
        )
    return tuple(sorted(files, key=lambda item: item.path))


def _folder_hash(snapshot: _GithubSnapshot, root: str, manifest: dict[str, Any]) -> str:
    if not root:
        return _entry_blob_sha(manifest)
    for entry in snapshot.trees:
        if str(entry.get("path") or "") == root:
            return _entry_blob_sha(entry)
    return _entry_blob_sha(manifest)


async def _discover_skills(
    client: httpx.AsyncClient, snapshot: _GithubSnapshot
) -> tuple[tuple[GithubSkillCandidate, ...], tuple[str, ...]]:
    _ = client
    manifests: dict[str, dict[str, Any]] = {}
    for entry in snapshot.blobs:
        path = str(entry.get("path") or "")
        if not path or not is_skill_manifest_filename(PurePosixPath(path).name):
            continue
        root = _manifest_root(path)
        if not _is_within_scope(root, snapshot.source.path):
            continue
        current = manifests.get(root)
        if current is None or _manifest_priority(path) < _manifest_priority(
            str(current.get("path") or "")
        ):
            manifests[root] = entry

    roots = sorted(
        manifests, key=lambda value: (len(PurePosixPath(value).parts), value)
    )
    selected_roots: list[str] = []
    for root in roots:
        if not _is_nested_skill(root, selected_roots):
            selected_roots.append(root)

    candidates: list[GithubSkillCandidate] = []
    for root in selected_roots:
        entry = manifests[root]
        display_name = (
            PurePosixPath(root).name
            if root
            else snapshot.source.repository.rsplit("/", 1)[-1]
        )
        candidates.append(
            GithubSkillCandidate(
                name=display_name,
                description="",
                path=root,
                manifest_path=str(entry["path"]),
                folder_hash=_folder_hash(snapshot, root, entry),
                manifest_sha=_entry_blob_sha(entry),
                files=_candidate_files(snapshot, root, entry),
            )
        )
    if not candidates:
        requested = f" at '{snapshot.source.path}'" if snapshot.source.path else ""
        raise SkillInstallError(
            f"No valid SKILL.md found in GitHub repository{requested}"
        )
    return tuple(candidates), ()


def _index_cache_key(source: GithubSource) -> str:
    identity = "\0".join(
        (
            source.repository.lower(),
            source.ref or "__default__",
            source.path or "__root__",
        )
    )
    return "skills:github:index:v1:" + hashlib.sha256(identity.encode()).hexdigest()


def _index_lock_key(source: GithubSource) -> str:
    return _index_cache_key(source) + ":lock"


def _serialize_index(index: _GithubIndex) -> dict[str, Any]:
    return {
        "version": GITHUB_INDEX_SCHEMA_VERSION,
        "cached_at": index.cached_at,
        "source": {
            "repository": index.snapshot.source.repository,
            "ref": index.snapshot.source.ref,
            "path": index.snapshot.source.path,
        },
        "resolved_ref": index.snapshot.resolved_ref,
        "resolved_commit": index.snapshot.resolved_commit,
        "tree_sha": index.snapshot.tree_sha,
        "commit_etag": index.snapshot.commit_etag,
        "warnings": list(index.warnings),
        "candidates": [
            {
                "name": candidate.name,
                "description": candidate.description,
                "path": candidate.path,
                "manifest_path": candidate.manifest_path,
                "folder_hash": candidate.folder_hash,
                "manifest_sha": candidate.manifest_sha,
                "files": [
                    {"path": file.path, "blob_sha": file.blob_sha, "size": file.size}
                    for file in candidate.files
                ],
            }
            for candidate in index.candidates
        ],
    }


def _deserialize_index(value: object) -> _GithubIndex | None:
    if (
        not isinstance(value, dict)
        or value.get("version") != GITHUB_INDEX_SCHEMA_VERSION
    ):
        return None
    try:
        source_value = value["source"]
        if not isinstance(source_value, dict):
            return None
        source = GithubSource(
            repository=str(source_value["repository"]),
            ref=str(source_value["ref"]) if source_value.get("ref") else None,
            path=str(source_value["path"]) if source_value.get("path") else None,
        )
        candidates = tuple(
            GithubSkillCandidate(
                name=str(item["name"]),
                description=str(item["description"]),
                path=str(item["path"]),
                manifest_path=str(item["manifest_path"]),
                folder_hash=str(item["folder_hash"])
                if item.get("folder_hash")
                else None,
                manifest_sha=str(item["manifest_sha"])
                if item.get("manifest_sha")
                else None,
                files=tuple(
                    GithubSkillFile(
                        path=str(file["path"]),
                        blob_sha=str(file["blob_sha"]),
                        size=int(file["size"]),
                    )
                    for file in item["files"]
                ),
            )
            for item in value["candidates"]
        )
        return _GithubIndex(
            snapshot=_GithubSnapshot(
                source=source,
                resolved_ref=str(value["resolved_ref"]),
                resolved_commit=str(value["resolved_commit"]),
                tree_sha=str(value["tree_sha"]),
                blobs=(),
                trees=(),
                commit_etag=str(value["commit_etag"])
                if value.get("commit_etag")
                else None,
            ),
            candidates=candidates,
            warnings=tuple(str(item) for item in value.get("warnings", [])),
            cached_at=float(value["cached_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def _cached_index(source: GithubSource) -> _GithubIndex | None:
    return _deserialize_index(await cache.get(_index_cache_key(source)))


async def _store_index(index: _GithubIndex) -> bool:
    payload = _serialize_index(index)
    size = len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    if size > MAX_GITHUB_INDEX_BYTES:
        return False
    await cache.set(
        _index_cache_key(index.snapshot.source),
        payload,
        expire=GITHUB_INDEX_TTL_SECONDS,
    )
    return True


async def _build_index(client: httpx.AsyncClient, source: GithubSource) -> _GithubIndex:
    snapshot = await _load_snapshot(client, source)
    candidates, warnings = await _discover_skills(client, snapshot)
    return _GithubIndex(
        snapshot=snapshot,
        candidates=candidates,
        warnings=warnings,
        cached_at=time.time(),
    )


async def _get_index(
    client: httpx.AsyncClient, source: GithubSource, *, force_refresh: bool = False
) -> tuple[_GithubIndex, Literal["fresh", "miss"]]:
    cached = await _cached_index(source)
    if cached is not None and not force_refresh:
        return cached, "fresh"
    async with cache.lock(_index_lock_key(source), expire=30, wait=True):
        cached = await _cached_index(source)
        if cached is not None and not force_refresh:
            return cached, "fresh"
        if cached is not None and force_refresh:
            refreshed_snapshot = await _refresh_snapshot_if_changed(client, cached)
            if refreshed_snapshot is None:
                refreshed = _GithubIndex(
                    snapshot=cached.snapshot,
                    candidates=cached.candidates,
                    warnings=cached.warnings,
                    cached_at=time.time(),
                )
                await _store_index(refreshed)
                return refreshed, "fresh"
            candidates, warnings = await _discover_skills(client, refreshed_snapshot)
            index = _GithubIndex(
                snapshot=refreshed_snapshot,
                candidates=candidates,
                warnings=warnings,
                cached_at=time.time(),
            )
        else:
            index = await _build_index(client, source)
        await _store_index(index)
        return index, "miss"


def _preview_from_index(
    source: GithubSource, index: _GithubIndex, cache_state: Literal["fresh", "miss"]
) -> GithubPreview:
    return GithubPreview(
        source=source,
        resolved_ref=index.snapshot.resolved_ref,
        resolved_commit=index.snapshot.resolved_commit,
        skills=index.candidates,
        warnings=index.warnings,
        cache_state=cache_state,
        cached_at=index.cached_at,
    )


async def preview_github_skills(
    service: SkillsService, *, owner_id, source: str
) -> GithubPreview:
    _ = service, owner_id
    parsed_source = parse_github_source(source)
    async with httpx.AsyncClient(
        headers=_headers(), follow_redirects=False, timeout=30.0
    ) as client:
        index, cache_state = await _get_index(client, parsed_source)
    return _preview_from_index(parsed_source, index, cache_state)


def _skill_source_url(source: GithubSource, commit: str, path: str) -> str:
    suffix = f"/{path}" if path else ""
    return f"https://github.com/{source.repository}/tree/{commit}{suffix}"


async def _install_candidate(
    service: SkillsService,
    *,
    owner_id,
    snapshot: _GithubSnapshot,
    candidate: GithubSkillCandidate,
    replace_existing: bool,
    sandbox,
    files: dict[str, bytes],
) -> GithubSkillInstall:
    if not files:
        raise SkillInstallError("GitHub skill does not contain files")
    if len(files) > MAX_GITHUB_SKILL_FILES:
        raise SkillInstallError("GitHub skill contains too many files")
    if sum(len(content) for content in files.values()) > MAX_GITHUB_SKILL_BYTES:
        raise SkillInstallError("GitHub skill exceeds the allowed size")

    with tempfile.TemporaryDirectory(prefix="github_skill_") as tmp:
        skill_root = Path(tmp) / "skill"
        skill_root.mkdir()
        digest = hashlib.sha256()
        total = 0
        for raw_relative, content in sorted(files.items()):
            relative = PurePosixPath(_safe_relative_skill_path(raw_relative))
            total += len(content)
            if total > MAX_GITHUB_SKILL_BYTES:
                raise SkillInstallError("GitHub skill exceeds the allowed size")
            target = (skill_root / Path(*relative.parts)).resolve()
            if not target.is_relative_to(skill_root.resolve()):
                raise SkillInstallError("Unsafe GitHub skill path")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            digest.update(relative.as_posix().encode())
            digest.update(b"\0")
            digest.update(content)

        manifest = service._find_skill_manifest_path(skill_root)
        parsed = parse_skill_md(manifest.read_text(encoding="utf-8"))
        content_hash = digest.hexdigest()
        existing = await service.repo.get_by_owner_and_name(owner_id, parsed.name)
        metadata = {
            **parsed.metadata,
            "github_source": snapshot.source.repository,
            "github_ref": snapshot.resolved_ref,
            "github_path": candidate.path,
            "github_manifest_path": candidate.manifest_path,
            "resolved_commit": snapshot.resolved_commit,
            "content_hash": content_hash,
            "folder_hash": candidate.folder_hash,
            "manifest_sha": candidate.manifest_sha,
        }
        if existing is not None:
            old = existing.metadata_ or {}
            if (
                existing.source_type == SkillSourceType.GITHUB
                and old.get("github_source") == snapshot.source.repository
                and old.get("github_path") == candidate.path
                and old.get("resolved_commit") == snapshot.resolved_commit
                and old.get("content_hash") == content_hash
            ):
                return GithubSkillInstall(
                    existing,
                    snapshot.resolved_commit,
                    content_hash,
                    status="already-installed",
                )
            if not replace_existing:
                raise SkillInstallError(
                    f"Skill {parsed.name!r} is already installed; enable replace_existing to update it"
                )
        storage_path = await sandbox.install_skill_files(
            owner_id, parsed.name, skill_root
        )
        source_url = _skill_source_url(
            snapshot.source, snapshot.resolved_commit, candidate.path
        )
        if existing is not None:
            skill = await service.repo.update(
                existing,
                description=parsed.description,
                source_type=SkillSourceType.GITHUB,
                source_url=source_url,
                storage_path=storage_path,
                metadata_=metadata,
            )
        else:
            skill = await service.repo.create(
                owner_id=owner_id,
                name=parsed.name,
                description=parsed.description,
                source_type=SkillSourceType.GITHUB,
                source_url=source_url,
                storage_path=storage_path,
                metadata_=metadata,
            )
            if skill is None:
                raise SkillInstallError(f"Skill {parsed.name!r} already exists")
        await service.invalidate_list_cache(owner_id)
        return GithubSkillInstall(skill, snapshot.resolved_commit, content_hash)


async def _already_installed_candidate(
    service: SkillsService,
    *,
    owner_id,
    snapshot: _GithubSnapshot,
    candidate: GithubSkillCandidate,
    manifest: ParsedSkill,
) -> GithubSkillInstall | None:
    existing = await service.repo.get_by_owner_and_name(owner_id, manifest.name)
    if existing is None:
        return None
    metadata = existing.metadata_ or {}
    if (
        existing.source_type == SkillSourceType.GITHUB
        and metadata.get("github_source") == snapshot.source.repository
        and metadata.get("github_path") == candidate.path
        and metadata.get("resolved_commit") == snapshot.resolved_commit
    ):
        return GithubSkillInstall(
            existing,
            snapshot.resolved_commit,
            str(metadata.get("content_hash") or ""),
            status="already-installed",
        )
    return None


async def install_github_skills(
    service: SkillsService,
    *,
    owner_id,
    source: str,
    selections: list[GithubInstallSelection],
    sandbox,
) -> GithubInstallBatch:
    parsed_source = parse_github_source(source)
    if not selections:
        raise SkillInstallError("Select at least one skill to install")
    paths = [selection.path for selection in selections]
    if len(paths) != len(set(paths)):
        raise SkillInstallError("A GitHub skill path may be selected only once")
    async with httpx.AsyncClient(
        headers=_headers(), follow_redirects=False, timeout=30.0
    ) as client:
        index, cache_state = await _get_index(client, parsed_source)
        preview = _preview_from_index(parsed_source, index, cache_state)
        by_path = {candidate.path: candidate for candidate in preview.skills}
        missing = [path for path in paths if path not in by_path]
        if missing:
            raise SkillInstallError(
                "Selected GitHub skill path is not present in the current repository: "
                + ", ".join(missing)
            )
        selected = [(selection, by_path[selection.path]) for selection in selections]
        results: dict[str, GithubInstallResult] = {}
        fallback: list[tuple[GithubInstallSelection, GithubSkillCandidate]] = []

        raw_headers = {"User-Agent": "giga-agent-skill-installer"}
        async with httpx.AsyncClient(
            headers=raw_headers, follow_redirects=False, timeout=30.0
        ) as raw_client:
            manifest_semaphore = asyncio.Semaphore(SKILLS_SH_DOWNLOAD_CONCURRENCY)

            async def read_manifest(candidate: GithubSkillCandidate) -> ParsedSkill:
                async with manifest_semaphore:
                    return await _read_raw_skill_manifest(
                        raw_client, index.snapshot, candidate
                    )

            manifest_values = await asyncio.gather(
                *(read_manifest(candidate) for _, candidate in selected),
                return_exceptions=True,
            )

        downloads: list[
            tuple[GithubInstallSelection, GithubSkillCandidate, ParsedSkill]
        ] = []
        for (selection, candidate), manifest_value in zip(selected, manifest_values):
            if isinstance(manifest_value, BaseException):
                logger.info(
                    "github_skill_delivery_fallback",
                    delivery="partial_clone",
                    reason="manifest_read_failed",
                    repository=index.snapshot.source.repository,
                    path=candidate.path,
                )
                fallback.append((selection, candidate))
                continue
            existing = await _already_installed_candidate(
                service,
                owner_id=owner_id,
                snapshot=index.snapshot,
                candidate=candidate,
                manifest=manifest_value,
            )
            if existing is not None:
                results[candidate.path] = GithubInstallResult(
                    candidate=candidate, status=existing.status, install=existing
                )
                continue
            downloads.append((selection, candidate, manifest_value))

        async with httpx.AsyncClient(
            headers={"User-Agent": "giga-agent-skill-installer"},
            follow_redirects=False,
            timeout=SKILLS_SH_DOWNLOAD_TIMEOUT_SECONDS,
        ) as skills_sh_client:
            download_values = await asyncio.gather(
                *(
                    _download_skills_sh_snapshot(
                        skills_sh_client,
                        index.snapshot.source.repository,
                        _skills_sh_slug(manifest.name),
                    )
                    for _, _, manifest in downloads
                ),
                return_exceptions=True,
            )

        for (selection, candidate, _), files in zip(downloads, download_values):
            if isinstance(files, BaseException):
                logger.info(
                    "github_skill_delivery_fallback",
                    delivery="partial_clone",
                    reason="skills_sh_download_failed",
                    repository=index.snapshot.source.repository,
                    path=candidate.path,
                )
                fallback.append((selection, candidate))
                continue
            try:
                installed = await _install_candidate(
                    service,
                    owner_id=owner_id,
                    snapshot=index.snapshot,
                    candidate=candidate,
                    replace_existing=selection.replace_existing,
                    sandbox=sandbox,
                    files=files,
                )
            except SkillInstallError as exc:
                results[candidate.path] = GithubInstallResult(
                    candidate=candidate, status="error", error=str(exc)
                )
            else:
                logger.info(
                    "github_skill_delivery",
                    delivery="skills_sh",
                    repository=index.snapshot.source.repository,
                    path=candidate.path,
                )
                results[candidate.path] = GithubInstallResult(
                    candidate=candidate, status=installed.status, install=installed
                )

        if fallback:
            fallback_candidates = [candidate for _, candidate in fallback]
            try:
                deliveries = await _partial_clone_deliveries(
                    index.snapshot, fallback_candidates
                )
            except SkillInstallError as exc:
                for _, candidate in fallback:
                    results[candidate.path] = GithubInstallResult(
                        candidate=candidate, status="error", error=str(exc)
                    )
            else:
                for selection, candidate in fallback:
                    try:
                        installed = await _install_candidate(
                            service,
                            owner_id=owner_id,
                            snapshot=index.snapshot,
                            candidate=candidate,
                            replace_existing=selection.replace_existing,
                            sandbox=sandbox,
                            files=deliveries[candidate.path].files,
                        )
                    except SkillInstallError as exc:
                        results[candidate.path] = GithubInstallResult(
                            candidate=candidate, status="error", error=str(exc)
                        )
                    else:
                        logger.info(
                            "github_skill_delivery",
                            delivery="partial_clone",
                            repository=index.snapshot.source.repository,
                            path=candidate.path,
                        )
                        results[candidate.path] = GithubInstallResult(
                            candidate=candidate,
                            status=installed.status,
                            install=installed,
                        )

        return GithubInstallBatch(
            preview=preview,
            results=tuple(results[selection.path] for selection in selections),
        )


def _snapshot_folder_hash(
    snapshot: _GithubSnapshot, path: str, manifest_path: str | None = None
) -> str | None:
    if not path:
        for entry in snapshot.blobs:
            entry_path = str(entry.get("path") or "")
            if manifest_path and entry_path == manifest_path:
                return _entry_blob_sha(entry)
            if (
                not manifest_path
                and is_skill_manifest_filename(PurePosixPath(entry_path).name)
                and _manifest_root(entry_path) == ""
            ):
                return _entry_blob_sha(entry)
        return None
    for entry in snapshot.trees:
        if str(entry.get("path") or "") == path:
            return _entry_blob_sha(entry)
    return None


async def check_github_skill_updates(
    service: SkillsService, *, owner_id
) -> tuple[GithubSkillUpdate, ...]:
    skills = [
        skill
        for skill in await service.repo.get_by_owner(owner_id)
        if skill.source_type == SkillSourceType.GITHUB
    ]
    grouped: dict[tuple[str, str], list[Skill]] = {}
    updates: list[GithubSkillUpdate] = []
    for skill in skills:
        metadata = skill.metadata_ or {}
        source = metadata.get("github_source")
        ref = metadata.get("github_ref")
        path = metadata.get("github_path")
        if (
            not isinstance(source, str)
            or not isinstance(ref, str)
            or not isinstance(path, str)
            or not metadata.get("folder_hash")
        ):
            updates.append(
                GithubSkillUpdate(
                    skill,
                    source if isinstance(source, str) else None,
                    ref if isinstance(ref, str) else None,
                    path if isinstance(path, str) else None,
                    "uncheckable",
                )
            )
            continue
        grouped.setdefault((source, ref), []).append(skill)

    semaphore = asyncio.Semaphore(3)

    async def check_group(
        source: str, ref: str, group: list[Skill]
    ) -> list[GithubSkillUpdate]:
        async with semaphore:
            try:
                async with httpx.AsyncClient(
                    headers=_headers(), follow_redirects=False, timeout=30.0
                ) as client:
                    first_path = str(
                        (group[0].metadata_ or {}).get("github_path") or ""
                    )
                    cached = (
                        await _cached_index(
                            GithubSource(source, ref, first_path or None)
                        )
                        or await _cached_index(GithubSource(source, ref))
                        or await _cached_index(GithubSource(source))
                    )
                    if cached is not None and cached.snapshot.commit_etag:
                        refreshed = await _refresh_snapshot_if_changed(client, cached)
                        if refreshed is None:
                            await _store_index(
                                _GithubIndex(
                                    snapshot=cached.snapshot,
                                    candidates=cached.candidates,
                                    warnings=cached.warnings,
                                    cached_at=time.time(),
                                )
                            )
                            cached_by_path = {
                                candidate.path: candidate
                                for candidate in cached.candidates
                            }
                            if all(
                                str((skill.metadata_ or {}).get("github_path") or "")
                                in cached_by_path
                                for skill in group
                            ):
                                return [
                                    GithubSkillUpdate(
                                        skill,
                                        source,
                                        ref,
                                        str(
                                            (skill.metadata_ or {}).get("github_path")
                                            or ""
                                        ),
                                        "up_to_date"
                                        if cached_by_path[
                                            str(
                                                (skill.metadata_ or {}).get(
                                                    "github_path"
                                                )
                                                or ""
                                            )
                                        ].folder_hash
                                        == (skill.metadata_ or {}).get("folder_hash")
                                        else "update_available",
                                        available_commit=cached.snapshot.resolved_commit,
                                    )
                                    for skill in group
                                ]
                            snapshot = await _load_snapshot(
                                client, GithubSource(source, ref)
                            )
                        else:
                            snapshot = refreshed
                    else:
                        snapshot = await _load_snapshot(
                            client, GithubSource(source, ref)
                        )
            except SkillInstallError as exc:
                return [
                    GithubSkillUpdate(
                        skill,
                        source,
                        ref,
                        str((skill.metadata_ or {}).get("github_path") or ""),
                        "error",
                        error=str(exc),
                    )
                    for skill in group
                ]
        result: list[GithubSkillUpdate] = []
        for skill in group:
            metadata = skill.metadata_ or {}
            path = str(metadata["github_path"])
            latest_hash = _snapshot_folder_hash(
                snapshot,
                path,
                str(metadata["github_manifest_path"])
                if metadata.get("github_manifest_path")
                else None,
            )
            if latest_hash is None:
                status: Literal[
                    "removed_from_source", "up_to_date", "update_available"
                ] = "removed_from_source"
            elif latest_hash == metadata.get("folder_hash"):
                status = "up_to_date"
            else:
                status = "update_available"
            result.append(
                GithubSkillUpdate(
                    skill,
                    source,
                    ref,
                    path,
                    status,
                    available_commit=snapshot.resolved_commit,
                )
            )
        return result

    checked = await asyncio.gather(
        *(check_group(source, ref, group) for (source, ref), group in grouped.items())
    )
    for group in checked:
        updates.extend(group)
    return tuple(updates)


async def install_github_skill(
    service: SkillsService,
    *,
    owner_id,
    requirement_name: str,
    source: str,
    ref: str | None,
    sandbox,
    replace_existing: bool = False,
) -> GithubSkillInstall:
    raw_source = source
    if ref:
        raw_source = f"https://github.com/{source}/tree/{quote(ref, safe='')}"
    preview = await preview_github_skills(service, owner_id=owner_id, source=raw_source)
    matches = [skill for skill in preview.skills if skill.name == requirement_name]
    if len(matches) != 1:
        raise SkillInstallError(
            f"Expected one GitHub skill named {requirement_name!r}, found {len(matches)}"
        )
    batch = await install_github_skills(
        service,
        owner_id=owner_id,
        source=raw_source,
        selections=[
            GithubInstallSelection(
                path=matches[0].path, replace_existing=replace_existing
            )
        ],
        sandbox=sandbox,
    )
    result = batch.results[0]
    if result.install is None:
        raise SkillInstallError(result.error or "Failed to install GitHub skill")
    return result.install
