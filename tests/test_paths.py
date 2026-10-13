"""Tests for canonical, link-safe path handling (Stage 5)."""

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from proofsentinel import manifest as manifest_module
from proofsentinel import paths as paths_module
from proofsentinel.models import TargetDescriptor
from proofsentinel.paths import (
    PathSafetyError,
    preflight_evidence_directory,
    resolve_interpreter,
    resolve_target,
    resolve_target_root,
    resolve_within_root,
)

REPARSE_POINT = 0x400


# --- helpers ---------------------------------------------------------------


@pytest.fixture(scope="session")
def symlinks_work(tmp_path_factory: pytest.TempPathFactory) -> bool:
    probe = tmp_path_factory.mktemp("symlink-probe")
    (probe / "target").write_text("x", encoding="utf-8")
    try:
        os.symlink(probe / "target", probe / "link")
    except (OSError, NotImplementedError):
        return False
    return True


@pytest.fixture
def need_symlinks(symlinks_work: bool) -> None:
    """Skip when this machine cannot create symlinks, but never skip silently in CI."""
    if symlinks_work:
        return
    message = "cannot create symlinks on this machine"
    if os.environ.get("CI") == "true":
        pytest.fail(f"{message}; link tests are required in CI")
    pytest.skip(message)


def make_junction(link: Path, target: Path) -> None:
    import _winapi  # exists only on Windows

    _winapi.CreateJunction(str(target), str(link))


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions only")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A canonical target root with a fixture file and a fake interpreter inside it."""
    (tmp_path / "target").mkdir()
    target = (tmp_path / "target").resolve()
    (target / "tests").mkdir()
    (target / "tests" / "case.json").write_text("{}", encoding="utf-8")
    (target / ".venv" / "bin").mkdir(parents=True)
    (target / ".venv" / "bin" / "python").write_text("fake", encoding="utf-8")
    return target


@pytest.fixture
def manifest_file(tmp_path: Path) -> Path:
    folder = tmp_path / "manifests"
    folder.mkdir()
    path = folder / "manifest.toml"
    path.write_text("# placeholder\n", encoding="utf-8")
    return path


def target_for(root: Path, python: str = ".venv/bin/python") -> TargetDescriptor:
    return TargetDescriptor(
        name="Example",
        root=root,
        python_executable=Path(python),
        expected_git_commit="a" * 40,
    )


# --- classification of links and reparse points ----------------------------


def test_link_classification_uses_symlink_mode_and_reparse_flag() -> None:
    is_link_like = paths_module._is_link_like
    plain_dir = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
    plain_file = SimpleNamespace(st_mode=stat.S_IFREG)
    symlink = SimpleNamespace(st_mode=stat.S_IFLNK)
    junction = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=REPARSE_POINT)
    other_flags = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x20)
    assert not is_link_like(plain_dir)
    assert not is_link_like(plain_file)
    assert not is_link_like(other_flags)
    assert is_link_like(symlink)
    assert is_link_like(junction)


def test_reserved_name_lists_cannot_drift_apart() -> None:
    assert paths_module._WINDOWS_RESERVED_NAMES == manifest_module._WINDOWS_RESERVED_NAMES


# --- relative paths inside the target root ---------------------------------


def test_fixture_inside_root_resolves_to_a_canonical_path(root: Path) -> None:
    assert resolve_within_root(root, "tests/case.json") == root / "tests" / "case.json"


def test_missing_fixture_is_rejected_unless_existence_is_not_required(root: Path) -> None:
    with pytest.raises(PathSafetyError, match="cannot be resolved"):
        resolve_within_root(root, "tests/missing.json")
    assert resolve_within_root(root, "tests/missing.json", must_exist=False) == (
        root / "tests" / "missing.json"
    )


