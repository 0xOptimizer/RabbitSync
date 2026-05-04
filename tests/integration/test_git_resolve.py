"""Integration tests for git_resolve covering all four folder/git combinations."""

from __future__ import annotations

from pathlib import Path

from rabbitsync.core.git_resolve import resolve


def test_resolve_root_folder_is_repo_root(make_repo) -> None:  # noqa: ANN001
    """Folder is itself a git repo root: subpath == ''."""
    repo: Path = make_repo("repo-root")
    ctx = resolve(repo)
    assert ctx.has_git is True
    assert ctx.is_root is True
    assert ctx.git_root == repo.resolve()
    assert ctx.subpath == ""
    assert ctx.git_dir is not None
    assert ctx.git_dir.exists()


def test_resolve_subpath_folder_inside_repo(make_subpath_repo) -> None:  # noqa: ANN001
    """Folder is `proj/src/`; .git is at `proj/.git`. subpath should be 'src'."""
    repo, sub = make_subpath_repo("proj", "src")
    ctx = resolve(sub)
    assert ctx.has_git is True
    assert ctx.is_root is False
    assert ctx.git_root == repo.resolve()
    assert ctx.subpath == "src"
    assert ctx.git_dir is not None
    assert ctx.git_dir.exists()


def test_resolve_deeper_subpath(tmp_path: Path, make_subpath_repo) -> None:  # noqa: ANN001
    """Subpath two levels deep should be normalized with forward slashes."""
    repo, sub = make_subpath_repo("proj", "src")
    nested = sub / "inner" / "deeper"
    nested.mkdir(parents=True, exist_ok=True)
    ctx = resolve(nested)
    assert ctx.has_git is True
    assert ctx.git_root == repo.resolve()
    assert ctx.subpath == "src/inner/deeper"


def test_resolve_non_git_folder(make_non_git_dir) -> None:  # noqa: ANN001
    """Folder not in any git repo: has_git is False, git_root is None."""
    plain: Path = make_non_git_dir()
    ctx = resolve(plain)
    assert ctx.has_git is False
    assert ctx.git_root is None
    assert ctx.subpath is None
    assert ctx.git_dir is None
    assert ctx.is_root is False


def test_resolve_missing_folder_raises(tmp_path: Path) -> None:
    """Resolving a non-existent path should raise FileNotFoundError."""
    missing = tmp_path / "does-not-exist"
    try:
        resolve(missing)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_resolve_path_to_file_raises(tmp_path: Path) -> None:
    """Resolving a file (not a directory) should raise NotADirectoryError."""
    f = tmp_path / "file.txt"
    f.write_text("x", encoding="utf-8")
    try:
        resolve(f)
    except NotADirectoryError:
        return
    raise AssertionError("expected NotADirectoryError")
