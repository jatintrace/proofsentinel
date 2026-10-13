"""Canonical, link-safe path handling for ProofSentinel (Stage 5).

Nothing here opens, reads, hashes or executes a file. These functions only ask the
operating system what a path is (lstat, stat, resolve) and refuse anything ambiguous:
paths that escape the target root, links and reparse points, device names and
other Windows tricks. Callers use the canonical paths that come back.

Known limit: a path can change between the check and its later use. Later stages
verify file identity again before sensitive reads and writes.
"""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from proofsentinel.models import TargetDescriptor

_MAX_COMPONENT_CHARS = 255
_MAX_RELATIVE_PATH_CHARS = 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400  # Windows: symlinks, junctions and other reparse points

_FORBIDDEN_CHARACTERS = re.compile(r'[<>:"|?*\\]')

# Mirrors manifest.py. A test keeps the two sets identical.
_WINDOWS_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


class PathSafetyError(Exception):
    """A path is unsafe, ambiguous or missing. The message is safe to print."""


def _fail(what: str, message: str) -> NoReturn:
    raise PathSafetyError(f"{what}: {message}")


def _show(value: object, limit: int = 80) -> str:
    """Quote untrusted text so control characters appear as escapes, and shorten it."""
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedInterpreter:
    """The interpreter to run, after link checks."""

    entry: Path  # the path to execute: inside the target root, possibly a venv symlink
    final: Path  # the regular file at the end of any link chain


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolvedTarget:
    """A target whose root and interpreter passed every path check."""

    root: Path
    interpreter: ResolvedInterpreter


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------


def _is_link_like(info: os.stat_result) -> bool:
    """True for symbolic links and, on Windows, for any reparse point (junctions included)."""
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _lstat_or_none(path: Path) -> os.stat_result | None:
    """Inspect a path without following a final link. None means it does not exist."""
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as exc:
        raise PathSafetyError(f"cannot inspect a path: {exc.strerror or 'unknown error'}") from exc


def _reject_unsafe_text(path: Path, what: str) -> None:
    text = os.fspath(path)
    if "\x00" in text:
        _fail(what, "must not contain NUL")
    if text.startswith(("\\\\", "//")):
        _fail(what, "network (UNC) and device paths are not allowed")


def _validate_component(component: str, what: str) -> None:
    if component in ("", ".", ".."):
        _fail(what, f"has an empty, '.' or '..' part: {_show(component)}")
    if len(component) > _MAX_COMPONENT_CHARS:
        _fail(what, f"has a part longer than {_MAX_COMPONENT_CHARS} characters")
    if not component.isprintable() or _FORBIDDEN_CHARACTERS.search(component):
        _fail(what, f"part {_show(component)} contains a character that is not allowed")
    if component != component.rstrip(" ."):
        _fail(what, f"part {_show(component)} ends with a space or period")
    if component.split(".", 1)[0].rstrip(" ").lower() in _WINDOWS_RESERVED_NAMES:
        _fail(what, f"part {_show(component)} is a reserved Windows device name")


def _split_relative(relative: str, what: str) -> tuple[str, ...]:
    """Check a relative path written with forward slashes and split it into parts."""
    if not relative:
        _fail(what, "must not be empty")
    if len(relative) > _MAX_RELATIVE_PATH_CHARS:
        _fail(what, f"is longer than {_MAX_RELATIVE_PATH_CHARS} characters")
    if relative.startswith("/") or re.match(r"[A-Za-z]:", relative):
        _fail(what, "must be relative to the target root")
    if "\\" in relative:
        _fail(what, "must use forward slashes")
    components = tuple(relative.split("/"))
    for component in components:
        _validate_component(component, what)
    return components


def _reject_links_below(
    root: Path, components: tuple[str, ...], what: str, *, allow_final_symlink: bool = False
) -> None:
    """Refuse links and reparse points on the way down from root. Missing parts end the walk."""
    current = root
    for index, component in enumerate(components):
        current = current / component
        info = _lstat_or_none(current)
        if info is None:
            return
        if not _is_link_like(info):
            continue
        is_final = index == len(components) - 1
        if is_final and allow_final_symlink and stat.S_ISLNK(info.st_mode):
            continue
        _fail(what, f"passes through a link or reparse point at {_show(component)}")