@pytest.mark.parametrize(
    ("relative", "fragment"),
    [
        ("", "must not be empty"),
        (".", "empty, '.' or '..'"),
        ("..", "empty, '.' or '..'"),
        ("../outside.json", "empty, '.' or '..'"),
        ("tests/../../outside.json", "empty, '.' or '..'"),
        ("tests/../case.json", "empty, '.' or '..'"),
        ("tests/./case.json", "empty, '.' or '..'"),
        ("tests//case.json", "empty, '.' or '..'"),
        ("tests/", "empty, '.' or '..'"),
        ("/etc/passwd", "relative"),
        ("C:/Windows/win.ini", "relative"),
        ("C:win.ini", "relative"),
        ("tests\\case.json", "forward slashes"),
        ("\\\\server\\share\\x", "forward slashes"),
        ("file.txt:hidden", "not allowed"),
        ("a<b", "not allowed"),
        ("a>b", "not allowed"),
        ('a"b', "not allowed"),
        ("a|b", "not allowed"),
        ("a?b", "not allowed"),
        ("a*b", "not allowed"),
        ("tab\there", "not allowed"),
        ("escape\x1bhere", "not allowed"),
        ("nul\x00byte", "not allowed"),
        ("bidi\u202eflip", "not allowed"),
        ("trailing.", "ends with a space or period"),
        ("trailing ", "ends with a space or period"),
        ("dir./file", "ends with a space or period"),
        ("con", "reserved Windows device name"),
        ("CON", "reserved Windows device name"),
        ("nul.txt", "reserved Windows device name"),
        ("tests/aux", "reserved Windows device name"),
        ("tests/com1.log", "reserved Windows device name"),
        ("lpt9", "reserved Windows device name"),
        ("a" * 256, "longer than 255"),
        ("a/" * 600, "longer than 1024"),
    ],
)
def test_unsafe_relative_paths_are_rejected(root: Path, relative: str, fragment: str) -> None:
    with pytest.raises(PathSafetyError) as excinfo:
        resolve_within_root(root, relative)
    assert fragment in str(excinfo.value)


def test_names_that_only_resemble_reserved_names_are_accepted(root: Path) -> None:
    for name in ("console.txt", "nullable", "com10", "auxiliary.json"):
        assert resolve_within_root(root, name, must_exist=False) == root / name


def test_control_characters_are_escaped_in_error_messages(root: Path) -> None:
    with pytest.raises(PathSafetyError) as excinfo:
        resolve_within_root(root, "escape\x1bhere")
    assert "\x1b" not in str(excinfo.value)


