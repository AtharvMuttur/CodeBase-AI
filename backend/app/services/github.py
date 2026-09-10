"""GitHub URL parsing and cloning helpers for Phase 2 ingestion.

This module is intentionally small:

* ``parse_github_url`` validates a user-supplied URL and returns a structured
  ``GithubRef``. Anything that doesn't look like a public ``github.com``
  ``owner/repo`` URL is rejected — we never want to feed untrusted input
  into ``subprocess.run``.
* ``default_branch`` runs ``git ls-remote --symref`` to discover the
  repository's default branch (the GitHub UI doesn't expose it through
  the public REST API without a token).
* ``clone_to_temp`` clones the repo into a temporary directory under the
  configured workspace root and returns the path plus the HEAD commit
  SHA. The token (if configured) is injected only into the clone URL
  in-process and never logged or returned.

All ``subprocess.run`` calls use list-form argv with ``shell=False`` so
there's no opportunity for command injection. The parser has already
restricted the URL to ``https://github.com/<owner>/<repo>`` before any
shell is involved.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _git_environment() -> dict[str, str]:
    """Prevent Git from blocking the background indexer on a prompt."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


# GitHub enforces the same character set for usernames and repo names
# (with a couple of edge cases for legacy repos). We keep the regex
# strict so a path-traversal or shell-metacharacter attempt is rejected
# at the URL-parse boundary.
_GH_OWNER_RE = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_GH_NAME_RE = r"[A-Za-z0-9._-]+"

# Bare URL: https://github.com/<owner>/<repo>  (optional .git and trailing /)
_GH_URL_RE = re.compile(
    rf"^https?://github\.com/(?P<owner>{_GH_OWNER_RE})/(?P<name>{_GH_NAME_RE})(?:\.git)?/?$"
)


class GithubURLError(ValueError):
    """Raised when a URL is not a valid public github.com owner/repo URL."""


@dataclass(frozen=True)
class GithubRef:
    """A parsed GitHub repository reference."""

    owner: str
    name: str
    full_name: str          # "owner/name"
    clone_url: str          # "https://github.com/owner/name.git"


def parse_github_url(url: str) -> GithubRef:
    """Parse and validate a GitHub repository URL.

    Accepted forms:
        https://github.com/<owner>/<repo>
        https://github.com/<owner>/<repo>.git
        http://github.com/<owner>/<repo>           (rewritten to https)

    Rejected: anything not under github.com, anything with extra path
    segments, query strings, fragments, or owner/name containing
    characters outside GitHub's allowed set.
    """
    if not isinstance(url, str) or not url.strip():
        raise GithubURLError("github url is empty")

    candidate = url.strip()

    # Parse first so we can reject non-github hosts without touching a regex.
    parsed = urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        raise GithubURLError("github url must use http or https")
    if parsed.netloc.lower() != "github.com":
        raise GithubURLError("github url must be on github.com")
    if parsed.query or parsed.fragment:
        raise GithubURLError("github url must not contain query strings or fragments")

    # The path should be exactly /<owner>/<repo> (with optional .git).
    match = _GH_URL_RE.match(candidate)
    if not match:
        raise GithubURLError(
            "github url must look like https://github.com/<owner>/<repo>"
        )

    owner = match.group("owner")
    # The regex captures ``.git`` as part of the name when present —
    # strip it so downstream code (and the API response) sees the
    # canonical repo name.
    raw_name = match.group("name")
    name = raw_name[:-4] if raw_name.endswith(".git") else raw_name

    # Final defensive length check — paths over 100 chars are pathological.
    if len(owner) > 100 or len(name) > 100:
        raise GithubURLError("github owner or name is too long")

    return GithubRef(
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        clone_url=f"https://github.com/{owner}/{name}.git",
    )


def _build_auth_url(ref: GithubRef, token: Optional[str]) -> str:
    """Build a clone URL with an optional token.

    The token is interpolated into the URL only when configured. The
    returned URL is never logged or returned to the API client — it's
    used solely by ``subprocess.run`` for the duration of the clone.
    """
    if not token:
        return ref.clone_url
    # Strip any leading "https://" from the clone URL so we can inject
    # the credential inline. Result is still https — the basic-auth
    # segment is just URL-encoded.
    return f"https://x-access-token:{token}@github.com/{ref.owner}/{ref.name}.git"


