"""Read-only filesystem backend with virtual root containment."""

import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

import wcmatch.glob as wcglob

from deepagents.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from deepagents.backends.utils import check_empty_content, format_content_with_line_numbers


class ReadOnlyFilesystemBackend(BackendProtocol):
    """Filesystem backend that permits read/list/search/download only.

    Paths are interpreted as virtual absolute paths under ``root_dir``. For
    example, ``/README.md`` maps to ``root_dir / "README.md"`` rather than the
    host path ``/README.md``.
    """

    def __init__(
        self,
        root_dir: str | Path,
        *,
        allowed_prefixes: tuple[str, ...] = ("/",),
        deny_git: bool = True,
        max_file_size_mb: int = 10,
    ) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.allowed_prefixes = tuple(self._normalize_prefix(prefix) for prefix in allowed_prefixes)
        self.deny_git = deny_git
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024

    def _normalize_prefix(self, prefix: str) -> str:
        if not prefix:
            msg = "Allowed prefixes must be non-empty virtual absolute paths"
            raise ValueError(msg)
        normalized = prefix if prefix.startswith("/") else f"/{prefix}"
        if normalized != "/":
            normalized = normalized.rstrip("/")
        return normalized

    def _normalize_virtual_path(self, path: str) -> PurePosixPath:
        if not path or not path.startswith("/"):
            msg = "Path must be a virtual absolute path starting with '/'"
            raise ValueError(msg)
        virtual = PurePosixPath(path)
        parts = virtual.parts
        if any(part in {"..", "~"} for part in parts):
            msg = "Path traversal is not allowed"
            raise ValueError(msg)
        if self.deny_git and ".git" in parts:
            msg = ".git paths are denied by this read-only backend"
            raise PermissionError(msg)
        virtual_str = virtual.as_posix()
        if not self._is_allowed_prefix(virtual_str):
            msg = f"Path '{virtual_str}' is outside allowed read prefixes"
            raise PermissionError(msg)
        return virtual

    def _is_allowed_prefix(self, virtual_path: str) -> bool:
        for prefix in self.allowed_prefixes:
            if prefix == "/" or virtual_path == prefix or virtual_path.startswith(f"{prefix}/"):
                return True
        return False

    def _resolve_path(self, path: str) -> Path:
        virtual = self._normalize_virtual_path(path)
        relative_parts = [part for part in virtual.parts if part != "/"]
        candidate = self.root_dir
        for part in relative_parts:
            candidate = candidate / part
            if candidate.is_symlink():
                msg = "Symlink traversal is denied by this read-only backend"
                raise PermissionError(msg)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self.root_dir)
        except ValueError as exc:
            msg = f"Path '{path}' resolves outside root directory"
            raise PermissionError(msg) from exc
        return resolved

    def _to_virtual_path(self, path: Path) -> str:
        rel = path.resolve(strict=False).relative_to(self.root_dir)
        rel_str = rel.as_posix()
        return f"/{rel_str}" if rel_str != "." else "/"

    def _should_skip_path(self, path: Path) -> bool:
        try:
            rel_parts = path.resolve(strict=False).relative_to(self.root_dir).parts
        except ValueError:
            return True
        return (self.deny_git and ".git" in rel_parts) or path.is_symlink()

    def _open_read_text(self, path: Path) -> str:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r", encoding="utf-8") as file:
            return file.read()

    def _open_read_bytes(self, path: Path) -> bytes:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as file:
            return file.read()

    def _check_readable_file(self, path: Path, original_path: str) -> str | None:
        if not path.exists():
            return f"Error: File '{original_path}' not found"
        if not path.is_file():
            return f"Error: Path '{original_path}' is not a file"
        try:
            if path.stat().st_size > self.max_file_size_bytes:
                return f"Error: File '{original_path}' exceeds maximum read size"
        except OSError as exc:
            return f"Error reading file '{original_path}': {exc}"
        return None

    def ls_info(self, path: str) -> list[FileInfo]:
        try:
            dir_path = self._resolve_path(path)
        except (PermissionError, ValueError):
            return []
        if not dir_path.exists() or not dir_path.is_dir():
            return []
        results: list[FileInfo] = []
        try:
            children = sorted(dir_path.iterdir(), key=lambda child: child.name)
        except (OSError, PermissionError):
            return []
        for child in children:
            if self._should_skip_path(child):
                continue
            try:
                is_dir = child.is_dir()
                is_file = child.is_file()
            except OSError:
                continue
            if not is_dir and not is_file:
                continue
            try:
                stat_result = child.stat()
                modified_at = datetime.fromtimestamp(stat_result.st_mtime).isoformat()
            except OSError:
                stat_result = None
                modified_at = ""
            virtual_path = self._to_virtual_path(child)
            if is_dir:
                results.append(
                    {
                        "path": f"{virtual_path}/" if not virtual_path.endswith("/") else virtual_path,
                        "is_dir": True,
                        "size": 0,
                        "modified_at": modified_at,
                    }
                )
            else:
                results.append(
                    {
                        "path": virtual_path,
                        "is_dir": False,
                        "size": int(stat_result.st_size) if stat_result is not None else 0,
                        "modified_at": modified_at,
                    }
                )
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        try:
            resolved_path = self._resolve_path(file_path)
        except (PermissionError, ValueError) as exc:
            return f"Error: {exc}"
        file_error = self._check_readable_file(resolved_path, file_path)
        if file_error:
            return file_error
        try:
            content = self._open_read_text(resolved_path)
        except (OSError, UnicodeDecodeError) as exc:
            return f"Error reading file '{file_path}': {exc}"
        empty_msg = check_empty_content(content)
        if empty_msg:
            return empty_msg
        lines = content.splitlines()
        if offset >= len(lines):
            return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"
        selected_lines = lines[offset : min(offset + limit, len(lines))]
        return format_content_with_line_numbers(selected_lines, start_line=offset + 1)

    def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None) -> list[GrepMatch] | str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Invalid regex pattern: {exc}"
        try:
            base_path = self._resolve_path(path or "/")
        except (PermissionError, ValueError):
            return []
        if not base_path.exists():
            return []
        candidates = [base_path] if base_path.is_file() else base_path.rglob("*")
        matches: list[GrepMatch] = []
        for candidate in candidates:
            if self._should_skip_path(candidate):
                continue
            try:
                if not candidate.is_file() or candidate.stat().st_size > self.max_file_size_bytes:
                    continue
            except OSError:
                continue
            virtual_path = self._to_virtual_path(candidate)
            if glob and not self._matches_glob(virtual_path, glob):
                continue
            try:
                content = self._open_read_text(candidate)
            except (OSError, UnicodeDecodeError):
                continue
            for line_num, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    matches.append({"path": virtual_path, "line": line_num, "text": line})
        return matches

    def _matches_glob(self, virtual_path: str, pattern: str) -> bool:
        stripped = virtual_path.lstrip("/")
        flags = wcglob.BRACE | wcglob.GLOBSTAR
        return wcglob.globmatch(stripped, pattern, flags=flags) or wcglob.globmatch(Path(stripped).name, pattern, flags=flags)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        if ".." in PurePosixPath(pattern).parts:
            return []
        normalized_pattern = pattern.lstrip("/")
        try:
            search_path = self._resolve_path(path)
        except (PermissionError, ValueError):
            return []
        if not search_path.exists() or not search_path.is_dir():
            return []
        results: list[FileInfo] = []
        try:
            candidates = search_path.rglob(normalized_pattern)
        except ValueError:
            return []
        for candidate in candidates:
            if self._should_skip_path(candidate):
                continue
            try:
                if not candidate.is_file():
                    continue
                stat_result = candidate.stat()
            except OSError:
                continue
            results.append(
                {
                    "path": self._to_virtual_path(candidate),
                    "is_dir": False,
                    "size": int(stat_result.st_size),
                    "modified_at": datetime.fromtimestamp(stat_result.st_mtime).isoformat(),
                }
            )
        results.sort(key=lambda item: item.get("path", ""))
        return results

    def write(self, file_path: str, content: str) -> WriteResult:
        _ = content
        return WriteResult(error=f"ReadOnlyFilesystemBackend denies write to {file_path}")

    def edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        _ = old_string, new_string, replace_all
        return EditResult(error=f"ReadOnlyFilesystemBackend denies edit to {file_path}")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                resolved_path = self._resolve_path(path)
                file_error = self._check_readable_file(resolved_path, path)
                if file_error:
                    error = "file_not_found" if "not found" in file_error else "permission_denied"
                    responses.append(FileDownloadResponse(path=path, content=None, error=error))
                    continue
                responses.append(FileDownloadResponse(path=path, content=self._open_read_bytes(resolved_path), error=None))
            except FileNotFoundError:
                responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
            except IsADirectoryError:
                responses.append(FileDownloadResponse(path=path, content=None, error="is_directory"))
            except PermissionError:
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))
            except ValueError:
                responses.append(FileDownloadResponse(path=path, content=None, error="invalid_path"))
        return responses