def test_symlink_to_outside_the_root_is_rejected(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    os.symlink(outside, root / "tests" / "escape.json")
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_within_root(root, "tests/escape.json")


def test_symlink_that_stays_inside_the_root_is_also_rejected(
    root: Path, need_symlinks: None
) -> None:
    os.symlink(root / "tests" / "case.json", root / "tests" / "alias.json")
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_within_root(root, "tests/alias.json")


def test_symlinked_directory_in_the_path_is_rejected(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "case.json").write_text("{}", encoding="utf-8")
    os.symlink(elsewhere, root / "linked", target_is_directory=True)
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_within_root(root, "linked/case.json")


def test_dangling_symlink_is_rejected(root: Path, need_symlinks: None) -> None:
    os.symlink(root / "does-not-exist", root / "dangling.json")
    with pytest.raises(PathSafetyError):
        resolve_within_root(root, "dangling.json", must_exist=False)


def test_containment_check_is_a_second_layer_behind_the_link_check(
    root: Path, tmp_path: Path, need_symlinks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    os.symlink(outside, root / "tests" / "escape.json")
    monkeypatch.setattr(paths_module, "_reject_links_below", lambda *args, **kwargs: None)
    with pytest.raises(PathSafetyError, match="escapes the target root"):
        resolve_within_root(root, "tests/escape.json")


@windows_only
def test_junction_in_the_path_is_rejected(root: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "case.json").write_text("{}", encoding="utf-8")
    make_junction(root / "junction", elsewhere)
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_within_root(root, "junction/case.json")


# --- the target root -------------------------------------------------------


def test_relative_root_is_resolved_against_the_manifest_folder(
    manifest_file: Path, root: Path
) -> None:
    relative = Path(os.path.relpath(root, manifest_file.parent))
    assert resolve_target_root(manifest_file, relative) == root


def test_absolute_root_is_accepted(manifest_file: Path, root: Path) -> None:
    assert resolve_target_root(manifest_file, root) == root


def test_missing_root_is_rejected(manifest_file: Path, tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError, match="does not exist"):
        resolve_target_root(manifest_file, tmp_path / "nowhere")


def test_root_that_is_a_file_is_rejected(manifest_file: Path, root: Path) -> None:
    with pytest.raises(PathSafetyError, match="must be a directory"):
        resolve_target_root(manifest_file, root / "tests" / "case.json")


@pytest.mark.parametrize("text", ["\\\\server\\share\\project", "//server/share/project"])
def test_network_paths_are_rejected_for_the_root(manifest_file: Path, text: str) -> None:
    with pytest.raises(PathSafetyError, match="network"):
        resolve_target_root(manifest_file, Path(text))


def test_relative_root_follows_a_symlinked_manifest_to_its_real_folder(
    tmp_path: Path, need_symlinks: None
) -> None:
    real_dir = tmp_path / "a" / "b"
    real_dir.mkdir(parents=True)
    real_manifest = real_dir / "manifest.toml"
    real_manifest.write_text("# placeholder\n", encoding="utf-8")
    (tmp_path / "a" / "target").mkdir()
    (tmp_path / "target").mkdir()
    link_dir = tmp_path / "links"
    link_dir.mkdir()
    os.symlink(real_manifest, link_dir / "manifest.toml")
    result = resolve_target_root(link_dir / "manifest.toml", Path("../target"))
    assert result == (tmp_path / "a" / "target").resolve()


def test_nul_in_a_root_is_rejected_cleanly(manifest_file: Path) -> None:
    with pytest.raises(PathSafetyError, match="NUL"):
        resolve_target_root(manifest_file, Path("bad\x00root"))


def test_symlinked_root_is_rejected(
    manifest_file: Path, root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    link = tmp_path / "root-link"
    os.symlink(root, link, target_is_directory=True)
    with pytest.raises(PathSafetyError, match="must not be a symbolic link"):
        resolve_target_root(manifest_file, link)


def test_link_further_up_the_path_is_allowed_and_canonicalized(
    manifest_file: Path, root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    parent_link = tmp_path / "parent-link"
    os.symlink(root.parent, parent_link, target_is_directory=True)
    assert resolve_target_root(manifest_file, parent_link / "target") == root


@windows_only
def test_junction_root_is_rejected(manifest_file: Path, root: Path, tmp_path: Path) -> None:
    junction = tmp_path / "root-junction"
    make_junction(junction, root)
    with pytest.raises(PathSafetyError, match="must not be a symbolic link"):
        resolve_target_root(manifest_file, junction)


# --- the interpreter -------------------------------------------------------


def test_regular_interpreter_inside_the_root_is_accepted(root: Path) -> None:
    result = resolve_interpreter(root, Path(".venv/bin/python"))
    assert result.entry == root / ".venv" / "bin" / "python"
    assert result.final == result.entry


def test_venv_style_symlink_to_a_system_file_is_accepted(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    system_python = tmp_path / "system-python"
    system_python.write_text("fake", encoding="utf-8")
    (root / ".venv" / "bin" / "python").unlink()
    os.symlink(system_python, root / ".venv" / "bin" / "python")
    result = resolve_interpreter(root, Path(".venv/bin/python"))
    assert (
        result.entry == root / ".venv" / "bin" / "python"
    )  # the path to execute stays in the venv
    assert result.final == system_python.resolve()


def test_symlink_chain_is_accepted_when_it_ends_at_a_regular_file(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    real = tmp_path / "real-python"
    real.write_text("fake", encoding="utf-8")
    middle = tmp_path / "python3"
    os.symlink(real, middle)
    (root / ".venv" / "bin" / "python").unlink()
    os.symlink(middle, root / ".venv" / "bin" / "python")
    assert resolve_interpreter(root, Path(".venv/bin/python")).final == real.resolve()


def test_symlink_to_a_directory_is_rejected(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    (root / ".venv" / "bin" / "python").unlink()
    os.symlink(tmp_path, root / ".venv" / "bin" / "python", target_is_directory=True)
    with pytest.raises(PathSafetyError, match="regular file"):
        resolve_interpreter(root, Path(".venv/bin/python"))


def test_dangling_and_looping_symlinks_are_rejected(root: Path, need_symlinks: None) -> None:
    entry = root / ".venv" / "bin" / "python"
    entry.unlink()
    os.symlink(root / "missing", entry)
    with pytest.raises(PathSafetyError):
        resolve_interpreter(root, Path(".venv/bin/python"))
    entry.unlink()
    os.symlink(entry, entry)  # points at itself
    with pytest.raises(PathSafetyError):
        resolve_interpreter(root, Path(".venv/bin/python"))


def test_symlinked_directory_above_the_interpreter_is_rejected(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    elsewhere = tmp_path / "elsewhere-venv"
    (elsewhere / "bin").mkdir(parents=True)
    (elsewhere / "bin" / "python").write_text("fake", encoding="utf-8")
    os.symlink(elsewhere, root / "linked-venv", target_is_directory=True)
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_interpreter(root, Path("linked-venv/bin/python"))


def test_reparse_point_that_is_not_a_symlink_is_rejected_as_interpreter(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_lstat = paths_module._lstat_or_none
    entry = root / ".venv" / "bin" / "python"
    reparse = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=REPARSE_POINT)

    def fake_lstat(path: Path) -> object:
        return reparse if path == entry else real_lstat(path)

    monkeypatch.setattr(paths_module, "_lstat_or_none", fake_lstat)
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_interpreter(root, Path(".venv/bin/python"))


def test_missing_interpreter_is_rejected(root: Path) -> None:
    with pytest.raises(PathSafetyError, match="does not exist"):
        resolve_interpreter(root, Path(".venv/bin/python3"))


def test_interpreter_that_is_a_directory_is_rejected(root: Path) -> None:
    with pytest.raises(PathSafetyError, match="regular file"):
        resolve_interpreter(root, Path(".venv/bin"))


@pytest.mark.parametrize(
    "python",
    [
        "/usr/bin/python3",
        "C:/Python/python.exe",
        "C:python.exe",
        "../outside/python",
        ".venv/../python",
    ],
)
def test_interpreter_must_be_relative_and_stay_inside_the_root(root: Path, python: str) -> None:
    with pytest.raises(PathSafetyError):
        resolve_interpreter(root, Path(python))


@windows_only
def test_junction_above_the_interpreter_is_rejected(root: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere-venv"
    (elsewhere / "bin").mkdir(parents=True)
    (elsewhere / "bin" / "python").write_text("fake", encoding="utf-8")
    make_junction(root / "junction-venv", elsewhere)
    with pytest.raises(PathSafetyError, match="link or reparse point"):
        resolve_interpreter(root, Path("junction-venv/bin/python"))


def test_resolve_target_combines_root_and_interpreter(manifest_file: Path, root: Path) -> None:
    result = resolve_target(manifest_file, target_for(root))
    assert result.root == root
    assert result.interpreter.entry == root / ".venv" / "bin" / "python"


# --- the evidence directory ------------------------------------------------


def test_new_directory_next_to_the_target_is_accepted_and_not_created(
    root: Path, tmp_path: Path
) -> None:
    before = sorted(path.name for path in tmp_path.iterdir())
    result = preflight_evidence_directory(tmp_path / "evidence", root)
    assert result == tmp_path.resolve() / "evidence"
    assert not result.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == before


def test_relative_output_is_resolved_against_the_current_directory(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert preflight_evidence_directory(Path("evidence"), root) == tmp_path.resolve() / "evidence"


def test_existing_directory_or_file_is_never_overwritten(root: Path, tmp_path: Path) -> None:
    (tmp_path / "taken-dir").mkdir()
    (tmp_path / "taken-file").write_text("x", encoding="utf-8")
    for name in ("taken-dir", "taken-file"):
        with pytest.raises(PathSafetyError, match="already exists"):
            preflight_evidence_directory(tmp_path / name, root)


def test_dangling_symlink_counts_as_existing(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    os.symlink(tmp_path / "nowhere", tmp_path / "dangling")
    with pytest.raises(PathSafetyError, match="already exists"):
        preflight_evidence_directory(tmp_path / "dangling", root)


def test_missing_parent_is_rejected_and_nothing_is_created(root: Path, tmp_path: Path) -> None:
    with pytest.raises(PathSafetyError, match="cannot be resolved"):
        preflight_evidence_directory(tmp_path / "no-such-parent" / "evidence", root)
    assert not (tmp_path / "no-such-parent").exists()


def test_parent_that_is_a_file_is_rejected(root: Path, tmp_path: Path) -> None:
    (tmp_path / "plain-file").write_text("x", encoding="utf-8")
    with pytest.raises(PathSafetyError):
        preflight_evidence_directory(tmp_path / "plain-file" / "evidence", root)


def test_evidence_inside_the_target_root_is_rejected(root: Path) -> None:
    with pytest.raises(PathSafetyError, match="outside the target repository"):
        preflight_evidence_directory(root / "evidence", root)
    with pytest.raises(PathSafetyError, match="outside the target repository"):
        preflight_evidence_directory(root / "tests" / "evidence", root)


def test_parent_link_that_leads_into_the_target_root_is_rejected(
    root: Path, tmp_path: Path, need_symlinks: None
) -> None:
    os.symlink(root, tmp_path / "sneaky", target_is_directory=True)
    with pytest.raises(PathSafetyError, match="outside the target repository"):
        preflight_evidence_directory(tmp_path / "sneaky" / "evidence", root)


@pytest.mark.parametrize("name", ["con", "NUL.txt", "evidence.", "evidence ", "bad:name", "a*b"])
def test_unsafe_evidence_names_are_rejected(root: Path, tmp_path: Path, name: str) -> None:
    with pytest.raises(PathSafetyError):
        preflight_evidence_directory(tmp_path / name, root)


@pytest.mark.parametrize("text", [".", "..", ""])
def test_evidence_path_must_name_a_new_directory(root: Path, text: str) -> None:
    with pytest.raises(PathSafetyError):
        preflight_evidence_directory(Path(text), root)


def test_network_paths_are_rejected_for_evidence(root: Path) -> None:
    with pytest.raises(PathSafetyError, match="network"):
        preflight_evidence_directory(Path("\\\\server\\share\\evidence"), root)