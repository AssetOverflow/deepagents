"""Base sandbox implementation with execute() as the only abstract method.

This module provides a base class that implements all SandboxBackendProtocol
methods using shell commands executed via execute(). Concrete implementations
only need to implement the execute() method.

It also provides GrpcSandbox for high-performance file I/O via gRPC.
"""

from __future__ import annotations

import base64
import json
import shlex
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import grpc

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)

if TYPE_CHECKING:
    from deepagents.backends import sandbox_io_pb2_grpc

_GLOB_COMMAND_TEMPLATE = """python3 -c "
import glob
import os
import json
import base64

# Decode base64-encoded parameters
path = base64.b64decode('{path_b64}').decode('utf-8')
pattern = base64.b64decode('{pattern_b64}').decode('utf-8')

os.chdir(path)
matches = sorted(glob.glob(pattern, recursive=True))
for m in matches:
    stat = os.stat(m)
    result = {{
        'path': m,
        'size': stat.st_size,
        'mtime': stat.st_mtime,
        'is_dir': os.path.isdir(m)
    }}
    print(json.dumps(result))
" 2>/dev/null"""

_WRITE_COMMAND_TEMPLATE = """python3 -c "
import os
import sys
import base64

file_path = '{file_path}'

# Check if file already exists (atomic with write)
if os.path.exists(file_path):
    print(f'Error: File \\'{file_path}\\' already exists', file=sys.stderr)
    sys.exit(1)

# Create parent directory if needed
parent_dir = os.path.dirname(file_path) or '.'
os.makedirs(parent_dir, exist_ok=True)

# Decode and write content
content = base64.b64decode('{content_b64}').decode('utf-8')
with open(file_path, 'w') as f:
    f.write(content)
" 2>&1"""

_EDIT_COMMAND_TEMPLATE = """python3 -c "
import sys
import base64

# Read file content
with open('{file_path}', 'r') as f:
    text = f.read()

# Decode base64-encoded strings
old = base64.b64decode('{old_b64}').decode('utf-8')
new = base64.b64decode('{new_b64}').decode('utf-8')

# Count occurrences
count = text.count(old)

# Exit with error codes if issues found
if count == 0:
    sys.exit(1)  # String not found
elif count > 1 and not {replace_all}:
    sys.exit(2)  # Multiple occurrences without replace_all

# Perform replacement
if {replace_all}:
    result = text.replace(old, new)
else:
    result = text.replace(old, new, 1)

# Write back to file
with open('{file_path}', 'w') as f:
    f.write(result)

print(count)
" 2>&1"""

_READ_COMMAND_TEMPLATE = """python3 -c "
import os
import sys

file_path = '{file_path}'
offset = {offset}
limit = {limit}

# Check if file exists
if not os.path.isfile(file_path):
    print('Error: File not found')
    sys.exit(1)

# Check if file is empty
if os.path.getsize(file_path) == 0:
    print('System reminder: File exists but has empty contents')
    sys.exit(0)

# Read file with offset and limit
with open(file_path, 'r') as f:
    lines = f.readlines()

# Apply offset and limit
start_idx = offset
end_idx = offset + limit
selected_lines = lines[start_idx:end_idx]

# Format with line numbers (1-indexed, starting from offset + 1)
for i, line in enumerate(selected_lines):
    line_num = offset + i + 1
    # Remove trailing newline for formatting, then add it back
    line_content = line.rstrip('\\n')
    print(f'{{line_num:6d}}\\t{{line_content}}')
" 2>&1"""