def default_branch(ref: GithubRef, *, token: Optional[str] = None) -> str:
    """Return the repository's default branch.

    Uses ``git ls-remote --symref <url> HEAD`` and parses the line
    starting with ``ref: refs/heads/<branch>``.

    Falls back to ``"main"`` if the remote didn't return a symref
    (very old repos).
    """
    auth_url = _build_auth_url(ref, token)
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--symref", auth_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
            env=_git_environment(),
        )
    except subprocess.TimeoutExpired as exc:
        raise GithubURLError(f"git ls-remote timed out for {ref.full_name}") from exc
    except FileNotFoundError as exc:
        raise GithubURLError("git is not installed on the backend container") from exc

    if result.returncode != 0:
        # Git exits non-zero for 404 / 401 / 403; surface a clean error.
        stderr = (result.stderr or "").strip().splitlines()
        msg = stderr[-1] if stderr else f"git ls-remote failed with code {result.returncode}"
        if "could not read Username" in msg or "terminal prompts disabled" in msg:
            raise GithubURLError(
                "GitHub authentication is required for this repository; "
                "configure GITHUB_TOKEN and retry"
            )
        raise GithubURLError(f"{msg} (repo={ref.full_name})")

    # Format: "ref: refs/heads/main\tHEAD"
    for line in (result.stdout or "").splitlines():
        if line.startswith("ref: refs/heads/"):
            return line.split(":", 1)[1].split()[0].replace("refs/heads/", "").strip()
    return "main"


def clone_to_temp(
    ref: GithubRef,
    *,
    branch: str,
    token: Optional[str] = None,
    workspace_root: Optional[Path] = None,
) -> tuple[Path, str]:
    """Clone ``ref`` into a temp directory and return (path, commit_sha).

    The clone runs in a directory under ``workspace_root`` so the
    backend process can find it (and the Docker volume already maps
    ``/app/workspace``). The function takes care of:

    * building the auth URL when a token is configured,
    * running ``git clone --depth 1 --branch <branch>`` (shallow — we
      only need the working tree for Phase 2),
    * capturing the HEAD commit SHA,
    * cleaning up if anything goes wrong.

    The token is never logged or returned to the caller.
    """
    # Default to the same workspace directory the Docker compose
    # volume mounts at /app/workspace. Override by passing
    # ``workspace_root`` (used by tests).
    root = Path(workspace_root) if workspace_root else Path("/app/workspace")
    root.mkdir(parents=True, exist_ok=True)

    # `tempfile.mkdtemp` may live on a different filesystem than our
    # workspace volume (e.g. /tmp on a host that doesn't bind-mount it).
    # We create the directory inside the workspace explicitly so the
    # resulting path is reachable by the rest of the indexer.
    temp_dir = tempfile.mkdtemp(prefix=f"github-{ref.name}-", dir=str(root))
    target = Path(temp_dir)
    auth_url = _build_auth_url(ref, token)

    logger.info(
        "github_clone_start",
        extra={"repo": ref.full_name, "branch": branch},
    )

    try:
        # --depth 1 keeps the clone cheap and avoids pulling history
        # we will never inspect. --single-branch avoids fetching
        # every other branch on the remote.
        result = subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                branch,
                "--single-branch",
                auth_url,
                str(target),
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            shell=False,
            env=_git_environment(),
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip().splitlines()
            msg = (
                stderr[-1]
                if stderr
                else f"git clone failed with code {result.returncode}"
            )
            # The auth URL contains the token — strip it from the error
            # message before re-raising so we don't leak credentials to
            # logs.
            msg = msg.replace(token, "***") if token else msg
            if "could not read Username" in msg or "terminal prompts disabled" in msg:
                raise GithubURLError(
                    "GitHub authentication is required for this repository; "
                    "configure GITHUB_TOKEN and retry"
                )
            raise GithubURLError(f"clone failed for {ref.full_name}: {msg}")

        # Read the HEAD commit SHA inside the cloned repo.
        head_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
            cwd=str(target),
        )
        if head_proc.returncode != 0:
            raise GithubURLError(
                f"could not read HEAD commit after cloning {ref.full_name}"
            )
        commit_sha = head_proc.stdout.strip()
        logger.info(
            "github_clone_done",
            extra={"repo": ref.full_name, "branch": branch, "commit": commit_sha[:12]},
        )
        return target, commit_sha
    except Exception:
        # Best-effort cleanup if the clone fails mid-way.
        shutil.rmtree(target, ignore_errors=True)
        raise


def remove_temp(path: Path) -> None:
    """Remove a cloned tree. Errors are swallowed — the temp dir is
    already best-effort, and the next container rebuild will garbage
    collect it anyway."""
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "GithubRef",
    "GithubURLError",
    "parse_github_url",
    "default_branch",
    "clone_to_temp",
    "remove_temp",
]
