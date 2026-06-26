from pathlib import Path

from deepagents.backends import ReadOnlyFilesystemBackend
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_read_only_backend_supports_read_list_glob_grep_and_download(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "hello\nneedle\n")
    _write(tmp_path / "src" / "app.py", "print('needle')\n")
    _write(tmp_path / ".git" / "config", "secret\n")

    backend = ReadOnlyFilesystemBackend(tmp_path)

    assert isinstance(backend, BackendProtocol)
    assert not isinstance(backend, SandboxBackendProtocol)

    listed = backend.ls_info("/")
    assert [item["path"] for item in listed] == ["/README.md", "/src/"]

    read = backend.read("/README.md")
    assert "1" in read
    assert "hello" in read
    assert "needle" in read

    globbed = backend.glob_info("**/*.py")
    assert [item["path"] for item in globbed] == ["/src/app.py"]

    matches = backend.grep_raw("needle", glob="**/*.py")
    assert matches == [{"path": "/src/app.py", "line": 1, "text": "print('needle')"}]

    downloads = backend.download_files(["/README.md"])
    assert downloads[0].error is None
    assert downloads[0].content == b"hello\nneedle\n"


def test_read_only_backend_denies_mutations(tmp_path: Path) -> None:
    _write(tmp_path / "README.md", "hello\n")
    backend = ReadOnlyFilesystemBackend(tmp_path)

    write_result = backend.write("/new.txt", "new")
    edit_result = backend.edit("/README.md", "hello", "goodbye")
    uploads = backend.upload_files([("/upload.txt", b"upload")])

    assert write_result.error is not None
    assert edit_result.error is not None
    assert uploads[0].error == "permission_denied"
    assert not (tmp_path / "new.txt").exists()
    assert not (tmp_path / "upload.txt").exists()
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_read_only_backend_rejects_invalid_prefix_and_git_paths(tmp_path: Path) -> None:
    _write(tmp_path / "allowed" / "README.md", "hello\n")
    _write(tmp_path / ".git" / "config", "secret\n")
    backend = ReadOnlyFilesystemBackend(tmp_path, allowed_prefixes=("/allowed",))

    assert "hello" in backend.read("/allowed/README.md")
    assert backend.ls_info("/") == []
    assert backend.glob_info("**/*") == []
    assert backend.grep_raw("hello", path="/") == []

    git_read = backend.read("/.git/config")
    assert "denied" in git_read
    assert backend.download_files(["/.git/config"])[0].error == "permission_denied"


def test_read_only_backend_rejects_traversal_relative_and_oversized_paths(tmp_path: Path) -> None:
    _write(tmp_path / "small.txt", "small\n")
    _write(tmp_path / "large.txt", "large\n")
    backend = ReadOnlyFilesystemBackend(tmp_path, max_file_size_mb=0)

    assert "virtual absolute path" in backend.read("small.txt")
    assert "traversal" in backend.read("/../small.txt")
    assert "exceeds maximum read size" in backend.read("/large.txt")
    assert backend.download_files(["small.txt"])[0].error == "invalid_path"


def test_read_only_backend_skips_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    _write(target, "secret\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        return

    backend = ReadOnlyFilesystemBackend(tmp_path)

    assert "/link.txt" not in [item["path"] for item in backend.ls_info("/")]
    assert "Symlink traversal" in backend.read("/link.txt")
    assert backend.glob_info("*.txt") == [{"path": "/target.txt", "is_dir": False, "size": 7, "modified_at": backend.glob_info("*.txt")[0]["modified_at"]}]