class BaseSandbox(SandboxBackendProtocol, ABC):
    """Base sandbox implementation with execute() as abstract method.

    This class provides default implementations for all protocol methods
    using shell commands. Subclasses only need to implement execute().
    """

    @abstractmethod
    def execute(
        self,
        command: str,
    ) -> ExecuteResponse:
        """Execute a command in the sandbox and return ExecuteResponse.

        Args:
            command: Full shell command string to execute.

        Returns:
            ExecuteResponse with combined output, exit code, optional signal, and truncation flag.
        """
        ...

    def ls_info(self, path: str) -> list[FileInfo]:
        """Structured listing with file metadata using os.scandir."""
        cmd = f"""python3 -c "
import os
import json

path = '{path}'

try:
    with os.scandir(path) as it:
        for entry in it:
            result = {{
                'path': entry.name,
                'is_dir': entry.is_dir(follow_symlinks=False)
            }}
            print(json.dumps(result))
except FileNotFoundError:
    pass
except PermissionError:
    pass
" 2>/dev/null"""

        result = self.execute(cmd)

        file_infos: list[FileInfo] = []
        for line in result.output.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                file_infos.append({"path": data["path"], "is_dir": data["is_dir"]})
            except json.JSONDecodeError:
                continue

        return file_infos

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with line numbers using a single shell command."""
        # Use template for reading file with offset and limit
        cmd = _READ_COMMAND_TEMPLATE.format(file_path=file_path, offset=offset, limit=limit)
        result = self.execute(cmd)

        output = result.output.rstrip()
        exit_code = result.exit_code

        if exit_code != 0 or "Error: File not found" in output:
            return f"Error: File '{file_path}' not found"

        return output

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file. Returns WriteResult; error populated on failure."""
        # Encode content as base64 to avoid any escaping issues
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")

        # Single atomic check + write command
        cmd = _WRITE_COMMAND_TEMPLATE.format(file_path=file_path, content_b64=content_b64)
        result = self.execute(cmd)

        # Check for errors (exit code or error message in output)
        if result.exit_code != 0 or "Error:" in result.output:
            error_msg = result.output.strip() or f"Failed to write file '{file_path}'"
            return WriteResult(error=error_msg)

        # External storage - no files_update needed
        return WriteResult(path=file_path, files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences. Returns EditResult."""
        # Encode strings as base64 to avoid any escaping issues
        old_b64 = base64.b64encode(old_string.encode("utf-8")).decode("ascii")
        new_b64 = base64.b64encode(new_string.encode("utf-8")).decode("ascii")

        # Use template for string replacement
        cmd = _EDIT_COMMAND_TEMPLATE.format(file_path=file_path, old_b64=old_b64, new_b64=new_b64, replace_all=replace_all)
        result = self.execute(cmd)

        exit_code = result.exit_code
        output = result.output.strip()

        if exit_code == 1:
            return EditResult(error=f"Error: String not found in file: '{old_string}'")
        if exit_code == 2:
            return EditResult(error=f"Error: String '{old_string}' appears multiple times. Use replace_all=True to replace all occurrences.")
        if exit_code != 0:
            return EditResult(error=f"Error: File '{file_path}' not found")

        count = int(output)
        # External storage - no files_update needed
        return EditResult(path=file_path, files_update=None, occurrences=count)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Structured search results or error string for invalid input."""
        search_path = shlex.quote(path or ".")

        # Build grep command to get structured output
        grep_opts = "-rHnF"  # recursive, with filename, with line number, fixed-strings (literal)

        # Add glob pattern if specified
        glob_pattern = ""
        if glob:
            glob_pattern = f"--include='{glob}'"

        # Escape pattern for shell
        pattern_escaped = shlex.quote(pattern)

        cmd = f"grep {grep_opts} {glob_pattern} -e {pattern_escaped} {search_path} 2>/dev/null || true"
        result = self.execute(cmd)

        output = result.output.rstrip()
        if not output:
            return []

        # Parse grep output into GrepMatch objects
        matches: list[GrepMatch] = []
        for line in output.split("\n"):
            # Format is: path:line_number:text
            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append(
                    {
                        "path": parts[0],
                        "line": int(parts[1]),
                        "text": parts[2],
                    }
                )

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Structured glob matching returning FileInfo dicts."""
        # Encode pattern and path as base64 to avoid escaping issues
        pattern_b64 = base64.b64encode(pattern.encode("utf-8")).decode("ascii")
        path_b64 = base64.b64encode(path.encode("utf-8")).decode("ascii")

        cmd = _GLOB_COMMAND_TEMPLATE.format(path_b64=path_b64, pattern_b64=pattern_b64)
        result = self.execute(cmd)

        output = result.output.strip()
        if not output:
            return []

        # Parse JSON output into FileInfo dicts
        file_infos: list[FileInfo] = []
        for line in output.split("\n"):
            try:
                data = json.loads(line)
                file_infos.append(
                    {
                        "path": data["path"],
                        "is_dir": data["is_dir"],
                    }
                )
            except json.JSONDecodeError:
                continue

        return file_infos

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier for the sandbox backend."""

    @abstractmethod
    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the sandbox.

        Implementations must support partial success - catch exceptions per-file
        and return errors in FileUploadResponse objects rather than raising.
        """

    @abstractmethod
    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the sandbox.

        Implementations must support partial success - catch exceptions per-file
        and return errors in FileDownloadResponse objects rather than raising.
        """


class GrpcSandbox(SandboxBackendProtocol):
    """High-performance sandbox backend using gRPC for file operations.

    This class implements all SandboxBackendProtocol methods using fast gRPC
    calls instead of slow shell-wrapped Python scripts. It communicates with
    a Sandbox I/O Server that runs locally or remotely alongside the execution
    environment.

    The gRPC approach replaces a multi-step process (shell startup, Python
    interpreter startup, Base64 encoding/decoding, file I/O) with a single,
    fast RPC network call, drastically reducing latency for common file
    operations.

    Args:
        rpc_endpoint: The gRPC endpoint to connect to (e.g., "localhost:50051").
        sandbox_id: Optional explicit sandbox ID. If not provided, it will be
            fetched from the server.

    Example:
        >>> sandbox = GrpcSandbox("localhost:50051")
        >>> content = sandbox.read("/path/to/file.txt")
        >>> result = sandbox.write("/path/to/new.txt", "content")
    """

    def __init__(self, rpc_endpoint: str, sandbox_id: str | None = None) -> None:
        """Initialize the gRPC client and connect to the Sandbox I/O Server.

        Args:
            rpc_endpoint: The gRPC endpoint to connect to (e.g., "localhost:50051").
            sandbox_id: Optional explicit sandbox ID. If not provided, it will be
                fetched from the server.
        """
        # Import here to avoid circular imports and for lazy loading
        from deepagents.backends import sandbox_io_pb2, sandbox_io_pb2_grpc

        self._rpc_endpoint = rpc_endpoint
        self._channel: grpc.Channel = grpc.insecure_channel(rpc_endpoint)
        self._stub: sandbox_io_pb2_grpc.SandboxIORouterStub = sandbox_io_pb2_grpc.SandboxIORouterStub(self._channel)
        self._sandbox_id = sandbox_id
        self._pb2 = sandbox_io_pb2

    def _handle_rpc_error(self, e: grpc.RpcError, operation: str) -> str:
        """Format RPC errors consistently.

        Args:
            e: The gRPC RpcError to handle.
            operation: The operation that failed.

        Returns:
            Formatted error string.
        """
        return f"Error: RPC communication failed during {operation}: {e.details()}"

    @property
    def id(self) -> str:
        """Unique identifier for the sandbox backend.

        Returns:
            The sandbox ID, either from the constructor or fetched from server.
        """
        if self._sandbox_id is None:
            try:
                response = self._stub.GetId(self._pb2.Empty())
                self._sandbox_id = response.id
            except grpc.RpcError:
                # Return a fallback ID if server is unreachable
                return f"grpc-sandbox-{self._rpc_endpoint}"
        return self._sandbox_id

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content via fast RPC call.

        Args:
            file_path: Absolute path to the file to read.
            offset: Line number to start reading from (0-indexed).
            limit: Maximum number of lines to read.

        Returns:
            String containing file content formatted with line numbers,
            or an error string if the file doesn't exist or can't be read.
        """
        request = self._pb2.ReadRequest(file_path=file_path, offset=offset, limit=limit)
        try:
            response = self._stub.ReadFile(request)
            return response.output
        except grpc.RpcError as e:
            return self._handle_rpc_error(e, "read")

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file via RPC.

        The Sandbox I/O Server implements the file existence check atomically.

        Args:
            file_path: Absolute path where the file should be created.
            content: String content to write to the file.

        Returns:
            WriteResult with path on success or error on failure.
        """
        request = self._pb2.WriteRequest(file_path=file_path, content=content)
        try:
            response = self._stub.WriteFile(request)
            if response.error:
                # files_update=None is correct for external storage
                return WriteResult(error=response.error, files_update=None)
            return WriteResult(path=response.path, files_update=None)
        except grpc.RpcError as e:
            return WriteResult(error=self._handle_rpc_error(e, "write"), files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences via RPC.

        Args:
            file_path: Absolute path to the file to edit.
            old_string: Exact string to search for and replace.
            new_string: String to replace old_string with.
            replace_all: If True, replace all occurrences.

        Returns:
            EditResult with path and occurrences on success, or error on failure.
        """
        request = self._pb2.EditRequest(
            file_path=file_path,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )
        try:
            response = self._stub.EditFile(request)
            if response.error:
                return EditResult(error=response.error, files_update=None)
            return EditResult(
                path=response.path,
                files_update=None,
                occurrences=response.occurrences,
            )
        except grpc.RpcError as e:
            return EditResult(error=self._handle_rpc_error(e, "edit"), files_update=None)

    def ls_info(self, path: str) -> list[FileInfo]:
        """List directory contents with metadata via streaming RPC.

        Args:
            path: Absolute path to the directory to list.

        Returns:
            List of FileInfo dicts containing file metadata.
        """
        request = self._pb2.ListRequest(path=path)
        try:
            file_infos: list[FileInfo] = []
            for item in self._stub.ListInfo(request):
                info: FileInfo = {
                    "path": item.path,
                    "is_dir": item.is_dir,
                }
                if item.size:
                    info["size"] = item.size
                if item.modified_at:
                    info["modified_at"] = item.modified_at
                file_infos.append(info)
            return file_infos
        except grpc.RpcError:
            return []

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for pattern in files via streaming RPC.

        Args:
            pattern: Literal string to search for (NOT regex).
            path: Optional directory path to search in.
            glob: Optional glob pattern to filter files.

        Returns:
            List of GrepMatch dicts on success, or error string on failure.
        """
        request = self._pb2.GrepRequest(pattern=pattern, path=path or "", glob=glob or "")
        try:
            matches: list[GrepMatch] = []
            for match in self._stub.GrepRaw(request):
                matches.append({"path": match.path, "line": match.line, "text": match.text})
            return matches
        except grpc.RpcError as e:
            return self._handle_rpc_error(e, "grep")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern via streaming RPC.

        Args:
            pattern: Glob pattern with wildcards to match file paths.
            path: Base directory to search from.

        Returns:
            List of FileInfo dicts for matching files.
        """
        request = self._pb2.GlobRequest(pattern=pattern, path=path)
        try:
            file_infos: list[FileInfo] = []
            for item in self._stub.GlobInfo(request):
                info: FileInfo = {"path": item.path, "is_dir": item.is_dir}
                if item.size:
                    info["size"] = item.size
                if item.modified_at:
                    info["modified_at"] = item.modified_at
                file_infos.append(info)
            return file_infos
        except grpc.RpcError:
            return []

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a command in the sandbox via RPC.

        Args:
            command: Full shell command string to execute.

        Returns:
            ExecuteResponse with combined output, exit code, and truncation flag.
        """
        request = self._pb2.ExecuteRequest(command=command)
        try:
            response = self._stub.Execute(request)
            return ExecuteResponse(
                output=response.output,
                exit_code=response.exit_code,
                truncated=response.truncated,
            )
        except grpc.RpcError as e:
            return ExecuteResponse(output=self._handle_rpc_error(e, "execute"), exit_code=1)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the sandbox via RPC.

        Args:
            files: List of (path, content) tuples to upload.

        Returns:
            List of FileUploadResponse objects, one per input file.
        """
        file_uploads = [self._pb2.FileUpload(path=path, content=content) for path, content in files]
        request = self._pb2.UploadRequest(files=file_uploads)
        try:
            response = self._stub.UploadFiles(request)
            return [
                FileUploadResponse(
                    path=result.path,
                    error=result.error if result.error else None,  # type: ignore[arg-type]
                )
                for result in response.results
            ]
        except grpc.RpcError:
            # Return error for all files
            return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the sandbox via RPC.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects, one per input path.
        """
        request = self._pb2.DownloadRequest(paths=paths)
        try:
            response = self._stub.DownloadFiles(request)
            return [
                FileDownloadResponse(
                    path=result.path,
                    content=result.content if not result.error else None,
                    error=result.error if result.error else None,  # type: ignore[arg-type]
                )
                for result in response.results
            ]
        except grpc.RpcError:
            # Return error for all files
            return [FileDownloadResponse(path=path, content=None, error="file_not_found") for path in paths]

    def close(self) -> None:
        """Close the gRPC channel.

        Should be called when the sandbox is no longer needed to clean up
        resources.
        """
        if self._channel:
            self._channel.close()