def _resolve(path: Path, what: str, *, strict: bool) -> Path:
    try:
        return path.resolve(strict=strict)
    except (OSError, RuntimeError) as exc:  # missing parts, link loops, permissions
        raise PathSafetyError(f"{what}: cannot be resolved ({type(exc).__name__})") from exc


# ---------------------------------------------------------------------------
# Public checks
# ---------------------------------------------------------------------------


def resolve_target_root(manifest_path: Path, root: Path) -> Path:
    """Return the canonical target root. A relative root is relative to the manifest's folder."""
    what = "target.root"
    _reject_unsafe_text(root, what)
    manifest_dir = _resolve(manifest_path, "manifest path", strict=True).parent
    joined = manifest_dir / root  # an absolute root replaces manifest_dir
    info = _lstat_or_none(joined)
    if info is None:
        _fail(what, "does not exist")
    if _is_link_like(info):
        _fail(what, "must not be a symbolic link, junction or reparse point")
    canonical = _resolve(joined, what, strict=True)
    if not stat.S_ISDIR(os.stat(canonical).st_mode):
        _fail(what, "must be a directory")
    return canonical


def resolve_within_root(
    root: Path, relative: str, *, what: str = "path", must_exist: bool = True
) -> Path:
    """Return the canonical path of a file inside the target root (for fixtures and file checks).

    The path must be relative, written with forward slashes, free of '..' and
    Windows tricks, and must not pass through any link or reparse point.
    """
    components = _split_relative(relative, what)
    _reject_links_below(root, components, what)
    resolved = _resolve(root.joinpath(*components), what, strict=must_exist)
    if not resolved.is_relative_to(root):
        _fail(what, "escapes the target root")
    return resolved


def resolve_interpreter(root: Path, python: Path) -> ResolvedInterpreter:
    """Check the target's Python interpreter. The entry must be inside the root.

    A final symbolic link (the usual virtual-environment layout on Linux) is allowed
    if the whole chain ends at an existing regular file. Any other link or
    reparse point is refused.
    """
    what = "target.python"
    _reject_unsafe_text(python, what)
    components = _split_relative(python.as_posix(), what)
    _reject_links_below(root, components, what, allow_final_symlink=True)
    entry = root.joinpath(*components)
    if _lstat_or_none(entry) is None:
        _fail(what, "does not exist")
    final = _resolve(entry, what, strict=True)
    if not stat.S_ISREG(os.stat(final).st_mode):
        _fail(what, "must resolve to a regular file")
    return ResolvedInterpreter(entry=entry, final=final)


def resolve_target(manifest_path: Path, target: TargetDescriptor) -> ResolvedTarget:
    """Resolve the target root and interpreter named by a validated manifest."""
    root = resolve_target_root(manifest_path, target.root)
    return ResolvedTarget(
        root=root, interpreter=resolve_interpreter(root, target.python_executable)
    )


def preflight_evidence_directory(output: Path, target_root: Path) -> Path:
    """Check an evidence directory path without creating anything. Returns its canonical path.

    The directory must not exist, its parent must, and it must lie outside the target root.
    """
    what = "evidence directory"
    _reject_unsafe_text(output, what)
    if output.name in ("", ".", ".."):
        _fail(what, "must name a new directory")
    _validate_component(output.name, what)
    parent = _resolve(output.parent, f"{what} parent", strict=True)
    if not stat.S_ISDIR(os.stat(parent).st_mode):
        _fail(what, "parent must be a directory")
    candidate = parent / output.name
    if os.path.lexists(candidate):
        _fail(what, "already exists; v0.1 never overwrites evidence")
    if candidate.is_relative_to(target_root):
        _fail(what, "must be outside the target repository")
    return candidate